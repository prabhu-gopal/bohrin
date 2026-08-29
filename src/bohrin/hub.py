"""Resolve a Hugging Face Hub ``repo_id`` to a local snapshot (docs/05 §3).

``bohrin scan lerobot/pusht`` has to work: it is the first command in the README and the
only one a stranger can run without owning a robot. Everything downstream of this module
sees an ordinary local directory, so no adapter, detector, or report knows the Hub exists.

Two deliberate constraints:

* **Video is never fetched.** The scan reads Parquet columns only, so pulling the MP4s
  would multiply the download by one to three orders of magnitude to produce byte-identical
  findings. ``allow_patterns`` keeps the transfer to ``meta/`` + ``data/``.
* **This is the only network call in the tool.** It happens exactly when the user typed a
  repo id, never as a side effect of scanning a local path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: A Hub repo id: ``owner/name``, each a Hub-legal slug, and exactly one slash.
#: Deliberately strict — ``./data/foo`` and ``C:\x\y`` must never match.
_REPO_ID = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")

#: Fetched from a LeRobot repo. Everything the profile and the three core detector families
#: read lives in ``meta/`` (info.json, stats.json, episodes, tasks) and ``data/`` (Parquet).
METADATA_PATTERNS = ("meta/*", "meta/**/*")
DATA_PATTERNS = ("data/*", "data/**/*.parquet")


def _silent_tqdm() -> type:
    """A tqdm subclass that renders nothing — for ``--ci`` and non-TTY runs."""
    from tqdm.auto import tqdm

    class _Silent(tqdm):  # type: ignore[misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

    return _Silent


class HubUnavailableError(RuntimeError):
    """Raised when a repo id was given but the Hub could not satisfy it."""


def looks_like_repo_id(target: str) -> bool:
    """True if ``target`` is a Hub repo id rather than a filesystem path.

    An existing local path always wins: a directory literally named ``lerobot/pusht``
    relative to the cwd is what the user meant, and silently preferring the Hub copy would
    scan data they did not point at.
    """
    if Path(target).exists():
        return False
    if os.sep in target.replace("/", os.sep) and target.count("/") != 1:
        return False
    return bool(_REPO_ID.match(target))


def split_revision(target: str) -> tuple[str, str | None]:
    """``"owner/name@abc123"`` -> ``("owner/name", "abc123")``; no ``@`` -> revision ``None``.

    Pinning matters for anything whose numbers are meant to be reproducible: a Hub dataset
    can be re-uploaded under the same id, and a benchmark that cites a fire rate against an
    unpinned dataset is citing a moving target. ``@`` is the separator the Hub itself uses.
    """
    repo_id, sep, revision = target.partition("@")
    return (repo_id, revision) if sep and revision else (target, None)


def resolve(
    repo_id: str,
    *,
    metadata_only: bool = False,
    revision: str | None = None,
    quiet: bool = False,
) -> Path:
    """Download ``repo_id``'s tabular files and return the local snapshot directory.

    Raises :class:`HubUnavailableError` with an actionable message on any failure — a bare
    ``huggingface_hub`` traceback on a typo'd repo name reads as a crash in bohrin.
    """
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError
    except ImportError as exc:  # pragma: no cover - huggingface_hub is a core dependency
        raise HubUnavailableError(
            f"scanning the Hub repo {repo_id!r} needs huggingface_hub, which is missing from "
            f"this environment. Install it with: pip install huggingface_hub"
        ) from exc

    patterns = list(METADATA_PATTERNS) if metadata_only else [*METADATA_PATTERNS, *DATA_PATTERNS]
    try:
        local = snapshot_download(
            repo_id,
            repo_type="dataset",
            revision=revision,
            allow_patterns=patterns,
            tqdm_class=_silent_tqdm() if quiet else None,
        )
    except RepositoryNotFoundError as exc:
        raise HubUnavailableError(
            f"no dataset repo {repo_id!r} on the Hugging Face Hub. Check the spelling, or pass a "
            f"local path instead. If the repo is private, log in first: huggingface-cli login"
        ) from exc
    except HfHubHTTPError as exc:
        raise HubUnavailableError(
            f"could not fetch {repo_id!r} from the Hugging Face Hub ({exc.__class__.__name__}). "
            f"Check your network, or download the dataset and scan the local directory."
        ) from exc
    except OSError as exc:
        raise HubUnavailableError(f"could not fetch {repo_id!r} from the Hugging Face Hub: {exc}") from exc

    root = Path(local)
    if not (root / "meta").is_dir():
        raise HubUnavailableError(
            f"{repo_id!r} is on the Hub but has no meta/ directory, so it is not a LeRobot "
            f"dataset. bohrin reads LeRobot v2.1 and v3.0; other Hub layouts are not supported yet."
        )
    return root
