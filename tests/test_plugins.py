"""Entry-point discovery: one bad plugin must never take the others down.

Built-in and third-party operators arrive through the same entry points, so a plugin that fails
to import, or that advertises something that is not a class, is skipped with a warning. A crash
here would switch the whole battery off because of one package nobody asked Bohrin to check.
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib.metadata import EntryPoint

import pytest

import bohrin._plugins as plugins
from bohrin.ir.task import Candidate, Task
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator


class _Good(MutationOperator):
    rationale = "test double"

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield from ()


def _entry_points(*points: EntryPoint) -> object:
    return lambda group: [p for p in points if p.group == group]


def test_a_plugin_that_fails_to_load_is_skipped_with_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = EntryPoint(name="broken", value="no_such_module_anywhere:Operator", group=plugins.MUTATORS)
    good = EntryPoint(name="good", value=f"{__name__}:_Good", group=plugins.MUTATORS)
    monkeypatch.setattr(plugins, "entry_points", _entry_points(broken, good))

    with pytest.warns(UserWarning, match="failed to load plugin 'broken'"):
        found = plugins.load_plugin_classes(plugins.MUTATORS)

    assert list(found) == ["good"], "the working plugin still loads"


def test_a_plugin_that_is_not_a_class_is_skipped_with_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    not_a_class = EntryPoint(name="function", value="os.path:join", group=plugins.MUTATORS)
    monkeypatch.setattr(plugins, "entry_points", _entry_points(not_a_class))

    with pytest.warns(UserWarning, match="is not a class"):
        assert plugins.load_plugin_classes(plugins.MUTATORS) == {}


def test_an_operator_without_an_id_takes_its_entry_point_name(monkeypatch: pytest.MonkeyPatch) -> None:
    good = EntryPoint(name="acme_hollow", value=f"{__name__}:_Good", group=plugins.MUTATORS)
    monkeypatch.setattr(plugins, "entry_points", _entry_points(good))
    import bohrin.mutate as mutate

    monkeypatch.setattr(mutate, "load_plugin_classes", plugins.load_plugin_classes)
    assert [op.id for op in discover()] == ["acme_hollow"]
