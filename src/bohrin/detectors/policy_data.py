"""Family J — POLICY↔DATA (docs/04 §J, docs/07 §7).

The family that turns L1 from "lint the data" into "lint the data **for this model**".
Every detector here is inert without ``--policy``: ``applicable`` returns ``False`` when
no :class:`PolicyProfile` was parsed, so a normal scan is completely unaffected.

These checks are unusually high-value because the failures they catch are *silent*. A
proprio-dim mismatch does not crash π0 — it zero-fills, and the model quietly underperforms
(arXiv 2505.05540). A normalization mismatch does not raise — every action is mis-scaled by
a constant factor. Both look like "the policy just isn't very good".
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin.detectors._common import blast_over, dataset_provenance, make_finding, sparkline
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import (
    ActionSpace,
    Family,
    NormScheme,
    PolicyFamily,
    PolicyProfile,
    Severity,
)
from bohrin.policy.loader import PROPRIO_DEPENDENT, norm_key
from bohrin.profile.action_space import infer_action_space
from bohrin.profile.dataset_profile import DatasetProfile
from bohrin.report.model import Evidence, Finding, Locus

#: A dataset q99 this many times the checkpoint's constant is a real mis-scaling, not
#: sampling noise. Chosen well above the spread seen between honest re-recordings of the
#: same task, so a merely *different* dataset does not trip it.
_NORM_RATIO = 1.5
#: Absolute floor: ignore dimensions whose constants are ~0, where a ratio is meaningless.
_NORM_FLOOR = 1e-6

# NOTE: `infer_action_space` moved to `bohrin.profile.action_space` — the temporal family
# needs the same inference, and duplicating it would let the two drift apart.


class _PolicyDetector(Detector):
    """Base for the family: applicable only when a checkpoint was actually parsed."""

    family = Family.POLICY_DATA
    requires = Requirements(needs_policy=True)

    def applicable(self, profile: DatasetProfile, policy: PolicyProfile | None) -> bool:
        return policy is not None


class DimMismatchDetector(_PolicyDetector):
    """Checkpoint input/output widths vs the dataset's actual dims."""

    id = "policy_data.dim_mismatch"
    description = "Checkpoint expects different action/proprio widths than the dataset provides."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        policy = ctx.policy
        if policy is None:
            return []
        out: list[Finding] = []
        checks = (
            ("action", policy.expected_action_dim, ctx.schema.action_dim),
            ("proprio", policy.expected_proprio_dim, ctx.schema.proprio_dim),
        )
        for name, expected, actual in checks:
            if expected is None or actual is None or expected == actual:
                continue
            out.append(
                make_finding(
                    self,
                    severity=Severity.HIGH,
                    confidence=1.0,  # a shape disagreement is a fact, not an estimate
                    title=f"Checkpoint expects {expected}-D {name}; dataset provides {actual}-D",
                    mechanism=(
                        f"The checkpoint's {name} width does not match the data's. At best this "
                        "crashes at train time; at worst the loader silently pads or truncates, "
                        "and the model learns a shifted mapping that is wrong in every dimension. "
                        + (
                            "A 2× difference usually means a bimanual model on single-arm data."
                            if max(expected, actual) == 2 * min(expected, actual)
                            else ""
                        )
                    ).strip(),
                    fix_text=(
                        f"Confirm the checkpoint targets this embodiment. Either re-export the "
                        f"policy with {name}_dim={actual}, or map the dataset's {name} vector "
                        f"onto the {expected} channels the model expects."
                    ),
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={"expected": float(expected), "actual": float(actual)},
                        notes=f"policy family: {policy.family.value}",
                    ),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                    fix_machine={"action": "align_dimensions", "channel": name, "expected": expected},
                )
            )
        return out


