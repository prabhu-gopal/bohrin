"""``bohrin verify``: facts about what a change did to the tests and the code, beside what it claims.

It compares the files at a base commit with the working tree, including uncommitted work, reports
facts read from syntax trees, and puts them beside any commit message that claims success. It
reports facts, never "cheated": a refactor can delete tests honestly, so facts alone exit 0, and a
fact beside a claim of success exits 1 (``--strict`` exits 1 on any fact, for CI).

Only Python files and pytest configuration are read. A file over :data:`MAX_BYTES`, or one that is
not UTF-8 or does not parse, is listed as not checked rather than guessed at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from bohrin.history import git
from bohrin.history.facts import CONFIG_FILES, NOT_CHECKED, Fact, facts, success_claims

VERIFY_REPORT_SCHEMA = "https://bohrin.com/schema/verify-report/v1"

#: Files larger than this are listed as not checked: a generated or vendored file is not a change
#: anyone reviews line by line, and parsing it could take long.
MAX_BYTES = 2_000_000


def _relevant(path: str) -> bool:
    return path.endswith(".py") or path.rsplit("/", 1)[-1] in CONFIG_FILES


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """What ``bohrin verify`` found about one change."""

    since: str
    base: str
    changed: tuple[str, ...]
    commits: int
    facts: tuple[Fact, ...]
    claims: tuple[tuple[str, str], ...]
    not_checked: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        """The report as ``https://bohrin.com/schema/verify-report/v1``."""
        return {
            "$schema": VERIFY_REPORT_SCHEMA,
            "since": self.since,
            "base": self.base,
            "files_changed": list(self.changed),
            "commits": self.commits,
            "facts": [
                {"rule": f.rule, "weakness": f.weakness, "kind": f.kind, "path": f.path, "message": f.message}
                for f in self.facts
            ],
            "success_claims": [{"commit": commit, "message": message} for commit, message in self.claims],
            "not_checked": list(self.not_checked),
        }


def _read_disk(path: Path) -> str | None:
    """A working-tree file, read without following a symlink and never past :data:`MAX_BYTES`."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("not a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("too large")
    return data.decode("utf-8")


def verify(start: Path, since: str | None = None) -> VerifyReport:
    """Facts about the change from ``since`` (default: where this branch started) to the working tree.

    Raises :class:`bohrin.history.git.GitError` when ``start`` is not in a git repository or
    ``since`` names no commit.
    """
    root = git.top_level(start)
    base = git.resolve(root, since) if since else git.default_base(root)
    old_paths = {path for path in git.files_at(root, base) if _relevant(path)}
    new_paths = {path for path in git.working_files(root) if _relevant(path)}

    before: dict[str, str | None] = {}
    after: dict[str, str | None] = {}
    skipped: list[str] = []
    for path in sorted(old_paths | new_paths):
        try:
            old = git.read_at(root, base, path).decode("utf-8") if path in old_paths else None
            if old is not None and len(old) > MAX_BYTES:
                raise ValueError("too large")
            new = _read_disk(root / path) if path in new_paths else None
        except (UnicodeDecodeError, ValueError, OSError):
            skipped.append(path)
            continue
        if old != new:
            before[path], after[path] = old, new

    found, unreadable = facts(before, after)
    history = git.messages(root, base)
    order = {"fact": 0, "observation": 1}
    ordered = sorted(found, key=lambda f: (order.get(f.kind, 2), f.path, f.rule))
    not_checked = [
        *NOT_CHECKED,
        *(f"{path} (not UTF-8, too large or unreadable)" for path in skipped),
        *(f"{path} (does not parse)" for path in unreadable),
    ]
    return VerifyReport(
        since=since or "the start of this branch",
        base=base,
        changed=tuple(sorted(before)),
        commits=len(history),
        facts=tuple(ordered),
        claims=tuple(success_claims(history)),
        not_checked=tuple(not_checked),
    )


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


def render(report: VerifyReport) -> str:
    """The report as text, in the four parts every Bohrin command uses."""
    lines = [
        f"bohrin verify · since {report.since} ({report.base[:7]}) · {len(report.changed)} files changed · "
        f"{report.commits} commits",
        "",
    ]
    hard = [f for f in report.facts if f.kind == "fact"]
    if not report.facts:
        lines.append("  Nothing in this change weakens tests or code in the ways Bohrin checks.")
    else:
        soft = len(report.facts) - len(hard)
        verdict = f"  {_count(len(hard), 'fact')} and {_count(soft, 'observation')} about this change"
        if report.claims:
            verdict += f", beside {_count(len(report.claims), 'commit message')} claiming success"
        lines.append(verdict + ".")
    lines.append("")
    for fact in report.facts:
        lines.append(f"  {fact.weakness}  {fact.kind:<11}  {fact.message}")
    if report.facts and report.claims:
        lines += ["", "  Commit messages that claim success:"]
        lines += [f"    {commit}  {message}" for commit, message in report.claims]
    lines += ["", "  Not checked: " + "; ".join(report.not_checked) + "."]
    lines.append("  Next: bohrin verify --strict   (exit 1 on any fact, for CI)")
    return "\n".join(lines)


@cache
def verify_report_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/verify-report/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.history").joinpath("verify-report.v1.json").read_text("utf-8"))
    return loaded


__all__ = ["MAX_BYTES", "VERIFY_REPORT_SCHEMA", "VerifyReport", "render", "verify", "verify_report_schema"]
