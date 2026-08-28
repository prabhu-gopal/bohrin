"""Pick a corpus of natively-recorded, high-rate community LeRobot datasets.

The first benchmark corpus (``benchmarks/2026-08-26-lerobot-20-v0.1.0/``) has a defect it
documents in its own limitations: 14 of its 20 datasets are Open X-Embodiment conversions
recorded at 5 Hz, and every native dataset in it runs faster. Control rate and conversion
provenance are therefore *perfectly confounded* there, which means that corpus cannot tell
a threshold bug apart from an artifact of format conversion, and it says little about the
user bohrin is built for: someone teleoperating a low-cost arm and recording at 20-50 Hz
directly in LeRobot format.

This script selects the corpus that breaks the confound. It reads only ``meta/info.json``
per candidate (a few KB), so probing several hundred datasets costs little.

Selection is deliberately mechanical, and every rule is recorded in the manifest so the
corpus can be criticised rather than taken on trust:

* **Native, not converted.** Anything under the ``lerobot/`` org is excluded: that is the
  curated mirror the first corpus already covers, and it is where the OXE conversions live.
* **High control rate.** ``fps >= 20``. This is the property that breaks the confound.
* **Actually scannable.** Must declare an action and a proprioceptive state, and hold
  enough episodes for the episode-level detectors to have anything to say.
* **Bounded.** Very large datasets are skipped so a full sweep stays laptop-sized; the
  cap is recorded rather than silently applied.
* **Pinned.** Every dataset is recorded with the commit SHA it was selected at, and the
  sweep scans ``owner/name@sha``. A Hub dataset can be re-uploaded under the same id, so an
  unpinned corpus is a moving target.

    python scripts/select_corpus.py --target 100 --out results/manifest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download

#: Search terms covering the low-cost arms bohrin's intended user actually owns, plus a
#: general sweep so the corpus is not defined purely by hardware brand names.
SEARCH_TERMS = ("so101", "so100", "koch", "moss", "lekiwi", "so_101", "so-101", "aloha", "")

#: Minimum control rate. The first corpus is overwhelmingly 5 Hz; this is the axis that
#: separates the two populations.
MIN_FPS = 20

#: Episode floor. Several detectors compare episodes against their siblings and abstain
#: below a handful, so a 3-episode dataset would contribute silence rather than evidence.
MIN_EPISODES = 10

#: Frame ceiling, so one enormous dataset cannot dominate the sweep's wall time. Recorded
#: in the manifest because it biases the corpus toward smaller recordings.
MAX_FRAMES = 300_000

#: The curated org whose datasets the first corpus already covers.
EXCLUDED_ORG = "lerobot/"


def candidates(api: HfApi, limit_per_term: int) -> dict[str, int]:
    """Union of Hub search results across :data:`SEARCH_TERMS`, mapped to download count."""
    found: dict[str, int] = {}
    for term in SEARCH_TERMS:
        kwargs: dict[str, Any] = {"filter": "LeRobot", "limit": limit_per_term}
        if term:
            kwargs["search"] = term
        for d in api.list_datasets(**kwargs):
            if not d.id.startswith(EXCLUDED_ORG):
                found[d.id] = d.downloads or 0
    return found


def probe(api: HfApi, repo_id: str) -> dict[str, Any] | None:
    """Read one dataset's ``meta/info.json`` and its current SHA, or ``None`` if unusable."""
    try:
        path = hf_hub_download(repo_id, "meta/info.json", repo_type="dataset")
        info = json.loads(Path(path).read_text())
        sha = api.dataset_info(repo_id).sha
    except Exception:
        return None
    features = info.get("features") or {}
    action = features.get("action") or {}
    state = features.get("observation.state") or {}
    fps, episodes, frames = info.get("fps"), info.get("total_episodes"), info.get("total_frames")
    if not (isinstance(fps, int | float) and isinstance(episodes, int) and isinstance(frames, int)):
        return None
    return {
        "dataset": repo_id,
        "sha": sha,
        "robot_type": info.get("robot_type"),
        "fps": fps,
        "episodes": episodes,
        "frames": frames,
        "action_dim": (action.get("shape") or [None])[0],
        "state_dim": (state.get("shape") or [None])[0],
        "codebase_version": info.get("codebase_version"),
    }


def eligible(row: dict[str, Any]) -> str | None:
    """``None`` if the dataset belongs in the corpus, else the rule that rejected it."""
    if row["fps"] < MIN_FPS:
        return f"fps<{MIN_FPS}"
    if row["episodes"] < MIN_EPISODES:
        return f"episodes<{MIN_EPISODES}"
    if row["frames"] > MAX_FRAMES:
        return f"frames>{MAX_FRAMES}"
    if not row["action_dim"] or not row["state_dim"]:
        return "no action or state"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=100, help="How many datasets to select.")
    parser.add_argument("--probe", type=int, default=420, help="How many candidates to probe.")
    parser.add_argument("--limit-per-term", type=int, default=300)
    parser.add_argument("--out", default="results/manifest.json")
    args = parser.parse_args(argv)

    api = HfApi()
    pool = candidates(api, args.limit_per_term)
    ranked = sorted(pool, key=lambda k: -pool[k])
    print(f"{len(pool)} candidate datasets; probing the {args.probe} most-downloaded\n")

    selected: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    probed = 0
    for repo_id in ranked[: args.probe]:
        row = probe(api, repo_id)
        probed += 1
        if row is None:
            rejected["unreadable"] = rejected.get("unreadable", 0) + 1
            continue
        why = eligible(row)
        if why:
            rejected[why] = rejected.get(why, 0) + 1
            continue
        row["downloads"] = pool[repo_id]
        selected.append(row)
        print(f"  [{len(selected):>3}] {repo_id:52s} {row['fps']:>3.0f}Hz {row['episodes']:>5} eps")
        if len(selected) >= args.target:
            break

    manifest = {
        "generated": "2026-08-27",
        "selection_rules": {
            "min_fps": MIN_FPS,
            "min_episodes": MIN_EPISODES,
            "max_frames": MAX_FRAMES,
            "excluded_org": EXCLUDED_ORG,
            "search_terms": [t for t in SEARCH_TERMS if t],
            "ranked_by": "hub download count, descending",
        },
        "probed": probed,
        "rejected": rejected,
        "datasets": selected,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1))
    print(f"\nprobed {probed}, selected {len(selected)}")
    print("rejected:", rejected)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
