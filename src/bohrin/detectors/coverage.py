"""Family E — COVERAGE: did you show enough of the world? (docs/04 §E, docs/07 §5).

**The highest-value family.** The *Data Scaling Laws* result (ICLR 2025 Oral,
arXiv 2410.18647) shows generalization scales as a power law in the **diversity** of
environments and objects, and that past a threshold, more demonstrations of the *same*
thing barely help. So the single most useful thing Layer 1 can usually tell a user is
"your problem is diversity, not quantity."

These detectors are deliberately **scale-free**: they compare spread *relative* to the
motion in the data, so a threshold means the same thing for a 2 cm insertion task and a
2 m mobile-manipulation task.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.analysis import embeddings
from bohrin.analysis.neighbors import effective_diversity, non_iid_pvalue
from bohrin.analysis.shapes import resample
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding, sparkline
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.encoders import get_encoder
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding

_EPS = 1e-12


class ModeCollapseDetector(Detector):
    """Flags a dataset that demonstrates the task essentially one single way."""

    id = "coverage.mode_collapse"
    family = Family.COVERAGE
    requires = Requirements(min_episodes=6)
    description = (
        "Detects when every demonstration follows nearly the same path — a policy trained on "
        "one strategy fails the moment the world differs."
    )

    #: Cross-demo deviation below this fraction of the travelled path means "one way only".
    _RATIO = 0.12

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        shapes = np.vstack([embeddings.shape_embedding(ep) for ep in episodes])
        mean_shape = shapes.mean(axis=0)
        deviation = float(np.mean(np.linalg.norm(shapes - mean_shape, axis=1)))
        # Scale: the typical distance travelled within a demo (same units as the embedding).
        scale = float(
            np.mean([np.linalg.norm(np.diff(resample(embeddings.trajectory(ep), 16), axis=0)) for ep in episodes])
        )
        if scale <= _EPS:
            return []
        ratio = deviation / scale
        if ratio >= self._RATIO:
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=float(min(1.0, 1.0 - ratio / self._RATIO)),
                title=f"All {len(episodes)} demos show essentially one strategy",
                mechanism=(
                    "Every demonstration follows nearly the same path, so the policy only ever "
                    "learns one way to do the task. It will fail the moment the object, the "
                    "approach angle, or the clutter differs — the classic covariate-shift failure."
                ),
                fix_text=(
                    "Collect demonstrations that vary the strategy: different approach "
                    "directions, object placements, and starting configurations. Diversity "
                    "drives generalization far more than raw demonstration count."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"shape_deviation_ratio": ratio},
                    thresholds={"ratio": self._RATIO},
                    notes="cross-demo trajectory deviation relative to distance travelled",
                ),
                blast=blast_over(len(episodes), ctx.profile.n_episodes, frac_steps=1.0),
                fix_machine={"action": "collect_diverse_strategies"},
            )
        ]


class InitialConditionDiversityDetector(Detector):
    """Flags a narrow distribution of starting configurations."""

    id = "coverage.initial_condition_diversity"
    family = Family.COVERAGE
    requires = Requirements(needs_proprio=True, min_episodes=6)
    description = "Detects demonstrations that all start from nearly the same configuration."

    _RATIO = 0.1  # initial spread below 10% of the workspace extent is narrow

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        starts = embeddings.initial_states(episodes)
        if starts.size == 0:
            return []
        all_states = np.vstack([embeddings.trajectory(ep) for ep in episodes])
        width = min(starts.shape[1], all_states.shape[1])
        start_spread = float(np.mean(np.std(starts[:, :width], axis=0)))
        workspace = float(np.mean(np.std(all_states[:, :width], axis=0)))
        if workspace <= _EPS:
            return []
        ratio = start_spread / workspace
        if ratio >= self._RATIO:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, 1.0 - ratio / self._RATIO)),
                title="Every demo starts from almost the same configuration",
                mechanism=(
                    "A narrow initial-condition distribution makes the policy brittle to the "
                    "real-world start variation it will actually meet at deployment."
                ),
                fix_text="Randomize the starting pose and object placement between demonstrations.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"initial_spread_ratio": ratio}, thresholds={"ratio": self._RATIO}),
                blast=blast_over(len(episodes), ctx.profile.n_episodes),
            )
        ]


class SceneDiversityDetector(Detector):
    """How many *visually distinct* scenes do the demonstrations actually cover?

    This is the most direct implementation of the *Data Scaling Laws* result: generalization
    scales as a power law in the diversity of **environments and objects**, and past a
    threshold more demonstrations of the same scene add almost nothing. Proprioception
    cannot see a scene — only pixels can — so this detector is the visual half of COVERAGE.

    It runs on the frame-0 embedding of each episode (the scene before the robot disturbs
    it), using the configured encoder: the offline tiled-statistics default, or frozen
    DINOv2 via ``--encoder dinov2`` when semantic similarity matters.
    """

    id = "coverage.scene_diversity"
    family = Family.COVERAGE
    requires = Requirements(needs_images=True, min_episodes=8)
    description = (
        "Estimates how many visually distinct scenes the demos cover. Scene/object diversity "
        "drives generalization far more than demonstration count."
    )

    _RATIO = 0.4  # distinct scenes below 40% of the episode count is heavy scene reuse
    _NOISE_MULTIPLE = 3.0  # scenes closer than this × sensor noise are the *same* scene

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        first: list[FloatArray] = []
        second: list[FloatArray] = []
        for ep in ctx.episodes:
            for cam in sorted(ep.steps.images):
                stream = ep.steps.images[cam]
                if stream:
                    first.append(np.asarray(stream[0].array(), dtype=np.float64))
                    # A second frame of the *same* scene calibrates what sensor noise looks
                    # like, giving us a physical scale for "these are the same scene".
                    second.append(np.asarray(stream[min(1, len(stream) - 1)].array(), dtype=np.float64))
                break  # one camera is enough to characterize the scene
        if len(first) < self.requires.min_episodes:
            return []
        encoder = get_encoder(ctx.config.encoder)
        matrix = encoder.encode(first)
        noise_ref = encoder.encode(second)
        if matrix.size == 0 or noise_ref.shape != matrix.shape:
            return []

        # NOTE: no standardization here. Z-scoring would rescale sensor noise up to unit
        # variance and make a dataset of identical scenes look perfectly diverse.
        within = float(np.median(np.linalg.norm(matrix - noise_ref, axis=1)))
        n = matrix.shape[0]
        distinct = effective_diversity(matrix, radius=self._NOISE_MULTIPLE * max(within, _EPS))
        if distinct >= self._RATIO * n:
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=float(min(1.0, 1.0 - distinct / max(self._RATIO * n, 1.0))),
                title=f"{n} demos cover only about {distinct} distinct scene(s)",
                mechanism=(
                    "Generalization scales as a power law in the diversity of scenes and "
                    "objects; beyond a threshold, extra demonstrations of the *same* scene "
                    "barely help (Data Scaling Laws, ICLR 2025 Oral). A policy trained here "
                    "will likely fail in any environment it has not literally seen."
                ),
                fix_text=(
                    "Collect in more environments, with more object instances and placements, "
                    "rather than repeating the same setup."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_episodes": float(n),
                        "distinct_scenes": float(distinct),
                        "sensor_noise_scale": within,
                    },
                    thresholds={"diversity_ratio": self._RATIO, "noise_multiple": self._NOISE_MULTIPLE},
                    notes=f"visual encoder: {encoder.name}",
                ),
                blast=blast_over(n, ctx.profile.n_episodes),
                fix_machine={"action": "collect_more_scenes", "distinct_scenes": distinct},
            )
        ]


class RedundancyDetector(Detector):
    """The headline finding: how much *effective* diversity the demonstrations carry."""

    id = "coverage.redundancy"
    family = Family.COVERAGE
    requires = Requirements(min_episodes=10)
    description = (
        "Estimates effective diversity vs raw demonstration count, and tests whether sampling "
        "was non-IID (near-duplicate or session-clustered)."
    )

    _RATIO = 0.5  # effective diversity below half the demo count is heavy redundancy
    _P = 0.01  # non-IID p-value threshold

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        n = len(episodes)
        if n < self.requires.min_episodes:
            return []
        matrix = embeddings.standardize(embeddings.stack(episodes))
        if matrix.size == 0:
            return []
        distinct = effective_diversity(matrix)
        p_value = non_iid_pvalue(matrix, rng=ctx.rng)
        redundant = distinct < self._RATIO * n
        if not redundant and p_value >= self._P:
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH if redundant else Severity.MEDIUM,
                confidence=float(1.0 - p_value) if p_value < self._P else 0.8,
                title=f"Your {n} demos carry the diversity of about {distinct}",
                mechanism=(
                    "Generalization scales with the diversity of scenes and objects, not with "
                    "raw demonstration count — past a threshold, more of the same barely helps "
                    "(Data Scaling Laws, ICLR 2025). Near-duplicate demonstrations consume "
                    "collection effort without buying generalization."
                ),
                fix_text=(
                    "Collect *different* scenes, objects and placements rather than more "
                    "repetitions of the ones you have."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_episodes": float(n),
                        "effective_diversity": float(distinct),
                        "non_iid_p_value": p_value,
                    },
                    thresholds={"diversity_ratio": self._RATIO, "p_value": self._P},
                ),
                blast=blast_over(n, ctx.profile.n_episodes),
                fix_machine={"action": "collect_diverse_scenes", "effective_diversity": distinct},
            )
        ]


class TaskImbalanceDetector(Detector):
    """Flags a multitask dataset whose episodes are heavily skewed toward a few tasks.

    Multitask and language-conditioned policies learn the rare tasks poorly when the data is
    imbalanced — the loss is dominated by the common ones, and balanced re-sampling or
    targeted collection is the fix (*Towards balanced behaviour cloning from imbalanced
    datasets*, Auton. Robots 2025). This is invisible in an aggregate profile: the dataset
    looks large and healthy while one task has three demos and another three hundred.

    Runs only when the source actually carries per-episode task labels and there is more than
    one task — a single-task dataset cannot be "imbalanced".
    """

    id = "coverage.task_imbalance"
    family = Family.COVERAGE
    requires = Requirements(min_episodes=8)
    description = "Detects heavy task/skill imbalance across episodes, which starves the rare tasks."

    #: Normalised-entropy floor. 1.0 is a perfectly uniform task mix; below this the mix is
    #: skewed enough that the rare tasks are under-represented. Chosen so a mild imbalance
    #: (which is normal and harmless) passes and only a real starvation trips it.
    _MIN_EVENNESS = 0.7
    #: And the rarest task must be this many times under its fair share before we complain,
    #: so a dataset that is merely *not exactly uniform* is left alone.
    _STARVATION = 4.0

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        labels = [ep.task.text for ep in ctx.episodes if ep.task is not None and ep.task.text]
        if len(labels) < self.requires.min_episodes:
            return []
        counts: dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        if len(counts) < 2:
            return []

        total = sum(counts.values())
        n_tasks = len(counts)
        freqs = np.array([c / total for c in counts.values()], dtype=np.float64)
        # Shannon evenness: entropy normalised by log(n_tasks) → 1.0 when uniform.
        entropy = float(-np.sum(freqs * np.log(freqs)))
        evenness = entropy / np.log(n_tasks) if n_tasks > 1 else 1.0
        fair_share = total / n_tasks
        rarest_task, rarest_count = min(counts.items(), key=lambda kv: kv[1])
        starvation = fair_share / rarest_count if rarest_count else float("inf")

        if evenness >= self._MIN_EVENNESS or starvation < self._STARVATION:
            return []

        commonest_task, commonest_count = max(counts.items(), key=lambda kv: kv[1])
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, 1.0 - evenness)),
                title=(
                    f"Task mix is imbalanced across {n_tasks} tasks: "
                    f"'{_short(rarest_task)}' has {rarest_count}, '{_short(commonest_task)}' has {commonest_count}"
                ),
                mechanism=(
                    "In a multitask dataset the training loss is dominated by the common tasks, "
                    "so the rare ones are learned poorly however large the dataset is. The rare "
                    "task looks 'hard' when it is really just starved of data."
                ),
                fix_text=(
                    "Collect more demonstrations of the under-represented tasks, or balance them "
                    "with weighted sampling at train time."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_tasks": float(n_tasks),
                        "evenness": evenness,
                        "starvation_ratio": float(starvation),
                        "rarest_count": float(rarest_count),
                        "commonest_count": float(commonest_count),
                    },
                    thresholds={"min_evenness": self._MIN_EVENNESS, "starvation": self._STARVATION},
                    series=sparkline(np.array(sorted(counts.values()), dtype=np.float64)),
                    series_label="episodes per task (sorted)",
                ),
                blast=blast_over(total, ctx.profile.n_episodes),
                fix_machine={"action": "balance_tasks", "rarest": rarest_task, "rarest_count": rarest_count},
            )
        ]


def _short(text: str, limit: int = 32) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
