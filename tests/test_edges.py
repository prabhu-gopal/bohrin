"""Edges that no other test reaches: malformed input to the certificates, and the entry points.

Each is a promise the documentation makes (a certificate says "not proved" for code that does not
compile, rather than raising; ``python -m`` runs the same program as the installed command).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from bohrin.cli import CLEAN, run
from bohrin.relations.certify import same_bytecode_except_local_names, same_syntax


@pytest.mark.parametrize("broken", ["def f(:\n", "x = 1\n\0"])
def test_a_certificate_over_code_that_does_not_parse_proves_nothing(broken: str) -> None:
    assert same_syntax(broken, broken) is False
    assert same_bytecode_except_local_names(broken, broken) is False


def test_code_that_parses_but_does_not_compile_has_no_bytecode_to_compare() -> None:
    """``return`` outside a function parses, so its tree exists, but it never compiles."""
    assert same_syntax("return 1\n", "return 1\n") is True
    assert same_bytecode_except_local_names("return 1\n", "return 1\n") is False


def test_the_console_script_exits_with_mains_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["bohrin"])
    with pytest.raises(SystemExit) as stopped:
        run()
    assert stopped.value.code == CLEAN


@pytest.mark.parametrize(("module", "expect"), [("bohrin", "power"), ("bohrin.spec", "BGW-101")])
def test_each_module_runs_as_a_program(module: str, expect: str) -> None:
    done = subprocess.run([sys.executable, "-m", module], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert expect in done.stdout
