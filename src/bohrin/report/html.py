"""The HTML renderer — Stage ⑥ (docs/02 §6, docs/05 §5).

A single **self-contained** file (inlined CSS, no external requests) with progressive
disclosure: severity tally → ranked clusters → per-finding evidence and fix. Safe to attach to a PR
or open offline. Pure sink — it never mutates the report. The aesthetic is the Apple/macOS
clean look: generous whitespace, a green primary, semantic severity colors only.
"""

from __future__ import annotations

from html import escape

from bohrin.ir.schema import Severity
from bohrin.report.messages import Catalog, catalog
from bohrin.report.model import Cluster, Report

_SEV_COLOR: dict[Severity, str] = {
    Severity.HIGH: "#d7263d",
    Severity.MEDIUM: "#e8a13a",
    Severity.LOW: "#3a86c8",
    Severity.INFO: "#8a8f98",
}

_CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --green:#1a7f4b; --card:#fbfbfd; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1c1c1e; --fg:#f5f5f7; --muted:#a1a1a6; --line:#38383c; --green:#30d158; --card:#2c2c2e; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width: 860px; margin: 0 auto; padding: 40px 24px 80px; }
h1 { font-size: 22px; font-weight: 600; margin: 0; }
.sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
.score { display:flex; align-items:baseline; gap:14px; margin:28px 0 8px; }
.score .n { font-size: 52px; font-weight: 650; let-spacing:-1px; font-variant-numeric: tabular-nums; }
.score .of { color: var(--muted); font-size: 18px; }
.tally { display:flex; gap:14px; flex-wrap:wrap; margin: 6px 0 28px; font-size:13px; }
.chip { display:inline-flex; align-items:center; gap:6px; }
.dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
details { background:var(--card); border:1px solid var(--line); border-radius:12px;
  margin:10px 0; padding:0 16px; overflow:hidden; }
