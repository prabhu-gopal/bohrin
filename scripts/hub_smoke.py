"""Scan a fixed set of real public LeRobot datasets and report what fired.

This is the release gate that unit tests cannot be: the suite runs on synthetic fixtures
where we control the ground truth, so by construction it cannot tell us whether a detector
fires on *ordinary, healthy* data. Only real datasets can, and precision is the whole
product — a HIGH that fires on most curated public datasets carries no information and
breaks `--fail-on HIGH` for everyone using it in CI.

Run it before tagging a release, and whenever you touch a threshold:

    python scripts/hub_smoke.py                     # scan and print the table
    python scripts/hub_smoke.py --json out.json     # also save per-dataset detail

No video is fetched (bohrin never decodes it), so the whole corpus is roughly 50 MB and a
full pass takes a couple of minutes on a laptop.

What to look for: the `as HIGH` column. A detector reporting HIGH on most of these is
almost certainly mis-severitied rather than right — these are curated, published, widely
used datasets. See docs/11_HUB_SMOKE_RESULTS.md for the last recorded run.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

from bohrin.api import scan
from bohrin.ir.schema import Severity

#: Chosen for breadth of embodiment and provenance, not for size: ALOHA, xArm, PR2, Franka,
#: Stretch, UR5, Unitree H1, and the pusht family, spanning sim and real, 2-DoF to 14-DoF.
DATASETS = (
    "lerobot/nyu_rot_dataset",
    "lerobot/ucsd_kitchen_dataset",
    "lerobot/cmu_stretch",
    "lerobot/pusht",
    "lerobot/dlr_edan_shared_control",
    "lerobot/dlr_sara_grid_clamp",
    "lerobot/utokyo_pr2_opening_fridge",
    "lerobot/dlr_sara_pour",
    "lerobot/xarm_lift_medium",
    "lerobot/tokyo_u_lsmo",
    "lerobot/utokyo_pr2_tabletop_manipulation",
    "lerobot/pusht_keypoints",
    "lerobot/asu_table_top",
    "lerobot/aloha_sim_insertion_human",
    "lerobot/unitreeh1_warehouse",
    "lerobot/austin_buds_dataset",
    "lerobot/ucsd_pick_and_place_dataset",
    "lerobot/utokyo_saytap",
    "lerobot/nyu_franka_play_dataset",
    "lerobot/aloha_mobile_cabinet",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", dest="json_path", help="Write per-dataset detail here.")
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS), help="Override the corpus.")
    args = parser.parse_args(argv)

    rows: list[dict[str, object]] = []
    fires: collections.Counter[str] = collections.Counter()
    highs: collections.Counter[str] = collections.Counter()
    failures = 0

    for repo_id in args.datasets:
        started = time.time()
        try:
            report = scan(repo_id)
        except Exception as exc:  # a crash on real data is exactly the thing this hunts for
            failures += 1
            elapsed = time.time() - started
            print(f"FAIL {repo_id:44s} {elapsed:5.1f}s  {type(exc).__name__}: {exc}", file=sys.stderr)
            rows.append({"dataset": repo_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            continue

        elapsed = time.time() - started
        counts = report.counts
        for cluster in report.clusters:
            for detector_id in cluster.detector_ids:
                fires[detector_id] += 1
                if cluster.severity is Severity.HIGH:
                    highs[detector_id] += 1
        print(
            f"ok   {repo_id:44s} {elapsed:5.1f}s  {report.dataset.format:12s} "
            f"{report.dataset.n_episodes:5d} eps  "
            f"H{counts[Severity.HIGH]} M{counts[Severity.MEDIUM]} L{counts[Severity.LOW]}",
            flush=True,
        )
        rows.append(
            {
                "dataset": repo_id,
                "ok": True,
                "seconds": round(elapsed, 1),
                "format": report.dataset.format,
                "episodes": report.dataset.n_episodes,
                "high": counts[Severity.HIGH],
                "medium": counts[Severity.MEDIUM],
                "low": counts[Severity.LOW],
                "findings": [
                    {"severity": c.severity.value, "detectors": list(c.detector_ids), "title": c.title}
                    for c in report.clusters
                ],
            }
        )

    scanned = len(args.datasets) - failures
    print(f"\n{scanned}/{len(args.datasets)} datasets scanned without error\n")
    print(f"{'detector':46s} {'fires':>6s} {'rate':>6s} {'as HIGH':>8s} {'HIGH rate':>10s}")
    print("-" * 80)
    for detector_id, count in fires.most_common():
        high = highs[detector_id]
        flag = "  ← suspicious" if scanned and high / scanned > 0.5 else ""
        print(f"{detector_id:46s} {count:6d} {count / scanned:6.0%} {high:8d} {high / scanned:10.0%}{flag}")

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
