"""The CLI surface: exit codes, streams, and errors that are messages not tracebacks."""

from __future__ import annotations

from pathlib import Path

import pytest

from bohrin.cli import main


def test_version_and_help_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["--version"], ["--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0


def test_list_probes_names_both_open_probes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list-probes"]) == 0
    out = capsys.readouterr().out
    assert "weak_oracle" in out
    assert "determinism" in out


def test_explain_prints_the_probe_rationale(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "weak_oracle"]) == 0
    assert "verifier" in capsys.readouterr().out.lower()


def test_explain_unknown_probe_lists_what_exists(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "no_such_probe"]) == 1
    err = capsys.readouterr().err
    assert "unknown probe" in err.lower()
    assert "weak_oracle" in err, "telling the user what is wrong without what to try is not help"


def test_a_missing_path_is_a_message_not_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["audit", "./definitely-not-a-taskset"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == "", "a failed audit produces no findings on stdout"
    assert "error" in captured.err
    assert "Traceback" not in captured.err
    # The extras hint belongs on a path that exists in an unrecognised format — see
    # test_unknown_format_names_the_verifiers_extra. Offering it here would answer a
    # mistyped path with advice to install something, which is the wrong problem.
    assert "no such file or directory" in captured.err.lower()
    assert "pip install" not in captured.err


def test_unknown_format_names_the_verifiers_extra(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "some_file.txt").write_text("not a taskset", encoding="utf-8")

    assert main(["audit", str(tmp_path)]) == 2
    err = " ".join(capsys.readouterr().err.split())  # rich soft-wraps at the console width
    assert "bohrin[verifiers]" in err, "the extra must survive rendering — rich eats bare brackets"
