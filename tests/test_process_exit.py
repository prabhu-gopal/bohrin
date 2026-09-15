"""The ``bohrin`` command ends when its work is done, even if a library will not let go.

Found on the 2026-09-15 sweep: after an environment's dataset build failed, Bohrin printed its
error and the process never exited. A native stack showed Python had already finished and the C
runtime's ``exit`` was blocked in Apache Arrow's global thread-pool destructor. Plain Python with
no Bohrin installed hung the same way, so the cause is inherited, but the hung terminal is ours.

These run the real console entry point in a child process. A blocking exit handler stands in for
the native destructor: both only run if normal interpreter shutdown is allowed to proceed, so a
handler that sleeps for ten minutes is a faithful and portable proxy for the Arrow hang.
"""

from __future__ import annotations

import subprocess
import sys

#: Far longer than any of these should take, far shorter than the ten-minute handler.
_DEADLINE = 60


def _entry(body: str, *argv: str) -> subprocess.CompletedProcess[str]:
    script = "\n".join(
        [
            "import atexit, sys, time",
            "import bohrin.cli as cli",
            f"sys.argv = ['bohrin', *{list(argv)!r}]",
            body,
            "cli._run()",
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=_DEADLINE, check=False
    )


def test_a_library_blocking_shutdown_cannot_hang_the_command() -> None:
    """Before: the process outlived its own report indefinitely."""
    body = "\n".join(
        [
            "def main(argv=None):",
            "    atexit.register(time.sleep, 600)  # stands in for a destructor that never returns",
            "    print('report printed')",
            "    return 2",
            "cli.main = main",
        ]
    )
    proc = _entry(body)  # raises TimeoutExpired, failing the test, if exit is still blocked

    assert proc.returncode == 2, "the audit's own exit code survives the early exit"
    assert "report printed" in proc.stdout


def test_output_written_without_a_newline_is_not_lost() -> None:
    """Skipping teardown must not skip flushing: the report is the whole point of the run."""
    body = "\n".join(
        ["def main(argv=None):", "    sys.stdout.write('no trailing newline')", "    return 0", "cli.main = main"]
    )
    proc = _entry(body)

    assert proc.returncode == 0
    assert proc.stdout == "no trailing newline"


def test_version_and_help_still_exit_zero_through_the_entry_point() -> None:
    """argparse leaves --version and --help by raising SystemExit, not by returning."""
    for flag in ("--version", "--help"):
        proc = _entry("", flag)
        assert proc.returncode == 0, flag
        assert proc.stdout.strip(), f"{flag} printed nothing"


def test_bad_arguments_still_exit_two_with_a_message() -> None:
    proc = _entry("", "audit")  # the path is required

    assert proc.returncode == 2
    assert "usage:" in proc.stderr


def test_ctrl_c_still_exits_130() -> None:
    body = "\n".join(["def main(argv=None):", "    raise KeyboardInterrupt", "cli.main = main"])
    proc = _entry(body)

    assert proc.returncode == 130
    assert "Traceback" not in proc.stderr
