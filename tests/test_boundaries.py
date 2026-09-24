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


def test_no_module_can_reach_a_network_or_start_a_process() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(_imports(ast.parse(path.read_text(encoding="utf-8"))) & FORBIDDEN)
        for path in SRC.rglob("*.py")
    }
    assert {path: mods for path, mods in offenders.items() if mods} == {}


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
