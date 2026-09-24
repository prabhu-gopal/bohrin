"""Mechanical proofs that a rewriting of a program does not change what it does.

A positive control is a correct program a correct grader must accept. If a rewriting silently
changed behaviour, Bohrin would accuse a correct grader of rejecting correct work, so no rewriting
is emitted on judgement: each is emitted only when one of these checks proves it equivalent. The
robustness literature verified its rewritings by human review (over 90% preserved meaning, ReCode,
arXiv:2212.10264); a claim about someone else's grader needs every one.

* :func:`same_syntax`: the two programs have the same syntax tree. Layout and comments are not
  in the tree, so a reformatting or a comment removal that passes this changed nothing that runs.
* :func:`same_bytecode_except_local_names`: the two programs compile to the same instructions,
  constants and global names, and differ only in what their local variables are called. A local
  renamed into a clash with a global compiles to a different instruction, and an f-string such as
  ``f"{x=}"`` embeds the name as a constant, so both fail here. What bytecode cannot see (code that
  reads its own local names at run time through ``locals()``, ``eval`` or frame introspection) is
  refused before renaming, by the rewriting itself.
"""

from __future__ import annotations

import ast
from inspect import CO_VARARGS, CO_VARKEYWORDS
from types import CodeType


def same_syntax(left: str, right: str) -> bool:
    """Whether two sources parse to the same syntax tree, ignoring layout and comments."""
    try:
        return ast.dump(ast.parse(left)) == ast.dump(ast.parse(right))
    except (SyntaxError, ValueError, RecursionError):
        return False


def _parameters(code: CodeType) -> int:
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & CO_VARARGS) + bool(code.co_flags & CO_VARKEYWORDS)
    return count


def _canonical(code: CodeType) -> tuple[object, ...]:
    """A code object with the names of its non-parameter locals replaced by their positions."""
    kept = _parameters(code)
    varnames = tuple(name if index < kept else index for index, name in enumerate(code.co_varnames))
    consts = tuple(_canonical(const) if isinstance(const, CodeType) else const for const in code.co_consts)
    return (
        code.co_name,
        code.co_code,
        consts,
        code.co_names,
        varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_flags,
    )


def same_bytecode_except_local_names(left: str, right: str) -> bool:
    """Whether two sources compile to the same program up to the names of non-parameter locals."""
    try:
        return _canonical(compile(left, "<left>", "exec")) == _canonical(compile(right, "<right>", "exec"))
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return False


__all__ = ["same_bytecode_except_local_names", "same_syntax"]
