"""Probe 3 — Ground Truth Rejected.

    Will this verifier reject the taskset's own declared answer?

The other half of the Verification Gap. :mod:`~bohrin.probes.weak_oracle` asks whether a
verifier accepts work that is wrong; this asks whether it rejects work that is right.

Both are the same failure of a reward signal, and the second is not the lesser one. A
verifier that rejects correct answers trains a model *away* from correct behaviour: the
gradient says the right answer was wrong. Published measurement puts the scale of this
beyond argument — a category-level audit of four widely used verifiers over 307,420
verdicts found self-validation, a verifier accepting certified-equivalent renderings of
**its own ground truth**, ranging from 53.8% to 95.2%, with whitespace and punctuation
alone causing 93.0% of in-contract failures on one of them. Separately, over 38% of
model-generated responses in one RL training set were found to be false negatives.

**This probe does not contribute to the Verification Gap, deliberately.** Its ``weight`` is
zero, so it reports findings without moving the score, and the reason is a soundness
argument rather than caution.

Three situations produce an identical result, and only the first is a defect:

* the comparison really is broken, and correct answers are being discarded;
* the verifier enforces an **output contract the prompt documents** — ``reverse_text``
  requires the answer inside ``<reversed_text>`` tags while its taskset stores the bare
  reversal, so refusing the stored value is that verifier working correctly;
* the reward **never reads the reply** — ``code_golf`` scores
  ``trace.metrics.get("passed")``, a value set elsewhere in the episode, so nothing
  submitted offline can pass and nothing was really refused.

Both of the latter were found in the public corpus, by running this probe over it. Bohrin
cannot yet separate them from the real defect, and a score that pooled all three would
report correct verifiers as broken — the one thing this codebase forbids outright.

So the finding is reported for a human to judge, and the number stays out of it. When the
gap is split into acceptance and rejection sides, a rejection-side score can carry this
without contaminating the acceptance-side one.

**Wording discipline.** This probe reports a *search budget*, never a verdict about
correctness: "no rendering of the declared answer was accepted (12 tried)". It does not
say "this verifier rejects correct answers", because the renderings tried are a finite
catalogue and the thirteenth might have passed. That is the same discipline
:mod:`~bohrin.probes.determinism` follows when it quotes detection power instead of
claiming determinism.
"""

from __future__ import annotations

import shlex

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.execute.runner import score_many
from bohrin.ir.evidence import Finding, GroundTruthRejected
from bohrin.ir.task import Candidate, Provenance, Task
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.relations import renderings
from bohrin.scoring.interval import rate


class GroundTruthRejectedProbe(Probe):
    """Submit the taskset's own answer, every way the catalogue can render it."""

    id = "ground_truth_rejected"
    family = "rejection"

    #: Reported, never scored — see the module docstring. A weight of zero keeps the probe
    #: out of both sums in the Verification Gap while leaving it visible in the report.
    weight = 0.0

    def explain(self) -> str:
        return (
            "Submits the taskset's own declared answer, re-rendered every way the "
            "metamorphic-relation catalogue certifies as meaning-preserving, and reports "
            "tasks where the verifier accepted none of them. A verifier that rejects "
            "correct work trains a model away from it, which is the same defect as "
            "accepting wrong work with the sign flipped.\n\n"
            "What it cannot see: whether the rejection is a defect or a documented output "
            "contract. A verifier requiring the answer inside particular tags is behaving "
            "correctly when it rejects the bare stored value, and Bohrin cannot yet tell "
            "that apart from a broken comparison. So this probe reports what it tried and "
            "how many renderings were refused, and contributes nothing to the Verification "
            "Gap. It also cannot see past its own catalogue: a null result means the "
            "renderings tried were accepted, not that every correct answer would be."
        )

    async def run(self, source: TaskSource, config: ScanConfig) -> ProbeResult:
        tasks = list(source.tasks())
        if config.only_tasks:
            tasks = [t for t in tasks if t.id in config.only_tasks]
        if config.max_tasks is not None:
            tasks = tasks[: config.max_tasks]

        # Same two refusals weak_oracle makes, for the same reasons: a task with no reward
        # function has no verifier to audit, and one needing a runtime cannot be scored
        # honestly without one.
        scoreable = [
            t for t in tasks if t.reward_fns and not t.metadata.get("requires_runtime") and (t.reference or "").strip()
        ]
        if not scoreable:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                tasks_probed=len(tasks),
                reason=(
                    "no task has both a declared answer and a reward function that can be "
                    "scored offline, so there is no ground truth to submit"
                ),
            )

        work: list[tuple[Task, Candidate]] = []
        tried: dict[str, list[str]] = {}
        for task in scoreable:
            rendered = renderings(task.reference or "")
            tried[task.id] = [relation_id for relation_id, _ in rendered]
            for relation_id, payload in rendered:
                work.append(
                    (
                        task,
                        Candidate(
                            payload=payload,
                            provenance=Provenance(
                                operator="ground_truth",
                                base=relation_id,
                                detail=f"the taskset's declared answer, rendered by {relation_id}",
                            ),
                            # Never a ground: this candidate is *correct*. It can never
                            # become an exploit, and nothing here may report one.
                            ground=None,
                        ),
                    )
                )

        outcomes = await score_many(source, work, config)

        accepted: set[str] = set()
        errored: dict[str, str] = {}
        scored: set[str] = set()
        for out in outcomes:
            if out.error is not None or out.verdict is None:
                errored.setdefault(out.task.id, out.error or "unknown")
                continue
            scored.add(out.task.id)
            if out.verdict.passed:
                accepted.add(out.task.id)

        if not scored:
            sample = next(iter(errored.values()), "unknown")
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(scoreable),
                reason=f"every scoring attempt failed; first error: {sample}",
                detail={"errors": len(errored)},
            )

        findings: list[Finding] = []
        for task in scoreable:
            # Only tasks we actually managed to score can be judged. A task whose every
            # submission errored tells us nothing about the verifier's rejections.
            if task.id not in scored or task.id in accepted:
                continue
            findings.append(
                GroundTruthRejected(
                    task_id=task.id,
                    reference=task.reference or "",
                    relations_tried=tuple(tried.get(task.id, ())),
                    repro_args=f"--task {shlex.quote(task.id)} --probe {self.id}",
                )
            )

        return ProbeResult(
            probe_id=self.id,
            status=ProbeStatus.OK,
            tasks_probed=len(scored),
            # Present so the result is well-formed and the rate is visible in --json. It is
            # kept out of the Verification Gap by `weight = 0.0`, not by hiding it.
            sub_score=len(findings) / len(scored) if scored else 0.0,
            findings=tuple(findings),
            detail={
                "relations_available": len(renderings("probe")),
                "tasks_scored": len(scored),
                "tasks_rejecting_ground_truth": len(findings),
                "rate": rate(len(findings), len(scored)),
                "scored_out_of_gap": True,
            },
        )


__all__ = ["GroundTruthRejectedProbe"]
