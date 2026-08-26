"""Regenerate every figure in this report from ``results/sweep.json``.

One source of truth: the sweep JSON written by ``scripts/hub_smoke.py``. Nothing here
re-scans, re-downloads, or re-derives a number by hand — if a figure disagrees with the
report text, the JSON is what settles it.

Deliberately outside the project's dependency set. ``matplotlib`` is a *reporting* tool,
not something ``bohrin scan`` imports, and pyproject.toml's dependency policy is that a
declared dependency must be imported by shipped code. Build the throwaway environment
this script documents instead:

    python -m venv .venv-figures
    .venv-figures/bin/pip install -r scripts/requirements.txt
    .venv-figures/bin/python scripts/make_figures.py

Each figure is written twice: PNG (150 dpi, for the Markdown report) and PDF (vector,
for the LaTeX paper), so the paper never embeds a raster chart.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: this script only ever writes files

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, PercentFormatter, ScalarFormatter

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "sweep_full.json"
RESULTS_TRIAGE = ROOT / "results" / "sweep_default.json"
FIGURES = ROOT / "figures"

# --- Design tokens -------------------------------------------------------------------
# Light-surface only: these figures are printed into a PDF, so a single committed look is
# correct. Values from the validated reference palette; both palettes below were checked
# with the data-viz validator before use (categorical 2-slot: all pass; severity ordinal
# ramp: monotone L, ΔL gaps, 2.13:1 light-end contrast, 7° hue spread — all pass).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

SERIES_BLUE = "#2a78d6"  # categorical slot 1 — "fired, below HIGH"
STATUS_HIGH = "#d03b3b"  # status critical — "fired at HIGH"

# Ordinal severity ramp, light → dark = LOW → HIGH.
SEV = {"low": "#e89b9b", "medium": "#d03b3b", "high": "#8f1f1f"}

FONT = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": FONT,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "text.color": INK,
        "axes.labelcolor": INK_2,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.edgecolor": BASELINE,
        "axes.linewidth": 0.8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "legend.frameon": False,
    }
)


def load() -> list[dict]:
    """The uncapped (``--full``) sweep: every episode of every dataset was read."""
    return json.loads(RESULTS.read_text())


def _strip(ax, *, xgrid: bool = True) -> None:
    """Recessive chrome: no box, hairline grid on the value axis only."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    if xgrid:
        ax.xaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)
        ax.set_axisbelow(True)
    ax.yaxis.grid(False)
    ax.tick_params(length=0)


def save(fig, name: str) -> None:
    FIGURES.mkdir(exist_ok=True)
    # PNG keeps the chart surface (it is read on its own, against a page of unknown
    # colour); the PDF drops it so the figure sits flush on the paper's white stock.
    fig.savefig(FIGURES / f"{name}.png", dpi=150, bbox_inches="tight")
    fig.savefig(FIGURES / f"{name}.pdf", bbox_inches="tight", transparent=True)
    plt.close(fig)
    print(f"wrote figures/{name}.png and .pdf")


def short(name: str) -> str:
    return name.removeprefix("lerobot/")


# --- Figure 1 ------------------------------------------------------------------------
def fig_detector_rates(rows: list[dict]) -> None:
    """Per-detector fire rate across the corpus, with the HIGH share called out.

    Emphasis form, not categorical: the story is *which few detectors report HIGH on a
    large share of healthy public data*, so the HIGH portion carries the status colour and
    everything else recedes to one series hue.
    """
    ok = [r for r in rows if r.get("ok")]
    n = len(ok)
    fires: collections.Counter[str] = collections.Counter()
    highs: collections.Counter[str] = collections.Counter()
    for row in ok:
        seen, seen_high = set(), set()
        for f in row["findings"]:
            for det in f["detectors"]:
                seen.add(det)
                if f["severity"] == "HIGH":
                    seen_high.add(det)
        fires.update(seen)
        highs.update(seen_high)

    order = sorted(fires, key=lambda d: (fires[d], highs[d]))
    y = range(len(order))
    fire_pct = [100 * fires[d] / n for d in order]
    high_pct = [100 * highs[d] / n for d in order]
    rest_pct = [f - h for f, h in zip(fire_pct, high_pct, strict=True)]

    fig, ax = plt.subplots(figsize=(7.2, 7.4))
    ax.barh(y, high_pct, height=0.62, color=STATUS_HIGH, zorder=3, label="fired at HIGH")
    # 2px surface gap between the two segments, per the mark spec.
    ax.barh(
        y,
        rest_pct,
        height=0.62,
        left=[h + 0.6 for h in high_pct],
        color=SERIES_BLUE,
        zorder=3,
        label="fired below HIGH",
    )
    for i, (f, h) in enumerate(zip(fire_pct, high_pct, strict=True)):
        label = f"{f:.0f}%" + (f"  ({h:.0f}% HIGH)" if h else "")
        ax.text(f + 2.0, i, label, va="center", ha="left", fontsize=7.5, color=INK_2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(order, fontsize=7.5, color=INK_2)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(PercentFormatter())
    ax.set_xlabel(f"share of the {n}-dataset corpus on which the detector fired")
    ax.set_title("Detector fire rate on 20 curated public LeRobot datasets", loc="left", color=INK, pad=14)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.02), ncol=1)
    _strip(ax)
    save(fig, "fig1_detector_fire_rates")