class MissingProprioDetector(_PolicyDetector):
    """The target family consumes proprioception the dataset never recorded."""

    id = "policy_data.missing_proprio"
    description = "Target policy zero-fills a proprioceptive state this dataset lacks."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        policy = ctx.policy
        if policy is None:
            return []
        needs = policy.family in PROPRIO_DEPENDENT or bool(policy.expected_proprio_dim)
        if not needs or ctx.schema.proprio_dim:
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=1.0,
                title=f"{policy.family.value} expects proprioception this dataset never recorded",
                mechanism=(
                    "When the state input is absent it is substituted with zero arrays — "
                    "unnatural, non-representative states that the model never saw in "
                    "pretraining. Nothing errors; the policy just performs worse, which is "
                    "easy to misread as 'this task is hard' (arXiv 2505.05540)."
                ),
                fix_text=(
                    "Record the robot's joint/end-effector state alongside the actions, or "
                    "select a policy variant that takes vision only."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"expected_proprio_dim": float(policy.expected_proprio_dim or 0)},
                    notes=f"policy family: {policy.family.value}",
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                fix_machine={"action": "record_proprio"},
            )
        ]


class NormalizationMismatchDetector(_PolicyDetector):
    """The dataset's measured range vs the checkpoint's baked-in normalization constants."""

    id = "policy_data.normalization_mismatch"
    description = "Dataset action range disagrees with the checkpoint's normalization constants."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        policy = ctx.policy
        if policy is None or not policy.norm_stats:
            return []
        # Only compare like with like: a q99 and a mean are different quantities.
        if policy.norm_scheme is not NormScheme.QUANTILE_Q01_Q99:
            return []

        stats = ctx.profile.action
        worst_dim, worst_ratio, ratios = -1, 0.0, []
        for dim in range(stats.dim):
            entry = policy.norm_stats.get(norm_key("action", dim))
            if entry is None or entry.q99 is None:
                continue
            declared = abs(float(entry.q99))
            measured = abs(float(stats.q99[dim]))
            if declared < _NORM_FLOOR:
                continue
            ratio = measured / declared
            ratios.append(ratio)
            if ratio > worst_ratio:
                worst_dim, worst_ratio = dim, ratio

        if worst_dim < 0 or worst_ratio < _NORM_RATIO:
            return []

        clamps = policy.clamps_actions
        clamp_note = (
            "This model clamps its outputs, which bounds the damage but still distorts the action distribution."
            if clamps
            else "This model does not clamp its outputs, so the mis-scaling passes straight to the robot."
        )
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=min(1.0, worst_ratio / (2.0 * _NORM_RATIO)),
                title=(
                    f"Dataset q99 for action dim {worst_dim} is {worst_ratio:.1f}× "
                    "the checkpoint's normalization constant"
                ),
                mechanism=(
                    "The checkpoint un-normalizes its outputs with constants baked in at "
                    "training time. When the data's true range disagrees, every predicted "
                    f"action is mis-scaled by roughly that factor. {clamp_note}"
                ),
                fix_text=(
                    "Re-compute the normalization statistics on this dataset and re-export the "
                    "checkpoint, or normalize the dataset into the checkpoint's expected range."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"worst_ratio": worst_ratio, "dimension": float(worst_dim)},
                    thresholds={"ratio": _NORM_RATIO},
                    series=sparkline(np.asarray(ratios, dtype=np.float64)),
                    series_label="measured ÷ declared q99, per action dimension",
                ),
                locus=Locus(dimensions=[worst_dim]),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                fix_machine={"action": "recompute_norm_stats", "dimension": worst_dim},
            )
        ]


