"""Family I — LABEL / LANGUAGE: are tasks labeled and coherent? (docs/04 §I, docs/07 §2, §7).

Matters most for VLA / language-conditioned training. Two deliberate design choices:

* These detectors only engage on datasets that **are** labelled. An unlabelled dataset is
  simply not language-conditioned — reporting "no instructions" on it would be noise.
* Following DROID (which collects three annotations per episode on purpose), multiple
  surface *phrasings* of the same task are **good** and are never flagged. Only a phrasing
  that spans clearly different behaviours is reported.

``label.trajectory_label_mismatch`` implements **Confident Learning** proper (Northcutt et
al., JAIR 2021): cross-validated out-of-sample probabilities, per-class thresholds, and the
confident joint — the method that surfaced ~100k label errors in ImageNet.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import numpy as np
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

from bohrin.analysis import embeddings
from bohrin.analysis.confident_learning import confident_joint, label_error_mask, self_confidence
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding, Locus


def _labelled(ctx: AnalysisContext) -> list[tuple[Episode, str]]:
    return [ep_text for ep_text in ((ep, _text(ep)) for ep in ctx.episodes) if ep_text[1]]


def _text(episode: Episode) -> str:
    return episode.task.text.strip() if episode.task and episode.task.text else ""


class MissingLabelDetector(Detector):
    """Flags episodes with no instruction in an otherwise-labelled dataset."""

    id = "label.missing_or_empty"
    family = Family.LABEL
    requires = Requirements(min_episodes=4)
    description = "Detects missing task instructions in a labelled dataset (untrainable for a VLA)."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        total = len(ctx.episodes)
        labelled = _labelled(ctx)
        # Only meaningful if the dataset *is* labelled; an unlabelled dataset is simply not
        # language-conditioned and reporting on it would be noise.
        if not labelled or len(labelled) == total or total == 0:
            return []
        missing = [ep.episode_id for ep in ctx.episodes if not _text(ep)]
        frac = len(missing) / total
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=1.0,
                title=f"{len(missing)} of {total} episodes have no task instruction",
                mechanism=(
                    "A language-conditioned model needs the instruction for every sample. "
                    "Episodes without one are untrainable, or worse, train the model to map an "
                    "empty instruction to real behaviour."
                ),
                fix_text="Annotate the missing episodes, or drop them if the dataset is meant to be labelled.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"missing_fraction": frac}),
                locus=Locus(episodes=missing[:50]),
                blast=blast_over(len(missing), ctx.profile.n_episodes),
            )
        ]


# NOTE: `label.inconsistent_phrasing` is deliberately NOT shipped yet.
#
# docs/04 §I (refined by DROID, docs/07 §7) requires it to flag only instructions whose
# *semantics* differ, never mere paraphrase — DROID collects three phrasings per episode on
# purpose, so "correcting" that would be a false positive on a best practice. Distinguishing
# paraphrase from genuinely different meaning needs a text embedding, not geometry. Every
# purely geometric proxy we measured failed to separate the classes at all (a correctly
# labelled group and a genuinely ambiguous one scored 27.5 vs 27.1 on the same statistic),
# so it waits for the embedding view rather than shipping an unfalsifiable check.


class TrajectoryLabelMismatchDetector(Detector):
    """Confident-Learning mislabel detection over trajectory embeddings (docs/07 §2)."""

    id = "label.trajectory_label_mismatch"
    family = Family.LABEL
    requires = Requirements(min_episodes=10)
    description = (
        "Flags an episode whose trajectory matches a different task than its label, using "
        "Confident Learning (the confident joint over cross-validated predictions)."
    )

    _MIN_PER_CLASS = 3

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        labelled = _labelled(ctx)
        names = [text for _, text in labelled]
        classes = sorted(set(names))
        if len(labelled) < self.requires.min_episodes or len(classes) < 2:
            return []
        counts = Counter(names)
        if min(counts.values()) < self._MIN_PER_CLASS:
            return []  # too few examples per task to estimate the joint reliably

        matrix = embeddings.standardize(embeddings.stack([ep for ep, _ in labelled], embeddings.shape_embedding))
        if matrix.size == 0:
            return []
        # The kNN classifier raises on NaN/inf. Rows and their labels are filtered together
        # because a suspect is reported as `labelled[i]` — dropping rows alone would accuse the
        # wrong episode of being mislabeled.
        finite = np.isfinite(matrix).all(axis=1)
        if not bool(finite.all()):
            matrix = matrix[finite]
            labelled = [item for item, ok in zip(labelled, finite.tolist(), strict=True) if ok]
            names = [text for _, text in labelled]
            classes = sorted(set(names))
            counts = Counter(names)
            if len(labelled) < self.requires.min_episodes or len(classes) < 2:
                return []
            if min(counts.values()) < self._MIN_PER_CLASS:
                return []
        index = {name: i for i, name in enumerate(classes)}
        labels = np.array([index[name] for name in names], dtype=np.int64)

        # Out-of-sample probabilities: a model that had seen an example would simply memorize
        # its (possibly wrong) label, and no error would ever look like one.
        folds = max(2, min(4, int(min(counts.values()))))
        neighbours = max(1, min(3, len(labelled) // folds - 1))
        try:
            probs = cross_val_predict(
                KNeighborsClassifier(n_neighbors=neighbours),
                matrix,
                labels,
                cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=0),
                method="predict_proba",
            ).astype(np.float64)
        except ValueError:
            return []
        if probs.shape[1] != len(classes):
            return []

        mask = label_error_mask(labels, probs)
        if not bool(mask.any()):
            return []
        suspects = [labelled[int(i)][0].episode_id for i in np.nonzero(mask)[0]]
        joint = confident_joint(labels, probs)
        off_diagonal = float(joint.sum() - np.trace(joint))
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=float(np.clip(np.max(1.0 - self_confidence(labels, probs)[mask]), 0.0, 1.0)),
                title=f"{len(suspects)} episode(s) look mislabeled",
                mechanism=(
                    "Confident Learning compares each episode's instruction against what a "
                    "cross-validated model confidently predicts from its trajectory. These "
                    "episodes' motions match a different task than their label says, and "
                    "mislabeled data actively teaches the wrong instruction→behaviour map."
                ),
                fix_text="Review and correct the instruction on the flagged episodes.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_suspects": float(len(suspects)),
                        "n_tasks": float(len(classes)),
                        "off_diagonal_mass": off_diagonal,
                    },
                    notes="confident joint (Northcutt et al., JAIR 2021)",
                ),
                locus=Locus(episodes=suspects[:50]),
                blast=blast_over(len(suspects), ctx.profile.n_episodes),
            )
        ]
