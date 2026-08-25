"""The Python entry point: ``bohrin.scan(path) -> Report`` (docs/05 §4).

The same engine the CLI drives, importable for notebooks, training scripts, and dataloader
guards. Keyword arguments mirror the CLI flags one-to-one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from bohrin.config import DEFAULT_FPR, ScanConfig, load_yaml
from bohrin.engine import ProgressFn, run_scan
from bohrin.hub import looks_like_repo_id
from bohrin.hub import resolve as resolve_repo_id
from bohrin.profile.episode_reservoir import DEFAULT_MEMORY_BUDGET_MB
from bohrin.report.model import Report


def scan(
    path: str | Path,
    *,
    format: str | None = None,  # mirrors the --format flag deliberately
    policy: str | None = None,
    target: str | None = None,
    full: bool = False,
    sample_episodes: int | None = None,
    no_vision: bool = False,
    only: Sequence[str] = (),
    disable: Sequence[str] = (),
    seed: int = 0,
    fpr: float = DEFAULT_FPR,
    lang: str = "en",
    encoder: str = "tiled",
    calibration: str | None = None,
    max_episode_memory_mb: int = DEFAULT_MEMORY_BUDGET_MB,
    progress: ProgressFn | None = None,
) -> Report:
    """Scan a dataset and return a :class:`Report`. Zero flags is the intended common path.

    A ``bohrin.yaml`` found at ``path`` (or in it, if it's a directory) supplies the
    declared schema map and may set the format (docs/02 §1.3).

    ``path`` may be a local directory, a single-file dataset, or a Hugging Face Hub
    ``owner/name`` repo id — the one and only case in which bohrin touches the network.
    An existing local path always takes precedence over a same-named Hub repo.

    ``policy`` raises :class:`~bohrin.policy.loader.UnreadablePolicyError` if the checkpoint
    cannot be read safely, and ``target`` raises
    :class:`~bohrin.policy.target.UnknownTargetError` for an unrecognized family — neither
    is ever accepted and quietly ignored, because a clean report must never stand in for a
    check that did not run.
    """
    path_str = str(path)
    #: A Hub repo id becomes a local snapshot before anything else looks at it, so every
    #: adapter, detector and report below this line only ever sees a directory.
    #: huggingface_hub draws its own byte-level download bar on stderr, which is far more
    #: informative than a two-tick stage of ours; we suppress it in exactly the cases where
    #: we already suppress our own progress (``--ci``, or a non-TTY).
    source: str | None = None
    if looks_like_repo_id(path_str):
        source = path_str
        path = resolve_repo_id(path_str, quiet=progress is None)
        path_str = str(path)
    schema_map = load_yaml(path) if Path(path).exists() else {}
    resolved_format = format or schema_map.get("format")
    config = ScanConfig(
        path=path_str,
        source=source,
        format=resolved_format,
        policy=policy,
        target=target,
        full=full,
        sample_episodes=sample_episodes,
        no_vision=no_vision,
        only=tuple(only),
        disable=tuple(disable),
        seed=seed,
        fpr=fpr,
        lang=lang,
        encoder=encoder,
        calibration=calibration,
        max_episode_memory_mb=max_episode_memory_mb,
        schema_map=schema_map,
    )
    return run_scan(config, progress=progress)
