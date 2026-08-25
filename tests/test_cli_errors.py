"""User-facing error paths and the RLDS pure helpers (final P3 sweep).

Two gaps this closes:

* **The CLI used to print a traceback** for the most common first-run mistake — a wrong
  path or an unsupported container. A traceback reads as "this tool crashed" rather than
  "fix your input", which is the worst possible first impression for an adoption-led tool.
  These tests also pin the *stream*: diagnostics go to stderr and never to stdout, so
  ``bohrin scan x --json - | jq`` stays parseable when the scan fails.
* **RLDS was the only adapter with no test**, because TensorFlow is an optional heavy
  dependency. Its two decision points that do *not* need TF — format detection (files only)
  and step flattening (pure) — are covered here, so the untested surface is just the TF
  call itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import _synth
from bohrin.adapters.rlds import RldsAdapter, flatten_step
from bohrin.cli import main
from bohrin.policy.target import target_families

# --------------------------------------------------------------- CLI: user errors, not crashes


def test_a_missing_path_prints_a_message_not_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["scan", "./definitely-not-a-dataset"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""  # nothing on stdout: a failed scan produces no findings
    assert "error" in captured.err
    assert "Traceback" not in captured.err
    assert "no such path" in captured.err  # names the actual cause, not a format problem
    assert "owner/name" in captured.err  # and the next thing to try


def test_an_unrecognized_directory_names_the_format_escape_hatch(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A path that exists but matches no adapter is a different failure with a different fix."""
    (tmp_path / "some_data.bin").write_bytes(b"")
    code = main(["scan", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    assert "--format" in captured.err  # tells the user what to try next


def test_unknown_target_is_reported_before_the_path_is_touched(capsys: pytest.CaptureFixture[str]) -> None:
    """An argument typo must not be reported as a problem with the dataset."""
    code = main(["scan", "./definitely-not-a-dataset", "--target", "gpt5"])
    err = capsys.readouterr().err
    assert code == 2
    assert "--target" in err
    assert "could not detect the format" not in err


def test_target_error_lists_spellings_that_actually_work(capsys: pytest.CaptureFixture[str]) -> None:
    """Every value the message offers must be accepted — otherwise it sends users in circles."""
    main(["scan", "./nope", "--target", "bogus"])
    err = capsys.readouterr().err.replace("\n", "")
    for name in target_families():
        assert name in err


def test_unreadable_checkpoint_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    code = main(["scan", uri, "--policy", "./no-such-checkpoint.safetensors"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err + captured.out


def test_pickled_checkpoint_refusal_reaches_the_user(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"\x80\x04 not really a pickle")
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    code = main(["scan", uri, "--policy", str(ckpt)])
    err = capsys.readouterr().err
    assert code == 2
    assert "safetensors" in err  # the message names the way forward


def test_successful_scan_still_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    assert main(["scan", uri]) == 0
    assert "No findings. The data looks clean." in capsys.readouterr().out


# ------------------------------------------------------------------------- RLDS, without TF


def test_rlds_detects_a_tfds_directory(tmp_path: Path) -> None:
    """Detection reads files only, so it works even when the extra isn't installed."""
    root = tmp_path / "ds"
    root.mkdir()
    (root / "features.json").write_text(json.dumps({"steps": {"action": {"shape": [7]}}}))
    (root / "dataset_info.json").write_text(json.dumps({"name": "demo"}))
    assert RldsAdapter().detect(root) == pytest.approx(0.95)


def test_rlds_ignores_directories_that_merely_have_json(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    root.mkdir()
    (root / "features.json").write_text(json.dumps({"something_else": 1}))
    assert RldsAdapter().detect(root) == 0.0


def test_rlds_ignores_a_plain_directory(tmp_path: Path) -> None:
    assert RldsAdapter().detect(tmp_path) == 0.0


def test_rlds_survives_corrupt_features_json(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    root.mkdir()
    (root / "features.json").write_text("{not json")
    assert RldsAdapter().detect(root) == 0.0


def test_flatten_step_produces_mapper_ready_keys() -> None:
    """The flattening rule decides what the schema mapper can even see."""
    flat = flatten_step(
        {
            "action": [1, 2],
            "observation": {"state": [3], "image": "px", "nested": {"depth": "d"}},
        }
    )
    assert set(flat) == {"action", "observation/state", "observation/image", "observation/nested/depth"}


def test_flatten_step_handles_an_empty_step() -> None:
    assert flatten_step({}) == {}
