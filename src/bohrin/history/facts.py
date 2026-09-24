"""Facts about a change, read from the syntax trees of the files before and after it.

Every rule reports a fact a reviewer can check by looking at the diff, never a verdict: a deleted
test, three fewer assertions, a new skip marker. Comparing syntax trees rather than lines means
reformatting never looks like a removed assertion, and a test moved to another file never looks
like a deleted one. Each fact names the weakness class it is evidence of.

Rules that need more than two versions of a file to judge fairly (a mock of the unit under test,
a test's expected value copied into the source) are not here yet, and a report says so.
"""

from __future__ import annotations

import ast
import configparser
import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace

from bohrin.history import oracle

#: Configuration files whose pytest settings decide which tests run.
CONFIG_FILES = frozenset({"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"})

#: Settings that decide which tests are collected and run.
_SELECTION_KEYS = ("addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs")

#: pytest hooks through which a conftest.py can change what a test run reports.
_REPORT_HOOKS = frozenset(
    {
        "pytest_runtest_makereport",
        "pytest_runtest_protocol",
        "pytest_runtest_call",
        "pytest_report_teststatus",
        "pytest_collection_modifyitems",
        "pytest_runtest_logreport",
    }
)

#: Names whose reassignment changes what a timing measurement reads.
_TIMERS = frozenset({"time.perf_counter", "time.time", "time.monotonic", "time.process_time", "torch.cuda.synchronize"})

NOT_CHECKED = (
    "a test's expected value copied into the source",
    "files other than Python and pytest configuration",
)


@dataclass(frozen=True, slots=True)
class Fact:
    """One fact about the change, with the weakness class it is evidence of."""

    rule: str
    weakness: str
    path: str
    message: str
    #: ``observation`` for what an honest change also does routinely (a CLI adds ``sys.exit``).
    kind: str = "fact"
    #: The line in the new version the fact is about, when the file still exists.
    line: int | None = None
    #: The test or function the fact is about, when it is about one.
    subject: str = ""


def is_test_file(path: str) -> bool:
    """A Python test module or pytest's ``conftest.py``, by the conventions pytest itself uses."""
    if not path.endswith(".py"):
        return False
    name = path.rsplit("/", 1)[-1]
    parts = path.split("/")[:-1]
    return (
        name == "conftest.py"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or any(part in ("test", "tests") for part in parts)
    )


def _parse(text: str | None) -> ast.Module | None:
    if text is None:
        return None
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return ""


def _is_check(node: ast.AST) -> bool:
    """An assertion: ``assert``, ``self.assert*``, ``mock.assert_*``, or ``pytest.raises``/``warns``."""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call):
        name = _dotted(node.func)
        last = name.rsplit(".", 1)[-1]
        return last.startswith("assert") or name in ("pytest.raises", "pytest.warns", "pytest.fail")
    return False


def _checks(tree: ast.AST) -> int:
    return sum(1 for node in ast.walk(tree) if _is_check(node))


def _tests(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Test functions and methods by name (``Class.test_x`` for methods)."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test"):
                    found[f"{node.name}.{item.name}"] = item
    return found


#: Markers that skip or expect failure whatever the circumstances.
_UNCONDITIONAL_SKIPS = frozenset(
    {
        "pytest.mark.skip",
        "pytest.mark.xfail",
        "unittest.skip",
        "unittest.expectedFailure",
        "pytest.skip",
        "pytest.xfail",
    }
)
#: Markers that skip only when a condition holds, such as a missing optional dependency.
_CONDITIONAL_SKIPS = frozenset({"pytest.mark.skipif", "unittest.skipIf", "unittest.skipUnless"})


def _skip_counts(tree: ast.AST) -> tuple[int, int]:
    """``(unconditional, conditional)`` skip and xfail markers.

    ``@pytest.mark.skip`` and an unguarded ``pytest.skip()`` skip whatever happens. ``skipif(...)``,
    and a ``pytest.skip()`` call inside an ``if``, skip only when something holds, such as an
    optional file being absent. A called marker (``skipif(...)``) is counted once, as the call.
    """
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    guarded = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        for branch in (*node.body, *node.orelse)
        for inner in ast.walk(branch)
    }
    unconditional = conditional = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
        elif isinstance(node, ast.Attribute) and id(node) not in called:
            name = _dotted(node)
        else:
            continue
        if name in _CONDITIONAL_SKIPS or (name in _UNCONDITIONAL_SKIPS and id(node) in guarded):
            conditional += 1
        elif name in _UNCONDITIONAL_SKIPS:
            unconditional += 1
    return unconditional, conditional


