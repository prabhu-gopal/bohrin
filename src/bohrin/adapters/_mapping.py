"""The schema mapper — how a *custom* container becomes Canonical IR (docs/02 §1.3).

LeRobot and RLDS declare their own schema, so their adapters read it. Everything else —
raw HDF5, a directory of ``.npz``, a Zarr replay buffer — is a bag of arrays with names
chosen by whoever recorded it. This module answers one question for those formats:

    given these array names and shapes, which one is the action, which the proprioception,
    which the timestamps, and which are cameras?

Two sources of truth, in priority order:

1. **Declared** — a ``bohrin.yaml`` written by ``bohrin init``. Always wins. This is the
   long-tail escape hatch: if inference is wrong, the user states the mapping once.
2. **Inferred** — name matching against the conventions actually used across the public
   corpora (robomimic, Diffusion Policy/UMI, DROID, and the ad-hoc layouts in between),
   then a shape-based tie-break.

Inference is deliberately **conservative**: when nothing matches confidently we return
``None`` and let the caller raise, rather than silently profiling the wrong array. A
detector battery pointed at the wrong column produces confident nonsense, which is worse
than an error message telling the user to run ``bohrin init``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: Candidate names for each role, most specific first. Matching is case-insensitive and
#: compares both the full key and its last path segment, so ``data/demo_0/actions`` and
#: ``actions`` both resolve. Sources: robomimic (``actions``, ``obs/``), Diffusion Policy
#: and UMI replay buffers (``action``, ``state``, ``robot0_eef_pos``), DROID/RLDS
#: (``action``, ``observation/state``).
_ACTION_NAMES = ("action", "actions", "act", "action_dict", "cmd", "command")
_PROPRIO_NAMES = (
    "observation.state",
    "observation/state",
    "proprio",
    "proprioception",
    "state",
    "states",
    "qpos",
    "joint_positions",
    "joint_position",
    "robot_state",
    "eef_pose",
    "robot0_eef_pos",
    "obs",
)
_TIMESTAMP_NAMES = ("timestamp", "timestamps", "time", "t", "stamp", "time_stamp")
_REWARD_NAMES = ("reward", "rewards", "r")
#: Substrings that mark an array as pixels rather than a low-dimensional signal.
_IMAGE_HINTS = ("image", "rgb", "camera", "cam", "img", "pixels", "wrist", "front", "side", "top")
_DEPTH_HINTS = ("depth", "disparity", "pointcloud", "point_cloud", "xyz")

#: An array is treated as pixels if it has this many dims (T, H, W[, C]) and a plausible
#: channel count. Shape is the tie-break when the *name* is uninformative.
_MIN_IMAGE_NDIM = 3
_IMAGE_CHANNELS = (1, 3, 4)


@dataclass(frozen=True, slots=True)
class ArrayInfo:
    """What the mapper needs to know about one candidate array: its name and shape."""

    key: str
    shape: tuple[int, ...]

    @property
    def leaf(self) -> str:
        """The last path segment, lowercased — ``data/demo_0/actions`` → ``actions``."""
        return self.key.replace("\\", "/").rsplit("/", 1)[-1].lower()

    @property
    def ndim(self) -> int:
        return len(self.shape)


@dataclass(frozen=True, slots=True)
class SchemaMapping:
    """The resolved answer: which key plays which role."""

    action: str
    proprio: str | None = None
    timestamp: str | None = None
    reward: str | None = None
    images: tuple[str, ...] = ()
    depth: tuple[str, ...] = ()

    @property
    def used_keys(self) -> frozenset[str]:
        """Every key this mapping claims — the caller may treat the rest as unused."""
        named = {self.action, self.proprio, self.timestamp, self.reward}
        return frozenset({k for k in named if k} | set(self.images) | set(self.depth))


class UnmappableDatasetError(ValueError):
    """Raised when no array can be identified as the action — the one required column.

    Carries the candidate keys, because the fix is always "tell me which one it is".
    """

    def __init__(self, keys: Sequence[str]) -> None:
        listed = ", ".join(sorted(keys)[:12]) or "(none)"
        super().__init__(
            "could not identify the action array in this dataset. "
            f"Candidate arrays: {listed}. "
            "Run `bohrin init <path>` to declare the mapping in a bohrin.yaml, "
            "or pass --format to select a different adapter."
        )


def _match(info: ArrayInfo, names: Sequence[str]) -> int | None:
    """Rank of the first matching name (lower is better), or ``None``."""
    leaf, full = info.leaf, info.key.lower()
    for rank, name in enumerate(names):
        if leaf == name or full == name or full.endswith("/" + name):
            return rank
    return None


def _is_image(info: ArrayInfo) -> bool:
    if any(h in info.key.lower() for h in _DEPTH_HINTS):
        return False
    if any(h in info.key.lower() for h in _IMAGE_HINTS):
        return info.ndim >= _MIN_IMAGE_NDIM
    # Name says nothing — fall back to shape: (T, H, W) or (T, H, W, C).
    if info.ndim == 4:
        return info.shape[-1] in _IMAGE_CHANNELS
    return False


def _is_depth(info: ArrayInfo) -> bool:
    return any(h in info.key.lower() for h in _DEPTH_HINTS) and info.ndim >= _MIN_IMAGE_NDIM


def _pick(arrays: Sequence[ArrayInfo], names: Sequence[str], *, exclude: frozenset[str]) -> str | None:
    """The best-matching key for a role, or ``None`` if nothing matches."""
    ranked: list[tuple[int, str]] = []
    for a in arrays:
        if a.key in exclude:
            continue
        rank = _match(a, names)
        if rank is not None:
            ranked.append((rank, a.key))
    return min(ranked)[1] if ranked else None


def _widest_2d(arrays: Sequence[ArrayInfo], *, exclude: frozenset[str]) -> str | None:
    """The widest ``(T, D)`` array — the shape-based fallback for the action column."""
    candidates = [a for a in arrays if a.ndim == 2 and a.key not in exclude and not _is_image(a)]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (a.shape[1], a.key)).key


def infer_mapping(
    arrays: Sequence[ArrayInfo],
    declared: Mapping[str, object] | None = None,
    *,
    allow_shape_fallback: bool = True,
) -> SchemaMapping:
    """Resolve array names to IR roles. Declared entries always beat inference.

    ``declared`` is the ``schema_map`` section of a ``bohrin.yaml``; recognized keys are
    ``action``, ``proprio``, ``timestamp``, ``reward``, ``images`` and ``depth``.

    Raises :class:`UnmappableDatasetError` if the action column cannot be identified —
    guessing it would mean profiling an arbitrary array and reporting the result as fact.
    """
    declared = declared or {}
    present = {a.key for a in arrays}

    def declared_str(role: str) -> str | None:
        value = declared.get(role)
        return str(value) if isinstance(value, str) else None

    def declared_seq(role: str) -> tuple[str, ...]:
        value = declared.get(role)
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(str(v) for v in value)
        return ()

    action = declared_str("action") or _pick(arrays, _ACTION_NAMES, exclude=frozenset())
    if action is None and allow_shape_fallback:
        action = _widest_2d(arrays, exclude=frozenset())
    if action is None or action not in present:
        raise UnmappableDatasetError(sorted(present))

    claimed = {action}
    proprio = declared_str("proprio") or _pick(arrays, _PROPRIO_NAMES, exclude=frozenset(claimed))
    if proprio:
        claimed.add(proprio)
    timestamp = declared_str("timestamp") or _pick(arrays, _TIMESTAMP_NAMES, exclude=frozenset(claimed))
    if timestamp:
        claimed.add(timestamp)
    reward = declared_str("reward") or _pick(arrays, _REWARD_NAMES, exclude=frozenset(claimed))
    if reward:
        claimed.add(reward)

    images = declared_seq("images") or tuple(sorted(a.key for a in arrays if a.key not in claimed and _is_image(a)))
    depth = declared_seq("depth") or tuple(sorted(a.key for a in arrays if a.key not in claimed and _is_depth(a)))

    return SchemaMapping(
        action=action,
        proprio=proprio,
        timestamp=timestamp,
        reward=reward,
        images=images,
        depth=depth,
    )
