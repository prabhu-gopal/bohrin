"""Reading git history safely, from a repository that may not be trusted.

``bohrin verify`` runs in repositories a coding agent has just worked in, so the repository's own
configuration is treated as hostile. Ordinary "read-only" git commands can run programs a
repository names: ``core.fsmonitor`` runs a command on ``git status`` and ``git diff``; textconv and
clean filters from ``.gitattributes`` run when git diffs the working tree; ``diff.external`` runs
an external diff program; a bare repository buried in the tree can bring its own configuration.

So this module:

* **never asks git about the working tree.** Working-tree files are read by Bohrin itself; git is
  asked only about committed history, through plumbing commands that apply no filters and no
  textconv: ``rev-parse``, ``merge-base``, ``ls-tree``, ``cat-file blob`` and ``log``;
* **switches off everything that can run a program** on every call, on the command line, where it
  overrides the repository's configuration: ``core.fsmonitor=false``, an empty ``diff.external``,
  ``core.hooksPath`` pointing nowhere, and ``safe.bareRepository=explicit``;
* **ignores system and global configuration**, never prompts, takes no optional locks, and gives
  up after a time limit.

It is the only module in the library that starts a process (``tests/test_boundaries.py`` enforces
that), and the only program it starts is ``git``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: Every git call starts with these: no program named by the repository can run.
_SAFE = (
    "git",
    "--no-pager",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "diff.external=",
    "-c",
    f"core.hooksPath={os.devnull}",
    "-c",
    "safe.bareRepository=explicit",
    "-c",
    "protocol.allow=never",
)

TIMEOUT_S = 30


class GitError(Exception):
    """Git could not answer: not a repository, an unknown revision, or git is not installed."""


def _environment() -> dict[str, str]:
    keep = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "SYSTEMROOT", "TMPDIR")}
    return {
        **keep,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }


def _git(root: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(
            [*_SAFE, "-C", str(root), *args],
            capture_output=True,
            timeout=TIMEOUT_S,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git did not answer within {TIMEOUT_S} seconds") from exc
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(message[-1] if message else f"git {args[0]} failed")
    return done.stdout


def top_level(path: Path) -> Path:
    """The root of the working tree that contains ``path``."""
    return Path(_git(path, "rev-parse", "--show-toplevel").decode("utf-8").strip())


def resolve(root: Path, revision: str) -> str:
    """The full commit ID ``revision`` names. Raises ``GitError`` for anything that is not a commit."""
    try:
        output = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{revision}^{{commit}}")
    except GitError as exc:
        raise GitError(f"{revision!r} names no commit in this repository") from exc
    return output.decode("ascii").strip()


def default_base(root: Path) -> str:
    """Where to compare from when no ``--since`` is given.

    The merge-base with the remote's default branch, so a feature branch is compared with where it
    started; failing that, the previous commit; failing that (a repository with one commit), HEAD.
    """
    for upstream in ("origin/HEAD", "origin/main", "origin/master"):
        try:
            return _git(root, "merge-base", "HEAD", upstream).decode("ascii").strip()
        except GitError:
            continue
    for revision in ("HEAD~1", "HEAD"):
        try:
            return resolve(root, revision)
        except GitError:
            continue
    raise GitError("the repository has no commits yet")


def files_at(root: Path, commit: str) -> list[str]:
    """Every file path in ``commit``'s tree."""
    output = _git(root, "ls-tree", "-r", "-z", "--name-only", "--full-tree", commit)
    return [path.decode("utf-8", "surrogateescape") for path in output.split(b"\0") if path]


def read_at(root: Path, commit: str, path: str) -> bytes:
    """The committed content of ``path`` at ``commit``, exactly as stored: no filter, no textconv."""
    return _git(root, "cat-file", "blob", f"{commit}:{path}")


def working_files(root: Path) -> list[str]:
    """Files in the working tree that git tracks or would track: committed, staged or new."""
    tracked = _git(root, "ls-files", "-z", "--cached")
    untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    paths = {path.decode("utf-8", "surrogateescape") for path in (tracked + b"\0" + untracked).split(b"\0") if path}
    # A symlink is skipped: a hostile repository could point one at a device that never stops reading.
    return sorted(path for path in paths if (root / path).is_file() and not (root / path).is_symlink())


def messages(root: Path, base: str) -> list[tuple[str, str]]:
    """``(short commit ID, message)`` for every commit after ``base`` up to HEAD."""
    output = _git(root, "log", "--no-show-signature", "--format=%h%x00%B%x01", f"{base}..HEAD")
    entries = []
    for record in output.decode("utf-8", "replace").split("\x01"):
        record = record.strip("\n")
        if "\0" in record:
            short, message = record.split("\0", 1)
            entries.append((short.strip(), message.strip()))
    return entries


__all__ = ["GitError", "default_base", "files_at", "messages", "read_at", "resolve", "top_level", "working_files"]
