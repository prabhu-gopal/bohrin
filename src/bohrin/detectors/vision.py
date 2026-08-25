"""Family H — VISION: are the cameras trustworthy? (docs/04 §H).

Only runs when images exist and ``--no-vision`` is not set, and decodes a **sampled** subset
of frames through the IR's lazy handles (docs/03 §3) — a proprio-only scan never touches a
pixel. Frames are decoded once per episode and shared across the checks in this module.

``vision.compression_artifacts`` is deliberately toned down: published evidence is mixed on
whether reasonable compression hurts policy success, so it reports INFO with that caveat
rather than inflating a defect we cannot substantiate.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.detectors._common import blast_over, dataset_provenance, gate_scores, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding, Locus

_SAMPLES_PER_EPISODE = 8
_FROZEN_TOL = 1e-6  # mean abs pixel difference below this is an identical frame
_ACTION_EPS = 1e-3
_BLUR_FRAC = 0.25  # fraction of frames below the blur floor to report
_DROPOUT_FRAC = 0.02


def _sample_frames(episode: Episode, camera: str, rng: np.random.Generator) -> list[FloatArray]:
    """Decode a bounded, deterministic sample of frames for one camera."""
    frames = episode.steps.images.get(camera)
    if not frames:
        return []
    n = len(frames)
    count = min(_SAMPLES_PER_EPISODE, n)
    idx = np.linspace(0, n - 1, count).astype(int)
    return [np.asarray(frames[int(i)].array(), dtype=np.float64) for i in idx]


def _cameras(ctx: AnalysisContext) -> list[str]:
    keys: set[str] = set()
    for ep in ctx.episodes:
        keys.update(ep.steps.images.keys())
    return sorted(keys)


def _laplacian_variance(frame: FloatArray) -> float:
    """Variance of the discrete Laplacian — the standard sharpness/blur proxy."""
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    lap = -4.0 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(np.var(lap))


class FrozenFramesDetector(Detector):
    """Flags a camera feed that stops changing while the robot is still moving."""

    id = "vision.frozen_frames"
    family = Family.VISION
    requires = Requirements(needs_images=True)
    description = "Detects a frozen/dropped camera feed while the arm is moving — a broken perception→action map."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        offenders: list[str] = []
        for ep in ctx.episodes:
            action = np.asarray(ep.steps.action, dtype=np.float64)
            moving = bool(np.mean(np.linalg.norm(action, axis=1)) > _ACTION_EPS)
            if not moving:
                continue
            for cam in ep.steps.images:
                frames = _sample_frames(ep, cam, ctx.rng)
                if len(frames) < 2:
                    continue
                diffs = [float(np.mean(np.abs(frames[i] - frames[i - 1]))) for i in range(1, len(frames))]
                if max(diffs) < _FROZEN_TOL:
                    offenders.append(ep.episode_id)
                    break
        if not offenders:
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=1.0,
                title=f"Camera frozen while the robot moved in {len(offenders)} episode(s)",
                mechanism=(
                    "The image stream stops changing while actions are still being issued. The "
                    "policy is taught that identical pixels correspond to different actions, "
                    "which breaks the perception→action mapping it must learn."
                ),
                fix_text="Check the camera pipeline for dropped frames; drop or re-record the affected episodes.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"n_episodes": float(len(offenders))}),
                locus=Locus(episodes=offenders[:50]),
                blast=blast_over(len(offenders), ctx.profile.n_episodes),
            )
        ]


class BlurExposureDetector(Detector):
    """Flags systematically blurred or blown-out frames."""

    id = "vision.blur_exposure"
    family = Family.VISION
    requires = Requirements(needs_images=True)
    description = "Detects motion blur and over/under-exposure that make frames unusable as policy input."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        sharpness: list[float] = []
        saturated: list[float] = []
        for ep in ctx.episodes:
            for cam in ep.steps.images:
                for frame in _sample_frames(ep, cam, ctx.rng):
                    sharpness.append(_laplacian_variance(frame))
                    hi = float(np.mean(frame >= 254.0))
                    lo = float(np.mean(frame <= 1.0))
                    saturated.append(max(hi, lo))
        if len(sharpness) < 4:
            return []
        median_sharp = float(np.median(sharpness))
        floor = 0.1 * median_sharp
        blurred = float(np.mean([s < floor for s in sharpness]))
        # Clipping only counts as bad exposure when detail was actually lost with it.
        #
        # A large uniform region at the sensor limit is not necessarily overexposure: measured on
        # `lerobot/pusht`, 83.6 % of pixels sit at >= 254 because the benchmark *renders* a pure
        # white background, and the frames are perfectly crisp. On the raw pixel test that scored
        # "100 % of sampled frames are blurred or badly exposed" on one of the most widely used
        # datasets in the field — a MEDIUM on every episode, from a synthetic backdrop.
        #
        # What makes overexposure a defect is destroyed information, and that shows up as lost
        # gradient. Requiring both conditions keeps genuine blown-out frames (flat *and* clipped)
        # while sparing a flat backdrop behind a sharp subject. Pairing them also reuses the
        # relative sharpness floor above rather than adding an absolute pixel threshold, which is
        # what misfired here in the first place.
        clipped = float(np.mean([s > 0.5 and v < floor for s, v in zip(saturated, sharpness, strict=True)]))
        if blurred < _BLUR_FRAC and clipped < _BLUR_FRAC:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, max(blurred, clipped))),
                title=f"{max(blurred, clipped) * 100:.0f}% of sampled frames are blurred or badly exposed",
                mechanism=(
                    "Unusable frames are noise on the policy's most important input. When they "
                    "cluster in a subset of episodes they bias perception systematically."
                ),
                fix_text="Improve lighting or shutter speed; drop the unusable frames.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"blurred_fraction": blurred, "clipped_fraction": clipped},
                    thresholds={"fraction": _BLUR_FRAC},
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]


class CameraDropoutDetector(Detector):
    """Flags a camera present in most episodes but missing from some."""

    id = "vision.camera_dropout"
    family = Family.VISION
    requires = Requirements(needs_images=True)
    description = "Detects inconsistent camera availability across episodes, which breaks multi-cam models."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        cameras = _cameras(ctx)
        total = len(ctx.episodes)
        if not cameras or total == 0:
            return []
        findings: list[Finding] = []
        for cam in cameras:
            missing = [ep.episode_id for ep in ctx.episodes if cam not in ep.steps.images]
            frac = len(missing) / total
            if not missing or frac > 0.5 or frac < _DROPOUT_FRAC:
                continue
            findings.append(
                make_finding(
                    self,
                    severity=Severity.MEDIUM,
                    confidence=1.0,
                    title=f"Camera {cam!r} is missing from {len(missing)} of {total} episodes",
                    mechanism=(
                        "Inconsistent modality availability across episodes breaks multi-camera "
                        "models, which must either drop the episodes or hallucinate the stream."
                    ),
                    fix_text=f"Re-export the affected episodes with {cam!r}, or drop the camera from the schema.",
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(metrics={"missing_fraction": frac}),
                    locus=Locus(episodes=missing[:50], camera=cam),
                    blast=blast_over(len(missing), ctx.profile.n_episodes),
                )
            )
        return findings


class ViewpointDriftDetector(Detector):
    """Flags a camera that appears to have moved partway through collection."""

    id = "vision.viewpoint_drift"
    family = Family.VISION
    requires = Requirements(needs_images=True, min_episodes=8)
    description = "Detects a camera bumped mid-collection — a hidden distribution shift the model can't reconcile."

    _Z = 6.0

    def _step_deltas(self, ctx: AnalysisContext, camera: str) -> FloatArray:
        """Episode-to-episode change in the camera's first-frame signature."""
        signature = _first_frame_signatures(ctx, camera)
        if signature.shape[0] < 2:
            return np.empty(0, dtype=np.float64)
        deltas: FloatArray = np.linalg.norm(np.diff(signature, axis=0), axis=1)
        return deltas

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """First-frame signature deltas, pooled over cameras — what :meth:`run` gates on."""
        blocks = [d for cam in _cameras(ctx) if (d := self._step_deltas(ctx, cam)).size]
        return np.concatenate(blocks) if blocks else None

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        for cam in _cameras(ctx):
            # A viewpoint change shows up as a step in the first-frame signature series.
            deltas = self._step_deltas(ctx, cam)
            if deltas.shape[0] < 7:
                continue
            decision = gate_scores(ctx, self, deltas, fallback_z=self._Z)
            if not decision.fired:
                continue
            at = decision.worst
            return [
                make_finding(
                    self,
                    severity=Severity.MEDIUM,
                    confidence=decision.worst_confidence,
                    title=f"Camera {cam!r} viewpoint shifts after episode {at}",
                    mechanism=(
                        "The scene background changes abruptly partway through collection — the "
                        "camera was most likely bumped or remounted. This is a hidden "
                        "distribution shift the model cannot reconcile with proprioception."
                    ),
                    fix_text="Re-calibrate the camera pose, or treat the two segments as separate datasets.",
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={"at_episode": float(at), **decision.evidence_metrics()},
                        thresholds=decision.evidence_thresholds(),
                        notes=decision.note(),
                    ),
                    locus=Locus(camera=cam),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
                )
            ]
        return []


