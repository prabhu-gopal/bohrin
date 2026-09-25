"""Fuzz every reader of untrusted input: each must refuse bad input cleanly, never crash.

Bohrin reads files other people wrote: finding records, registry records, conformance results,
results files, decisions files, and the source code of the tests ``bohrin verify`` compares. A
reader that meets malformed input must raise ``ValueError`` (or ``TypeError``) naming the problem;
any other exception is a crash a user would see as a traceback. :func:`check` feeds one input to
every reader and enforces that.

Run it with coverage-guided fuzzing (Linux, Python 3.12 or later, where Atheris has wheels):

    uv sync --frozen && uv pip install --require-hashes -r fuzz/requirements.txt
    uv run --no-sync python fuzz/fuzz_readers.py -max_total_time=60 fuzz/corpus

``tests/test_fuzz.py`` also runs :func:`check` on a fixed corpus and on seeded mutations of it in
every test run, so the harness itself can never rot.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from typing import Any

from bohrin.conformance import read_results as read_conformance_results
from bohrin.decisions import read_decisions
from bohrin.evidence.finding import Finding
from bohrin.history.facts import facts
from bohrin.ir.task import Task
from bohrin.registry import read_record
from bohrin.relations import positive_controls
from bohrin.stats.error_rate import read_outcome, read_planted
from bohrin.stats.results import read_row

#: Readers of parsed JSON, by name.
JSON_READERS: dict[str, Callable[[Any], object]] = {
    "finding": Finding.from_json,
    "registry-record": read_record,
    "conformance-results": read_conformance_results,
    "results-row": read_row,
    "finding-outcome": read_outcome,
    "recall-row": read_planted,
}

#: The only exceptions a reader may raise on bad input.
REFUSALS = (ValueError, TypeError)


def check(data: bytes) -> None:
    """Feed ``data`` to every reader, as JSON, as TOML and as Python source. Raises on a crash."""
    text = data.decode("utf-8", "replace")
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        parsed = None
    if parsed is not None:
        for reader in JSON_READERS.values():
            with contextlib.suppress(*REFUSALS):
                reader(parsed)
    with contextlib.suppress(*REFUSALS):
        read_decisions(text)
    # A reference solution, from an environment someone else wrote: its positive controls.
    positive_controls(Task(id="fuzz", prompt="", reference=text))
    # A test file changed into arbitrary text: facts must report, or list it as not checked.
    facts({"tests/test_fuzz.py": "def test_a():\n    assert f(1) == 1\n"}, {"tests/test_fuzz.py": text})


def main() -> None:  # pragma: no cover - runs only under the fuzzer
    import atheris  # type: ignore[import-not-found,import-untyped,unused-ignore]

    # Instrument every function already loaded (the readers above), or the fuzzer runs blind:
    # without coverage feedback its corpus never grows past its first input.
    atheris.instrument_all()
    atheris.Setup(sys.argv, lambda data: check(bytes(data)))
    atheris.Fuzz()


if __name__ == "__main__":  # pragma: no cover
    main()
