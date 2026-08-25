"""Checkpoint parsing — ``--policy`` → :class:`PolicyProfile` (docs/03 §6, docs/06 P3).

This is the seam that turns "lint the data" into "lint the data **for this model**". It
reads only *metadata*: shapes, config JSON, and baked-in normalization constants. It never
executes a checkpoint and never loads weights onto a device — a scan must stay a static
analysis, and running an untrusted `.pt` would be arbitrary code execution.

Four container types are understood, in order of how safe they are to read:

* **HuggingFace / LeRobot directory** — ``config.json`` plus an optional
  ``norm_stats.json``. Pure JSON; the richest and safest source.
* **safetensors** — a JSON header at a known offset. Read directly, no library needed.
* **ONNX** — input/output tensor shapes via ``onnxruntime`` (``bohrin[onnx]``).
* **PyTorch ``.pt``/``.pth``** — deliberately **not** unpickled. See ``_refuse_pickle``.

Anything unreadable yields a profile with ``UNKNOWN`` fields rather than a guess: a
fabricated expectation would make the POLICY↔DATA family invent mismatches.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bohrin.ir.schema import FeatureStats, NormScheme, PolicyFamily, PolicyProfile

_SAFETENSORS_SUFFIXES = frozenset({".safetensors"})
_ONNX_SUFFIXES = frozenset({".onnx"})
_PICKLE_SUFFIXES = frozenset({".pt", ".pth", ".bin", ".ckpt"})
_CONFIG_NAMES = ("config.json", "policy_config.json")
_NORM_NAMES = ("norm_stats.json", "normalization.json", "dataset_statistics.json")

#: The safetensors header length prefix: 8 bytes, little-endian u64.
_HEADER_LEN_BYTES = 8
#: Refuse to read an implausibly large header rather than allocating it.
_MAX_HEADER_BYTES = 64 * 1024 * 1024

#: Substrings in a checkpoint's declared architecture that identify the policy family.
#: Ordered most specific first — "openvla" must beat a bare "vla".
_FAMILY_HINTS: tuple[tuple[str, PolicyFamily], ...] = (
    ("openvla", PolicyFamily.VLA_OPENVLA),
    ("pi0", PolicyFamily.VLA_PI0),
    ("pi-0", PolicyFamily.VLA_PI0),
    ("octo", PolicyFamily.OCTO),
    ("diffusion", PolicyFamily.DIFFUSION),
    ("act", PolicyFamily.ACT),
    ("bc", PolicyFamily.BC_MLP),
)

#: Families that consume a proprioceptive state and zero-fill it when absent
#: (π0: arXiv 2505.05540). Used by ``policy_data.missing_proprio``.
PROPRIO_DEPENDENT = frozenset({PolicyFamily.VLA_PI0, PolicyFamily.OCTO, PolicyFamily.DIFFUSION})

#: Families that clamp their action outputs, which softens a normalization mismatch.
CLAMPING_FAMILIES = frozenset({PolicyFamily.VLA_OPENVLA})


class UnreadablePolicyError(ValueError):
    """Raised when a checkpoint cannot be read safely or at all."""


def _refuse_pickle(path: Path) -> None:
    """Refuse ``torch.load``-style containers.

    Unpickling executes arbitrary code by design. A data-quality tool that a user points
    at a checkpoint downloaded from the internet must not be the thing that runs it. The
    user can convert to safetensors — which exists precisely for this reason.
    """
    raise UnreadablePolicyError(
        f"{path.name}: reading pickled PyTorch checkpoints is not supported, because "
        "unpickling executes arbitrary code and a scan must stay a static analysis. "
        "Convert to safetensors, or pass the model's HuggingFace directory (config.json)."
    )


def read_safetensors_header(path: Path) -> dict[str, Any]:
    """Read a safetensors file's JSON header without loading any tensor data.

    Format: ``u64 header_len | header_json | tensor bytes``. Only the first two are read,
    so this is O(header) regardless of a multi-gigabyte checkpoint.
    """
    with path.open("rb") as fh:
        raw = fh.read(_HEADER_LEN_BYTES)
        if len(raw) < _HEADER_LEN_BYTES:
            raise UnreadablePolicyError(f"{path.name}: truncated safetensors header")
        (length,) = struct.unpack("<Q", raw)
        if length <= 0 or length > _MAX_HEADER_BYTES:
            raise UnreadablePolicyError(f"{path.name}: implausible safetensors header length {length}")
        header = fh.read(length)
    try:
        parsed: dict[str, Any] = json.loads(header)
    except json.JSONDecodeError as exc:
        raise UnreadablePolicyError(f"{path.name}: safetensors header is not valid JSON") from exc
    return parsed


def infer_family(text: str) -> PolicyFamily:
    """Map a declared architecture/model-type string to a :class:`PolicyFamily`."""
    lowered = text.lower()
    for hint, family in _FAMILY_HINTS:
        if hint in lowered:
            return family
    return PolicyFamily.UNKNOWN


def _first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _as_float_list(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def norm_key(feature: str, dim: int) -> str:
    """The per-dimension key used in :attr:`PolicyProfile.norm_stats` — ``action[3]``.

    ``FeatureStats`` is scalar per feature, while checkpoints publish one constant *per
    dimension*. Flattening to ``"<feature>[<dim>]"`` keeps the frozen P0 schema intact and
    lets a detector look up exactly the dimension it wants to report on.
    """
    return f"{feature}[{dim}]"


def parse_norm_stats(blob: Mapping[str, Any]) -> tuple[NormScheme | None, dict[str, FeatureStats]]:
    """Extract normalization constants from a checkpoint's stats JSON.

    Recognizes the two schemes checkpoints actually ship: quantile (q01/q99, used by π0 and
    LeRobot) and mean/std. The scheme matters because it decides *which* dataset statistic
    ``policy_data.normalization_mismatch`` is allowed to compare against — comparing a q99
    to a mean would be a category error that manufactures mismatches.
    """
    stats: dict[str, FeatureStats] = {}
    scheme: NormScheme | None = None
    for key, entry in blob.items():
        if not isinstance(entry, Mapping):
            continue
        feature = str(key)
        q01 = _as_float_list(entry.get("q01") or entry.get("p01"))
        q99 = _as_float_list(entry.get("q99") or entry.get("p99"))
        mean = _as_float_list(entry.get("mean"))
        std = _as_float_list(entry.get("std"))
        if q01 and q99 and len(q01) == len(q99):
            scheme = scheme or NormScheme.QUANTILE_Q01_Q99
            for i, (lo, hi) in enumerate(zip(q01, q99, strict=True)):
                stats[norm_key(feature, i)] = FeatureStats(
                    mean=(lo + hi) / 2.0, std=0.0, min=lo, max=hi, q01=lo, q99=hi
                )
        elif mean and std and len(mean) == len(std):
            scheme = scheme or NormScheme.MEANSTD
            for i, (mu, sigma) in enumerate(zip(mean, std, strict=True)):
                stats[norm_key(feature, i)] = FeatureStats(
                    mean=mu, std=sigma, min=mu - 3.0 * sigma, max=mu + 3.0 * sigma
                )
    return scheme, stats


def _dims_from_config(config: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Pull expected action/proprio dims from the many names configs use for them."""

    def first_int(*keys: str) -> int | None:
        for key in keys:
            value = config.get(key)
            if isinstance(value, int) and value > 0:
                return value
            if isinstance(value, Mapping):  # nested, e.g. {"action": {"shape": [7]}}
                shape = value.get("shape")
                if isinstance(shape, (list, tuple)) and shape:
                    return int(shape[-1])
        return None

    action = first_int("action_dim", "action_size", "n_action_dims", "output_dim", "action")
    proprio = first_int("state_dim", "proprio_dim", "obs_state_dim", "n_obs_dims", "observation.state")
    return action, proprio


