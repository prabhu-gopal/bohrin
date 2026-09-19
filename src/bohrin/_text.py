"""Text from a taskset, made safe to print and to paste.

Bohrin prints strings it did not write: task ids, prompts, declared answers, submitted payloads
and the grader's own error messages all come from the taskset under audit. Rich's ``escape``
neutralises Rich markup, but not terminal control sequences, and Rich passes CSI sequences
through unchanged. Measured before this module existed: a task id containing ``\\x1b[2J``
reached the terminal intact on three report lines, including the reproduction command.

That turns an audited taskset into something that can drive the auditor's own screen: clear
it, move the cursor up and erase the line reporting its exploit, or print a forged line. The
same holds for invisible bidirectional-override characters, which make displayed text read
differently from what it is.

Two functions close it, and nothing else in the package prints taskset text without them:

* :func:`safe` renders a string for the terminal. Every control character and bidirectional
  override becomes a visible escape such as ``\\x1b``, then Rich markup is escaped.
* :func:`shell_arg` quotes one argument of a reproduction command. Ordinary text is quoted
  exactly as ``shlex.quote`` would, so existing commands are unchanged; text containing a
  control character uses ANSI-C quoting (``$'...'``), which bash and zsh decode back to the
  exact original bytes, so the pasted command still reproduces the finding.
"""

from __future__ import annotations

import re
import shlex

from rich.markup import escape

#: C0 controls, DEL, C1 controls, and the bidirectional marks and overrides used to make text
#: display differently from its contents.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _escaped(char: str) -> str:
    """``char`` as ``\\xHH`` escapes of its UTF-8 bytes, understood by every POSIX shell's
    ANSI-C quoting, including the bash 3.2 that macOS ships, which has no ``\\u``."""
    return "".join(f"\\x{byte:02x}" for byte in char.encode("utf-8"))


def visible(text: str) -> str:
    """``text`` with every control character and bidirectional mark shown, not obeyed."""
    return _UNSAFE.sub(lambda match: _escaped(match.group()), text)


def safe(text: str) -> str:
    """``text`` ready to embed in a Rich markup string for the terminal."""
    return escape(visible(text))


def shell_arg(text: str) -> str:
    """One shell argument that reproduces ``text`` exactly when pasted.

    Identical to ``shlex.quote`` for ordinary text, so no existing reproduction command
    changes. Text a terminal would obey is written in ANSI-C quoting instead, where every
    unsafe character is an explicit escape rather than a raw byte on the screen.
    """
    if not _UNSAFE.search(text):
        return shlex.quote(text)
    parts: list[str] = []
    for char in text:
        if char == "\\":
            parts.append("\\\\")
        elif char == "'":
            parts.append("\\'")
        elif _UNSAFE.match(char):
            parts.append(_escaped(char))
        else:
            parts.append(char)
    return "$'" + "".join(parts) + "'"


__all__ = ["safe", "shell_arg", "visible"]
