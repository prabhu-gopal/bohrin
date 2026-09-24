"""The library never calls a grader, so it never needs a network, a process or ``exec``.

This is the first invariant in ARCHITECTURE.md, and it is a rule about what the code must *not*
do, which no ordinary test would notice being broken. So it is checked here directly, over the
source of every module: none imports a module that talks to a network or starts a process, and
none calls ``exec`` or ``eval``. ``compile`` is allowed: comparing bytecode runs nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bohrin"

#: Modules through which code reaches a network or another process.
FORBIDDEN = {
    "asyncio",
    "ftplib",
    "http",
    "httpx",
    "multiprocessing",
    "requests",
    "smtplib",
    "socket",
    "ssl",
    "subprocess",
    "urllib",
    "urllib3",
    "webbrowser",
}


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


#: The one module allowed to start a process, and the one module it may import to do so.
#: ``bohrin verify`` reads git history, so ``history/git.py`` runs ``git`` and nothing else.
GIT_MODULE = "history/git.py"


def test_no_module_can_reach_a_network_or_start_a_process() -> None:
    offenders = {}
    for path in SRC.rglob("*.py"):
        relative = str(path.relative_to(SRC))
        allowed = {"subprocess"} if relative == GIT_MODULE else set()
        found = (_imports(ast.parse(path.read_text(encoding="utf-8"))) & FORBIDDEN) - allowed
        if found:
            offenders[relative] = sorted(found)
    assert offenders == {}


def test_the_git_module_runs_only_git_with_its_protections() -> None:
    """Every process it starts begins with the prefix that switches off repository-named programs."""
    source = (SRC / GIT_MODULE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    runs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "Popen", "call", "check_output"}
    ]
    assert len(runs) == 1, "one place starts git, so its protections cannot be skipped"
    (run,) = runs
    command = run.args[0]
    assert isinstance(command, ast.List) and isinstance(command.elts[0], ast.Starred)
    assert ast.unparse(command.elts[0].value) == "_SAFE", "the command starts with the protective prefix"
    assert all(kw.arg != "shell" for kw in run.keywords), "never through a shell"
    for setting in ("core.fsmonitor=false", "diff.external=", "safe.bareRepository=explicit"):
        assert setting in source


def test_no_module_executes_code() -> None:
    calls = [
        f"{path.relative_to(SRC)}:{node.lineno} {node.func.id}"
        for path in SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval"}
    ]
    assert calls == []


def test_the_check_would_notice_a_forbidden_import() -> None:
    """The guard's own counterweight: it must actually see an import."""
    assert _imports(ast.parse("import subprocess\nfrom urllib.request import urlopen\n")) >= {"subprocess", "urllib"}


#: Plumbing that reads committed history and applies no filter, textconv or external program.
#: ``diff`` and ``status`` are absent on purpose: on the working tree they run a repository's
#: clean filters and fsmonitor even with every ``-c`` protection set, which a test in
#: tests/test_verify.py demonstrates.
READ_ONLY_GIT = {"cat-file", "log", "ls-files", "ls-tree", "merge-base", "rev-parse"}


def test_the_git_module_runs_only_read_only_plumbing() -> None:
    tree = ast.parse((SRC / GIT_MODULE).read_text(encoding="utf-8"))
    subcommands = {
        str(node.args[1].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_git"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
    }
    assert subcommands, "the check must see the git calls"
    assert subcommands <= READ_ONLY_GIT, f"not read-only plumbing: {sorted(subcommands - READ_ONLY_GIT)}"