def load_policy_profile(path: str | Path) -> PolicyProfile:
    """Parse ``path`` into a :class:`PolicyProfile`. Never executes the checkpoint.

    Raises :class:`UnreadablePolicyError` for pickled containers and unreadable files.
    """
    p = Path(path)
    if not p.exists():
        raise UnreadablePolicyError(f"{p}: no such checkpoint")
    if p.is_file() and p.suffix.lower() in _PICKLE_SUFFIXES:
        _refuse_pickle(p)

    if p.is_dir():
        return _from_directory(p)
    if p.suffix.lower() in _SAFETENSORS_SUFFIXES:
        return _from_safetensors(p)
    if p.suffix.lower() in _ONNX_SUFFIXES:
        return _from_onnx(p)
    raise UnreadablePolicyError(
        f"{p.name}: unrecognized checkpoint container. Supported: a HuggingFace/LeRobot "
        "directory, .safetensors, or .onnx."
    )


def _from_directory(root: Path) -> PolicyProfile:
    config_path = _first_existing(root, _CONFIG_NAMES)
    config: dict[str, Any] = {}
    if config_path is not None:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UnreadablePolicyError(f"{config_path.name}: unreadable config JSON") from exc

    declared = " ".join(
        str(config.get(k, "")) for k in ("model_type", "architectures", "policy_type", "type", "_class_name")
    )
    family = infer_family(declared or root.name)
    action_dim, proprio_dim = _dims_from_config(config)

    scheme: NormScheme | None = None
    norm_stats: dict[str, FeatureStats] = {}
    norm_path = _first_existing(root, _NORM_NAMES)
    if norm_path is not None:
        try:
            scheme, norm_stats = parse_norm_stats(json.loads(norm_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            scheme, norm_stats = None, {}

    cameras = config.get("camera_keys") or config.get("image_keys")
    expected_cameras = tuple(str(c) for c in cameras) if isinstance(cameras, (list, tuple)) else None

    # If the directory also holds a safetensors file, its shapes beat the config, which is
    # frequently copy-pasted between models and therefore stale.
    for shard in sorted(root.glob("*.safetensors")):
        shard_action, shard_proprio = _dims_from_safetensors(read_safetensors_header(shard))
        action_dim = shard_action or action_dim
        proprio_dim = shard_proprio or proprio_dim
        break

    return PolicyProfile(
        family=family,
        expected_action_dim=action_dim,
        expected_proprio_dim=proprio_dim,
        expected_cameras=expected_cameras,
        norm_scheme=scheme,
        norm_stats=norm_stats or None,
        clamps_actions=family in CLAMPING_FAMILIES if family is not PolicyFamily.UNKNOWN else None,
    )


def _dims_from_safetensors(header: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Infer input/output widths from tensor shapes in a safetensors header.

    Heuristic and honest about it: the *last* layer whose name mentions the action head
    gives the action width; a projection named for the state gives the proprio width. When
    no name matches we return ``None`` rather than picking an arbitrary tensor.
    """
    action_dim: int | None = None
    proprio_dim: int | None = None
    for name, meta in header.items():
        if name == "__metadata__" or not isinstance(meta, Mapping):
            continue
        shape = meta.get("shape")
        if not isinstance(shape, (list, tuple)) or not shape:
            continue
        lowered = name.lower()
        if "weight" not in lowered:
            continue
        if action_dim is None and any(k in lowered for k in ("action_head", "action_out", "action_proj")):
            action_dim = int(shape[0])
        if proprio_dim is None and any(k in lowered for k in ("state_proj", "proprio_proj", "state_encoder")):
            proprio_dim = int(shape[-1])
    return action_dim, proprio_dim


def _from_safetensors(path: Path) -> PolicyProfile:
    header = read_safetensors_header(path)
    metadata = header.get("__metadata__", {})
    declared = " ".join(str(v) for v in metadata.values()) if isinstance(metadata, Mapping) else ""
    family = infer_family(declared or path.stem)
    action_dim, proprio_dim = _dims_from_safetensors(header)
    return PolicyProfile(
        family=family,
        expected_action_dim=action_dim,
        expected_proprio_dim=proprio_dim,
        clamps_actions=family in CLAMPING_FAMILIES if family is not PolicyFamily.UNKNOWN else None,
    )


def _from_onnx(path: Path) -> PolicyProfile:
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise UnreadablePolicyError(
            "reading .onnx checkpoints requires the optional dependency: pip install 'bohrin[onnx]'"
        ) from exc
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    action_dim: int | None = None
    proprio_dim: int | None = None
    for output in session.get_outputs():
        shape = [d for d in output.shape if isinstance(d, int)]
        if shape:
            action_dim = int(shape[-1])
            break
    for inp in session.get_inputs():
        name = inp.name.lower()
        shape = [d for d in inp.shape if isinstance(d, int)]
        if shape and len(shape) <= 2 and any(k in name for k in ("state", "proprio", "qpos")):
            proprio_dim = int(shape[-1])
            break
    return PolicyProfile(
        family=infer_family(path.stem),
        expected_action_dim=action_dim,
        expected_proprio_dim=proprio_dim,
    )
