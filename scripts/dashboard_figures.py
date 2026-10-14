#!/usr/bin/env python3
"""Paper-ready copies of the dashboard's charts (M18 S6b, ai/EVIDENCE.md rule 4).

    from dashboard_figures import render_all
    figures = render_all(json.loads(Path("web/data/dashboard.json").read_text()), out_dir)

Every chart of `web/data/dashboard.json` that is not pending is drawn again with matplotlib from the
same spec the page draws (no other input: the values are those of the JSON), single-column width
(3.5 in), light theme, 8 pt text and nothing under 7 pt, as a vector PDF and a 300 dpi PNG. The colours
are the light tokens of web/css/app.css, so the paper and the app read alike. A pending chart is not
drawn: it has nothing to show but NOT MEASURED.

`check(figure)` re-opens both files and says whether they hold at that size: the PNG is 300 dpi and
1050 px wide, the PDF page is 3.5 in wide, no text is smaller than 7 pt and none leaves the page.
Nothing is measured here.
"""
from __future__ import annotations

import math
import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "css" / "app.css"
WIDTH_IN = 3.5      # one column of a two-column paper
DPI = 300
BASE_PT = 8.0
MIN_PT = 7.0
TOKENS = ("ink", "ink-2", "muted", "grid", "axis", "crit", "good", "s1", "s2", "s3", "s4")


def palette(css: Path = CSS) -> dict[str, str]:
    """The light theme's colour tokens: the first `:root` block of the stylesheet."""
    root = re.search(r":root\s*\{(.*?)\}", css.read_text(encoding="utf-8"), re.S)
    if not root:
        raise ValueError(f"{css} has no :root block")
    found = dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", root.group(1)))
    missing = [t for t in TOKENS if t not in found]
    if missing:
        raise ValueError(f"{css}: no light value for {missing}")
    return {t: found[t] for t in TOKENS}


def style(c: dict[str, str]) -> dict[str, Any]:
    return {
        "font.family": "DejaVu Sans", "font.size": BASE_PT, "axes.titlesize": BASE_PT,
        "axes.labelsize": BASE_PT, "xtick.labelsize": MIN_PT, "ytick.labelsize": MIN_PT,
        "legend.fontsize": MIN_PT, "axes.edgecolor": c["axis"], "axes.labelcolor": c["ink-2"],
        "xtick.color": c["ink-2"], "ytick.color": c["ink-2"], "text.color": c["ink"],
        "axes.grid": True, "grid.color": c["grid"], "grid.linewidth": 0.5, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
        "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": DPI, "figure.dpi": DPI,
        "legend.frameon": False, "lines.linewidth": 1.2,
    }


def colour(c: dict[str, str], slot: int | None) -> str:
    return c[f"s{((slot or 1) - 1) % 4 + 1}"]


def unit_label(unit: str | None) -> str:
    return (unit or "").strip()


def legend_below(ax: Any, handles: list | None = None, ncol: int = 2) -> None:
    kw = {"handles": handles} if handles else {}
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=ncol, handlelength=1.8,
              columnspacing=1.0, borderaxespad=0.0, **kw)


def ref_line(ax: Any, c: dict[str, str], ref: dict[str, Any] | None, *, vertical: bool = False) -> None:
    if not ref:
        return
    if vertical:
        ax.axvline(ref["value"], color=c["crit"], lw=0.8, ls=(0, (3, 2)))
        ax.annotate(ref["label"], xy=(ref["value"], 1.0), xycoords=("data", "axes fraction"),
                    xytext=(3, -2), textcoords="offset points", ha="left", va="top", color=c["crit"],
                    fontsize=MIN_PT)
    else:
        ax.axhline(ref["value"], color=c["crit"], lw=0.8, ls=(0, (3, 2)))
        ax.annotate(ref["label"], xy=(0.01, ref["value"]), xycoords=("axes fraction", "data"),
                    xytext=(0, 2), textcoords="offset points", ha="left", va="bottom", color=c["crit"],
                    fontsize=MIN_PT)


