"""Adapter detection and the missing-extra path."""

from __future__ import annotations

from pathlib import Path

import pytest

from bohrin.adapters.base import MissingExtraError, TaskSource, UnknownFormatError
from bohrin.adapters.memory import MemorySource
from bohrin.adapters.registry import detect, discover
from bohrin.adapters.verifiers_v1 import VerifiersV1Adapter
from bohrin.config import ScanConfig
from bohrin.ir.task import Task


def test_the_verifiers_adapter_is_registered() -> None:
    assert any(a.name == "verifiers_v1" for a in discover())


def test_detection_reads_files_only(tmp_path: Path) -> None:
    """Detection must work without the extra installed, so the error can be actionable."""
    root = tmp_path / "envs" / "demo"
    root.mkdir(parents=True)
    (root / "taskset.py").write_text("import verifiers.v1 as vf\n", encoding="utf-8")

    assert VerifiersV1Adapter().detect(tmp_path) == pytest.approx(0.7)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert VerifiersV1Adapter().detect(tmp_path) == pytest.approx(0.95)


def test_a_directory_of_junk_is_not_claimed(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    assert VerifiersV1Adapter().detect(tmp_path) == 0.0
    with pytest.raises(UnknownFormatError):
        detect(tmp_path)


def test_loading_without_the_extra_raises_a_missing_extra_error(tmp_path: Path) -> None:
    try:
        import verifiers.v1  # noqa: F401
    except ImportError:
        pass
    else:  # pragma: no cover - only when the optional extra is installed
        pytest.skip("verifiers is installed; the missing-extra path cannot be exercised")

    (tmp_path / "taskset.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(MissingExtraError, match=r"bohrin\[verifiers\]"):
        VerifiersV1Adapter().load(tmp_path, ScanConfig())


def test_memory_source_satisfies_the_task_source_protocol() -> None:
    source = MemorySource([Task(id="t", prompt="p")], lambda _t, _p: 1.0)
    assert isinstance(source, TaskSource)
