"""What each ``bohrin verify`` rule reports, in words a reviewer reads: the one place rules are described.

The SARIF renderer turns these into code-scanning rules, and a test holds this table, the rules the
code emits and the table in ``docs/SPEC.md`` to the same set, so a rule cannot be added without its
description, or described without existing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Rule:
    """One verify rule, as a reviewer sees it."""

    name: str
    weakness: str
    kind: str
    #: One line: what the rule reports.
    summary: str
    #: Why it matters and what to look at; shown as the rule's help.
    help: str


RULES: Mapping[str, Rule] = MappingProxyType(
    {
        "tests-removed": Rule(
            "TestsRemoved",
            "BGW-109",
            "fact",
            "Tests were deleted or emptied, and do not exist anywhere else.",
            "Tests that no longer run cannot fail. Check the tests were removed on purpose, not to make a change pass.",
        ),
        "check-weakened": Rule(
            "CheckWeakened",
            "BGW-109",
            "fact",
            "A test's checks dropped from comparing values to a weaker kind of check.",
            "A test that checked a value (or an error, containment or type) now checks only existence, truth, "
            "mock calls, a snapshot or nothing. It can now pass with wrong results.",
        ),
        "checks-removed": Rule(
            "ChecksRemoved",
            "BGW-109",
            "fact",
            "A test has fewer assertions than before.",
            "Each removed assertion is behaviour the test no longer checks.",
        ),
        "skips-added": Rule(
            "SkipsAdded",
            "BGW-109",
            "fact",
            "A test is now skipped or expected to fail, unconditionally.",
            "A skipped test never fails. Check the skip is temporary and tracked.",
        ),
        "conditional-skips-added": Rule(
            "ConditionalSkipsAdded",
            "BGW-109",
            "observation",
            "A test now skips under a condition.",
            "Conditional skips are routine (a missing optional dependency); check the condition cannot hold where "
            "the test matters.",
        ),
        "tolerance-loosened": Rule(
            "ToleranceLoosened",
            "BGW-134",
            "fact",
            "A numeric tolerance in a test was loosened.",
            "A wider tolerance accepts results further from the correct value, eventually clearly wrong ones.",
        ),
        "timeout-raised": Rule(
            "TimeoutRaised",
            "BGW-109",
            "fact",
            "A test's timeout was raised.",
            "A larger time budget can hide a hang or a performance regression.",
        ),
        "failure-swallowed": Rule(
            "FailureSwallowed",
            "BGW-109",
            "fact",
            "A check now sits inside a try whose except catches its failure.",
            "An except that catches AssertionError, Exception or everything silences the check it wraps.",
        ),
        "expected-value-changed": Rule(
            "ExpectedValueChanged",
            "BGW-109",
            "observation",
            "The value a test expects was changed.",
            "Changing an expectation is right when the intended behaviour changed, and wrong when the test was "
            "edited to match a new, incorrect output.",
        ),
        "subject-mocked": Rule(
            "SubjectMocked",
            "BGW-109",
            "observation",
            "A test now patches the function it is named after.",
            "A test that mocks the code it tests checks the mock, not the code.",
        ),
        "trivial-checks-added": Rule(
            "TrivialChecksAdded",
            "BGW-109",
            "observation",
            "A check that can never fail was added.",
            "assert True, or comparing a value with itself, always passes.",
        ),
        "tests-without-checks": Rule(
            "TestsWithoutChecks",
            "BGW-109",
            "observation",
            "A new test contains no assertion.",
            "A test with no assertion passes whenever the code runs, whatever it returns.",
        ),
        "report-hook-added": Rule(
            "ReportHookAdded",
            "BGW-108",
            "fact",
            "A conftest.py can now change what a test run reports.",
            "Hooks such as pytest_runtest_makereport, or a patch of TestReport, can turn failures into passes.",
        ),
        "selection-changed": Rule(
            "SelectionChanged",
            "BGW-109",
            "fact",
            "Which tests pytest collects or runs was changed in configuration.",
            "addopts, testpaths and similar settings can deselect tests without touching them.",
        ),
        "replaced-by-stub": Rule(
            "ReplacedByStub",
            "BGW-101",
            "fact",
            "A function that did work was replaced by a stub.",
            "A body of pass, ... or raise NotImplementedError does no work; check the change was meant to remove it.",
        ),
        "always-equal-added": Rule(
            "AlwaysEqualAdded",
            "BGW-103",
            "fact",
            "An __eq__ that always returns True was added.",
            "An object equal to everything passes every equality assertion without computing anything.",
        ),
        "timer-reassigned": Rule(
            "TimerReassigned",
            "BGW-113",
            "fact",
            "A timer such as time.perf_counter was reassigned.",
            "Replacing a timer changes what a performance measurement reads.",
        ),
        "exit-added": Rule(
            "ExitAdded",
            "BGW-102",
            "observation",
            "A call that exits the process was added to source.",
            "Routine in a command-line entry point; elsewhere, an exit before checks run can read as success.",
        ),
    }
)

__all__ = ["RULES", "Rule"]
