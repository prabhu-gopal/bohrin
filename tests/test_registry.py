"""Registry discovery via entry points + programmatic register (docs/06 P0/P1 DoD)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

import _synth  # noqa: F401 - importing registers the memory adapter for the session
from bohrin._plugins import load_plugin_classes
from bohrin.adapters.registry import discover as discover_adapters
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.detectors.registry import _REGISTERED, register
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.ir.schema import Family
from bohrin.report.model import Finding


def test_builtin_detectors_discovered_via_entry_points() -> None:
    classes = load_plugin_classes("bohrin.detectors")
    assert "stats.dead_dimension" in classes
    assert "causal.copycat_shortcut" in classes
    discovered = {d.id for d in discover_detectors()}
    assert "stats.dead_dimension" in discovered
    assert "integrity.nan_inf" in discovered


def test_lerobot_adapters_declared_as_entry_points() -> None:
    classes = load_plugin_classes("bohrin.adapters")
    assert "lerobot_v21" in classes
    assert "lerobot_v3" in classes


def test_memory_adapter_registered_programmatically() -> None:
    assert any(a.name == "memory" for a in discover_adapters())


def test_only_and_disable_globs() -> None:
    only = {d.id for d in discover_detectors(only=("integrity.*",))}
    assert only and all(d.startswith("integrity.") for d in only)
    disabled = {d.id for d in discover_detectors(disable=("integrity.*",))}
    assert all(not d.startswith("integrity.") for d in disabled)


def test_programmatic_register(clean_registry: None) -> None:
    @register
    class _InlineCheck(Detector):
        id = "test.inline"
        family = Family.INTEGRITY

        def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
            return []

    assert [d.id for d in discover_detectors(only=("test.*",))] == ["test.inline"]


def test_register_requires_id() -> None:
    with pytest.raises(ValueError, match="non-empty `id`"):

        @register
        class _NoId(Detector):
            def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
                return []


@pytest.fixture
def clean_registry() -> Iterator[None]:
    before = dict(_REGISTERED)
    try:
        yield
    finally:
        _REGISTERED.clear()
        _REGISTERED.update(before)
