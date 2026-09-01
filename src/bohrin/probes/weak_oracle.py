"""Probe 1 — Weak Oracle.

    Will this verifier accept work that is provably incorrect?

This is mutation testing with the roles relabelled: the candidate is the code under test,
**the verifier is the test suite**, and a surviving mutant is a wrong solution the verifier
accepted. The technique is decades old and no novelty is claimed for it; what matters here
is the discipline around what may be reported.
"""

from __future__ import annotations

from collections.abc import Iterable

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.execute.runner import ScoreOutcome, score_many
from bohrin.ir.evidence import Exploit, Finding, Unverified
from bohrin.ir.task import Candidate, Task
from bohrin.mutate import discover as discover_operators
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus


class WeakOracleProbe(Probe):
    """Submit provably-wrong candidates and record the ones that pass."""

    id = "weak_oracle"
    family = "acceptance"

    def explain(self) -> str:
        return (
            "Generates submissions that are provably incorrect and offers them to the "
            "verifier. Anything accepted is a false positive: a task that rewards failure. "
            "A candidate is only reported as an exploit when its wrongness was established "
            "independently of the verifier being audited — otherwise it is a lead, because "
            "a mutation that merely looks different may be behaviourally identical, and "
            "reporting that as a defect would accuse a correct verifier."
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

        work: list[tuple[Task, Candidate]] = [
            (task, cand) for task in tasks for op in operators for cand in op.apply(task)
        ]
        if not work:
            # Every operator declined. Honest outcome: the probe ran and found nothing it
            # could safely try, which is different from finding a clean verifier.
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                tasks_probed=len(tasks),
                reason="no operator could establish wrongness for any task (is a reference solution available?)",
            )

        outcomes = await score_many(source, work, config)
        findings, unverified, errors = self._triage(outcomes)

        compromised = {f.task_id for f in findings}
        return ProbeResult(
            probe_id=self.id,
            status=ProbeStatus.OK,
            tasks_probed=len(tasks),
            sub_score=len(compromised) / len(tasks),
            findings=tuple(findings),
            unverified=tuple(unverified),
            detail={
                "operators": [op.id for op in operators],
                "candidates_submitted": len(work),
                "tasks_compromised": len(compromised),
                "errors": errors,
            },
        )

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
