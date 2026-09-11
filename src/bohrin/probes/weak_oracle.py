"""Probe 1 — Weak Oracle.

    Will this verifier accept work that is provably incorrect?

This is mutation testing with the roles relabelled: the candidate is the code under test,
**the verifier is the test suite**, and a surviving mutant is a wrong solution the verifier
accepted. The technique is decades old and no novelty is claimed for it; what matters here
is the discipline around what may be reported.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace

from bohrin.adapters.base import TaskSource
from bohrin.adapters.verifiers_v1 import reference_renderings
from bohrin.config import ScanConfig
from bohrin.execute.runner import ScoreOutcome, score_many
from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, HarnessDisruption, Unverified
from bohrin.ir.task import Candidate, Provenance, Task, Verdict
from bohrin.mutate import discover as discover_operators
from bohrin.mutate.equivalence import code_equivalent, collides_under, reads_as_refusal
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.scoring.interval import rate


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


def _is_the_reference(payload: str, reference: str) -> bool:
    """Whether a candidate is the known-good answer, under any reading a correct verifier
    may apply: as an answer (every normalisation in the equivalence ladder) or as a program
    (Trivial Compiler Equivalence). Either one means the candidate cannot be wrong."""
    return collides_under(payload, reference) is not None or code_equivalent(payload, reference)


_OFF_SCALE = (
    "the verifier accepted this, but its rubric paid more than its own declared full marks on "
    "this task, so its scale is unknown and a reply reaching the bar cannot be shown to have "
    "scored like a correct one"
)


class _ScaleWatch:
    """A source that remembers every task on which the rubric paid past full marks.

    Wraps the baseline and the candidates alike. A reference paying 15 on a rubric whose
    weights promise at most 1 is as telling as a candidate doing so: either way, "reached
    full marks" on that task no longer means "scored like a correct reply".
    """

    def __init__(self, source: TaskSource) -> None:
        self._source = source
        self.off_scale: set[str] = set()

    def tasks(self) -> Iterator[Task]:
        return self._source.tasks()

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        verdict = await self._source.score(task, candidate)
        if verdict.scale_exceeded:
            self.off_scale.add(task.id)
        return verdict


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
        if config.only_operators:
            operators = [op for op in operators if op.id in config.only_operators]
        if not operators:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                reason=(
                    f"no operator matched --operator {', '.join(sorted(config.only_operators))}"
                    if config.only_operators
                    else "no mutation operators are registered"
                ),
            )

        tasks = list(source.tasks())
        if config.only_tasks:
            tasks = [t for t in tasks if t.id in config.only_tasks]
        if config.max_tasks is not None:
            tasks = tasks[: config.max_tasks]
        if not tasks:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                reason=(
                    f"no task matched --task {', '.join(sorted(config.only_tasks))}"
                    if config.only_tasks
                    else "the taskset is empty"
                ),
            )

        # Tasks the adapter has already declared unscoreable offline are excluded up front
        # rather than discovered through one failure per candidate. Cheaper, and the reason
        # reaches the user instead of an error count.
        offline, refused = self._partition_scoreable(tasks)

        watch = _ScaleWatch(source)
        measurable, baseline_failures, baseline_errors = await self._establish_baseline(watch, offline, config)
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
                    "no task could be measured offline: every task has no reward function at all, "
                    "or needs a runtime to score, or its reference solution fails its own verifier "
                    "— in which case an accepted mutant would be indistinguishable from a "
                    "submission-format problem"
                ),
                detail={"baseline_failures": baseline_detail, "baseline_errors": baseline_errors},
            )

        work: list[tuple[Task, Candidate]] = []
        # Redundant mutants are a known validity threat in mutation testing, and here they
        # also cost a real scoring call against someone else's environment. Two candidates
        # whose payloads are equal after stripping are the same submission as far as any
        # verifier is concerned, so only the first is sent.
        equivalent_suppressed = 0
        grounds_withdrawn = 0
        for task in measurable:
            submitted: set[str] = set()
            # On a task whose declared answer is itself a refusal, "correct" means only
            # "did not comply", and every candidate below is non-compliant. None of them is
            # wrong there, so each is submitted as a lead instead. Applied here rather than
            # left to operators so a third-party operator cannot miss it.
            refusal_task = bool(task.reference) and reads_as_refusal(task.reference or "")
            for op in operators:
                for cand in op.apply(task):
                    key = cand.payload.strip()
                    if key in submitted:
                        continue
                    # A grounded candidate that *is* the reference -- as an answer or as a
                    # program -- would accuse a verifier of accepting its own known-good
                    # answer. Applied to every candidate regardless of which operator
                    # produced it: first-party operators guard themselves, and this is the
                    # backstop for third-party ones, which reach the same seam with no
                    # privileged path and no review.
                    #
                    # Until 1.2 the backstop compared programs only. That left open the
                    # failure it exists for -- 1.0.1's launch blocker was ``1`` against a
                    # reference of ``1.0``, a collision of *answers*, and a third-party
                    # operator submitting ``70.0`` against ``70`` still reached a correct
                    # numeric grader as an exploit.
                    if cand.known_wrong and task.reference and _is_the_reference(cand.payload, task.reference):
                        equivalent_suppressed += 1
                        continue
                    if cand.known_wrong and refusal_task:
                        cand = replace(cand, ground=None)
                        grounds_withdrawn += 1
                    submitted.add(key)
                    work.append((task, cand))
        if not work:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                tasks_probed=len(measurable),
                reason="no operator could establish wrongness for any task (is a reference solution available?)",
            )

        outcomes = await score_many(watch, work, config)
        findings, unverified, errors = self._triage(outcomes)

        # A rubric that paid past its own declared full marks has a scale Bohrin cannot read,
        # so on that task "reached full marks" is not evidence of anything. Its tasks leave
        # the denominator and what it accepted becomes a lead. Found on real environments: a
        # 0-15 criteria sum and a 1-5 rating mean were both reported as exploited, because
        # 12 and 2.5 each clear a bar of 1.
        off_scale = watch.off_scale & {t.id for t in measurable}
        if off_scale:
            unverified = [
                *unverified,
                *(
                    Unverified(task_id=f.task_id, candidate=f.candidate, verdict=f.verdict, reason=_OFF_SCALE)
                    for f in findings
                    if isinstance(f, Exploit) and f.task_id in off_scale
                ),
            ]
            # Exploits only: a crash the payload triggered is a defect on any scale.
            findings = [f for f in findings if not (isinstance(f, Exploit) and f.task_id in off_scale)]
            measurable = [t for t in measurable if t.id not in off_scale]
        if not measurable:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(off_scale),
                unverified=tuple(unverified),
                reason=(
                    "not measured: on every task the rubric paid more than its own declared full "
                    "marks, so its scale is unknown and no accepted reply can be shown to have "
                    "scored like a correct one"
                ),
                detail={
                    "baseline_failures": baseline_detail,
                    "candidates_submitted": len(work),
                    "tasks_scale_unknown": len(off_scale),
                    "errors": errors,
                },
            )

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

        # Exploits only. A harness disruption is a robustness defect, not an acceptance:
        # nothing was accepted, so counting it here would raise the Verification Gap as
        # though the verifier had rewarded wrong work. It is reported alongside, and scored
        # separately from, the thing this sub-score measures.
        compromised = {f.task_id for f in findings if isinstance(f, Exploit)}
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
                "rate": rate(len(compromised), len(measurable)),
                "baseline_failures": baseline_detail,
                "baseline_errors": baseline_errors,
                "tasks_without_reference": unbaselined,
                # Candidates that were the reference itself, as an answer or as a program. A
                # non-zero count means an operator tried to accuse a verifier of accepting
                # its own answer.
                "equivalent_suppressed": equivalent_suppressed,
                # Candidates submitted as leads because the task's declared answer is a
                # refusal, where no non-compliant reply can be shown to be wrong.
                "grounds_withdrawn": grounds_withdrawn,
                # Tasks excluded because their rubric paid past its own declared full marks.
                "tasks_scale_unknown": len(off_scale),
                "errors": errors,
            },
        )

    @staticmethod
    def _partition_scoreable(tasks: Sequence[Task]) -> tuple[list[Task], list[BaselineFailure]]:
        """Split tasks the adapter can score offline from ones it has refused.

        Two reasons a task is refused, and the second is the more dangerous one.

        A task whose reward function needs a runtime cannot be scored honestly without one
        (scoring it offline would award full marks on a partial rubric). The adapter marks
        those; excluding them here means the user is told once, clearly, rather than through
        a wall of per-candidate errors.

        A task with **no reward function at all** has no verifier to audit. Every candidate
        submitted to it scores zero, so every one is "rejected", so the probe reports no
        accepted wrong solutions — and a taskset that was never examined comes back as
        ``0 / 100`` at full coverage. That is the strongest possible statement Bohrin can
        make, produced by measuring nothing.

        It is not a hypothetical. Five of the eighteen loadable environments in the public
        `verifiers` repository — ``wordle``, ``kuhn_poker``, ``openenv_wordle``,
        ``proposer_solver``, ``wiki_search`` — enumerate tasks carrying zero reward hooks,
        because they are judged cross-agent, at the episode level, or by a seat that is
        minted only once a model has run. All five reported a clean sweep.
        """
        offline: list[Task] = []
        refused: list[BaselineFailure] = []
        for task in tasks:
            needs = task.metadata.get("requires_runtime") or ()
            if not task.reward_fns:
                refused.append(
                    BaselineFailure(
                        task_id=task.id,
                        reward=0.0,
                        reason=(
                            "no reward function is attached to this task, so there is no verifier "
                            "to audit; it is judged elsewhere (cross-agent, per episode, or by a "
                            "task minted at runtime)"
                        ),
                    )
                )
            elif needs:
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

        # A crash is only the verifier's defect if the *payload* triggered it. A task where
        # every attempt failed is a setup, network or environment problem, and blaming the
        # grader for it would be a false accusation. Requiring at least one successful score
        # on the same task isolates the payload as the trigger -- and the burden of
        # well-formedness stays ours, which is why every payload is a plain string.
        scored_ok = {out.task.id for out in outcomes if out.error is None and out.verdict is not None}
        crashed: set[str] = set()

        for out in outcomes:
            if out.error is not None:
                errors += 1
                if out.task.id in scored_ok and out.task.id not in crashed:
                    crashed.add(out.task.id)
                    findings.append(
                        HarnessDisruption(
                            task_id=out.task.id,
                            error=out.error,
                            payload=out.candidate.payload,
                            operator=out.candidate.provenance.operator,
                            repro_args=(
                                f"--task {shlex.quote(out.task.id)} "
                                f"--operator {shlex.quote(out.candidate.provenance.operator)}"
                            ),
                        )
                    )
                continue
            verdict = out.verdict
            if verdict is None or not verdict.passed:
                continue

            key = (out.task.id, out.candidate.provenance.operator)
            if key in seen:
                continue
            seen.add(key)

            # Shell-quoted: a task id is taskset-supplied and routinely contains spaces
            # (`glossary` names its tasks "Ada Lovelace"), which would split into two
            # arguments and make the printed command fail with `unrecognized arguments`.
            repro_args = (
                f"--task {shlex.quote(out.task.id)} --operator {shlex.quote(out.candidate.provenance.operator)}"
            )
            if out.candidate.known_wrong:
                findings.append(
                    Exploit(task_id=out.task.id, candidate=out.candidate, verdict=verdict, repro_args=repro_args)
                )
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
