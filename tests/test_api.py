"""The seam: ``bohrin.api`` is stable, and plugins attach through it without harming one another.

The seam is versioned by :data:`PLUGIN_API`. Removing a name breaks every plugin that uses it, so
the names of version 1 are frozen here: removing one fails this test until the version changes.
Plugins attach through entry points exactly as the built-ins do, and three rules keep one from
harming another: a name belongs to its first owner (this package's first), a plugin written for
another seam version is skipped, and a plugin that fails to load is skipped. Each is shown here
on the command line, where a silently replaced command would do the most harm.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from importlib.metadata import entry_points as real_entry_points
from types import SimpleNamespace
from typing import Any

import pytest

import bohrin._plugins as plugins
import bohrin.api as api
from bohrin.cli import main
from bohrin.command import Command

#: Every name version 1 of the seam promises. Removing one is a breaking change: bump PLUGIN_API.
V1 = frozenset(
    {
        "ADAPTERS", "BASELINE", "BATTERY_VERSION", "CANNOT_RUN", "CATEGORIES", "CLEAN", "COMMANDS", "FINDINGS",
        "GROUPS", "MUTATORS", "NEEDS_SIGN_IN", "OUT_OF_CREDITS", "PLUGIN_API", "PROBES", "RELATIONS", "RENDERERS",
        "USAGE", "Acceptance", "AnswerInPrompt", "Attempt", "BaselineFailure", "Battery", "Candidate",
        "CheckFinding", "Command", "Control", "ControlAttempt", "CoverageScore", "DifferentiatingInput",
        "DifferentiatingObservation", "Exploit", "Finding", "Flake", "GapScore", "Ground", "GroundTruthRejected",
        "HarnessDisruption", "MutationOperator", "Payload", "ProbeResult", "ProbeStatus", "Provenance", "Relation",
        "Reproduction", "ReproductionResult", "Run", "Scorecard", "Scored", "Shape", "Source", "Submission", "Task",
        "Unverified", "Verdict", "Workspace", "battery", "check_conformance", "check_script", "coverage_score",
        "discover_operators", "discover_relations", "finding_id", "judge", "parse_result", "positive_controls",
        "probe_for", "probes", "read_conformance_results", "read_record", "Decision", "active_decisions",
        "format_decisions", "read_decisions", "scorecard", "to_sarif",
        "verification_gap", "weakness_list", "wilson_interval",
    }
)  # fmt: skip


def test_the_seam_is_version_1_and_keeps_every_name_it_promised() -> None:
    assert api.PLUGIN_API == 1
    missing = V1 - set(api.__all__)
    assert not missing, f"removed from the seam without bumping PLUGIN_API: {sorted(missing)}"


def test_every_name_of_the_seam_resolves() -> None:
    for name in api.__all__:
        assert getattr(api, name) is not None, name


def test_the_groups_are_the_six_published_ones() -> None:
    assert api.GROUPS == (
        "bohrin.mutators",
        "bohrin.relations",
        "bohrin.commands",
        "bohrin.adapters",
        "bohrin.probes",
        "bohrin.renderers",
    )


def test_this_package_registers_its_commands_like_any_plugin() -> None:
    from importlib.metadata import entry_points

    names = {e.name for e in entry_points(group=api.COMMANDS) if e.dist is not None and e.dist.name == "bohrin"}
    assert names == {"power", "verify", "conformance"}


# --------------------------------------------------------------------------- plugins on the command line


@dataclass
class _Entry:
    """An entry point from a named distribution, as importlib.metadata gives one."""

    name: str
    group: str
    target: Any
    owner: str
    dist: Any = field(init=False)

    def __post_init__(self) -> None:
        self.dist = SimpleNamespace(name=self.owner)

    def load(self) -> Any:
        return self.target


class _Hello(Command):
    help = "say hello"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--loud", action="store_true")

    def run(self, args: argparse.Namespace) -> int:
        print("HELLO" if args.loud else "hello")
        return 0


class _Impostor(Command):
    name = "verify"
    help = "pretends to be verify"

    def run(self, args: argparse.Namespace) -> int:
        print("nothing to see here")
        return 0


class _Rare(_Hello):
    rare = True
    usage = "whisper FILE"


class _FromTheFuture(_Hello):
    plugin_api = 2


def _with(monkeypatch: pytest.MonkeyPatch, *extra: _Entry) -> None:
    def entry_points(group: str) -> list[Any]:
        return [*real_entry_points(group=group), *(e for e in extra if e.group == group)]

    monkeypatch.setattr(plugins, "entry_points", entry_points)


def test_a_plugins_command_attaches_to_bohrin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with(monkeypatch, _Entry("hello", api.COMMANDS, _Hello, "acme-bohrin-hello"))
    assert main(["hello", "--loud"]) == 0
    assert capsys.readouterr().out == "HELLO\n"
    with pytest.raises(SystemExit):
        main(["--help"])
    listing = capsys.readouterr().out
    assert listing.index("power") < listing.index("verify") < listing.index("hello"), "this package's come first"


def test_no_plugin_can_replace_a_built_in_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    _with(monkeypatch, _Entry("verify", api.COMMANDS, _Impostor, "aaa-sorted-first"))
    with pytest.warns(UserWarning, match="aaa-sorted-first registers 'verify'.*keeping bohrin's"):
        code = main(["verify", str(tmp_path)])
    assert code == api.CANNOT_RUN, "the real verify ran: tmp_path is not a git repository"
    assert "nothing to see here" not in capsys.readouterr().out


def test_a_plugin_for_another_seam_version_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _Entry("hello", api.COMMANDS, _FromTheFuture, "acme"))
    with (
        pytest.warns(UserWarning, match="written for plugin API 2; this release provides 1"),
        pytest.raises(SystemExit),
    ):
        main(["hello"])


def test_a_rare_plugin_command_is_listed_by_help_more(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with(monkeypatch, _Entry("whisper", api.COMMANDS, _Rare, "acme"))
    assert main(["help", "more"]) == 0
    assert "bohrin whisper FILE" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "whisper" not in capsys.readouterr().out


def test_a_command_class_that_is_not_a_command_is_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with(monkeypatch, _Entry("stranger", api.COMMANDS, dict, "acme"))
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "stranger" not in capsys.readouterr().out


def test_with_no_rare_commands_help_more_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bohrin import cli

    assert cli._more([c for c in cli._commands() if not c.rare]).startswith("There are no rarely used commands")


def test_a_command_must_do_something() -> None:
    with pytest.raises(NotImplementedError):
        Command().run(argparse.Namespace())
