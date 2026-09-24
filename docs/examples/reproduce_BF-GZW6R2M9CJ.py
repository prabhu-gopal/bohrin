#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
#
# [tool.bohrin]
# schema = "https://bohrin.com/schema/reproduction/v1"
# finding = "BF-GZW6R2M9CJ"
# probe = "bohrin/empty-implementation@1"
# runs = 3
#
# [tool.bohrin.submission]
# kind = "source"
# sha256 = "sha256:60a654efdbfdbd6b99d73610003be0292733d39aed50c04b60887ab167db3ddd"
# ///
"""Reproduce BF-GZW6R2M9CJ: the grader pays full marks for `add` with its body replaced by `pass`.

This script needs nothing from Bohrin and makes no network call. It runs your grader, unchanged,
on the task's reference and on the submission below, three times each, and prints one line of
JSON saying what happened. Each run happens in a fresh process with a time limit, so nothing the
submission does can stop this script from reporting or carry over into the next run, and a run
that reports no reward counts as not paid. Read it before you run it: it is short on purpose.

    uv run reproduce_BF-GZW6R2M9CJ.py        # or: python reproduce_BF-GZW6R2M9CJ.py

Exit code: 0 reproduced, 1 not reproduced, 2 flaky, 3 the reference failed, 4 could not run.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

FINDING = "BF-GZW6R2M9CJ"
RUNS = 3
FULL_MARKS = 1.0
TIMEOUT_S = 60

#: The task's reference solution, which a correct grader must accept.
REFERENCE = "def add(a, b):\n    return a + b\n"

#: The exact submission the finding is about: the reference with every body replaced by `pass`.
SUBMISSION = "def add(a, b):\n    pass\n"
SUBMISSION_SHA256 = "sha256:60a654efdbfdbd6b99d73610003be0292733d39aed50c04b60887ab167db3ddd"

EXIT = {"reproduced": 0, "not-reproduced": 1, "flaky": 2, "baseline-failed": 3, "error": 4}


#: What runs in the fresh process: your grader, called exactly as your harness calls it. The last
#: line it prints is the reward; if it prints none (it exited, crashed or hung), the run is not paid.
CHILD = """
import json, sys
from toy_grader import grade  # the grader under test: your own code, on your machine
print(json.dumps({"reward": float(grade(sys.stdin.read()))}))
"""


def run_grader(solution: str) -> dict[str, object]:
    """Score one solution in a fresh process with a time limit; no reward reported means not paid."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", CHILD],
            input=solution,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            cwd=Path(__file__).resolve().parent,
            check=False,
        )
        reward = float(json.loads(done.stdout.strip().splitlines()[-1])["reward"])
    except (subprocess.TimeoutExpired, IndexError, KeyError, TypeError, ValueError):
        reward = 0.0
    return {"reward": reward, "passed": reward >= FULL_MARKS}


def outcome(runs: list[dict[str, object]], baseline: list[dict[str, object]]) -> str:
    """Reproduced only if the reference passed every run and the submission was paid every run."""
    submission_passed = {run["passed"] for run in runs}
    baseline_passed = {run["passed"] for run in baseline}
    if baseline_passed == {False}:
        return "baseline-failed"
    if len(baseline_passed) > 1 or len(submission_passed) > 1:
        return "flaky"
    return "reproduced" if submission_passed == {True} else "not-reproduced"


def main() -> int:
    """Check the submission is the one the finding names, run both, report one line of JSON."""
    report: dict[str, object] = {
        "$schema": "https://bohrin.com/schema/reproduction-result/v1",
        "finding": FINDING,
        "submission": {"kind": "source", "sha256": SUBMISSION_SHA256},
        "runs": [],
        "baseline_runs": [],
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    digest = "sha256:" + hashlib.sha256(SUBMISSION.encode("utf-8")).hexdigest()
    try:
        if digest != SUBMISSION_SHA256:
            raise RuntimeError("the embedded submission does not match its declared digest")
        baseline = [run_grader(REFERENCE) for _ in range(RUNS)]
        runs = [run_grader(SUBMISSION) for _ in range(RUNS)]
    except Exception as exc:  # anything that stops the grader running is reported, not raised
        report.update(outcome="error", error=f"{type(exc).__name__}: {exc}")
    else:
        report.update(runs=runs, baseline_runs=baseline, outcome=outcome(runs, baseline))
    print(json.dumps(report))
    return EXIT[str(report["outcome"])]


if __name__ == "__main__":
    sys.exit(main())
