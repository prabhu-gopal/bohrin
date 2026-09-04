"""Adapter registry and the generic protocol.

Everything specific to the verifiers adapter lives in test_verifiers_adapter.py, where it
is exercised against the real library rather than against assumptions about it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bohrin.adapters.base import TaskSource, UnknownFormatError
from bohrin.adapters.memory import MemorySource
from bohrin.adapters.registry import detect, discover
from bohrin.ir.task import Task


def test_the_verifiers_adapter_is_registered() -> None:
    assert any(a.name == "verifiers_v1" for a in discover())


def test_an_unrecognised_directory_names_what_is_installed(tmp_path: Path) -> None:
    """ "Unknown format" without the list of adapters gives the user nothing to act on."""
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")

    with pytest.raises(UnknownFormatError, match="verifiers_v1"):
        detect(tmp_path)


def test_a_missing_path_says_so_instead_of_advising_an_install(tmp_path: Path) -> None:
    """A mistyped path must not be answered with advice about installing extras.

    Every adapter's `detect` returns 0.0 for a path that is not there, so without an
    explicit check a typo is indistinguishable from an unsupported format — and the user
    is sent to fix the wrong problem.
    """
    missing = tmp_path / "definitely-not-here"

    with pytest.raises(UnknownFormatError, match="no such file or directory") as excinfo:
        detect(missing)

    assert "pip install" not in str(excinfo.value), "a missing path is not an extras problem"


def test_memory_source_satisfies_the_task_source_protocol() -> None:
    source = MemorySource([Task(id="t", prompt="p")], lambda _t, _p: 1.0)
    assert isinstance(source, TaskSource)


def test_a_missing_extra_is_reported_before_the_isolation_refusal(tmp_path: Path) -> None:
    """Both are refusals; only one is the user's actual problem.

    Without the extra the audit cannot run at *any* isolation level, so leading with
    "start docker" costs the user a round trip to fix something that will not help.
    """
    from bohrin.adapters.base import Adapter, MissingExtraError

    class _NeedsExtra(Adapter):
        name = "needs_extra"

        def detect(self, path: Path) -> float:
            return 1.0

        def check_requirements(self) -> None:
            raise MissingExtraError("install the thing")

        def load(self, path: Path, config: object) -> TaskSource:  # pragma: no cover
            raise AssertionError("load must not be reached when the extra is missing")

    adapter = _NeedsExtra()
    with pytest.raises(MissingExtraError, match="install the thing"):
        adapter.check_requirements()


def test_check_requirements_defaults_to_permitting(tmp_path: Path) -> None:
    """An adapter with no optional dependency should not have to implement anything."""
    from bohrin.adapters.base import Adapter

    class _NoExtras(Adapter):
        name = "no_extras"

        def detect(self, path: Path) -> float:
            return 1.0

        def load(self, path: Path, config: object) -> TaskSource:  # pragma: no cover
            raise AssertionError("not called")

    _NoExtras().check_requirements()  # must not raise
