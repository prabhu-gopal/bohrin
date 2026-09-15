"""Probe 4 — Answer Leakage.

    Is the declared answer already written in the prompt?

The first three probes ask what a verifier does with a reply. This one asks something that
needs no reply at all: whether the task hands its own answer to whoever reads the question.
A model does not have to solve a task whose answer it can copy, and a grader that checks
only whether the answer *appears* in the reply pays full marks for copying it back.

It is the commonest root cause behind the findings Bohrin already makes. Two unrelated
public environments were flagged for the same reason before this probe existed: the graded
field sat verbatim in the prompt, so echoing the prompt scored full marks without doing the
task. The published record says the pattern is not rare. An audit of SWE-bench found the fix
revealed in the issue text for 33.47% of instances, and filtering those out cut one agent's
resolution rate from 12.47% to 4.58%. The Agentic Benchmark Checklist makes "the agent is
isolated from any ground truth information" an item of its own.

**It executes nothing.** No reward function is called, so it reads tasks the other probes
must refuse — a reward that needs a runtime, a rubric whose scale is unknown — and it costs
no scoring calls against someone else's environment.

**It is reported, never scored, for the same reason ``ground_truth_rejected`` is.** Two
situations produce an identical result and only one is a defect:

* the answer leaked into the prompt, and the task no longer tests what it claims to;
* the task is **extractive by design** — reading comprehension, look-up, span extraction —
  where the answer is supposed to be found in the passage.

Bohrin cannot read which one a task intends, so the finding is a lead for a human, and its
wording is a fact rather than a verdict: *the declared answer appears verbatim in the
prompt*.

**How it avoids reporting coincidence.** A literal overlap between two strings is not
evidence of a leak, and a naive version of this check was measured flagging a taskset's own
name. Four guards, each of which can only remove a finding:

1. **The field compared is the declared answer** — for ``verifiers`` v1 tasksets, the field
   the reward function itself reads — never every string in the task data.
2. **An uninformative answer is not checked.** A reference with fewer than four letters or
   digits (``A``, ``12``, ``yes``) will appear in prompts by accident, so it is counted as
   not checked rather than guessed about.
3. **The match is whole-token**, after Unicode (NFKC), case and whitespace normalisation, so
   ``cat`` is not found inside ``concatenate``.
4. **A permutation-style control.** If the same answer also appears in the prompt of
   another task whose declared answer is provably different, its presence identifies
   nothing — it is shared vocabulary, like an option label or the name of the library every
   task is about — and the task is counted as a generic overlap instead. This is the
   cross-item null model contamination audits use: a signal that fires as often on
   mismatched pairs as on matched ones is not a signal.

Copy and echo tasks, whose declared answer *is* the prompt, are excluded outright.
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from collections.abc import Sequence

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import AnswerInPrompt, Finding
from bohrin.ir.task import Task
from bohrin.mutate.equivalence import collides_under, provably_distinct, reads_as_refusal, reads_as_structured_state
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.scoring.interval import rate

#: Letters and digits a declared answer needs before an overlap with the prompt means
#: anything. ``A``, ``12`` and ``yes`` occur in prompts by chance; four characters is the
#: shortest answer where a whole-token match is unlikely to be one.
MIN_INFORMATIVE_CHARS = 4

#: Answers from a closed set of two or three, which a prompt names by construction
#: ("answer yes or no") however the task is written.
_CLOSED_SET = frozenset({"true", "false", "none", "null", "yes", "no"})

#: How many other tasks the control compares against. Bounded so a full taskset of
#: thousands costs seconds rather than a quadratic scan, and recorded on every finding.
NULL_SAMPLE = 200

#: Characters of context kept either side of the match, so a reader can judge the finding.
_CONTEXT = 60


def _normalise(text: str) -> str:
    """Unicode-compatible, case-folded, whitespace-collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _informative(reference: str) -> bool:
    folded = _normalise(reference)
    return sum(ch.isalnum() for ch in folded) >= MIN_INFORMATIVE_CHARS and folded not in _CLOSED_SET


