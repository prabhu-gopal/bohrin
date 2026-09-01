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


def test_memory_source_satisfies_the_task_source_protocol() -> None:
    source = MemorySource([Task(id="t", prompt="p")], lambda _t, _p: 1.0)
    assert isinstance(source, TaskSource)