def grouped_bar(spec: dict[str, Any], c: dict[str, str]) -> Any:
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.6))
    cats, series = spec["categories"], spec["series"]
    width = 0.8 / len(series)
    for i, s in enumerate(series):
        xs = [k + (i - (len(series) - 1) / 2) * width for k in range(len(cats))]
        vals = [math.nan if v is None else v for v in s["values"]]
        bars = ax.bar(xs, vals, width=width * 0.92, color=colour(c, s.get("slot")), label=s["name"])
        if len(cats) * len(series) <= 4:  # few bars: each carries its value, a short one is read, not guessed
            ax.bar_label(bars, labels=["" if v is None else f"{v:g}" for v in s["values"]], padding=2,
                         fontsize=MIN_PT, color=c["ink-2"])
    ax.set_xticks(range(len(cats)))
    if len(cats) > 4:  # many categories side by side: slanted, so no two labels meet
        ax.set_xticklabels(cats, rotation=30, ha="right", rotation_mode="anchor")
    else:
        ax.set_xticklabels(["\n".join(textwrap.wrap(x, 12)) for x in cats])
    ax.grid(axis="x", visible=False)
    lo, hi = spec.get("yMin"), spec.get("yMax")
    if lo is not None or hi is not None:
        ax.set_ylim(lo, hi)
    ax.set_ylabel(unit_label(spec.get("unit")) or spec.get("yLabel", ""))
    ref_line(ax, c, spec.get("refLine"))
    if len(series) > 1:
        legend_below(ax, ncol=len(series))
    return fig


def cdf(spec: dict[str, Any], c: dict[str, str]) -> Any:
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.8))
    for s in spec["series"]:
        xs, ys = zip(*s["points"])
        ax.step(xs, ys, where="post", color=colour(c, s.get("slot")), ls=(0, (4, 2)) if s.get("dash") else "-",
                label=f"{s['name']} (n = {s['n']})" if "n" in s else s["name"])
    ax.set_xscale("log")
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(spec.get("xLabel", ""))
    ax.set_ylabel(spec.get("yLabel", ""))
    ref_line(ax, c, spec.get("refLine"), vertical=True)
    legend_below(ax, ncol=1)
    return fig


def line_log(spec: dict[str, Any], c: dict[str, str]) -> Any:
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.8))
    for s in spec["series"]:
        xs = [p[0] for p in s["points"]]
        ys = [math.nan if p[1] is None else p[1] for p in s["points"]]  # an UNSTABLE size stays a gap
        ax.plot(xs, ys, color=colour(c, s.get("slot")), marker="o", ms=2.5, label=s["name"])
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel(spec.get("xLabel", ""))
    ax.set_ylabel(f"time per call ({unit_label(spec.get('unit'))})" if spec.get("unit") else "")
    ref_line(ax, c, spec.get("refLine"))
    legend_below(ax, ncol=1)
    return fig


def histogram(spec: dict[str, Any], c: dict[str, str]) -> Any:
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.4))
    centers, counts = spec["binCenters"], spec["counts"]
    step = (centers[1] - centers[0]) if len(centers) > 1 else 1.0
    ax.bar(centers, counts, width=step * 0.92, color=c["s1"])
    band = spec.get("band")
    if band:
        for b in (-band, band):
            ax.axvline(b, color=c["crit"], lw=0.8, ls=(0, (3, 2)))
        ax.annotate(f"±{band:g}σ", xy=(band, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -2),
                    textcoords="offset points", ha="left", va="top", color=c["crit"], fontsize=MIN_PT)
    ax.grid(axis="x", visible=False)
    ax.set_xlabel(spec.get("xLabel", ""))
    ax.set_ylabel(spec.get("yLabel", ""))
    return fig


def matrix(spec: dict[str, Any], c: dict[str, str]) -> Any:
    """The scenario table: one outcome cell when the observed outcome is the expected one, both otherwise."""
    rows = spec["rows"]
    wrap = lambda s, n: "\n".join(textwrap.wrap(str(s), n, break_on_hyphens=False)) or "—"  # noqa: E731
    outcome = [r["observed"] if r["observed"] == r["expected"] else f"expected {r['expected']}, observed {r['observed']}"
               for r in rows]
    body = [[wrap(r["name"], 28), wrap(o, 21), "yes" if r["ok"] else "NO"] for r, o in zip(rows, outcome)]
    heights = [max(cell.count("\n") + 1 for cell in row) for row in body]
    total = sum(heights) + 1
    fig = plt.figure(figsize=(WIDTH_IN, 0.15 * total + 0.1))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.axis("off")
    t = ax.table(cellText=body, colLabels=["Scenario", "Outcome", "As expected"], cellLoc="left",
                 colLoc="left", colWidths=[0.47, 0.32, 0.21], bbox=(0, 0, 1, 1))
    t.auto_set_font_size(False)
    for (r, k), cell in t.get_celld().items():
        cell.set_fontsize(MIN_PT)
        cell.set_edgecolor(c["grid"])
        cell.set_linewidth(0.4)
        cell.set_height((1 if r == 0 else heights[r - 1]) / total)
        cell.PAD = 0.03
        if r == 0:
            cell.get_text().set_color(c["ink-2"])
            cell.get_text().set_fontweight("bold")
        elif k == 2:
            cell.get_text().set_color(c["good"] if rows[r - 1]["ok"] else c["crit"])
    return fig


