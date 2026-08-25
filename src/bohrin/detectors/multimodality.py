"""Family G — MULTIMODALITY: can the target model represent the data? (docs/04 §G).

At one state the demonstrations sometimes go two valid ways (left around the obstacle vs
right around it). A **unimodal MSE policy (BC / ACT-MSE) averages them into an invalid
middle action** — the textbook case for Diffusion Policy. This is the finding that changes
what architecture a user picks, so it is deliberately policy-weighted: HIGH for a unimodal
head, informational for a model that can already represent multiple modes.

Genuine multimodality is separated from noise with a BIC comparison between a one- and
two-component Gaussian mixture over the actions in each state neighbourhood.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.analysis.neighbors import knn
from bohrin.analysis.robust import keep_finite_rows
from bohrin.analysis.shapes import is_multimodal
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, PolicyFamily, Severity
from bohrin.profile.action_space import action_increments, resolve_action_space
from bohrin.report.model import Evidence, Finding

# Policy families that can natively represent multiple action modes.
_MULTIMODAL_CAPABLE = frozenset({PolicyFamily.DIFFUSION})

_NEIGHBOURHOOD = 24  # states per neighbourhood examined for contradictory actions
_MAX_PROBES = 40  # neighbourhoods sampled (bounded work)
_FRAC = 0.25  # fraction of neighbourhoods that must be multimodal to report
_TEMPORAL_MARGIN = 2.0  # modes must be this many typical step-changes apart
_MAX_STATES = 20_000  # cap on pooled steps entering the neighbour search (bounded work)


def _typical_step_change(ctx: AnalysisContext) -> float:
    """Median magnitude of the action change between consecutive steps."""
    deltas: list[FloatArray] = []
    space = resolve_action_space(ctx.profile, ctx.schema.action_space)
    for ep in ctx.episodes:
        action = action_increments(np.asarray(ep.steps.action, dtype=np.float64), space)
        if action.shape[0] >= 2:
            deltas.append(np.linalg.norm(np.diff(action, axis=0), axis=1))
    if not deltas:
        return 0.0
    return float(np.median(np.concatenate(deltas)))


class ContradictoryActionsDetector(Detector):
    """Flags states where demonstrations take genuinely different actions."""

    id = "multimodality.contradictory_actions"
    family = Family.MULTIMODALITY
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = (
        "Detects states where demos split into two valid action modes — a unimodal (BC/ACT-MSE) "
        "head averages them into an invalid motion."
    )

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        states, actions = _pairs(ctx)
        if states.shape[0] < _NEIGHBOURHOOD * 2:
            return []
        # Bound the neighbour search: a large reservoir pools hundreds of thousands of steps,
        # and this detector only needs a representative sample. Deterministic under --seed.
        if states.shape[0] > _MAX_STATES:
            keep = np.sort(ctx.rng.choice(states.shape[0], size=_MAX_STATES, replace=False))
            states, actions = states[keep], actions[keep]
        # Floor on what counts as "different actions": the typical change between
        # consecutive steps. Without it, a slow-moving state puts adjacent timesteps in the
        # same neighbourhood and their naturally-different actions look like two modes —
        # temporal aliasing, not two demonstrations disagreeing.
        min_gap = _TEMPORAL_MARGIN * _typical_step_change(ctx)

        _, idx = knn(states, _NEIGHBOURHOOD)
        probes = min(_MAX_PROBES, states.shape[0])
        chosen = ctx.rng.choice(states.shape[0], size=probes, replace=False)
        multimodal = sum(1 for i in chosen if is_multimodal(actions[idx[i]], min_gap=min_gap))
        frac = multimodal / probes
        if frac < _FRAC:
            return []

        capable = ctx.policy is not None and ctx.policy.family in _MULTIMODAL_CAPABLE
        severity = Severity.LOW if capable else Severity.HIGH
        fix = (
            "Your target model can already represent multiple modes, so this is informational."
            if capable
            else (
                "Use a policy class that can represent multiple modes (Diffusion Policy, or a "
                "flow/VAE head), or increase action-chunk context so the branch is disambiguated."
            )
        )
        return [
            make_finding(
                self,
                severity=severity,
                confidence=float(min(1.0, frac / _FRAC * 0.6)),
                title=f"Demos take contradictory actions at the same state ({frac * 100:.0f}% of probes)",
                mechanism=(
                    "At the same state, different demonstrations go different valid ways. A "
                    "unimodal regression head (BC or ACT with an MSE loss) fits the *average* of "
                    "those modes, which is often an invalid action that satisfies neither — the "
                    "textbook case for Diffusion Policy."
                ),
                fix_text=fix,
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"multimodal_fraction": frac, "probes": float(probes)},
                    thresholds={"fraction": _FRAC},
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=frac),
                fix_machine={"action": "use_multimodal_policy", "recommended": "diffusion"},
            )
        ]


class LabelConflictDetector(Detector):
    """Same state, different action, *different task label* — under-conditioning, not multimodality."""

    id = "multimodality.label_conflict"
    family = Family.MULTIMODALITY
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = "Detects contradictory actions that trace to two different tasks sharing a start state."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        labelled = [
            (ep, ep.task.text)
            for ep in ctx.episodes
            if ep.task is not None and ep.task.text and ep.steps.proprio is not None
        ]
        names = [text for _, text in labelled]
        if len(labelled) < 4 or len(set(names)) < 2:
            return []
        starts = np.vstack([np.asarray(ep.steps.proprio, dtype=np.float64)[0] for ep, _ in labelled])
        # Drop episodes whose start state is corrupt, keeping labels aligned with rows.
        finite = np.isfinite(starts).all(axis=1)
        if not bool(finite.all()):
            starts = starts[finite]
            labelled = [item for item, ok in zip(labelled, finite.tolist(), strict=True) if ok]
            names = [text for _, text in labelled]
            if len(labelled) < 4 or len(set(names)) < 2:
                return []
        _, idx = knn(starts, min(4, len(labelled) - 1))
        conflicts = sum(1 for i in range(len(labelled)) if any(names[j] != names[i] for j in idx[i]))
        frac = conflicts / len(labelled)
        if frac < 0.5:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, frac)),
                title="Different tasks share the same starting states",
                mechanism=(
                    "Episodes with different instructions begin from indistinguishable states. "
                    "Without conditioning on the task the policy cannot know which behaviour is "
                    "wanted — this is under-conditioning, not genuine multimodality."
                ),
                fix_text="Condition the policy on the task instruction, or split the dataset per task.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"conflicting_fraction": frac, "n_tasks": float(len(set(names)))}),
                blast=blast_over(len(labelled), ctx.profile.n_episodes),
            )
        ]


def _pairs(ctx: AnalysisContext) -> tuple[FloatArray, FloatArray]:
    """Pooled ``(state, commanded-motion)`` pairs across the reservoir.

    The action is reduced to increments for absolute spaces: "these two demos commanded
    different *motions* here" is the question, and an absolute pose answers a different one.
    """
    space = resolve_action_space(ctx.profile, ctx.schema.action_space)
    states: list[FloatArray] = []
    actions: list[FloatArray] = []
    for ep in ctx.episodes:
        proprio = ep.steps.proprio
        if proprio is None:
            continue
        s = np.asarray(proprio, dtype=np.float64)
        a = action_increments(np.asarray(ep.steps.action, dtype=np.float64), space)
        if s.shape[0] != a.shape[0]:
            continue
        states.append(s)
        actions.append(a)
    if not states:
        empty = np.empty((0, 0), dtype=np.float64)
        return empty, empty
    width_s = min(x.shape[1] for x in states)
    width_a = min(x.shape[1] for x in actions)
    # Filtered jointly so a state still lines up with the action taken from it; the neighbour
    # search raises on NaN, and mismatched lengths would silently pair the wrong rows.
    pooled_states, pooled_actions = keep_finite_rows(
        np.vstack([x[:, :width_s] for x in states]),
        np.vstack([x[:, :width_a] for x in actions]),
    )
    return pooled_states, pooled_actions
