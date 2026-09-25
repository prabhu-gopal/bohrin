"""Built-in positive controls: rewritings of a correct program that a correct grader must accept.

A grader tightened to stop cheating is exactly the kind that starts rejecting correct code: in one
hacker-fixer loop, two over-restrictive defences dragged a model's pass rate on correct code to 22%
(arXiv:2606.08960). So every audit measures correct-work acceptance beside the Coverage Score.

Each rewriting here returns ``None`` unless :mod:`bohrin.relations.certify` proves the result does
the same thing; silence is always the safe answer.
"""

from __future__ import annotations

import ast
import builtins
import io
import tokenize

from bohrin.relations.base import Relation
from bohrin.relations.certify import same_bytecode_except_local_names, same_syntax


class Reformatted(Relation):
    """The program re-laid out by Python's own unparser: new spacing, quotes and line breaks."""

    id = "reformatted"
    certification = "the rewritten program parses to the same syntax tree as the original"

    def render(self, answer: str) -> str | None:
        """``ast.unparse`` of the program, or ``None`` if it does not parse or does not change."""
        try:
            rewritten = ast.unparse(ast.parse(answer)) + "\n"
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None
        if rewritten.strip() == answer.strip() or not same_syntax(answer, rewritten):
            return None
        return rewritten


class CommentFree(Relation):
    """The program with its comments removed and its layout otherwise kept."""

    id = "comment_free"
    certification = "comments are not part of the syntax tree, and the tree is unchanged"

    def render(self, answer: str) -> str | None:
        """The program without ``#`` comments, or ``None`` if it has none or does not tokenize."""
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(answer).readline))
        except (tokenize.TokenError, SyntaxError, IndentationError):
            return None
        if not any(token.type == tokenize.COMMENT for token in tokens):
            return None
        kept = [token for token in tokens if token.type != tokenize.COMMENT]
        rewritten = tokenize.untokenize(kept)
        rewritten = "\n".join(line.rstrip() for line in rewritten.splitlines()).strip("\n") + "\n"
        return rewritten if same_syntax(answer, rewritten) else None


#: Calls through which a function can read its own local names at run time, which bytecode
#: equality cannot see. A function that makes one is never renamed.
_REFLECTIVE = frozenset({"locals", "vars", "eval", "exec", "dir", "globals", "compile", "__import__", "breakpoint"})
#: Constructs with scopes or bindings of their own, which renaming would have to follow; a function
#: containing one is left alone rather than renamed half-way.
_NESTED = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Import,
    ast.ImportFrom,
    ast.Match,
    ast.Global,
    ast.Nonlocal,
)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _renamable(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, _NESTED):
                return False
            if isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name in _REFLECTIVE or name.startswith("inspect.") or name == "sys._getframe":
                    return False
    return True


def _locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    arguments = function.args
    parameters = {
        a.arg
        for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
        if a is not None
    }
    bound: set[str] = set()
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
                bound.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
    return sorted(bound - parameters)


class RenamedLocals(Relation):
    """The program with each function's local variables renamed to fresh names.

    Parameters and function names are never renamed: callers can pass keyword arguments, and
    graders call functions by name.
    """

    id = "renamed_locals"
    certification = (
        "the program compiles to the same instructions, constants and globals, differing only in the names of "
        "local variables, and no renamed function reads its own local names at run time"
    )

    def render(self, answer: str) -> str | None:
        """The program with locals renamed, or ``None`` when nothing can be renamed and certified."""
        try:
            tree = ast.parse(answer)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None
        taken = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        taken |= {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
        taken |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        taken |= set(dir(builtins))
        renamed = 0
        counter = 0
        for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]:
            if not _renamable(function):
                continue
            mapping: dict[str, str] = {}
            for name in _locals(function):
                while f"local_{counter}" in taken:
                    counter += 1
                mapping[name] = f"local_{counter}"
                taken.add(mapping[name])
            for statement in function.body:
                for node in ast.walk(statement):
                    if isinstance(node, ast.Name) and node.id in mapping:
                        node.id = mapping[node.id]
                    elif isinstance(node, ast.ExceptHandler) and node.name in mapping:
                        node.name = mapping[node.name]
            renamed += len(mapping)
        if not renamed:
            return None
        rewritten = ast.unparse(tree) + "\n"
        return rewritten if same_bytecode_except_local_names(answer, rewritten) else None


__all__ = ["CommentFree", "Reformatted", "RenamedLocals"]