KINDS = {"groupedBar": grouped_bar, "cdf": cdf, "lineLog": line_log, "histogram": histogram, "matrix": matrix}


def stem(module: str, spec_id: str) -> str:
    return f"{module}_dash_" + re.sub(r"[^a-z0-9]+", "_", spec_id.lower()).strip("_")


def text_sizes(fig: Any) -> tuple[float, bool]:
    """The smallest font size of any visible text, and whether every visible text lies on the page."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    texts = list(fig.findobj(matplotlib.text.Text))
    texts += [cell.get_text() for ax in fig.axes for t in ax.tables for cell in t.get_celld().values()]
    sizes = [t.get_fontsize() for t in texts if t.get_visible() and t.get_text().strip()]
    drawn, page = fig.get_tightbbox(renderer), fig.bbox  # only what is drawn: no tick outside the axes
    inside = (drawn.x0 * fig.dpi >= page.x0 - 1 and drawn.x1 * fig.dpi <= page.x1 + 1
              and drawn.y0 * fig.dpi >= page.y0 - 1 and drawn.y1 * fig.dpi <= page.y1 + 1)
    for ax in fig.axes:  # a table clips nothing: its text has to stay inside its cell
        for t in ax.tables:
            for cell in t.get_celld().values():
                box, text = cell.get_window_extent(renderer), cell.get_text().get_window_extent(renderer)
                if text.x0 < box.x0 - 1 or text.x1 > box.x1 + 1 or text.y0 < box.y0 - 1 or text.y1 > box.y1 + 1:
                    inside = False
    return min(sizes, default=math.inf), inside


def render(spec: dict[str, Any], out_dir: Path, c: dict[str, str], module: str = "M18") -> dict[str, Any]:
    with plt.rc_context(style(c)):
        fig = KINDS[spec["kind"]](spec, c)
        fig.set_size_inches(WIDTH_IN, fig.get_size_inches()[1])
        if spec["kind"] != "matrix":  # the table fills its own page
            fig.set_layout_engine("constrained")
        smallest, inside = text_sizes(fig)
        name = stem(module, spec["id"])
        meta = {"Title": spec["title"], "Creator": "scripts/dashboard_figures.py (V-cloak M18 S6b)"}
        fig.savefig(out_dir / f"{name}.pdf", metadata=meta)
        fig.savefig(out_dir / f"{name}.png", dpi=DPI)
        size = [round(float(v), 3) for v in fig.get_size_inches()]
        plt.close(fig)
    return {"id": spec["id"], "kind": spec["kind"], "stem": name, "size_in": size, "dpi": DPI,
            "min_font_pt": smallest, "text_on_page": bool(inside)}


def render_all(dashboard: dict[str, Any], out_dir: Path, module: str = "M18") -> list[dict[str, Any]]:
    c = palette()
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    for spec in dashboard["charts"]:
        if spec.get("pending"):
            continue
        if spec["kind"] not in KINDS:
            raise ValueError(f"chart {spec['id']}: no paper figure for kind {spec['kind']!r}")
        figures.append(render(spec, out_dir, c, module) | {"spec": spec})
    return figures


def png_info(path: Path) -> tuple[int, int, float | None]:
    """Width, height and dots per inch (from the pHYs chunk) of a PNG."""
    import struct

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    w, h = struct.unpack(">II", data[16:24])
    dpi = None
    at = data.find(b"pHYs")
    if at > 0:
        px, _, unit = struct.unpack(">IIB", data[at + 4:at + 13])
        dpi = px * 0.0254 if unit == 1 else None
    return int(w), int(h), dpi


def pdf_width_in(path: Path) -> float:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"{path.name} is not a PDF")
    box = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    if not box:
        raise ValueError(f"{path.name}: no MediaBox")
    return (float(box.group(3)) - float(box.group(1))) / 72.0


def check(fig: dict[str, Any], out_dir: Path) -> dict[str, bool]:
    """Whether the two files of `fig` open and hold at one-column size."""
    png, pdf = out_dir / f"{fig['stem']}.png", out_dir / f"{fig['stem']}.pdf"
    w, _, dpi = png_info(png)
    plt.imread(png)  # it opens
    return {
        f"{fig['id']}: PNG at 300 dpi, {round(WIDTH_IN * DPI)} px wide": dpi is not None and round(dpi) == DPI
        and abs(w - WIDTH_IN * DPI) <= 2,
        f"{fig['id']}: PDF page {WIDTH_IN} in wide": abs(pdf_width_in(pdf) - WIDTH_IN) < 0.01,
        f"{fig['id']}: no text under {MIN_PT:g} pt": fig["min_font_pt"] >= MIN_PT,
        f"{fig['id']}: every text on the page": fig["text_on_page"],
    }
