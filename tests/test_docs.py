"""The documentation cannot drift from the code.

Every Python example in the tutorial and the README is run, and what it prints must equal the
output shown under it. Every relative link, and every ``#anchor`` in one, must resolve. Every
public class and function must have a docstring, because the docstrings are the API reference.
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="no docs/ in this checkout")

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _examples(page: Path) -> list[tuple[str, str | None]]:
    """``(code, expected output)`` for each Python block; the output is the next block, if it is output."""
    blocks = [(m.group(1), m.group(2)) for m in _FENCE.finditer(page.read_text(encoding="utf-8"))]
    out: list[tuple[str, str | None]] = []
    for i, (lang, body) in enumerate(blocks):
        if lang != "python":
            continue
        after = blocks[i + 1] if i + 1 < len(blocks) else None
        is_output = after is not None and (
            after[0] == "text" or (after[0] == "console" and not after[1].startswith("$"))
        )
        out.append((body, after[1] if is_output and after is not None else None))
    return out


@pytest.mark.parametrize("page", ["docs/tutorial.md", "README.md"])
def test_every_example_prints_what_the_page_shows(page: str) -> None:
    examples = _examples(ROOT / page)
    assert examples, f"{page} should have runnable examples"
    namespace: dict[str, object] = {"__name__": "__docs__"}
    for code, expected in examples:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            exec(compile(code, page, "exec"), namespace)
        if expected is not None:
            assert printed.getvalue().rstrip("\n") == expected.rstrip("\n"), f"{page}:\n{code}"


def _pages() -> list[Path]:
    return sorted([*ROOT.glob("*.md"), *DOCS.rglob("*.md"), *(ROOT / "conformance").glob("*.md")])


def _anchors(page: Path) -> set[str]:
    """GitHub's heading anchors: lower case, punctuation dropped, spaces as hyphens."""
    headings = re.findall(r"^#+\s+(.*)$", page.read_text(encoding="utf-8"), re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in headings}


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_resolves(page: Path) -> None:
    broken: list[str] = []
    for target in _LINK.findall(page.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        resolved = (page.parent / path).resolve() if path else page
        missing_anchor = anchor and resolved.suffix == ".md" and anchor not in _anchors(resolved)
        if not resolved.exists() or missing_anchor:
            broken.append(target)
    assert broken == []


def test_every_public_class_and_function_has_a_docstring() -> None:
    missing = []
    for source in sorted((ROOT / "src" / "bohrin").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        if not ast.get_docstring(tree):
            missing.append(f"{source.relative_to(ROOT)}: module")
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.ClassDef) or node.name.startswith("_"):
                continue
            if not ast.get_docstring(node):
                missing.append(f"{source.relative_to(ROOT)}:{node.lineno} {node.name}")
    assert missing == []


def test_the_documentation_map_lists_every_page() -> None:
    listed = (DOCS / "README.md").read_text(encoding="utf-8")
    for page in DOCS.rglob("*.md"):
        if page.name != "README.md":
            assert str(page.relative_to(DOCS)) in listed, f"docs/README.md does not list {page.relative_to(DOCS)}"
