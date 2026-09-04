"""Probe 2 — Determinism.

    Does the verifier return the same reward for the same submission?

A grader that disagrees with itself is unreliable by definition, and in an RL context that
is not cosmetic: it injects noise straight into the reward signal. Common causes are
timeouts, network access, unseeded randomness, filesystem or ordering dependence, and
clock sensitivity.

Two properties make this the right second probe for the open tier:

* **It is universal.** It needs no rubric structure and no reference solution, so it runs
  on the single-reward-function tasks that make up most of the real ecosystem. The
  composition probe originally planned here could not — see ``docs/03_PROBES.md``.
* **It cannot false-accuse.** Every other probe *infers* that a verifier is wrong. This
  one *observes* it: the same bytes were submitted N times and the grader disagreed with
  itself. There is no equivalence problem and no correctness judgement to get wrong.
"""

from __future__ import annotations

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.execute.runner import score_many
from bohrin.ir.evidence import Finding, Flake
from bohrin.ir.task import Candidate, Provenance, Task
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus

#: Rewards closer than this are treated as equal, so ordinary float noise is not reported
#: as a defect. A verifier whose reward wobbles in the twelfth decimal is not the problem
#: this probe exists to find.
_TOLERANCE = 1e-9

#: Flake rates the report quotes detection power for. Chosen to span the range a user
#: actually cares about: a coin-flip verifier down to a rare intermittent one.
_REFERENCE_RATES = (0.5, 0.2, 0.1, 0.05, 0.01)


def detection_power(rate: float, repeats: int) -> float:
    """Probability of observing disagreement in ``repeats`` runs of a verifier that flips
    with probability ``rate``.

    Disagreement is observed unless every run lands on the same side, so

        P(detect) = 1 - rate**n - (1 - rate)**n

    This matters because a "no variance observed" result is easy to misread as "this
    verifier is deterministic". It is not: at five repeats a verifier that flips 5% of the
    time is missed roughly 77% of the time. Published work on flaky-test detection makes
    the same point at larger budgets — even a thousand reruns has under a 10% chance of
    surfacing a flake with a rate near 1e-4.
    """
    if repeats < 2:
        return 0.0
    return 1.0 - rate**repeats - (1.0 - rate) ** repeats


class DeterminismProbe(Probe):
    """Submit the identical candidate repeatedly and look for disagreement."""

    id = "determinism"
    family = "reliability"

    def explain(self) -> str:
        return (
            "Submits one identical candidate to each task several times and reports any "
            "task whose verifier returns different rewards. A grader that disagrees with "
            "itself injects noise directly into the reward signal. This probe measures "
            "reliability, not correctness: a perfectly deterministic verifier can still be "
            "badly wrong, and findings here are reported separately for that reason."
        )

    @staticmethod
    def _probe_candidate(task: Task) -> Candidate:
        """A fixed submission. Correctness is irrelevant — only that it never varies."""
        payload = task.reference if task.reference is not None else "bohrin-determinism-probe"
        return Candidate(
            payload=payload,
            provenance=Provenance(
                operator="determinism",
                base="reference" if task.reference is not None else "constant",
                detail="identical submission repeated to detect verifier variance",
            ),
            ground=None,  # never an exploit: this probe makes no claim about correctness
        )

    async def run(self, source: TaskSource, config: ScanConfig) -> ProbeResult:
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
        if config.repeats < 2:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                reason=f"repeats={config.repeats}; at least 2 are needed to observe disagreement",
            )

        work = [(task, self._probe_candidate(task)) for task in tasks for _ in range(config.repeats)]
        outcomes = await score_many(source, work, config)

        rewards: dict[str, list[float]] = {task.id: [] for task in tasks}
        errors = 0
        for out in outcomes:
            if out.error is not None or out.verdict is None:
                errors += 1
                continue
            rewards[out.task.id].append(out.verdict.reward)

        findings: list[Finding] = []
        measured = 0
        for task in tasks:
            seen = rewards[task.id]
            if len(seen) < 2:
                continue  # too few successful scores to say anything
            measured += 1
            if max(seen) - min(seen) > _TOLERANCE:
                findings.append(
                    Flake(
                        task_id=task.id,
                        rewards=tuple(seen),
                        repro_args=f"--task {task.id} --probe determinism --repeats {config.repeats}",
                    )
                )

        if measured == 0:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.ERROR,
                tasks_probed=len(tasks),
                reason="every scoring attempt failed; no task could be measured",
                detail={"errors": errors},
            )

        # Quote the power of the measurement alongside its result. A null finding here
        # bounds the flake rate; it does not establish determinism, and the report must not
        # let a reader believe otherwise.
        power = {f"{r:g}": round(detection_power(r, config.repeats), 4) for r in _REFERENCE_RATES}

        return ProbeResult(
            probe_id=self.id,
            status=ProbeStatus.OK,
            tasks_probed=measured,
            sub_score=len(findings) / measured,
            findings=tuple(findings),
            detail={
                "repeats": config.repeats,
                "tasks_measured": measured,
                "errors": errors,
                "detection_power": power,
                "power_note": (
                    f"with {config.repeats} repeats, a verifier flipping 50% of the time is observed "
                    f"{power['0.5'] * 100:.0f}% of the time and one flipping 5% of the time "
                    f"{power['0.05'] * 100:.0f}% of the time; a null result bounds the rate rather "
                    f"than proving determinism"
                ),
            },
        )


__all__ = ["DeterminismProbe", "detection_power"]