def _whole_token(needle: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")


def _excerpt(prompt: str, reference: str) -> str:
    """The match in its context, taken from the prompt as written rather than normalised."""
    flat = " ".join(unicodedata.normalize("NFKC", prompt).split())
    needle = " ".join(unicodedata.normalize("NFKC", reference).split())
    match = re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", flat, re.IGNORECASE)
    if match is None:  # a case mapping NFKC and casefold disagree on; fall back to the folded text
        flat = _normalise(prompt)
        match = _whole_token(_normalise(reference)).search(flat)
        if match is None:
            return ""
    start, end = max(0, match.start() - _CONTEXT), min(len(flat), match.end() + _CONTEXT)
    return f"{'…' if start else ''}{flat[start:end]}{'…' if end < len(flat) else ''}"


class AnswerLeakageProbe(Probe):
    """Look for each task's declared answer inside its own prompt."""

    id = "answer_leakage"
    family = "task_validity"

    #: Reported, never scored — an extractive task and a leaked one look identical. See the
    #: module docstring.
    weight = 0.0

    def explain(self) -> str:
        return (
            "Looks for each task's declared answer written verbatim in that task's own prompt. "
            "A model does not have to solve a task whose answer it can copy, and a grader that "
            "checks only whether the answer appears in the reply pays full marks for copying it. "
            "It calls no reward function, so it also reads tasks the other probes cannot score.\n\n"
            "What it cannot see: whether the task is meant to contain its answer. In reading "
            "comprehension or look-up tasks the answer is supposed to be in the passage, and that "
            "looks exactly like a leak, so this probe reports what it found and contributes nothing "
            "to the Verification Gap. It does not check answers with fewer than four letters or "
            "digits, which appear in prompts by chance, and it does not report an answer that also "
            "appears in the prompt of a task with a different answer, where its presence identifies "
            "nothing. A paraphrased or partial leak is not detected."
        )

    async def run(self, source: TaskSource, config: ScanConfig) -> ProbeResult:
        tasks = list(source.tasks())
        if config.only_tasks:
            tasks = [t for t in tasks if t.id in config.only_tasks]
        if config.max_tasks is not None:
            tasks = tasks[: config.max_tasks]

        checked: list[Task] = []
        not_checked = 0
        by_design = 0
        for task in tasks:
            reference = (task.reference or "").strip()
            if not reference:
                continue
            if reads_as_structured_state(reference) or reads_as_refusal(reference) or not _informative(reference):
                not_checked += 1
                continue
            # A copy or echo task declares its prompt as its answer; the answer being in the
            # prompt is the task, not a leak.
            if task.prompt.strip() and collides_under(task.prompt, reference) is not None:
                by_design += 1
                continue
            checked.append(task)

        if not checked:
            return ProbeResult(
                probe_id=self.id,
                status=ProbeStatus.NOT_APPLICABLE,
                tasks_probed=len(tasks),
                reason=(
                    "no task declares an answer informative enough to look for: answers shorter than "
                    f"{MIN_INFORMATIVE_CHARS} letters or digits, yes/no answers, JSON objects and copy "
                    "tasks appear in prompts without anything having leaked"
                ),
                detail={"tasks_not_checked": not_checked, "tasks_prompt_is_answer": by_design},
            )

        normalised = {task.id: _normalise(task.prompt) for task in tasks}
        findings: list[Finding] = []
        generic = 0
        for task in checked:
            reference = (task.reference or "").strip()
            needle = _normalise(reference)
            pattern = _whole_token(needle)
            if needle not in normalised[task.id] or pattern.search(normalised[task.id]) is None:
                continue
            others = self._control_group(task, tasks)
            if any(needle in normalised[other.id] and pattern.search(normalised[other.id]) for other in others):
                generic += 1
                continue
            findings.append(
                AnswerInPrompt(
                    task_id=task.id,
                    reference=reference,
                    excerpt=_excerpt(task.prompt, reference),
                    compared_with=len(others),
                    repro_args=f"--task {shlex.quote(task.id)} --probe {self.id}",
                )
            )

        return ProbeResult(
            probe_id=self.id,
            status=ProbeStatus.OK,
            tasks_probed=len(checked),
            # Kept out of the Verification Gap by `weight = 0.0`, not by hiding the number.
            sub_score=len(findings) / len(checked),
            findings=tuple(findings),
            detail={
                "tasks_checked": len(checked),
                "tasks_answer_in_prompt": len(findings),
                # The answer was in the prompt, and also in the prompt of a task with a different
                # answer, so its presence identified nothing.
                "tasks_generic_overlap": generic,
                "tasks_not_checked": not_checked,
                "tasks_prompt_is_answer": by_design,
                "min_informative_chars": MIN_INFORMATIVE_CHARS,
                "rate": rate(len(findings), len(checked)),
                "scored_out_of_gap": True,
            },
        )

    @staticmethod
    def _control_group(task: Task, tasks: Sequence[Task]) -> list[Task]:
        """Up to :data:`NULL_SAMPLE` other tasks whose declared answer is provably different.

        An answer that appears in one of *their* prompts is shared vocabulary, not a leak. The
        group is taken in taskset order, so the same audit always compares against the same
        tasks and a finding reproduces.
        """
        reference = task.reference or ""
        group: list[Task] = []
        for other in tasks:
            if len(group) >= NULL_SAMPLE:
                break
            if other.id == task.id or not (other.reference or "").strip():
                continue
            if provably_distinct(other.reference or "", reference):
                group.append(other)
        return group


__all__ = ["MIN_INFORMATIVE_CHARS", "NULL_SAMPLE", "AnswerLeakageProbe"]