# --- Figure 2 ------------------------------------------------------------------------
def fig_dataset_severity(rows: list[dict]) -> None:
    """Findings per dataset, split by severity. Part-to-whole → stacked horizontal bar."""
    ok = sorted((r for r in rows if r.get("ok")), key=lambda r: r["high"] + r["medium"] + r["low"])
    names = [short(r["dataset"]) for r in ok]
    y = range(len(ok))

    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    left = [0.0] * len(ok)
    for key, label in (("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH")):
        vals = [r[key] for r in ok]
        ax.barh(y, vals, height=0.62, left=left, color=SEV[key], label=label, zorder=3)
        for i, (v, l0) in enumerate(zip(vals, left, strict=True)):
            if v:  # direct label — the mitigation the sub-3:1 steps require
                ax.text(
                    l0 + v / 2,
                    i,
                    str(v),
                    va="center",
                    ha="center",
                    fontsize=7.5,
                    color="#ffffff" if key != "low" else INK,
                )
        left = [l0 + v + 0.22 for l0, v in zip(left, vals, strict=True)]  # surface gap between segments

    for i, r in enumerate(ok):
        ax.text(left[i] + 0.5, i, f"{r['episodes_total']} eps", va="center", ha="left", fontsize=7, color=MUTED)

    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=7.5, color=INK_2)
    ax.set_xlabel("findings reported per dataset")
    ax.set_xlim(0, max(left) + 4)
    ax.xaxis.set_major_locator(FixedLocator(list(range(0, int(max(left)) + 3, 5))))
    ax.set_title("Findings per dataset, by severity", loc="left", color=INK, pad=14)
    ax.legend(loc="lower right", ncol=3)
    _strip(ax)
    save(fig, "fig2_dataset_severity")


# --- Figure 3 ------------------------------------------------------------------------
def fig_runtime(rows: list[dict]) -> None:
    """Scan wall-time against episode count.

    Plotted against *episodes*, not frames, because that is what the measurement supports:
    across this corpus wall-time correlates with episode count at r = 0.87 and with frame
    count at only r = 0.68. Per-episode fixed work dominates — ``aloha_mobile_cabinet``
    reads 127,500 frames in 2.1 s while ``ucsd_pick_and_place`` reads half that in 4.2 s,
    because it has 16x more episodes.
    """
    ok = [r for r in rows if r.get("ok")]
    xs = [r["episodes_total"] for r in ok]
    ys = [r["seconds"] for r in ok]

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.scatter(xs, ys, s=54, color=SERIES_BLUE, edgecolor=SURFACE, linewidth=1.6, zorder=3)
    # Label only the extremes — never a number on every point.
    slowest = max(ok, key=lambda r: r["seconds"])
    biggest = max(ok, key=lambda r: r["episodes_total"])
    smallest = min(ok, key=lambda r: r["episodes_total"])
    # Label only the extremes, each nudged clear of its neighbours: the right-hand points
    # would otherwise run off the canvas and the smallest would land on top of the next point.
    for r, (dx, dy, ha) in ((slowest, (-9, 6, "right")), (biggest, (-9, 6, "right")), (smallest, (9, -13, "left"))):
        ax.annotate(
            short(r["dataset"]),
            (r["episodes_total"], r["seconds"]),
            textcoords="offset points",
            xytext=(dx, dy),
            ha=ha,
            fontsize=7,
            color=INK_2,
        )
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator([10, 25, 50, 100, 250, 500, 1400]))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlabel("episodes in the dataset (log scale)")
    ax.set_ylabel("wall-clock seconds")
    ax.set_ylim(0, max(ys) * 1.28)
    ax.set_title("Scan cost tracks episode count, sub-linearly", loc="left", color=INK, pad=14)
    _strip(ax)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)
    save(fig, "fig3_runtime")


def main() -> None:
    rows = load()
    fig_detector_rates(rows)
    fig_dataset_severity(rows)
    fig_runtime(rows)


if __name__ == "__main__":
    main()