def _pure(node: ast.AST) -> bool:
    """An expression that gives the same value however often it is evaluated: no call anywhere in it."""
    return not any(isinstance(child, ast.Call | ast.Await | ast.Yield | ast.YieldFrom) for child in ast.walk(node))


def _trivial_checks(tree: ast.AST) -> list[int]:
    """Lines of checks that can never fail: ``assert True``, ``assert "text"``, ``assert x == x``.

    Two identical sides count only when neither calls anything. ``assert f(x) == f(x)`` calls ``f``
    twice and checks it gives the same answer both times, which is a real determinism test.
    """
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            test = node.test
            always_true = isinstance(test, ast.Constant) and bool(test.value)
            same_both_sides = (
                isinstance(test, ast.Compare)
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq | ast.Is)
                and ast.dump(test.left) == ast.dump(test.comparators[0])
                and _pure(test.left)
            )
            if always_true or same_both_sides:
                lines.append(node.lineno)
        elif isinstance(node, ast.Call) and _dotted(node.func).endswith(".assertTrue") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and bool(first.value):
                lines.append(node.lineno)
    return sorted(lines)


def _exits(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted(node.func) in ("sys.exit", "os._exit", "exit", "quit"):
            count += 1
        elif isinstance(node, ast.Raise) and node.exc is not None:
            raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if _dotted(raised) == "SystemExit":
                count += 1
    return count


def _always_equal(tree: ast.AST) -> int:
    """``__eq__`` methods whose body returns ``True`` unconditionally."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__eq__":
            body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            if (
                len(body) == 1
                and isinstance(body[0], ast.Return)
                and isinstance(body[0].value, ast.Constant)
                and body[0].value.value is True
            ):
                count += 1
    return count


def _timer_assignments(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
        )
        for target in targets:
            name = _dotted(target)
            if name in _TIMERS:
                found.append(name)
        if isinstance(node, ast.Call) and _dotted(node.func) == "setattr" and len(node.args) >= 2:
            owner, attr = node.args[0], node.args[1]
            if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                name = f"{_dotted(owner)}.{attr.value}"
                if name in _TIMERS:
                    found.append(name)
    return found


def _stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A body of only a docstring, ``pass``, ``...`` or ``raise NotImplementedError``."""
    for statement in function.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        if isinstance(statement, ast.Raise) and statement.exc is not None:
            raised = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc
            if _dotted(raised) == "NotImplementedError":
                continue
        return False
    return True


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    found[f"{node.name}.{item.name}"] = item
    return found


def _pairs(
    tests: Mapping[str, tuple[ast.Module | None, ast.Module | None]],
) -> list[tuple[str, str, oracle.Test | None, oracle.Test]]:
    """``(path, name, before, after)`` for every test in the new version, matched to its old self.

    A test is matched in the same file first; a test that moved to another file is matched by its
    name when that name is unique, so a move never reads as a new or a weakened test.
    """
    old_index = {(path, name): node for path, (old, _) in tests.items() if old for name, node in _tests(old).items()}
    new_index = {(path, name): node for path, (_, new) in tests.items() if new for name, node in _tests(new).items()}
    by_name: dict[str, list[oracle.Test]] = {}
    for (_, name), node in old_index.items():
        by_name.setdefault(name, []).append(node)
    pairs = []
    for (path, name), node in sorted(new_index.items(), key=lambda item: item[0]):
        before = old_index.get((path, name))
        if before is None and len(by_name.get(name, [])) == 1:
            before = by_name[name][0]
        pairs.append((path, name, before, node))
    return pairs


def _test_by_test(tests: Mapping[str, tuple[ast.Module | None, ast.Module | None]]) -> list[Fact]:
    """What happened to each test's oracle: weakened, loosened, swallowed, rewritten or mocked."""
    out: list[Fact] = []
    lost: dict[str, int] = {}
    lost_at: dict[str, int] = {}
    for path, name, before, after in _pairs(tests):
        if before is not None and ast.dump(before) == ast.dump(after):
            continue
        start = len(out)
        if before is not None and _checks(after) < _checks(before):
            lost[path] = lost.get(path, 0) + _checks(before) - _checks(after)
            lost_at[path] = min(lost_at.get(path, after.lineno), after.lineno)
        if before is not None:
            was, now = oracle.strength(before), oracle.strength(after)
            if was in oracle.STRONG and now in oracle.WEAK:
                out.append(
                    Fact(
                        "check-weakened",
                        "BGW-109",
                        path,
                        f"{name} in {path} was weakened: from {oracle.DESCRIPTIONS[was]} to "
                        f"{oracle.DESCRIPTIONS[now]} ({was} → {now})",
                    )
                )
            old_tol, new_tol = oracle.tolerances(before), oracle.tolerances(after)
            for key in sorted(set(new_tol)):
                if new_tol[key] > old_tol.get(key, new_tol[key]):
                    out.append(
                        Fact(
                            "tolerance-loosened",
                            "BGW-134",
                            path,
                            f"{key} in {name} loosened from {old_tol[key]:g} to {new_tol[key]:g}",
                        )
                    )
            old_timeout, new_timeout = oracle.timeouts(before), oracle.timeouts(after)
            if old_timeout and new_timeout > old_timeout:
                out.append(
                    Fact(
                        "timeout-raised",
                        "BGW-109",
                        path,
                        f"a timeout in {name} raised from {old_timeout:g} to {new_timeout:g} seconds",
                    )
                )
            old_expected, new_expected = oracle.expected_values(before), oracle.expected_values(after)
            rewritten = sorted(
                key for key in set(old_expected) & set(new_expected) if old_expected[key] != new_expected[key]
            )
            if rewritten:
                key = rewritten[0]
                out.append(
                    Fact(
                        "expected-value-changed",
                        "BGW-109",
                        path,
                        f"an expected value in {name} changed from {old_expected[key]} to {new_expected[key]}",
                        "observation",
                    )
                )
        swallowed = oracle.swallowed_checks(after) - (oracle.swallowed_checks(before) if before else 0)
        if swallowed > 0:
            out.append(
                Fact(
                    "failure-swallowed",
                    "BGW-109",
                    path,
                    f"{_plural(swallowed, 'check')} in {name} now inside a try whose except catches its failure",
                )
            )
        mocked = sorted(oracle.mocked_subjects(after) - (oracle.mocked_subjects(before) if before else set()))
        if mocked:
            out.append(
                Fact(
                    "subject-mocked",
                    "BGW-109",
                    path,
                    f"{name} now patches {mocked[0]}, the function it is named after, so it may test the mock",
                    "observation",
                )
            )
        out[start:] = [replace(fact, line=after.lineno, subject=name) for fact in out[start:]]
    for path, count in sorted(lost.items()):
        out.append(
            Fact(
                "checks-removed",
                "BGW-109",
                path,
                f"{_plural(count, 'assertion')} removed from tests in {path}",
                line=lost_at[path],
            )
        )
    return out


def _is_skip(node: ast.AST) -> bool:
    name = _dotted(node.func) if isinstance(node, ast.Call) else _dotted(node)
    return name in _UNCONDITIONAL_SKIPS | _CONDITIONAL_SKIPS


def _is_unchecked_test(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test") and not _checks(node)
    )


def _is_report_hook(node: ast.AST) -> bool:
    hook = isinstance(node, ast.FunctionDef) and node.name in _REPORT_HOOKS
    patch = isinstance(node, ast.Name | ast.Attribute) and _dotted(node).endswith("TestReport")
    return hook or patch


def _is_stub(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _stub(node)


#: For each file-level rule, which node in the new version the fact is about.
_LOCATORS: dict[str, Callable[[ast.AST], bool]] = {
    "skips-added": _is_skip,
    "conditional-skips-added": _is_skip,
    "trivial-checks-added": lambda node: isinstance(node, ast.Assert | ast.Call) and bool(_trivial_checks(node)),
    "tests-without-checks": _is_unchecked_test,
    "report-hook-added": _is_report_hook,
    "timer-reassigned": lambda node: isinstance(node, ast.Assign | ast.AugAssign) and bool(_timer_assignments(node)),
    "exit-added": lambda node: isinstance(node, ast.Call | ast.Raise) and bool(_exits(node)),
    "always-equal-added": lambda node: isinstance(node, ast.FunctionDef) and bool(_always_equal(node)),
    "replaced-by-stub": _is_stub,
}


def _first_line(rule: str, tree: ast.Module | None, text: str) -> int:
    """The first line in the new version a file-level fact is about; line 1 when none is closer."""
    if rule == "selection-changed":
        keys = [
            n
            for n, content in enumerate(text.splitlines(), start=1)
            if content.split("=")[0].strip() in _SELECTION_KEYS
        ]
        return min(keys, default=1)
    matches = _LOCATORS.get(rule)
    if tree is None or matches is None:
        return 1
    return min((node.lineno for node in ast.walk(tree) if hasattr(node, "lineno") and matches(node)), default=1)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _selection(path: str, text: str | None) -> dict[str, str]:
    """pytest's test-selection settings in a configuration file, by key."""
    if text is None:
        return {}
    name = path.rsplit("/", 1)[-1]
    try:
        if name == "pyproject.toml":
            section = tomllib.loads(text).get("tool", {}).get("pytest", {}).get("ini_options", {})
            return {key: str(section[key]) for key in _SELECTION_KEYS if key in section}
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        for section_name in ("pytest", "tool:pytest"):
            if parser.has_section(section_name):
                return {
                    key: parser.get(section_name, key)
                    for key in _SELECTION_KEYS
                    if parser.has_option(section_name, key)
                }
    except (tomllib.TOMLDecodeError, configparser.Error):
        return {}
    return {}


def facts(before: Mapping[str, str | None], after: Mapping[str, str | None]) -> tuple[list[Fact], list[str]]:
    """Facts about the change from ``before`` to ``after`` (path -> text, None when absent).

    Returns the facts and the paths that could not be parsed, which a report lists as not checked.
    """
    out: list[Fact] = []
    unreadable: list[str] = []
    paths = sorted(set(before) | set(after))
    trees: dict[str, tuple[ast.Module | None, ast.Module | None]] = {}
    for path in paths:
        if not path.endswith(".py"):
            continue
        old_text, new_text = before.get(path), after.get(path)
        old_tree, new_tree = _parse(old_text), _parse(new_text)
        if (old_text is not None and old_tree is None) or (new_text is not None and new_tree is None):
            unreadable.append(path)
            continue
        trees[path] = (old_tree, new_tree)

    tests = {path: pair for path, pair in trees.items() if is_test_file(path)}
    new_test_names = {name for _, new in tests.values() if new is not None for name in _tests(new)}

    # Tests deleted or emptied, unless every test in the file still exists somewhere.
    for path, (old, new) in tests.items():
        if old is None or path.endswith("conftest.py"):
            continue
        old_names = set(_tests(old))
        if not old_names:
            continue
        gone = old_names - set(_tests(new)) if new is not None else old_names
        if gone and not gone <= new_test_names:
            missing = sorted(gone - new_test_names)
            what = "deleted" if new is None else "emptied" if not _tests(new) else "lost tests"
            out.append(
                Fact(
                    "tests-removed",
                    "BGW-109",
                    path,
                    f"{path} {what}: {_plural(len(missing), 'test')} no longer "
                    f"{'exists' if len(missing) == 1 else 'exist'} anywhere (such as {', '.join(missing[:3])})",
                )
            )

    for path, (old, new) in tests.items():
        if new is None:
            continue
        new_skips, old_skips = _skip_counts(new), _skip_counts(old) if old else (0, 0)
        added = new_skips[0] - old_skips[0]
        if added > 0:
            out.append(
                Fact("skips-added", "BGW-109", path, f"{_plural(added, 'skip or xfail marker')} added in {path}")
            )
        conditional = new_skips[1] - old_skips[1]
        if conditional > 0:
            out.append(
                Fact(
                    "conditional-skips-added",
                    "BGW-109",
                    path,
                    f"{_plural(conditional, 'conditional skip')} added in {path}",
                    "observation",
                )
            )
        trivial_lines = _trivial_checks(new)
        trivial = len(trivial_lines) - (len(_trivial_checks(old)) if old else 0)
        if trivial > 0:
            out.append(
                Fact(
                    "trivial-checks-added",
                    "BGW-109",
                    path,
                    f"{_plural(trivial, 'check')} that cannot fail added in {path} (line "
                    f"{', '.join(map(str, trivial_lines[-trivial:]))})",
                    "observation",
                )
            )
        old_tests = _tests(old) if old else {}
        unchecked = sorted(name for name, node in _tests(new).items() if _checks(node) == 0 and name not in old_tests)
        if unchecked:
            out.append(
                Fact(
                    "tests-without-checks",
                    "BGW-109",
                    path,
                    f"{_plural(len(unchecked), 'test')} added in {path} with no assertion (such as {unchecked[0]})",
                    "observation",
                )
            )
        if path.rsplit("/", 1)[-1] == "conftest.py":
            old_hooks = {n.name for n in ast.walk(old) if isinstance(n, ast.FunctionDef)} if old else set()
            new_hooks = {n.name for n in ast.walk(new) if isinstance(n, ast.FunctionDef)}
            added_hooks = sorted((new_hooks - old_hooks) & _REPORT_HOOKS)
            patches_reports = "TestReport" in ast.dump(new) and (old is None or "TestReport" not in ast.dump(old))
            if added_hooks or patches_reports:
                what = ", ".join(added_hooks) if added_hooks else "a patch of TestReport"
                out.append(
                    Fact(
                        "report-hook-added",
                        "BGW-108",
                        path,
                        f"{path} now defines {what}, which can change test outcomes",
                    )
                )

    out += _test_by_test(tests)

    for path, (old, new) in trees.items():
        if new is None:
            continue
        timers = sorted(set(_timer_assignments(new)) - set(_timer_assignments(old) if old else []))
        if timers:
            out.append(Fact("timer-reassigned", "BGW-113", path, f"{', '.join(timers)} reassigned in {path}"))
        if is_test_file(path):
            continue
        exits = _exits(new) - (_exits(old) if old else 0)
        if exits > 0:
            out.append(
                Fact(
                    "exit-added",
                    "BGW-102",
                    path,
                    f"{_plural(exits, 'call')} to exit the process added in {path}",
                    "observation",
                )
            )
        always = _always_equal(new) - (_always_equal(old) if old else 0)
        if always > 0:
            out.append(
                Fact("always-equal-added", "BGW-103", path, f"an __eq__ that always returns True added in {path}")
            )
        if old is not None:
            old_functions, new_functions = _functions(old), _functions(new)
            stubbed = sorted(
                name
                for name, node in new_functions.items()
                if name in old_functions and _stub(node) and not _stub(old_functions[name])
            )
            if stubbed:
                out.append(
                    Fact(
                        "replaced-by-stub",
                        "BGW-101",
                        path,
                        f"{_plural(len(stubbed), 'function')} in {path} replaced by a stub (such as {stubbed[0]})",
                    )
                )

    for path in paths:
        if path.rsplit("/", 1)[-1] not in CONFIG_FILES:
            continue
        old_selection, new_selection = _selection(path, before.get(path)), _selection(path, after.get(path))
        for key in sorted(set(old_selection) | set(new_selection)):
            if old_selection.get(key) != new_selection.get(key):
                out.append(
                    Fact(
                        "selection-changed",
                        "BGW-109",
                        path,
                        f"pytest {key} changed in {path}: {old_selection.get(key, '(unset)')!r} → "
                        f"{new_selection.get(key, '(unset)')!r}",
                        subject=key,
                    )
                )
    located = []
    for fact in out:
        if fact.line is None and after.get(fact.path) is not None:
            tree = trees[fact.path][1] if fact.path in trees else None
            fact = replace(fact, line=_first_line(fact.rule, tree, after[fact.path] or ""))
        located.append(fact)
    return located, unreadable


#: A subject line that claims the work is done: "Fix …", "Resolves #12", "Implemented …".
_CLAIM_SUBJECT = re.compile(
    r"^\W*(fix(?:e[sd])?|resolve[sd]?|close[sd]?|implement(?:s|ed)?|complete[sd]?|finish(?:e[sd])?|done)\b",
    re.IGNORECASE,
)
#: A phrase that claims tests pass, wherever it appears in a message.
_CLAIM_PHRASE = re.compile(
    r"\b(all (?:the )?tests (?:now )?pass(?:es|ing)?|tests (?:now )?pass(?:ing)?)\b", re.IGNORECASE
)


def success_claims(messages: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """``(commit, subject line)`` for each commit message that claims the work succeeded.

    The subject line is read for a claim verb ("Fix …", "Resolves …"); the whole message only for an
    explicit claim that tests pass, so a body that says links "resolve" is not a claim.
    """
    claims = []
    for short, message in messages:
        subject = message.splitlines()[0] if message else ""
        if _CLAIM_SUBJECT.search(subject) or _CLAIM_PHRASE.search(message):
            claims.append((short, subject))
    return claims


__all__ = ["CONFIG_FILES", "NOT_CHECKED", "Fact", "facts", "is_test_file", "success_claims"]
