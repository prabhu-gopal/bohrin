"""Hub repo-id resolution — the path that makes `bohrin scan lerobot/pusht` work.

No network here. What is worth pinning is the *decision*: which strings are treated as a
repo id at all, and that a local path always wins. Getting that wrong either breaks every
relative path or silently scans somebody else's data instead of the user's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bohrin.adapters.registry import UnknownFormatError, select_adapter
from bohrin.hub import HubUnavailableError, looks_like_repo_id, resolve


@pytest.mark.parametrize("target", ["lerobot/pusht", "lerobot/aloha_mobile_cabinet", "HuggingFaceVLA/so100-v3"])
def test_repo_ids_are_recognized(target: str) -> None:
    assert looks_like_repo_id(target)


@pytest.mark.parametrize(
    "target",
    [
        "./data",  # explicitly relative
        "data",  # bare name, no slash
        "/abs/path/to/data",  # absolute
        "a/b/c",  # two slashes: a path, not a repo id
        "../sibling",
        "",
    ],
)
def test_paths_are_not_mistaken_for_repo_ids(target: str) -> None:
    assert not looks_like_repo_id(target)


def test_an_existing_local_path_always_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A directory literally named `owner/name` is what the user pointed at, not a Hub repo."""
    (tmp_path / "lerobot" / "pusht").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert not looks_like_repo_id("lerobot/pusht")


def test_a_missing_repo_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The message must name the fix; a huggingface_hub traceback reads as a bohrin crash."""
    from huggingface_hub.errors import RepositoryNotFoundError

    class _NotFound(RepositoryNotFoundError):
        """A raisable 404 that does not depend on huggingface_hub's constructor signature.

        Building a real one needs an httpx Response with a Request attached, and that
        signature has changed across hub releases — coupling this test to it would make an
        unrelated dependency bump look like a bohrin regression.
        """

        def __init__(self) -> None:
            Exception.__init__(self, "404 Client Error")

    def boom(*_args: object, **_kwargs: object) -> str:
        raise _NotFound

    monkeypatch.setattr("huggingface_hub.snapshot_download", boom)
    with pytest.raises(HubUnavailableError) as excinfo:
        resolve("nobody/nothing")
    message = str(excinfo.value)
    assert "nobody/nothing" in message
    assert "huggingface-cli login" in message


def test_video_is_never_fetched() -> None:
    """The scan reads Parquet columns only, so pulling MP4s would be pure download cost."""
    from bohrin.hub import DATA_PATTERNS, METADATA_PATTERNS

    for pattern in (*METADATA_PATTERNS, *DATA_PATTERNS):
        assert "videos" not in pattern
        assert not pattern.endswith(".mp4")


# ------------------------------------------------------------- error messages name the fix


def test_a_missing_path_says_so_rather_than_blaming_the_format(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as excinfo:
        select_adapter(tmp_path / "nope")
    assert "no such path" in str(excinfo.value)
    assert "owner/name" in str(excinfo.value)


def test_a_non_lerobot_directory_names_the_missing_file(tmp_path: Path) -> None:
    (tmp_path / "train.hdf5").write_bytes(b"")
    with pytest.raises(UnknownFormatError) as excinfo:
        select_adapter(tmp_path)
    message = str(excinfo.value)
    assert "meta/info.json" in message  # says exactly what was looked for
    assert "train.hdf5" in message  # and what was found instead
    assert "--format" in message  # and the way forward
