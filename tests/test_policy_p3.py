"""POLICY↔DATA — checkpoint parsing and Family J (docs/06 P3 DoD).

The DoD item is *"with `--policy`, a proprio-dim mismatch and a norm-stat mismatch are both
caught"*. Both are asserted below, along with the property that matters just as much: the
family is **completely inert** without a checkpoint, so adding it changed no existing scan.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import _synth
import bohrin
from bohrin.ir.schema import NormScheme, PolicyFamily, PolicyProfile, Severity
from bohrin.policy.loader import (
    UnreadablePolicyError,
    infer_family,
    load_policy_profile,
    norm_key,
    parse_norm_stats,
    read_safetensors_header,
)
from bohrin.policy.target import UnknownTargetError, profile_for_target

_ACTION_DIM = 6


# ------------------------------------------------------------------ checkpoint fixtures


def write_hf_checkpoint(
    root: Path,
    *,
    model_type: str = "pi0",
    action_dim: int | None = _ACTION_DIM,
    state_dim: int | None = 7,
    q99: list[float] | None = None,
) -> Path:
    out = root / "ckpt"
    out.mkdir(parents=True, exist_ok=True)
    config: dict[str, object] = {"model_type": model_type}
    if action_dim is not None:
        config["action_dim"] = action_dim
    if state_dim is not None:
        config["state_dim"] = state_dim
    (out / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if q99 is not None:
        stats = {"action": {"q01": [-v for v in q99], "q99": q99}}
        (out / "norm_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    return out


def write_safetensors(path: Path, header: dict[str, object]) -> Path:
    blob = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(blob)) + blob + b"\x00" * 8)
    return path


# ----------------------------------------------------------------------- parsing safety


def test_pickled_checkpoints_are_refused_not_loaded(tmp_path: Path) -> None:
    """Unpickling executes arbitrary code; a static analyzer must never be the thing that runs it."""
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"\x80\x04\x95 fake pickle")
    with pytest.raises(UnreadablePolicyError, match="arbitrary code"):
        load_policy_profile(ckpt)


def test_missing_checkpoint_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(UnreadablePolicyError, match="no such checkpoint"):
        load_policy_profile(tmp_path / "absent.safetensors")


def test_safetensors_header_is_read_without_loading_tensors(tmp_path: Path) -> None:
    path = write_safetensors(
        tmp_path / "m.safetensors",
        {"__metadata__": {"arch": "octo"}, "action_head.weight": {"shape": [9, 128]}},
    )
    header = read_safetensors_header(path)
    assert header["__metadata__"] == {"arch": "octo"}
    profile = load_policy_profile(path)
    assert profile.family is PolicyFamily.OCTO
    assert profile.expected_action_dim == 9


def test_implausible_header_length_is_rejected(tmp_path: Path) -> None:
    """A corrupt length prefix must not become a multi-gigabyte allocation."""
    path = tmp_path / "bad.safetensors"
    path.write_bytes(struct.pack("<Q", 2**62) + b"{}")
    with pytest.raises(UnreadablePolicyError, match="implausible"):
        read_safetensors_header(path)


def test_family_inference_prefers_the_specific_name() -> None:
    assert infer_family("openvla-7b") is PolicyFamily.VLA_OPENVLA
    assert infer_family("pi0_fast") is PolicyFamily.VLA_PI0
    assert infer_family("some_diffusion_policy") is PolicyFamily.DIFFUSION
    assert infer_family("totally unknown") is PolicyFamily.UNKNOWN


def test_norm_stats_flatten_per_dimension() -> None:
    scheme, stats = parse_norm_stats({"action": {"q01": [-1.0, -2.0], "q99": [1.0, 2.0]}})
    assert scheme is NormScheme.QUANTILE_Q01_Q99
    assert stats[norm_key("action", 1)].q99 == 2.0


def test_meanstd_scheme_is_recognized_separately() -> None:
    scheme, stats = parse_norm_stats({"action": {"mean": [0.0], "std": [1.0]}})
    assert scheme is NormScheme.MEANSTD
    assert stats[norm_key("action", 0)].std == 1.0


# ------------------------------------------------------------------------- the DoD pair


def test_proprio_dim_mismatch_is_caught(tmp_path: Path) -> None:
    """docs/06 P3 DoD, half one."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=10))
    ckpt = write_hf_checkpoint(tmp_path, state_dim=12)  # dataset proprio is 6-D
    report = bohrin.scan(uri, policy=str(ckpt))

    cluster = report.cluster("policy_data.dim_mismatch")
    assert cluster is not None
    assert cluster.severity is Severity.HIGH
    assert "12" in cluster.title
    assert "bimanual" in cluster.mechanism  # 12 = 2×6 → the useful hint fires


def test_normalization_mismatch_is_caught(tmp_path: Path) -> None:
    """docs/06 P3 DoD, half two: the checkpoint's constants are far below the real range."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=12))
    ckpt = write_hf_checkpoint(tmp_path, state_dim=6, q99=[0.01] * _ACTION_DIM)
    report = bohrin.scan(uri, policy=str(ckpt))

    cluster = report.cluster("policy_data.normalization_mismatch")
    assert cluster is not None
    assert cluster.severity is Severity.HIGH
    assert cluster.findings[0].evidence.metrics["worst_ratio"] > 1.5


def test_matching_checkpoint_produces_no_policy_findings(tmp_path: Path) -> None:
    """The zero-false-HIGH bar applies to this family too."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=10))
    ckpt = write_hf_checkpoint(tmp_path, model_type="act", action_dim=6, state_dim=6)
    report = bohrin.scan(uri, policy=str(ckpt))
    assert report.cluster("policy_data.dim_mismatch") is None
    assert report.cluster("policy_data.missing_proprio") is None


# --------------------------------------------------------------------------- inertness


def test_family_is_inert_without_a_checkpoint() -> None:
    """Adding Family J must not change a single existing scan."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=10))
    report = bohrin.scan(uri)
    assert not [d for d in report.detectors_run if d.startswith("policy_data.")]


def test_policy_detectors_are_registered_but_not_applicable() -> None:
    from bohrin.detectors.registry import discover

    ids = {d.id for d in discover()}
    assert {f"policy_data.{n}" for n in ("dim_mismatch", "missing_proprio", "ood_estimate")} <= ids


# ------------------------------------------------------------------------------ --target


def test_target_flag_enables_family_level_checks() -> None:
    """π0 zero-fills absent proprio — catchable from the architecture name alone."""
    episodes = [_synth.strip_proprio(ep) for ep in _synth.clean_dataset(n_episodes=10)]
    uri = _synth.register_memory_dataset(episodes, schema=_synth.make_schema(proprio_dim=None))
    report = bohrin.scan(uri, target="pi0")
    cluster = report.cluster("policy_data.missing_proprio")
    assert cluster is not None
    assert cluster.severity is Severity.HIGH


def test_unknown_target_is_rejected_not_ignored() -> None:
    with pytest.raises(UnknownTargetError, match="Accepted values"):
        profile_for_target("gpt5")


def test_target_profile_carries_family_only() -> None:
    """It must not invent constants the user never supplied."""
    profile = profile_for_target("pi0")
    assert profile == PolicyProfile(family=PolicyFamily.VLA_PI0)
