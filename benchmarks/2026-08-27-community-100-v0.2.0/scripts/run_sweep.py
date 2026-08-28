"""Scan every dataset in ``results/manifest.json``, pinned to the SHA it was selected at.

Unlike the first corpus's sweep, this one scans ``owner/name@sha`` rather than a bare repo
id. A Hub dataset can be re-uploaded under the same name, so an unpinned corpus is a moving
target and any fire rate quoted against it decays silently.

Only the default configuration is run. The question this corpus exists to answer is what a
user of bohrin 0.2.0 sees on natively-recorded data, so ``--all``, ``--full`` and policy
flags would all change the subject.

    python scripts/run_sweep.py --out results/sweep.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from bohrin.api import scan


def scan_one(entry: dict[str, Any]) -> dict[str, Any]:
    repo_id, sha = entry["dataset"], entry["sha"]
    started = time.time()
    try:
        report = scan(f"{repo_id}@{sha}")
    except Exception as exc:  # a crash on real data is exactly what this hunts for
        return {"dataset": repo_id, "sha": sha, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    d = report.dataset
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    findings = []
    for cluster in report.clusters:
        counts[cluster.severity.name] = counts.get(cluster.severity.name, 0) + 1
        findings.append({"severity": cluster.severity.name, "detectors": cluster.detector_ids, "title": cluster.title})
    return {
        "dataset": repo_id,
        "sha": sha,
        "ok": True,
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
    parser.add_argument("--manifest", default="results/manifest.json")
    parser.add_argument("--out", default="results/sweep.json")
    args = parser.parse_args(argv)

    entries = json.loads(Path(args.manifest).read_text())["datasets"]
    rows = []
    for i, entry in enumerate(entries, start=1):
        row = scan_one(entry)
        rows.append(row)
        if row["ok"]:
            print(
                f"[{i:>3}/{len(entries)}] ok   {row['dataset']:52s} {row['seconds']:5.1f}s "
                f"{row['episodes_scanned']:>4} eps  H{row['high']} M{row['medium']} L{row['low']}",
                flush=True,
            )
        else:
            print(f"[{i:>3}/{len(entries)}] FAIL {row['dataset']:52s} {row['error'][:70]}", flush=True)
        Path(args.out).write_text(json.dumps(rows, indent=1))  # checkpoint as we go
    ok = [r for r in rows if r["ok"]]
    print(f"\n{len(ok)}/{len(rows)} scanned without error; wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