class ActionSpaceMismatchDetector(_PolicyDetector):
    """Absolute-pose data fed to a delta-action model (or the reverse)."""

    id = "policy_data.action_space_mismatch"
    description = "Dataset action space (delta vs absolute) disagrees with the checkpoint's."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        policy = ctx.policy
        if policy is None:
            return []
        declared = ctx.schema.action_space
        expected = _expected_space(policy)
        if expected is ActionSpace.UNKNOWN:
            return []
        measured = declared if declared is not ActionSpace.UNKNOWN else infer_action_space(ctx.profile)
        if measured is ActionSpace.UNKNOWN or _compatible(measured, expected):
            return []
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=0.8 if declared is ActionSpace.UNKNOWN else 1.0,
                title=f"Data looks like {_phrase(measured)}; the model expects {_phrase(expected)}",
                mechanism=(
                    "A delta-action model integrates its own output; an absolute-pose model "
                    "commands a target directly. Feeding one the other's convention is silently "
                    "wrong — the loss still decreases, and the robot still moves, just not "
                    "toward the goal."
                ),
                fix_text=(
                    "Convert the action column to the model's convention "
                    f"({_phrase(expected)}), or select a checkpoint trained on {_phrase(measured)}."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    notes=(
                        f"dataset: {measured.value} "
                        f"({'declared' if declared is not ActionSpace.UNKNOWN else 'inferred'}); "
                        f"policy: {expected.value}"
                    )
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                fix_machine={"action": "convert_action_space", "to": expected.value},
            )
        ]


class OodEstimateDetector(_PolicyDetector):
    """How far this dataset sits from the checkpoint's likely training distribution."""

    id = "policy_data.ood_estimate"
    description = "Estimates how much of the dataset lies outside the checkpoint's normalized range."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        policy = ctx.policy
        if policy is None or not policy.norm_stats or policy.norm_scheme is not NormScheme.QUANTILE_Q01_Q99:
            return []
        stats = ctx.profile.action
        if stats.sample.size == 0:
            return []

        outside = np.zeros(stats.sample.shape[0], dtype=bool)
        compared = 0
        for dim in range(min(stats.dim, stats.sample.shape[1])):
            entry = policy.norm_stats.get(norm_key("action", dim))
            if entry is None or entry.q01 is None or entry.q99 is None:
                continue
            compared += 1
            column = stats.sample[:, dim]
            outside |= (column < float(entry.q01)) | (column > float(entry.q99))
        if compared == 0:
            return []

        frac = float(np.mean(outside))
        if frac < 0.05:
            return []
        severity = Severity.MEDIUM if frac >= 0.2 else Severity.LOW
        return [
            make_finding(
                self,
                severity=severity,
                confidence=0.7,
                title=f"~{frac * 100:.0f}% of steps fall outside the checkpoint's action range",
                mechanism=(
                    "Fine-tuning data far from the base model's coverage transfers poorly and "
                    "risks catastrophic forgetting. This is informational, not a defect: it "
                    "predicts a harder fine-tune, not broken data."
                ),
                fix_text=(
                    "Expect a longer fine-tune, or pick a base checkpoint whose training "
                    "distribution covers this workspace."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"fraction_outside": frac, "dimensions_compared": float(compared)},
                    thresholds={"report_above": 0.05},
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=frac),
                fix_machine={"action": "expect_harder_finetune", "fraction_outside": frac},
            )
        ]


# ------------------------------------------------------------------------------ helpers

_DELTA_SPACES = frozenset({ActionSpace.EEF_DELTA, ActionSpace.JOINT_VEL})
_ABSOLUTE_SPACES = frozenset({ActionSpace.EEF_ABS, ActionSpace.JOINT_POS})

#: Families whose public checkpoints are trained on delta actions. Left deliberately small:
#: an unlisted family yields UNKNOWN and the detector stays silent rather than guessing.
_FAMILY_SPACE: dict[PolicyFamily, ActionSpace] = {
    PolicyFamily.VLA_OPENVLA: ActionSpace.EEF_DELTA,
    PolicyFamily.OCTO: ActionSpace.EEF_DELTA,
}


def _expected_space(policy: PolicyProfile) -> ActionSpace:
    return _FAMILY_SPACE.get(policy.family, ActionSpace.UNKNOWN)


def _compatible(measured: ActionSpace, expected: ActionSpace) -> bool:
    """Delta-vs-absolute is the distinction that matters; joint-vs-EEF is not our call."""
    both_delta = measured in _DELTA_SPACES and expected in _DELTA_SPACES
    both_absolute = measured in _ABSOLUTE_SPACES and expected in _ABSOLUTE_SPACES
    return both_delta or both_absolute


def _phrase(space: ActionSpace) -> str:
    return "delta actions" if space in _DELTA_SPACES else "absolute poses"
