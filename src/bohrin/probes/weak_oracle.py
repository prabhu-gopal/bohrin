"""Probe 1 — Weak Oracle.

    Will this verifier accept work that is provably incorrect?

This is mutation testing with the roles relabelled: the candidate is the code under test,
**the verifier is the test suite**, and a surviving mutant is a wrong solution the verifier
accepted. The technique is decades old and no novelty is claimed for it; what matters here
is the discipline around what may be reported.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from bohrin.adapters.base import TaskSource
from bohrin.adapters.verifiers_v1 import reference_renderings
from bohrin.config import ScanConfig
from bohrin.execute.runner import ScoreOutcome, score_many
from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, Unverified
from bohrin.ir.task import Candidate, Provenance, Task
from bohrin.mutate import discover as discover_operators
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus


def _baseline_candidates(task: Task) -> list[Candidate]:
    """Plausible submissions of the known-good answer, most literal first.

    A taskset stores the *answer*; the verifier may require a particular *presentation* of
    it. Rather than assume the two are the same string, the baseline tries several and uses
    whichever the verifier accepts. None is ever wrong by construction, so none carries a
    ground and none can become an exploit.
    """
    reference = task.reference or ""
    if not reference.strip():
        return []
    return [
        Candidate(
            payload=rendering,
            provenance=Provenance(
                operator="baseline",
                base="reference",
                detail=f"the taskset's known-good answer, submitted as {rendering[:40]!r}",
            ),
            ground=None,
        )
        for rendering in reference_renderings(reference)
    ]


class WeakOracleProbe(Probe):
    """Submit provably-wrong candidates and record the ones that pass."""

    id = "weak_oracle"
    family = "acceptance"

    def explain(self) -> str:
        return (
            "Generates submissions that are provably incorrect and offers them to the "
            "verifier. Anything accepted is a false positive: a task that rewards failure. "
            "Where a reference solution exists it is submitted first and must pass — "
            "without that green baseline, an accepted mutant cannot be distinguished from "
            "Bohrin submitting candidates in a form the verifier does not understand. A "
            "candidate is only reported as an exploit when its wrongness was established "
            "independently of the verifier being audited; everything else is a lead."
        )

    async def run(self, source: TaskSource, config: ScanConfig) -> ProbeResult:
        operators = discover_operators()
        if not operators:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                reason="no mutation operators are registered",
            )

        tasks = list(source.tasks())
        if config.max_tasks is not None:
            tasks = tasks[: config.max_tasks]
        if not tasks:
            return ProbeResult(probe_id=self.id, status=ProbeStatus.NOT_APPLICABLE, reason="the taskset is empty")

        # Tasks the adapter has already declared unscoreable offline are excluded up front
        # rather than discovered through one failure per candidate. Cheaper, and the reason
        # reaches the user instead of an error count.
        offline, refused = self._partition_scoreable(tasks)

        measurable, baseline_failures, baseline_errors = await self._establish_baseline(source, offline, config)
        baseline_failures = [*refused, *baseline_failures]
        # Serialized identically on every path: a key whose type depends on status breaks
        # any consumer that reads the JSON.
        baseline_detail = [{"task_id": b.task_id, "reward": b.reward, "reason": b.reason} for b in baseline_failures]

        if not measurable:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(tasks),
                reason=(
                    "no task could be measured offline: every task either needs a runtime to score, "
                    "or its reference solution fails its own verifier — in which case an accepted "
                    "mutant would be indistinguishable from a submission-format problem"
                ),
                detail={"baseline_failures": baseline_detail, "baseline_errors": baseline_errors},
            )

        work: list[tuple[Task, Candidate]] = []
        # Redundant mutants are a known validity threat in mutation testing, and here they
        # also cost a real scoring call against someone else's environment. Two candidates
        # whose payloads are equal after stripping are the same submission as far as any
        # verifier is concerned, so only the first is sent.
        for task in measurable:
            submitted: set[str] = set()
            for op in operators:
                for cand in op.apply(task):
                    key = cand.payload.strip()
                    if key in submitted:
                        continue
                    submitted.add(key)
                    work.append((task, cand))
        if not work:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                tasks_probed=len(measurable),
                reason="no operator could establish wrongness for any task (is a reference solution available?)",
            )

        outcomes = await score_many(source, work, config)
        findings, unverified, errors = self._triage(outcomes)

        # If nothing was successfully scored there is no measurement, and a sub-score of
        # zero would report a verifier as clean that was never actually probed. This is the
        # exact failure the gap specification forbids, and only a real environment surfaced
        # it: every candidate errored while the probe reported "no accepted wrong solutions".
        scored = sum(1 for out in outcomes if out.error is None and out.verdict is not None)
        if scored == 0:
            sample = next((out.error for out in outcomes if out.error), "unknown")
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(measurable),
                reason=f"every scoring attempt failed ({errors} of {len(work)}); first error: {sample}",
                detail={"baseline_failures": baseline_detail, "errors": errors, "candidates_submitted": len(work)},
            )

        compromised = {f.task_id for f in findings}
        unbaselined = sum(1 for t in measurable if t.reference is None)
        return ProbeResult(
            probe_id=self.id,
            status=ProbeStatus.OK,
            tasks_probed=len(measurable),
            # Denominator is the measurable set, not every task. Dividing by tasks we could
            # not baseline would silently dilute the score toward "clean".
            sub_score=len(compromised) / len(measurable),
            findings=tuple(findings),
            unverified=tuple(unverified),
            detail={
                "operators": [op.id for op in operators],
                "candidates_submitted": len(work),
                "tasks_measurable": len(measurable),
                "tasks_compromised": len(compromised),
                "baseline_failures": baseline_detail,
                "baseline_errors": baseline_errors,
                "tasks_without_reference": unbaselined,
                "errors": errors,
            },
        )

    @staticmethod
    def _partition_scoreable(tasks: Sequence[Task]) -> tuple[list[Task], list[BaselineFailure]]:
        """Split tasks the adapter can score offline from ones it has refused.

        A task whose reward function needs a runtime cannot be scored honestly without one
        (scoring it offline would award full marks on a partial rubric). The adapter marks
        those; excluding them here means the user is told once, clearly, rather than through
        a wall of per-candidate errors.
        """
        offline: list[Task] = []
        refused: list[BaselineFailure] = []
        for task in tasks:
            needs = task.metadata.get("requires_runtime") or ()
            if needs:
                refused.append(
                    BaselineFailure(
                        task_id=task.id,
                        reward=0.0,
                        reason=f"reward function(s) {', '.join(needs)} require a runtime; cannot be scored offline",
                    )
                )
            else:
                offline.append(task)
        return offline, refused

    @staticmethod
    async def _establish_baseline(
        source: TaskSource, tasks: Sequence[Task], config: ScanConfig
    ) -> tuple[list[Task], list[BaselineFailure], int]:
        """Confirm each reference passes its own verifier before trusting any mutant.

        Tasks with no reference are admitted unbaselined: the structural operators (an
        empty reply, a refusal) remain valid there, and excluding those tasks entirely
        would make the probe useless on the many tasksets that ship no reference. The count
        is recorded so the report can say which tasks carried the weaker guarantee.
        """
        with_reference = [t for t in tasks if t.reference is not None]
        without_reference = [t for t in tasks if t.reference is None]

        if not with_reference:
            return without_reference, [], 0

        # Renderings are tried in waves: every still-unresolved task is scored against one
        # rendering in parallel, and a task drops out as soon as one is accepted. Submitting
        # all renderings at once would cost eight calls per task against a customer's
        # environment where one usually suffices.
        pending = {t.id: t for t in with_reference}
        best: dict[str, tuple[float, str | None]] = {t.id: (0.0, None) for t in with_reference}
        measurable: list[Task] = list(without_reference)
        errors = 0

        max_renderings = max((len(_baseline_candidates(t)) for t in with_reference), default=0)
        for index in range(max_renderings):
            wave = [
                (task, _baseline_candidates(task)[index])
                for task in pending.values()
                if index < len(_baseline_candidates(task))
            ]
            if not wave:
                break
            for out in await score_many(source, wave, config):
                reward, err = best[out.task.id]
                if out.error is not None or out.verdict is None:
                    best[out.task.id] = (reward, err or out.error)
                    continue
                if out.verdict.passed:
                    measurable.append(out.task)
                    pending.pop(out.task.id, None)
                    best[out.task.id] = (out.verdict.reward, None)
                elif out.verdict.reward > reward:
                    best[out.task.id] = (out.verdict.reward, err)
            if not pending:
                break

        failures: list[BaselineFailure] = []
        for task_id in pending:
            reward, err = best[task_id]
            if err is not None:
                errors += 1
            failures.append(
                BaselineFailure(
                    task_id=task_id,
                    reward=reward,
                    reason=err
                    or (
                        "no rendering of the known-good answer passed this task's own verifier "
                        "(tried the bare answer and several common presentations)"
                    ),
                )
            )
        return measurable, failures, errors

    @staticmethod
    def _triage(outcomes: Iterable[ScoreOutcome]) -> tuple[list[Finding], list[Unverified], int]:
        """Split accepted candidates into findings and leads. The split is the product."""
        findings: list[Finding] = []
        unverified: list[Unverified] = []
        errors = 0
        # One finding per (task, operator). An operator that tries six literals and has all
        # six accepted has found one defect, not six, and repeating it would push genuinely
        # different defects off the end of the report.
        seen: set[tuple[str, str]] = set()

        for out in outcomes:
            if out.error is not None:
                errors += 1
                continue
            verdict = out.verdict
            if verdict is None or not verdict.passed:
                continue

            key = (out.task.id, out.candidate.provenance.operator)
            if key in seen:
                continue
            seen.add(key)

            repro = f"bohrin audit --task {out.task.id} --operator {out.candidate.provenance.operator}"
            if out.candidate.known_wrong:
                findings.append(Exploit(task_id=out.task.id, candidate=out.candidate, verdict=verdict, repro=repro))
            else:
                unverified.append(
                    Unverified(
                        task_id=out.task.id,
                        candidate=out.candidate,
                        verdict=verdict,
                        reason="the verifier accepted this, but Bohrin could not establish that it is wrong",
                    )
                )
        return findings, unverified, errors


__all__ = ["WeakOracleProbe"]
