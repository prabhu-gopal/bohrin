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
from bohrin.config import ScanConfig
from bohrin.execute.runner import ScoreOutcome, score_many
from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, Unverified
from bohrin.ir.task import Candidate, Provenance, Task
from bohrin.mutate import discover as discover_operators
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus


def _baseline_candidate(task: Task) -> Candidate:
    """The reference itself, submitted unchanged. Never wrong by construction."""
    return Candidate(
        payload=task.reference or "",
        provenance=Provenance(
            operator="baseline",
            base="reference",
            detail="the taskset's own reference solution, submitted unchanged",
        ),
        ground=None,
    )


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

        measurable, baseline_failures, baseline_errors = await self._establish_baseline(source, tasks, config)
        # Serialized identically on every path: a key whose type depends on status breaks
        # any consumer that reads the JSON.
        baseline_detail = [{"task_id": b.task_id, "reward": b.reward, "reason": b.reason} for b in baseline_failures]

        if not measurable:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(tasks),
                reason=(
                    "no task could be baselined: every reference solution failed its own verifier, "
                    "so an accepted mutant would be indistinguishable from a submission-format problem"
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

        outcomes = await score_many(source, [(t, _baseline_candidate(t)) for t in with_reference], config)

        measurable: list[Task] = list(without_reference)
        failures: list[BaselineFailure] = []
        errors = 0

        for out in outcomes:
            if out.error is not None or out.verdict is None:
                errors += 1
                failures.append(
                    BaselineFailure(task_id=out.task.id, reward=0.0, reason=out.error or "no verdict returned")
                )
                continue
            if out.verdict.passed:
                measurable.append(out.task)
            else:
                failures.append(
                    BaselineFailure(
                        task_id=out.task.id,
                        reward=out.verdict.reward,
                        reason="the reference solution does not pass this task's own verifier",
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
