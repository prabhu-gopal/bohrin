"""A ``bohrin`` subcommand, as a plugin.

Every subcommand is a :class:`Command` registered under the ``bohrin.commands`` entry-point group,
the built-in ones included: there is no privileged path. The command line lists them, gives each
its own options, and runs the one the user named. A command follows the contract every verb
shares: its report on standard output (only JSON with ``--json``), errors on standard error, no
required prompt, and the exit codes below.
"""

from __future__ import annotations

import argparse

#: Exit codes, the same on every command.
CLEAN, FINDINGS, CANNOT_RUN, NEEDS_SIGN_IN, OUT_OF_CREDITS, USAGE = 0, 1, 2, 3, 4, 64


class Command:
    """One subcommand of ``bohrin``. Subclass it and register the class under ``bohrin.commands``."""

    #: What the user types, such as ``verify``. The entry-point name is used when this is empty.
    name: str = ""
    #: One line for the command list.
    help: str = ""
    #: A paragraph for ``bohrin <name> --help``.
    description: str = ""
    #: Listed by ``bohrin help more`` instead of the main command list.
    rare: bool = False
    #: How to call it, as ``help more`` shows it, such as ``conformance check FILE``. Defaults to the name.
    usage: str = ""

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """Add this command's arguments and options to ``parser``."""

    def run(self, args: argparse.Namespace) -> int:
        """Do the work and return an exit code."""
        raise NotImplementedError


__all__ = ["CANNOT_RUN", "CLEAN", "FINDINGS", "NEEDS_SIGN_IN", "OUT_OF_CREDITS", "USAGE", "Command"]