class DepthQualityDetector(Detector):
    """Flags depth streams with a heavy fraction of invalid ("hole") pixels."""

    id = "vision.depth_pointcloud_quality"
    family = Family.VISION
    requires = Requirements(needs_images=True)
    description = "Detects holes in depth data; 3D policies are highly sensitive to point-cloud quality."

    _HOLE_FRAC = 0.2

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        holes: list[float] = []
        cams: set[str] = set()
        for ep in ctx.episodes:
            for cam in ep.steps.depth:
                cams.add(cam)
                frames = ep.steps.depth.get(cam) or []
                n = min(_SAMPLES_PER_EPISODE, len(frames))
                for i in np.linspace(0, len(frames) - 1, n).astype(int) if n else []:
                    arr = np.asarray(frames[int(i)].array(), dtype=np.float64)
                    holes.append(float(np.mean((arr <= 0.0) | ~np.isfinite(arr))))
        if not holes:
            return []
        frac = float(np.mean(holes))
        if frac < self._HOLE_FRAC:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, frac)),
                title=f"{frac * 100:.0f}% of depth pixels are holes",
                mechanism=(
                    "3D policies are highly sensitive to point-cloud quality and segmentation; "
                    "large invalid regions degrade them substantially."
                ),
                fix_text=(
                    "Check the depth sensor range and surface materials; consider hole-filling or an RGB-only policy."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"hole_fraction": frac}, thresholds={"hole_fraction": self._HOLE_FRAC}),
                locus=Locus(camera=sorted(cams)[0] if cams else None),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]


