"""Test-only synthetic data + a memory adapter.

This is **not** shipped — it lives in the test suite so CI never needs a real dataset.

The baseline :func:`clean_dataset` is deliberately *diverse*: varied starting configurations,
varied drift directions and varied durations. That matters because the COVERAGE family is
supposed to complain about uniformity, so a "clean" fixture that was secretly uniform would
make those detectors look like false positives. Every fault injector plants exactly one
defect on top of that baseline.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.adapters.base import Adapter, DatasetHandle, Sampler
from bohrin.adapters.registry import register_adapter
from bohrin.calibrate.corpus import CalibrationCorpus
from bohrin.config import ScanConfig
from bohrin.detectors.base import AnalysisContext
from bohrin.ir.episode import Episode, StepView, TaskLabel
from bohrin.ir.schema import (
    ActionSpace,
    CameraSpec,
    DatasetSchema,
    FeatureStats,
    NormScheme,
    PolicyFamily,
    PolicyProfile,
    Provenance,
    SchemaHints,
)
from bohrin.policy.loader import norm_key
from bohrin.profile.dataset_profile import ProfileBuilder

_DEFAULT_HZ = 20.0
_DEFAULT_NAMES = ("x", "y", "z", "roll", "pitch", "grip")
_NOISE = 0.02


def make_schema(
    *,
    action_dim: int = 6,
    proprio_dim: int | None = 6,
    control_hz: float = _DEFAULT_HZ,
    embodiment: str = "synth_arm",
    action_space: ActionSpace = ActionSpace.EEF_DELTA,
    cameras: tuple[CameraSpec, ...] = (),
) -> DatasetSchema:
    names = _DEFAULT_NAMES[:action_dim]
    return DatasetSchema(
        action_dim=action_dim,
        action_space=action_space,
        action_names=names,
        proprio_dim=proprio_dim,
        proprio_names=names[:proprio_dim] if proprio_dim else None,
        control_hz=control_hz,
        embodiment=embodiment,
        cameras=cameras,
    )


def vision_schema(*, keys: Sequence[str] = ("front", "wrist")) -> DatasetSchema:
    """A schema that *declares* its cameras.

    ``vision.compression_artifacts`` iterates ``schema.cameras`` rather than the episodes'
    image keys, so a vision fixture built on the default (camera-less) schema leaves it inert.
    """
    return make_schema(cameras=tuple(CameraSpec(key=k, height=16, width=16) for k in keys))


def integrate(deltas: FloatArray, start: FloatArray | None = None) -> FloatArray:
    """State trajectory where ``proprio[t+1] - proprio[t] == action[t]`` (zero-lag convention)."""
    proprio = np.zeros_like(deltas)
    proprio[1:] = np.cumsum(deltas[:-1], axis=0)
    if start is not None:
        proprio = proprio + start
    return proprio


def _episode(
    index: int,
    action: FloatArray,
    proprio: FloatArray | None,
    *,
    prefix: str = "ep",
    task: str | None = None,
    hz: float = _DEFAULT_HZ,
) -> Episode:
    ts = np.arange(action.shape[0], dtype=np.float64) / hz
    view = StepView(action=action, timestamp=ts, proprio=proprio)
    src = Provenance(adapter="memory", uri="mem:synth", locator=f"episode_{index:04d}")
    label = TaskLabel(text=task) if task else None
    return Episode(episode_id=f"{prefix}{index:04d}", steps=view, source=src, task=label, success=True)


def clean_episode(schema: DatasetSchema, index: int, *, seed: int = 0, length: int | None = None) -> Episode:
    """A smooth, well-formed, *distinct* demonstration.

    Diverse by construction: its own start pose, its own drift direction, its own duration.
    Triggers no detector.
    """
    rng = np.random.default_rng((seed, index))
    dim = schema.action_dim
    n = length if length is not None else int(rng.integers(40, 56))
    start = rng.normal(0.0, 0.5, size=dim)
    direction = rng.normal(0.0, 1.0, size=dim)
    direction /= max(float(np.linalg.norm(direction)), 1e-9)
    action: FloatArray = rng.normal(0.0, _NOISE, size=(n, dim)) + 0.01 * direction
    return _episode(index, action, integrate(action, start))


def clean_dataset(
    *,
    n_episodes: int = 16,
    schema: DatasetSchema | None = None,
    seed: int = 0,
    length: int | None = None,
) -> list[Episode]:
    schema = schema or make_schema()
    return [clean_episode(schema, i, seed=seed, length=length) for i in range(n_episodes)]


# --------------------------------------------------------------------- simple injectors


def _copy(arr: FloatArray | None) -> FloatArray:
    return np.array(arr, dtype=np.float64)


def _set_action(ep: Episode, action: FloatArray) -> Episode:
    return replace(ep, steps=replace(ep.steps, action=action))


def _set_proprio(ep: Episode, proprio: FloatArray) -> Episode:
    return replace(ep, steps=replace(ep.steps, proprio=proprio))


def strip_proprio(ep: Episode) -> Episode:
    """Drop the proprioception column — a vision-only recording (docs/04 §J)."""
    return replace(ep, steps=replace(ep.steps, proprio=None))


def with_task(ep: Episode, task: str | None) -> Episode:
    return replace(ep, task=TaskLabel(text=task) if task else None)


def inject_nan(ep: Episode, *, dim: int = 0, step: int = 5) -> Episode:
    action = _copy(ep.steps.action)
    action[step, dim] = np.nan
    return _set_action(ep, action)


def inject_dead_dimension(episodes: Sequence[Episode], *, dim: int = 3) -> list[Episode]:
    out: list[Episode] = []
    for ep in episodes:
        action = _copy(ep.steps.action)
        action[:, dim] = 0.0
        out.append(_set_action(ep, action))
    return out


def inject_shape_mismatch(ep: Episode) -> Episode:
    action = _copy(ep.steps.action)[:, :-1]
    return replace(ep, steps=replace(ep.steps, action=action, proprio=None))


def inject_timestamp_gap(ep: Episode, *, at: int = 10, gap: float = 2.0) -> Episode:
    ts = _copy(ep.steps.timestamp)
    ts[at:] += gap
    return replace(ep, steps=replace(ep.steps, timestamp=ts))


def inject_duplicate_run(ep: Episode, *, at: int = 5, run: int = 15) -> Episode:
    action = _copy(ep.steps.action)
    action[at : at + run] = action[at]
    if ep.steps.proprio is not None:
        proprio = _copy(ep.steps.proprio)
        proprio[at : at + run] = proprio[at]
        ep = _set_proprio(ep, proprio)
    return _set_action(ep, action)


def inject_jerk(ep: Episode, *, factor: float = 8.0) -> Episode:
    rng = np.random.default_rng(999)
    action = _copy(ep.steps.action)
    noise = rng.normal(0.0, _NOISE * factor, size=action.shape)
    noise[::2] *= -1
    action = action + noise
    return _set_proprio(_set_action(ep, action), integrate(action))


def inject_jump(ep: Episode, *, at: int = 15, magnitude: float = 5.0) -> Episode:
    proprio = _copy(ep.steps.proprio)
    proprio[at:] += magnitude
    return _set_proprio(ep, proprio)


def inject_idle(ep: Episode, *, lead: int = 25) -> Episode:
    action = _copy(ep.steps.action)
    proprio = _copy(ep.steps.proprio)
    action[:lead] = 0.0
    proprio[:lead] = proprio[0]
    return _set_proprio(_set_action(ep, action), proprio)


def inject_outlier(ep: Episode, *, dim: int = 0, value: float = 50.0, step: int = 0) -> Episode:
    action = _copy(ep.steps.action)
    action[step, dim] = value
    return _set_action(ep, action)


def inject_lag(episodes: Sequence[Episode], *, shift: int = 2) -> list[Episode]:
    """Log actions ``shift`` steps out of phase with the state change they cause."""
    out: list[Episode] = []
    for ep in episodes:
        deltas = _copy(ep.steps.action)
        proprio = integrate(deltas)
        lagged: FloatArray = np.roll(deltas, shift, axis=0)
        lagged[:shift] = 0.0
        out.append(_set_proprio(_set_action(ep, lagged), proprio))
    return out


def inject_saturation(episodes: Sequence[Episode], *, dim: int = 0, frac: float = 0.4) -> list[Episode]:
    out: list[Episode] = []
    for ep in episodes:
        action = _copy(ep.steps.action)
        n = int(action.shape[0] * frac)
        action[:n, dim] = 1.0
        out.append(_set_action(ep, action))
    return out


def truncated_dataset(*, n_episodes: int = 16, short_at: int = 0) -> list[Episode]:
    schema = make_schema()
    episodes = [clean_episode(schema, i, length=40) for i in range(n_episodes)]
    episodes[short_at] = clean_episode(schema, short_at, length=5)
    return episodes


# --------------------------------------------------------------- Phase-2 fault datasets


def copycat_dataset(*, n_episodes: int = 16, seed: int = 0, length: int = 60) -> list[Episode]:
    """Actions are a strongly autocorrelated random walk → high previous-action R²."""
    dim = 6
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 7))
        walk: FloatArray = np.cumsum(rng.normal(0.0, _NOISE, size=(length, dim)), axis=0)
        out.append(_episode(i, walk, walk.copy(), prefix="cc"))
    return out


def single_strategy_dataset(*, n_episodes: int = 16, seed: int = 0, length: int = 48) -> list[Episode]:
    """Every demo follows essentially the same path → mode collapse / thin tube / narrow init."""
    dim = 6
    nominal = np.random.default_rng(seed).normal(0.0, _NOISE, size=(length, dim))
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 11))
        action: FloatArray = nominal + rng.normal(0.0, _NOISE * 0.02, size=nominal.shape)
        out.append(_episode(i, action, integrate(action), prefix="ss"))
    return out


def narrow_init_dataset(*, n_episodes: int = 16, seed: int = 0) -> list[Episode]:
    """Diverse motions but every demo starts from the same configuration."""
    schema = make_schema()
    out: list[Episode] = []
    for i in range(n_episodes):
        ep = clean_episode(schema, i, seed=seed, length=48)
        action = _copy(ep.steps.action)
        out.append(_episode(i, action, integrate(action), prefix="ni"))  # start fixed at 0
    return out


def redundant_dataset(*, n_distinct: int = 4, copies: int = 4, seed: int = 0) -> list[Episode]:
    """A handful of distinct demos, each repeated — high count, low effective diversity."""
    schema = make_schema()
    base = [clean_episode(schema, i, seed=seed, length=48) for i in range(n_distinct)]
    out: list[Episode] = []
    k = 0
    for ep in base:
        for _ in range(copies):
            rng = np.random.default_rng((seed, k, 13))
            action = _copy(ep.steps.action) + rng.normal(0.0, 1e-4, size=ep.steps.action.shape)
            out.append(_episode(k, action, integrate(action, _copy(ep.steps.proprio)[0]), prefix="rd"))
            k += 1
    return out


def teleport_dataset(*, n_episodes: int = 12, seed: int = 0, at: int = 20) -> list[Episode]:
    """One episode contains a physically impossible jump the action does not explain."""
    schema = make_schema()
    episodes = [clean_episode(schema, i, seed=seed, length=48) for i in range(n_episodes)]
    episodes[3] = inject_jump(episodes[3], at=at, magnitude=5.0)
    return episodes


def contradictory_dataset(*, n_episodes: int = 16, seed: int = 0, length: int = 48) -> list[Episode]:
    """At overlapping states the demos take two opposite actions → genuine multimodality."""
    dim = 6
    direction = np.zeros(dim)
    direction[0] = 1.0
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 17))
        sign = 1.0 if i % 2 == 0 else -1.0
        action: FloatArray = sign * 0.1 * direction + rng.normal(0.0, 0.005, size=(length, dim))
        # States stay in a shared region so the two action modes occupy the same neighbourhood.
        proprio: FloatArray = rng.normal(0.0, 0.05, size=(length, dim))
        out.append(_episode(i, action, proprio, prefix="cd"))
    return out


def two_style_dataset(*, n_episodes: int = 16, seed: int = 0) -> list[Episode]:
    """Half the demos are fast and loose, half are slow and precise."""
    dim = 6
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 19))
        fast = i % 2 == 0
        n = 30 if fast else 90
        scale = _NOISE * (4.0 if fast else 0.5)
        action: FloatArray = rng.normal(0.0, scale, size=(n, dim))
        out.append(_episode(i, action, integrate(action), prefix="st"))
    return out


def dtw_outlier_dataset(*, n_episodes: int = 12, seed: int = 0, length: int = 48) -> list[Episode]:
    """Consistent demos plus one that runs the trajectory backwards."""
    dim = 6
    nominal = np.random.default_rng(seed).normal(0.0, _NOISE, size=(length, dim))
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 23))
        action: FloatArray = nominal + rng.normal(0.0, _NOISE * 0.05, size=nominal.shape)
        proprio = integrate(action)
        if i == n_episodes - 1:
            proprio = proprio[::-1].copy() * 6.0  # a decisively different path
        out.append(_episode(i, action, proprio, prefix="dt"))
    return out


def varied_duration_dataset(*, n_episodes: int = 16, seed: int = 0) -> list[Episode]:
    """Same task, wildly inconsistent pacing."""
    schema = make_schema()
    lengths = [20, 40, 60, 90, 140, 200, 30, 170]
    return [clean_episode(schema, i, seed=seed, length=lengths[i % len(lengths)]) for i in range(n_episodes)]


def drift_dataset(*, n_episodes: int = 16, seed: int = 0, length: int = 48) -> list[Episode]:
    """The second half of the collection comes from a shifted distribution."""
    dim = 6
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 29))
        shifted = i >= n_episodes // 2
        offset = 0.6 if shifted else 0.0
        scale = _NOISE * (3.0 if shifted else 1.0)
        action: FloatArray = rng.normal(offset, scale, size=(length, dim))
        out.append(_episode(i, action, integrate(action), prefix="dr"))
    return out


def proprio_shortcut_dataset(*, n_episodes: int = 12, seed: int = 0, length: int = 48) -> list[Episode]:
    """The action is a deterministic linear function of the current state."""
    dim = 6
    weights = np.random.default_rng(seed).normal(0.0, 1.0, size=(dim, dim))
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 31))
        proprio: FloatArray = rng.normal(0.0, 0.5, size=(length, dim))
        action: FloatArray = proprio @ weights + rng.normal(0.0, 1e-4, size=(length, dim))
        out.append(_episode(i, action, proprio, prefix="ps"))
    return out


def labelled_dataset(
    *, n_episodes: int = 16, seed: int = 0, mislabel_at: int | None = None, drop_labels: int = 0
) -> list[Episode]:
    """Two visibly different tasks, correctly labelled unless asked otherwise."""
    dim = 6
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 37))
        group = i % 2
        direction = np.zeros(dim)
        direction[group] = 1.0
        action: FloatArray = 0.05 * direction + rng.normal(0.0, 0.002, size=(48, dim))
        task = "open the drawer" if group == 0 else "fold the towel"
        if mislabel_at is not None and i == mislabel_at:
            task = "fold the towel" if group == 0 else "open the drawer"
        if i < drop_labels:
            task = ""
        out.append(_episode(i, action, integrate(action), prefix="lb", task=task or None))
    return out


def ambiguous_label_dataset(*, n_episodes: int = 16, seed: int = 0) -> list[Episode]:
    """One instruction covering two clearly different motions."""
    episodes = labelled_dataset(n_episodes=n_episodes, seed=seed)
    return [with_task(ep, "do the thing") for ep in episodes]


# ------------------------------------------------------------------- vision fixtures


@dataclass(frozen=True)
class ArrayImage:
    """A materialized image that satisfies the :class:`~bohrin.ir.episode.LazyImage` protocol."""

    data: FloatArray

    @property
    def shape(self) -> tuple[int, int, int]:
        h, w, c = self.data.shape
        return int(h), int(w), int(c)

    def array(self) -> FloatArray:
        return self.data


def scene(rng: np.random.Generator) -> FloatArray:
    """A distinct 'scene': a 4×4 grid of random colour blocks upsampled to 16×16×3."""
    tiles = rng.integers(0, 255, size=(4, 4, 3)).astype(np.float64)
    base: FloatArray = np.repeat(np.repeat(tiles, 4, axis=0), 4, axis=1)
    return base


def _frames(
    rng: np.random.Generator,
    n: int,
    base: FloatArray,
    *,
    sharp: bool = True,
    shift: float = 0.0,
    blown_out: bool = False,
    flat_backdrop: bool = False,
) -> list[ArrayImage]:
    """Frames of one scene: the base plus small per-frame sensor noise.

    ``blown_out`` is genuine overexposure — the sensor pinned at its limit, so detail is gone.
    ``flat_backdrop`` keeps a sharp subject in front of a saturated *background*, which is what a
    rendered benchmark looks like and must **not** be reported as bad exposure.
    """
    out: list[ArrayImage] = []
    for _ in range(n):
        # A flat frame has near-zero Laplacian variance → reads as "blurred".
        img = base + rng.normal(0.0, 3.0, size=base.shape) if sharp else np.full(base.shape, 128.0)
        if blown_out:
            img = np.full(base.shape, 255.0)
        elif flat_backdrop:
            # Most of the frame pinned at white, with the original sharp scene left in a corner.
            img = np.full(base.shape, 255.0)
            h, w = base.shape[0] // 4, base.shape[1] // 4
            img[:h, :w] = base[:h, :w] + rng.normal(0.0, 3.0, size=base[:h, :w].shape)
        out.append(ArrayImage(np.clip(img + shift, 0.0, 255.0)))
    return out


def vision_dataset(
    *,
    n_episodes: int = 10,
    length: int = 24,
    seed: int = 0,
    frozen_at: int | None = None,
    blur: bool = False,
    drop_camera_at: int | None = None,
    viewpoint_shift_at: int | None = None,
    depth_holes: bool = False,
    single_scene: bool = False,
    blown_out: bool = False,
    flat_backdrop: bool = False,
) -> list[Episode]:
    """A dataset with camera streams, optionally carrying one planted vision defect.

    By default every episode is recorded in its *own* scene (good scene diversity). With
    ``single_scene=True`` all episodes share one scene — the Data-Scaling-Laws defect.
    """
    dim = 6
    shared = scene(np.random.default_rng((seed, 777)))
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 41))
        action: FloatArray = rng.normal(0.0, _NOISE, size=(length, dim)) + 0.01
        proprio = integrate(action)
        shift = 60.0 if viewpoint_shift_at is not None and i >= viewpoint_shift_at else 0.0
        sharp = not (blur and i < n_episodes // 2)
        # Applied to half the episodes, like `blur`: the sharpness floor is relative to the
        # dataset median, so a defect present in *every* frame moves the median with it and
        # becomes invisible by construction.
        blown = blown_out and i < n_episodes // 2
        # A camera bump is only detectable against a stable scene, so viewpoint-drift
        # fixtures share one scene the way a real fixed workspace would.
        stable = single_scene or viewpoint_shift_at is not None
        base = shared if stable else scene(rng)
        if frozen_at is not None and i == frozen_at:
            still = _frames(rng, 1, base, sharp=True)[0]
            frames = [still] * length
        else:
            frames = _frames(
                rng,
                length,
                base,
                sharp=sharp,
                shift=shift,
                blown_out=blown,
                flat_backdrop=flat_backdrop,
            )
        images: dict[str, Sequence[ArrayImage]] = {"front": frames}
        if not (drop_camera_at is not None and i < drop_camera_at):
            images["wrist"] = _frames(
                rng,
                length,
                scene(rng),
                sharp=True,
                blown_out=blown,
                flat_backdrop=flat_backdrop,
            )
        depth: dict[str, Sequence[ArrayImage]] = {}
        if depth_holes:
            holes: FloatArray = np.zeros((16, 16, 1), dtype=np.float64)  # 0 = invalid depth
            depth = {"front": [ArrayImage(holes)] * length}
        ts = np.arange(length, dtype=np.float64) / _DEFAULT_HZ
        view = StepView(action=action, timestamp=ts, proprio=proprio, images=images, depth=depth)
        src = Provenance(adapter="memory", uri="mem:vision", locator=f"episode_{i:04d}")
        out.append(Episode(episode_id=f"vs{i:04d}", steps=view, source=src, success=True))
    return out


# --------------------------------------------------------------------------- adapter


@dataclass(frozen=True)
class _MemoryDataset:
    episodes: tuple[Episode, ...]
    schema: DatasetSchema
    hints: SchemaHints


_REGISTRY: dict[str, _MemoryDataset] = {}


class _MemoryHandle:
    def __init__(self, dataset: _MemoryDataset) -> None:
        self._dataset = dataset

    def schema(self) -> DatasetSchema:
        return self._dataset.schema

    def profile_hints(self) -> SchemaHints:
        return self._dataset.hints

    def episode_count(self) -> int | None:
        return len(self._dataset.episodes)

    def iter_episodes(self, *, sample: Sampler) -> Iterator[Episode]:
        keep = set(sample.plan(len(self._dataset.episodes)).tolist())
        for i, ep in enumerate(self._dataset.episodes):
            if i in keep:
                yield ep


class MemoryAdapter(Adapter):
    """Serves an in-memory dataset registered via :func:`register_memory_dataset`."""

    name = "memory"

    def detect(self, path: Path) -> float:
        return 1.0 if str(path).startswith("mem:") else 0.0

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        return _MemoryHandle(_REGISTRY[str(path)])


register_adapter(MemoryAdapter)


def register_memory_dataset(
    episodes: Sequence[Episode],
    *,
    schema: DatasetSchema | None = None,
    hints: SchemaHints | None = None,
) -> str:
    """Register a dataset and return a ``mem:…`` path that ``bohrin.scan`` can open."""
    token = f"mem:{uuid.uuid4()}"  # single-colon scheme survives Path() normalization
    _REGISTRY[token] = _MemoryDataset(
        episodes=tuple(episodes),
        schema=schema or make_schema(),
        hints=hints or SchemaHints.empty(),
    )
    return token


def build_context(
    episodes: Sequence[Episode],
    *,
    schema: DatasetSchema | None = None,
    hints: SchemaHints | None = None,
    config: ScanConfig | None = None,
    policy: PolicyProfile | None = None,
    corpus: CalibrationCorpus | None = None,
) -> AnalysisContext:
    """Build an :class:`AnalysisContext` directly from episodes for unit-testing detectors."""
    schema = schema or make_schema()
    hints = hints or SchemaHints.empty()
    config = config or ScanConfig(path="mem:test")
    builder = ProfileBuilder(schema, hints, np.random.default_rng(1))
    for ep in episodes:
        builder.add(ep)
    profile = builder.finalize()
    return AnalysisContext(
        profile=profile,
        schema=schema,
        episodes=list(episodes),
        config=config,
        rng=np.random.default_rng(0),
        policy=policy,
        corpus=corpus or CalibrationCorpus.empty(),
    )


def smooth_demo(index: int, *, length: int = 60, erratic: bool = False, seed: int = 0) -> Episode:
    """A *smooth* reach-and-place trajectory — what real demonstrations actually look like.

    ``clean_dataset`` builds random-walk trajectories, which is right for testing statistics
    but wrong for testing path *shape*: a random walk turns constantly, so curvature is
    saturated and an erratic episode cannot stand out. This fixture is the realistic
    counterpart, and it is what makes ``smoothness.curvature`` falsifiable.
    """
    rng = np.random.default_rng(seed + index)
    schema = make_schema()
    t = np.linspace(0.0, 1.0, length)
    traj = np.zeros((length, schema.action_dim), dtype=np.float64)
    traj[:, 0] = t * rng.uniform(0.8, 1.2)
    traj[:, 1] = 0.3 * np.sin(np.pi * t) * rng.uniform(0.8, 1.2)
    traj[:, 2] = t * 0.2
    if erratic:
        traj[:, 1] += 0.15 * np.sin(2.0 * np.pi * t * 6.0)
    proprio = traj + rng.normal(0.0, 0.002, traj.shape)
    # Forward difference, matching the zero-lag convention `integrate` documents:
    # action[t] is the delta that *produces* proprio[t+1]. A backward difference here made
    # this fixture read as lagged data, so `temporal.action_observation_lag` and the DYNAMICS
    # residuals fired on a dataset meant to be clean — which silently disqualified it from
    # any test that scans it (calibration collection refuses datasets reporting HIGH).
    action = np.zeros_like(proprio)
    action[:-1] = np.diff(proprio, axis=0)
    src = Provenance(adapter="memory", uri="mem:synth", locator=f"episode_{index:04d}")
    return Episode(
        episode_id=f"ep{index:04d}",
        steps=StepView(
            action=action,
            proprio=proprio,
            timestamp=np.arange(length, dtype=np.float64) / _DEFAULT_HZ,
        ),
        source=src,
        success=True,
    )


def smooth_dataset(*, n_episodes: int = 16, erratic_at: Sequence[int] = (), seed: int = 0) -> list[Episode]:
    """A dataset of smooth demos, optionally with erratic ones planted at given indices.

    ``seed`` is threaded through so the benchmark gets an independent draw per trial rather
    than measuring the same dataset fifteen times.
    """
    return [smooth_demo(i, erratic=i in set(erratic_at), seed=seed) for i in range(n_episodes)]


# ------------------------------------------------------------- benchmark-completion fixtures
#
# Everything below exists so that *every* registered detector has a measured clean/faulted
# pair in the fault-injection benchmark. Each fixture plants exactly one defect on a baseline
# that its own detector considers clean — a "faulted" fixture that also trips other detectors
# would still measure recall correctly, but a "clean" one that trips its own detector would
# silently invert the measurement, so the clean side is the one to be careful with.


def wandering_dataset(*, n_episodes: int = 16, seed: int = 0, wander_at: Sequence[int] = (3,)) -> list[Episode]:
    """Direct reaches, except a few episodes that loop around before arriving.

    The detour is added *between* the endpoints so the straight-line distance stays
    comparable to the rest of the dataset — otherwise the episode is excluded as
    non-judgeable rather than reported as wandering.
    """
    out: list[Episode] = []
    wander = set(wander_at)
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 61))
        length = 60
        t = np.linspace(0.0, 1.0, length)
        proprio = np.zeros((length, 6), dtype=np.float64)
        proprio[:, 0] = t * rng.uniform(0.9, 1.1)
        proprio[:, 1] = 0.05 * np.sin(np.pi * t)
        if i in wander:
            # Several full loops orthogonal to the travel direction: much more path length
            # for the same displacement.
            proprio[:, 1] += 0.6 * np.sin(8.0 * np.pi * t)
            proprio[:, 2] += 0.6 * np.cos(8.0 * np.pi * t) - 0.6
        proprio += rng.normal(0.0, 0.001, proprio.shape)
        action = np.zeros_like(proprio)
        action[:-1] = np.diff(proprio, axis=0)
        out.append(_episode(i, action, proprio, prefix="wd"))
    return out


def _binary_gripper_dataset(*, n_episodes: int, seed: int, toggles: int, length: int = 60) -> list[Episode]:
    """Trajectories whose last action channel is a genuine binary gripper signal."""
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 67))
        action = np.zeros((length, 6), dtype=np.float64)
        action[:, :5] = rng.normal(0.0, _NOISE, size=(length, 5)) + 0.01
        # `_gripper_index` only trusts the last channel when its mass sits at the extremes,
        # so the signal has to be actually binary rather than merely bounded.
        grip = np.zeros(length, dtype=np.float64)
        if toggles > 0:
            period = max(1, length // (toggles + 1))
            grip = ((np.arange(length) // period) % 2).astype(np.float64)
        action[:, 5] = grip
        out.append(_episode(i, action, integrate(action), prefix="gr", hz=_DEFAULT_HZ))
    return out


def steady_gripper_dataset(*, n_episodes: int = 12, seed: int = 0) -> list[Episode]:
    """One deliberate open→close per demo: normal manipulation, not chatter."""
    return _binary_gripper_dataset(n_episodes=n_episodes, seed=seed, toggles=1)


def chattering_gripper_dataset(*, n_episodes: int = 12, seed: int = 0) -> list[Episode]:
    """A gripper toggling far faster than any real regrasp."""
    return _binary_gripper_dataset(n_episodes=n_episodes, seed=seed, toggles=40)


def pause_conflict_dataset(*, n_episodes: int = 12, seed: int = 0, length: int = 60) -> list[Episode]:
    """The operator holds still, then acts differently from the *same* state.

    The non-Markovian signature: a state is revisited (because the arm is stationary) while
    the actions issued from it disagree, so no state-conditioned single-step policy can fit
    both.
    """
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 71))
        proprio = np.cumsum(rng.normal(0.0, _NOISE, size=(length, 6)), axis=0)
        action = np.zeros_like(proprio)
        action[:-1] = np.diff(proprio, axis=0)
        # Freeze the state for a stretch, and disagree about what to do while frozen.
        hold = slice(20, 34)
        proprio[hold] = proprio[20]
        action[hold] = 0.0
        action[20:34:2] = 1.5  # every other frozen step commands a large, contradictory move
        out.append(_episode(i, action, proprio, prefix="pz"))
    return out


def degenerate_channel_dataset(*, n_episodes: int = 12, seed: int = 0, dim: int = 2) -> list[Episode]:
    """One channel that still moves, but only by sensor-noise amounts."""
    episodes = clean_dataset(n_episodes=n_episodes, seed=seed, length=48)
    out: list[Episode] = []
    for ep in episodes:
        action = _copy(ep.steps.action)
        action[:, dim] *= 1e-4  # nonzero, so `stats.dead_dimension` does not own this case
        out.append(_set_proprio(_set_action(ep, action), integrate(action)))
    return out


def mixed_units_dataset(*, n_episodes: int = 12, seed: int = 0) -> list[Episode]:
    """Half the channels in radians, half in degrees — the classic silent unit mix."""
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 73))
        action = rng.uniform(-1.5, 1.5, size=(48, 6))  # radians: range ≈ 3
        action[:, 3:] *= 120.0  # degrees: range ≈ 360
        out.append(_episode(i, action, integrate(action), prefix="mu"))
    return out


def declared_stats_hints(*, std: float, key: str = "action") -> SchemaHints:
    """Hints declaring a per-feature std, for ``integrity.declared_mismatch``."""
    return SchemaHints(
        declared_stats={key: FeatureStats(mean=0.0, std=std, min=-1.0, max=1.0)},
    )


def imbalanced_task_dataset(*, n_episodes: int = 20, seed: int = 0) -> list[Episode]:
    """A multitask dataset where one task has a single demo and another has almost all."""
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 79))
        # One rare task, the rest common: evenness collapses and the rare task is starved.
        task = "wipe the spill" if i == 0 else "open the drawer"
        action = rng.normal(0.0, _NOISE, size=(48, 6)) + 0.01
        out.append(_episode(i, action, integrate(action), prefix="ti", task=task))
    return out


def balanced_task_dataset(*, n_episodes: int = 20, seed: int = 0) -> list[Episode]:
    """The same shape of dataset with an even task mix — must not be reported."""
    tasks = ("open the drawer", "fold the towel", "wipe the spill", "stack the cups")
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 83))
        action = rng.normal(0.0, _NOISE, size=(48, 6)) + 0.01
        out.append(_episode(i, action, integrate(action), prefix="tb", task=tasks[i % len(tasks)]))
    return out


def shared_start_dataset(*, n_episodes: int = 16, seed: int = 0, shared: bool = True) -> list[Episode]:
    """Two tasks that either share their starting states (``shared``) or are separated.

    ``multimodality.label_conflict`` is about *under-conditioning*: the same start state has
    to lead to two differently-labelled behaviours. The separated variant gives each task its
    own region of state space, which is the healthy arrangement.
    """
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 89))
        group = i % 2
        task = "open the drawer" if group == 0 else "fold the towel"
        offset = np.zeros(6) if shared else np.full(6, 0.0 if group == 0 else 50.0)
        start = offset + rng.normal(0.0, 0.01, size=6)
        direction = np.zeros(6)
        direction[group] = 1.0
        action = 0.05 * direction + rng.normal(0.0, 0.002, size=(48, 6))
        out.append(_episode(i, action, integrate(action, start), prefix="ss2", task=task))
    return out


def blocky_vision_dataset(
    *, n_episodes: int = 6, length: int = 12, seed: int = 0, blocky: bool = True
) -> list[Episode]:
    """Camera frames with (or without) heavy 8×8 compression blocking."""
    out: list[Episode] = []
    for i in range(n_episodes):
        rng = np.random.default_rng((seed, i, 97))
        action = rng.normal(0.0, _NOISE, size=(length, 6)) + 0.01
        frames: list[ArrayImage] = []
        for _ in range(length):
            img = rng.uniform(0.0, 255.0, size=(32, 32, 3))
            if blocky:
                # Flatten each 8×8 tile toward its mean so the gradient energy concentrates on
                # the tile boundaries — the blocking signature. A *little* intra-tile detail is
                # kept deliberately: a perfectly flat tile has zero interior gradient, which
                # `_blockiness` treats as a blank frame (camera dropout's case) and skips, so a
                # noiseless fixture would leave the detector silent for the wrong reason.
                tiles = img.reshape(4, 8, 4, 8, 3).mean(axis=(1, 3))
                img = np.repeat(np.repeat(tiles, 8, axis=0), 8, axis=1)
                img = img + rng.normal(0.0, 1.5, size=img.shape)
            frames.append(ArrayImage(np.clip(img, 0.0, 255.0)))
        ts = np.arange(length, dtype=np.float64) / _DEFAULT_HZ
        view = StepView(action=action, timestamp=ts, proprio=integrate(action), images={"front": frames})
        src = Provenance(adapter="memory", uri="mem:vision", locator=f"episode_{i:04d}")
        out.append(Episode(episode_id=f"bk{i:04d}", steps=view, source=src, success=True))
    return out


# ------------------------------------------------------------------- policy profile fixtures


def policy_profile(
    *,
    family: PolicyFamily = PolicyFamily.ACT,
    action_dim: int | None = 6,
    proprio_dim: int | None = 6,
    norm_q99: float | None = None,
    norm_q01: float | None = None,
    dims: int = 6,
    clamps: bool | None = False,
) -> PolicyProfile:
    """A :class:`PolicyProfile` as if parsed from a checkpoint, for the POLICY↔DATA family."""
    norm_stats = None
    scheme = None
    if norm_q99 is not None:
        lo = norm_q01 if norm_q01 is not None else -norm_q99
        norm_stats = {
            norm_key("action", d): FeatureStats(mean=0.0, std=norm_q99, min=lo, max=norm_q99, q01=lo, q99=norm_q99)
            for d in range(dims)
        }
        scheme = NormScheme.QUANTILE_Q01_Q99
    return PolicyProfile(
        family=family,
        expected_action_dim=action_dim,
        expected_proprio_dim=proprio_dim,
        norm_scheme=scheme,
        norm_stats=norm_stats,
        clamps_actions=clamps,
    )
