"""Scan the benchmark corpus twice and record everything the report knows.

``scripts/hub_smoke.py`` in the repo root is the release gate: it answers "did anything
crash, and what fired?" This script exists because a *published* benchmark needs more than
that, and one field in particular caused a real error in an earlier draft of this report.

A default scan is **triage**: it caps at ``DEFAULT_TRIAGE_EPISODES`` (300) episodes. So the
report's ``n_episodes`` is *episodes scanned*, not *episodes in the dataset* — and pairing
it with a frame count read from ``meta/info.json`` (which describes the whole dataset)
silently mixes two different populations. ``DatasetInfo`` already distinguishes them via
``total_episodes`` and ``total_steps``; this script records both.

It also runs the corpus a second time with ``full=True`` (no cap), so the report can answer
the question a reviewer will ask: does triage sampling change the conclusions?

    python scripts/run_sweep.py --out results/
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from bohrin.api import scan

#: The corpus, identical to ``scripts/hub_smoke.py``'s ``DATASETS`` — chosen for breadth of
#: embodiment and provenance, not size. Kept as a literal so this run directory stays
#: reproducible even if the harness upstream changes its list.
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


def scan_one(repo_id: str, *, full: bool) -> dict[str, Any]:
    started = time.time()
    try:
        report = scan(repo_id, full=full)
    except Exception as exc:  # a crash on real data is exactly what this hunts for
        return {"dataset": repo_id, "ok": False, "full": full, "error": f"{type(exc).__name__}: {exc}"}
    d = report.dataset
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    findings = []
    for cluster in report.clusters:
        counts[cluster.severity.name] = counts.get(cluster.severity.name, 0) + 1
        findings.append({"severity": cluster.severity.name, "detectors": cluster.detector_ids, "title": cluster.title})
    return {
        "dataset": repo_id,
        "ok": True,
        "full": full,
        "seconds": round(time.time() - started, 2),
        "format": d.format,
        "episodes_scanned": d.n_episodes,
        "episodes_total": d.total_episodes,
        "sampled": d.sampled,
        "steps_scanned": d.total_steps,
        "embodiment": d.embodiment,
        "control_hz": d.control_hz,
        "action_dim": d.action_dim,
        "proprio_dim": d.proprio_dim,
        "high": counts["HIGH"],
        "medium": counts["MEDIUM"],
        "low": counts["LOW"],
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results", help="Directory for the JSON output.")
    parser.add_argument("--datasets", nargs="+", default=list(DATASETS))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for mode, full in (("default", False), ("full", True)):
        rows = []
        for repo_id in args.datasets:
            row = scan_one(repo_id, full=full)
            rows.append(row)
            if row["ok"]:
                cap = " (triaged)" if row["sampled"] else ""
                print(
                    f"{mode:8s} ok   {repo_id:44s} {row['seconds']:5.1f}s  "
                    f"{row['episodes_scanned']:>4}/{row['episodes_total']:<5} eps{cap:10s}"
                    f"  H{row['high']} M{row['medium']} L{row['low']}"
                )
            else:
                print(f"{mode:8s} FAIL {repo_id:44s} {row['error']}")
        path = out / f"sweep_{mode}.json"
        path.write_text(json.dumps(rows, indent=1))
        print(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
