"""The fuzz harness runs in every test run: on its corpus, and on seeded mutations of it.

``fuzz/fuzz_readers.py`` is run by a coverage-guided fuzzer on a schedule. Here the same check runs
deterministically, so a reader that starts crashing on malformed input fails the ordinary build,
and the harness cannot rot between fuzzing runs.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from bohrin.evidence import _strict as strict
from bohrin.stats.results import read_row

ROOT = Path(__file__).resolve().parents[1]
CORPUS = sorted((ROOT / "fuzz" / "corpus").iterdir())


def _harness() -> Any:
    spec = importlib.util.spec_from_file_location("fuzz_readers", ROOT / "fuzz" / "fuzz_readers.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuzz_readers"] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _harness()

#: Replacement values that have broken JSON readers elsewhere: wrong types, huge and odd numbers,
#: lone surrogates, deep nesting.
_HOSTILE: list[Any] = [None, True, 0, -0.0, 10**400, 1e308, "", "\x00", "\ud800", [], {}, [[[[]]]], "BGW-1" * 200]


def _mutate_json(value: Any, rng: random.Random) -> Any:
    if isinstance(value, dict) and value and rng.random() < 0.8:
        key = rng.choice(sorted(value))
        return {**value, key: _mutate_json(value[key], rng)}
    if isinstance(value, list) and value and rng.random() < 0.8:
        index = rng.randrange(len(value))
        return [*value[:index], _mutate_json(value[index], rng), *value[index + 1 :]]
    return rng.choice(_HOSTILE)


def _mutate_bytes(data: bytes, rng: random.Random) -> bytes:
    out = bytearray(data)
    for _ in range(rng.randint(1, 6)):
        if out and rng.random() < 0.7:
            out[rng.randrange(len(out))] = rng.choice(b'"[]{}:=,\n\\x0\x00\xff')
        else:
            out.insert(rng.randrange(len(out) + 1), rng.choice(b'"[{\n'))
    return bytes(out)


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_every_corpus_file_is_handled(path: Path) -> None:
    HARNESS.check(path.read_bytes())


def test_seeded_mutations_of_the_corpus_never_crash_a_reader() -> None:
    rng = random.Random(20260925)
    seeds = [path.read_bytes() for path in CORPUS]
    for _ in range(1500):
        seed = rng.choice(seeds)
        try:
            parsed = json.loads(seed)
        except (ValueError, RecursionError):  # not JSON, or nested past the parser's recursion
            HARNESS.check(_mutate_bytes(seed, rng))
            continue
        HARNESS.check(
            json.dumps(_mutate_json(parsed, rng)).encode() if rng.random() < 0.7 else _mutate_bytes(seed, rng)
        )


# --------------------------------------------------------------------------- what the fuzzing found


def test_an_integer_too_large_for_a_float_is_refused_not_a_crash() -> None:
    """JSON allows any number of digits; converting one with 400 raised OverflowError before."""
    with pytest.raises(ValueError, match="too large"):
        strict.number(10**400, "score")
    with pytest.raises(ValueError, match="too large"):
        read_row({"task_id": "t", "model": "m", "score": 10**400})


def test_the_harness_names_every_json_reader() -> None:
    assert set(HARNESS.JSON_READERS) == {
        "finding",
        "registry-record",
        "conformance-results",
        "results-row",
        "finding-outcome",
        "recall-row",
    }