summary { cursor:pointer; list-style:none; padding:14px 0; display:flex; align-items:center; gap:12px; }
summary::-webkit-details-marker { display:none; }
.badge { font-size:11px; font-weight:650; letter-spacing:.03em; padding:3px 8px; border-radius:999px;
  color:#fff; white-space:nowrap; }
.title { font-weight:550; flex:1; }
.meta { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.body { padding: 4px 0 18px; border-top:1px solid var(--line); }
.body p { margin:12px 0; }
.label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.mono { font-family: ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px;
  background:rgba(127,127,127,.10); padding:2px 6px; border-radius:6px; }
.fix { border-left:3px solid var(--green); padding-left:12px; }
footer { color:var(--muted); font-size:12px; margin-top:40px; }
.clean { color:var(--green); font-weight:550; }
.headline { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; margin:0 0 22px; font-size:15px; }
.spark { display:block; width:100%; height:52px; margin:8px 0 2px;
  background:rgba(127,127,127,.06); border-radius:8px; }
.spark polyline { fill:none; stroke:var(--green); stroke-width:1.5;
  vector-effect:non-scaling-stroke; stroke-linejoin:round; }
.caption { color:var(--muted); font-size:11.5px; }
.fam { display:flex; gap:10px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-bottom:22px; }
"""

#: Sparkline viewBox. The polyline is drawn in these units and scaled by CSS, so the
#: SVG stays resolution-independent without any JavaScript.
_SPARK_W = 600
_SPARK_H = 100


def _sparkline_svg(series: list[float], label: str) -> str:
    """Render a bounded float series as an inline, dependency-free SVG sparkline.

    A constant series (the dead-dimension case) is deliberately drawn as a centered flat
    line rather than skipped — the flatness *is* the evidence.
    """
    if len(series) < 2:
        return ""
    lo, hi = min(series), max(series)
    span = hi - lo
    n = len(series)
    if span <= 0:  # constant signal → centered flat line
        ys = [_SPARK_H / 2] * n
    else:
        pad = _SPARK_H * 0.12
        ys = [(_SPARK_H - pad) - ((v - lo) / span) * (_SPARK_H - 2 * pad) for v in series]
    pts = " ".join(f"{i * _SPARK_W / (n - 1):.1f},{y:.1f}" for i, y in enumerate(ys))
    caption = f'<div class="caption">{escape(label)} · range [{lo:.4g}, {hi:.4g}]</div>' if label else ""
    return (
        f'<svg class="spark" viewBox="0 0 {_SPARK_W} {_SPARK_H}" preserveAspectRatio="none" '
        f'role="img" aria-label="{escape(label or "signal")}">'
        f'<polyline points="{pts}"/></svg>{caption}'
    )


class HtmlRenderer:
    """Renders a :class:`Report` to a self-contained HTML string. A :class:`Renderer`."""

    def render(self, report: Report, *, lang: str | None = None) -> str:
        cat = catalog(lang)
        d = report.dataset
        meta_bits = [escape(d.format), f"{d.n_episodes} episodes"]
        if d.embodiment:
            meta_bits.append(escape(d.embodiment))
        if d.control_hz:
            meta_bits.append(f"{d.control_hz:.0f} Hz")
        if d.cameras:
            meta_bits.append(f"{len(d.cameras)} cam")
        subtitle = " · ".join(meta_bits)

        counts = report.counts
        tally = "".join(
            f'<span class="chip"><span class="dot" style="background:{_SEV_COLOR[s]}"></span>'
            f"{counts[s]} {escape(cat.severity[s])}</span>"
            for s in (Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
            if counts[s]
        )
        body = (
            "".join(self._cluster(c, cat) for c in report.clusters)
            if report.clusters
            else f'<p class="clean">{escape(cat.no_findings)}</p>'
        )
        headline = self._headline(report, cat)
        families = report.family_counts()
        fam = "".join(f"<span>{escape(cat.family[f])} <b>{n}</b></span>" for f, n in families.items() if n)
        return (
            "<!doctype html><html lang='" + escape(cat.lang) + "'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>bohrin · {escape(d.uri)}</title><style>{_CSS}</style></head><body><div class='wrap'>"
            f"<h1>bohrin · {escape(d.uri)}</h1><div class='sub'>{subtitle}</div>"
            f"<div class='tally'>{tally or f'<span class=clean>{escape(cat.clean)}</span>'}</div>"
            f"{f'<div class=fam>{fam}</div>' if fam else ''}"
            f"{headline}"
            f"{body}"
            f"<footer>{len(report.detectors_run)} detectors · schema {report.schema_version} · "
            f"bohrin {report.bohrin_version}. {escape(cat.footer_local)}</footer>"
            "</div></body></html>"
        )

    def _headline(self, report: Report, cat: Catalog) -> str:
        """Depth 1 — the one sentence a skimming reader should leave with (docs/05 §5)."""
        blocking = [c for c in report.clusters if c.severity is Severity.HIGH]
        if not blocking:
            if not report.clusters:
                return ""
            return f'<p class="headline">{escape(cat.nothing_blocking)}</p>'
        titles = [c.title[0].lower() + c.title[1:] for c in blocking[:2]]
        what = " and ".join(escape(t) for t in titles)
        more = f" (plus {len(blocking) - 2} more)" if len(blocking) > 2 else ""
        return f'<p class="headline"><b>{escape(cat.things_to_fix)}:</b> {what}{more}.</p>'

    def _cluster(self, c: Cluster, cat: Catalog) -> str:
        color = _SEV_COLOR[c.severity]
        first = c.findings[0] if c.findings else None
        ev = first.evidence if first else None
        parts = [f"<p><span class='label'>{escape(cat.why_it_hurts)}</span><br>{escape(c.mechanism)}</p>"]

        if ev and ev.metrics:
            metrics = " · ".join(f"{escape(k)}=<span class='mono'>{v:.4g}</span>" for k, v in ev.metrics.items())
            parts.append(f"<p><span class='label'>{escape(cat.evidence)}</span><br>{metrics}</p>")
        if ev and ev.series:
            parts.append(_sparkline_svg(ev.series, ev.series_label))

        where = self._where(c)
        if where:
            parts.append(f"<p><span class='label'>{escape(cat.where)}</span><br>{where}</p>")
        parts.append(f"<p class='fix'><span class='label'>{escape(cat.fix)}</span><br>{escape(c.fix.text)}</p>")
        if first:
            p = first.provenance
            trail = " · ".join(escape(b) for b in (p.adapter, p.locator) if b)
            parts.append(f"<p class='caption'>{escape(cat.provenance)}: {trail}</p>")

        return (
            "<details><summary>"
            f"<span class='badge' style='background:{color}'>{escape(cat.severity[c.severity])}</span>"
            f"<span class='title'>{escape(c.title)}</span>"
            f"<span class='meta'>{c.blast_radius.n_episodes} eps · {escape(c.id)}</span>"
            f"</summary><div class='body'>{''.join(parts)}</div></details>"
        )

    def _where(self, c: Cluster) -> str:
        """The locus, rendered so a user can open exactly that spot in their data."""
        loc = c.findings[0].locus if c.findings else None
        if loc is None:
            return ""
        bits: list[str] = []
        if loc.dimension_names:
            bits.append("dims " + ", ".join(f"<span class='mono'>{escape(n)}</span>" for n in loc.dimension_names))
        elif loc.dimensions:
            bits.append("dims " + ", ".join(str(d) for d in loc.dimensions))
        if loc.camera:
            bits.append(f"camera <span class='mono'>{escape(loc.camera)}</span>")
        if loc.step_window:
            bits.append(f"steps {loc.step_window[0]}–{loc.step_window[1]}")
        if loc.episodes:
            shown = ", ".join(escape(e) for e in loc.episodes[:8])
            extra = f" +{len(loc.episodes) - 8} more" if len(loc.episodes) > 8 else ""
            bits.append(f"episodes {shown}{extra}")
        return " · ".join(bits)