def _first_frame_signatures(ctx: AnalysisContext, camera: str) -> FloatArray:
    """A cheap per-episode signature of frame 0 (coarse spatial means) for drift detection."""
    rows: list[FloatArray] = []
    for ep in ctx.episodes:
        frames = ep.steps.images.get(camera)
        if not frames:
            continue
        frame = np.asarray(frames[0].array(), dtype=np.float64)
        gray = frame.mean(axis=2) if frame.ndim == 3 else frame
        h, w = gray.shape[:2]
        if h < 4 or w < 4:
            continue
        # 4×4 block means — robust to noise, sensitive to a viewpoint change.
        blocks = [
            float(gray[y * h // 4 : (y + 1) * h // 4, x * w // 4 : (x + 1) * w // 4].mean())
            for y in range(4)
            for x in range(4)
        ]
        rows.append(np.array(blocks, dtype=np.float64))
    return np.vstack(rows) if rows else np.empty((0, 16), dtype=np.float64)


class CompressionArtifactsDetector(Detector):
    """Flags *extreme* block/ringing artifacts — reported honestly as INFO (docs/04 §H).

    The evidence here is genuinely mixed. Policy success on reasonably compressed data is
    often comparable to raw (Learned Compression for VLA, arXiv 2606.16253), so flagging
    ordinary JPEG would be a false alarm dressed up as rigor. This detector therefore fires
    only on severe blocking and never rises above INFO, and its message says so.
    """

    id = "vision.compression_artifacts"
    family = Family.VISION
    requires = Requirements(needs_images=True, min_episodes=2)
    description = "Detects extreme compression blocking (INFO — moderate compression is usually fine)."

    #: JPEG's transform is 8×8, so blocking energy concentrates at multiples of 8.
    _BLOCK = 8
    #: Ratio of gradient energy at block boundaries to elsewhere. 1.0 means no blocking;
    #: this threshold is set high so only visually obvious artifacting qualifies.
    _BLOCKINESS = 2.5

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        cameras = [c.key for c in ctx.schema.cameras]
        if not cameras or ctx.config.no_vision:
            return []
        out: list[Finding] = []
        for camera in cameras:
            scores: list[float] = []
            for episode in ctx.episodes:
                for frame in _sample_frames(episode, camera, ctx.rng):
                    score = _blockiness(frame, self._BLOCK)
                    if score > 0:
                        scores.append(score)
            if not scores:
                continue
            median = float(np.median(scores))
            if median < self._BLOCKINESS:
                continue
            out.append(
                make_finding(
                    self,
                    severity=Severity.INFO,
                    confidence=0.6,
                    title=f"Camera '{camera}' shows heavy compression blocking",
                    mechanism=(
                        "Gradient energy concentrates on the codec's 8×8 block boundaries, "
                        "which means visible blocking. Published results suggest moderate "
                        "compression is usually harmless for policy success, so this is "
                        "informational — worth a look only if your task depends on "
                        "fine-grained visual detail."
                    ),
                    fix_text=(
                        "If the task needs fine detail (small parts, textures, precise "
                        "insertion), re-encode at a higher quality. Otherwise no action."
                    ),
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={"blockiness": median},
                        thresholds={"blockiness": self._BLOCKINESS},
                        notes="INFO by design: evidence on compression harming policies is mixed.",
                    ),
                    locus=Locus(camera=camera),
                    blast=blast_over(len(ctx.episodes), ctx.profile.n_episodes),
                    fix_machine={"action": "consider_reencode", "camera": camera},
                )
            )
        return out


def _blockiness(frame: FloatArray, block: int) -> float:
    """Ratio of mean gradient magnitude at block boundaries to that elsewhere.

    Returns 0.0 when the frame is too small or has no gradient at all, so a blank frame
    (which ``vision.camera_dropout`` owns) never registers as compressed.
    """
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    if gray.shape[0] < 2 * block or gray.shape[1] < 2 * block:
        return 0.0
    diff = np.abs(np.diff(gray, axis=1))
    if diff.size == 0:
        return 0.0
    columns = np.arange(diff.shape[1])
    on_edge = ((columns + 1) % block) == 0
    if not on_edge.any() or on_edge.all():
        return 0.0
    edge = float(np.mean(diff[:, on_edge]))
    interior = float(np.mean(diff[:, ~on_edge]))
    if interior <= 1e-9:
        return 0.0
    return edge / interior
