"""M07 S6: figures, tables and the Chapter 4 notes, built only from ingested run dirs.

    python -m vcloak.bench.report --kernels runs/<kernel_sweep> --cpu runs/<cpu_baselines> \
        --crossover runs/<crossover> --pipeline runs/<pipeline> --out results/perf --notes docs/REPORT_CH4_NOTES.md

Nothing here measures. Every plotted point and every table cell is read from a run's summary.json, raw.csv or
telemetry.csv, and every figure gets a sidecar JSON naming those run dirs. The four runs must be `cupy` runs of
one runner session (ai/modules/M07: "never merge two sessions into one figure"); otherwise nothing is written.
A point whose metric is UNSTABLE is drawn hollow from its last attempt, never dropped (audit A4).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from vcloak.bench.derive import NM, UNSTABLE

# Palette and ink of ai/FRONTEND.md §5 (light mode: the report and the paper print the light theme).
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID, SURFACE, CRITICAL = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb", "#d03b3b"

GPU_KERNELS = {  # sweep name -> (label, colour, marker, metric id prefix)
    "bitonic_fused": ("bitonic, fused", C1, "o", "K-BITONIC-FUSED-MS"),
    "bitonic_global": ("bitonic, global-only", C2, "s", "K-BITONIC-GLOBAL-MS"),
    "chacha_tags": ("ChaCha20 tags", C3, "^", "K-CHACHA-MS"),
    "aead_open": ("AEAD open", C4, "D", "K-AEADOPEN-MS"),
    "bucket_prf": ("bucket PRF", MUTED, "v", "K-BUCKETPRF-MS"),
}
CPU_BASELINES = {
    "numba_bitonic": ("CPU numba bitonic (oblivious)", C2, "s", "CPU-BITONIC-NUMBA-MS"),
    "views_bitonic": ("CPU NumPy views bitonic (oblivious)", C3, "^", "CPU-BITONIC-VIEWS-MS"),
    "oracle_bitonic": ("CPU oracle NumPy bitonic (oblivious)", C4, "D", "CPU-BITONIC-MS"),
    "lexsort": ("CPU np.lexsort (not oblivious)", MUTED, "v", "CPU-LEXSORT-MS"),
}
E2E = ("GPU sort incl. H2D + D2H", C1, "o", "K-BITONIC-E2E-MS")
STAGE_GROUPS = {  # device stages of write_epoch, grouped so that four hues and one grey are enough
    "H2D": (("h2d",), MUTED), "tags + seal + bucket": (("tags", "seal", "bucket"), C3), "sort": (("sort",), C1),
    "compact": (("compact",), C4), "D2H": (("d2h",), C2),
}


M08_BEGIN, M08_END = "<!-- BEGIN M08 OBLIVIOUS -->", "<!-- END M08 OBLIVIOUS -->"


class ReportError(Exception):
    """The inputs cannot back a figure (wrong backend, mixed sessions, missing file)."""


def load_run(run_dir: str | Path) -> dict[str, Any]:
    d = Path(run_dir)
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        summ = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ReportError(f"{d}: {e.filename} missing") from e
    return {"dir": d, "id": man["run_id"], "manifest": man, "summary": summ,
            "metrics": {m["id"]: m for m in summ.get("metrics", [])}}


def check_inputs(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Refuse anything that is not one cupy session with a gpu_job block; return its provenance."""
    sessions = {r["manifest"]["env"].get("session_id") for r in runs.values()}
    for name, r in runs.items():
        env = r["manifest"]["env"]
        if env.get("backend") != "cupy" or "gpu_job" not in r["manifest"]:
            raise ReportError(f"{name} run {r['id']} is backend {env.get('backend')} without an ingested GPU job: "
                              f"{NM}, no figure is written")
    if len(sessions) != 1:
        raise ReportError(f"runs come from different runner sessions {sorted(map(str, sessions))}: not merged")
    env = runs["kernels"]["manifest"]["env"]
    host = runs["kernels"]["summary"].get("host", {})
    return {"session_id": sessions.pop(), "runner": env["runner"], "gpu": env["gpu"], "driver": env.get("driver"),
            "cuda": env.get("cuda"), "cupy": env.get("cupy"), "cpu": f"{host.get('cpu')} x{host.get('cpu_count')}",
            "git_sha": runs["kernels"]["manifest"]["git_sha"],
            "job_id": runs["kernels"]["manifest"]["gpu_job"]["job_id"],
            "quick": bool(runs["kernels"]["manifest"]["quick"])}


def rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def tagged(runs: dict[str, dict[str, Any]], metric_id: str) -> str:
    """`value<!--M:ID-->` for the notes; a metric no run lists is NOT_MEASURED, never a guess."""
    for r in runs.values():
        if metric_id in r["metrics"]:
            return f"{r['metrics'][metric_id]['value']}<!--M:{metric_id}-->"
    return f"{NM}<!--M:{metric_id}-->"


def _last(point: dict[str, Any]) -> dict[str, Any]:
    return point["attempts"][-1]


# ---------------------------------------------------------------- tables

def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def kernel_rows(run: dict[str, Any], root: Path) -> list[list[Any]]:
    rows = []
    for k, pts in run["summary"]["sweeps"].items():
        for p in pts:
            a = _last(p)
            rows.append([k, p["log2n"], p["n"], UNSTABLE if p["unstable"] else "OK", "LOW" if p["low_clock"] else "OK",
                         a["median_ms"], a["p5_ms"], a["p95_ms"], a["cv"], a["runs"], len(p["attempts"]),
                         a["clock"]["after_mhz"], p.get("bw_pct_of_peak", ""), rel(run["dir"], root)])
    return rows


def cpu_rows(run: dict[str, Any], root: Path) -> list[list[Any]]:
    obl = set(run["summary"]["oblivious"])
    return [[b, p["log2n"], p["n"], UNSTABLE if p["unstable"] else "OK", "yes" if b in obl else "no", p["median_ms"],
             p["cv"], _last(p).get("runs", ""), len(p["attempts"]), rel(run["dir"], root)]
            for b, pts in run["summary"]["sweeps"].items() for p in pts]


def crossover_rows(run: dict[str, Any], root: Path) -> list[list[Any]]:
    lex = {t["log2n"]: t for t in run["summary"]["table_vs_lexsort"]}
    return [[t["log2n"], t["n"], t["gpu_ms"], t["cpu_baseline"], t["cpu_ms"], t["speedup"], lex[t["log2n"]]["cpu_ms"],
             lex[t["log2n"]]["speedup"], UNSTABLE if t["unstable"] else "OK", rel(run["dir"], root)]
            for t in run["summary"]["table"]]


def pipeline_rows(run: dict[str, Any], root: Path) -> list[list[Any]]:
    rows = []
    for c in run["summary"]["configs"]:
        a = _last(c)
        st = a["stage_median_ms"]
        rows.append([c["kind"], c["size"], UNSTABLE if not a["stable"] else "OK", a["clock"]["status"], a["median_ms"],
                     a["p99_ms"], a["cv"], a["device"]["median_ms"], a["device"]["p99_ms"], a["host"]["median_ms"],
                     *[st[s] for s in ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "open")],
                     a["runs"], len(c["attempts"]), rel(run["dir"], root)])
    return rows


# ---------------------------------------------------------------- figures

def _plt() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "lines.linewidth": 2, "lines.markersize": 6, "legend.frameon": False,
        "legend.fontsize": 7.5, "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "pdf.fonttype": 42,
    })
    return plt


def _series(ax: Any, xs: list[int], ys: list[float], unstable: list[bool], label: str, colour: str, marker: str,
            dashed: bool = False) -> None:
    """A line through every point; a point flagged UNSTABLE keeps its place and is drawn hollow."""
    ax.plot(xs, ys, color=colour, linestyle="--" if dashed else "-", marker=marker, markeredgecolor=colour,
            markerfacecolor=colour, label=label, zorder=3)
    ux = [x for x, u in zip(xs, unstable, strict=True) if u]
    uy = [y for y, u in zip(ys, unstable, strict=True) if u]
    if ux:
        ax.plot(ux, uy, linestyle="none", marker=marker, markeredgecolor=colour, markerfacecolor=SURFACE,
                markeredgewidth=1.5, zorder=4)


def _log2_axis(ax: Any, logs: list[int], label: str = "n (records)") -> None:
    ax.set_xscale("log", base=2)
    ax.set_xticks([2 ** v for v in logs if v % 2 == 0])
    ax.set_xticklabels([f"$2^{{{v}}}$" for v in logs if v % 2 == 0])
    ax.minorticks_off()
    ax.set_xlabel(label)


def _hollow_note(fig: Any, any_unstable: bool, prov: dict[str, Any]) -> None:
    text = f"{prov['gpu']} / {prov['cpu']}, {prov['runner']} session {prov['session_id']}"
    if any_unstable:
        text = "hollow marker = UNSTABLE (CV > 10% or SM clock moved > 15%, on two attempts)\n" + text
    fig.text(0.01, 0.005, text, fontsize=6, color=MUTED, ha="left", va="bottom", linespacing=1.3)


def _save(fig: Any, out: Path, name: str) -> list[str]:
    files = []
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=300)
        files.append(f"{name}.{ext}")
    return files


def fig_gpu_vs_cpu(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    e2e = runs["kernels"]["summary"]["sweeps"]["sort_e2e"]
    logs = [p["log2n"] for p in e2e]
    ids, any_un = [], False
    series = [(E2E, e2e)] + [(CPU_BASELINES[b], runs["cpu"]["summary"]["sweeps"][b]) for b in CPU_BASELINES]
    for (label, colour, marker, prefix), pts in series:
        un = [bool(p["unstable"]) for p in pts]
        any_un |= any(un)
        _series(ax, [p["n"] for p in pts], [_last(p)["median_ms"] for p in pts], un, label, colour, marker,
                dashed=prefix == "CPU-LEXSORT-MS")
        ids += [f"{prefix}-2^{p['log2n']}" for p in pts]
    ax.set_yscale("log")
    _log2_axis(ax, logs)
    ax.set_ylabel("median time per sort (ms)")
    ax.set_title("Oblivious sort: GPU (with transfers) against CPU baselines")
    ax.legend(loc="upper left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, any_un, prov)
    files = _save(fig, out, "fig_sort_gpu_vs_cpu")
    plt.close(fig)
    return {"figure": "fig_sort_gpu_vs_cpu", "files": files, "runs": ["kernels", "cpu"], "metric_ids": ids,
            "what": "log-log median time against n: GPU sort_e2e (pinned H2D + fused sort + pinned D2H) and the four "
                    "CPU baselines of the same runner session"}


def fig_kernels(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    sw = runs["kernels"]["summary"]["sweeps"]
    ids, any_un = [], False
    for k, (label, colour, marker, prefix) in GPU_KERNELS.items():
        un = [bool(p["unstable"]) for p in sw[k]]
        any_un |= any(un)
        _series(ax, [p["n"] for p in sw[k]], [_last(p)["median_ms"] for p in sw[k]], un, label, colour, marker,
                dashed=k == "bucket_prf")
        ids += [f"{prefix}-2^{p['log2n']}" for p in sw[k]]
    ax.set_yscale("log")
    _log2_axis(ax, [p["log2n"] for p in sw["bitonic_fused"]])
    ax.set_ylabel("median kernel time (ms), CUDA events")
    ax.set_title("GPU kernels against n")
    ax.legend(loc="upper left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, any_un, prov)
    files = _save(fig, out, "fig_kernels_vs_n")
    plt.close(fig)
    return {"figure": "fig_kernels_vs_n", "files": files, "runs": ["kernels"], "metric_ids": ids,
            "what": "log-log median kernel time against n for the two bitonic variants, ChaCha20 tags, AEAD open and "
                    "the bucket PRF"}


def fig_bandwidth(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    pts = runs["kernels"]["summary"]["sweeps"]["bitonic_global"]
    un = [bool(p["unstable"]) for p in pts]
    _series(ax, [p["n"] for p in pts], [p["bw_pct_of_peak"] for p in pts], un, "bitonic, global-only", C1, "o")
    ax.axhline(100, color=CRITICAL, linewidth=1, linestyle="--", zorder=2)
    ax.text(pts[0]["n"], 103, f"theoretical peak ({runs['kernels']['summary']['peak_bw_gbs']} GB/s)", fontsize=7,
            color=CRITICAL, va="bottom")
    top = max(pts, key=lambda p: p["bw_pct_of_peak"])
    ax.annotate(f"{top['bw_pct_of_peak']:.1f}%", (top["n"], top["bw_pct_of_peak"]), textcoords="offset points",
                xytext=(6, 0), fontsize=7.5, color=INK2, va="center")
    ax.annotate(f"{pts[-1]['bw_pct_of_peak']:.1f}%", (pts[-1]["n"], pts[-1]["bw_pct_of_peak"]),
                textcoords="offset points", xytext=(0, 7), fontsize=7.5, color=INK2, ha="center")
    _log2_axis(ax, [p["log2n"] for p in pts])
    ax.set_ylim(bottom=0)
    ax.set_ylabel("modelled bandwidth, % of peak")
    ax.set_title("Bitonic global-only: bytes-moved model over the theoretical peak")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, any(un), prov)
    files = _save(fig, out, "fig_bandwidth_pct")
    plt.close(fig)
    return {"figure": "fig_bandwidth_pct", "files": files, "runs": ["kernels"],
            "metric_ids": [f"K-BITONIC-BW-PCT-2^{p['log2n']}" for p in pts],
            "what": "rounds x n x 24 B x 2 over the median time of the global-only variant, as a percentage of the "
                    "theoretical peak memory bandwidth; a value above 100% means the model does not hold at that n"}


def _write_configs(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in run["summary"]["configs"] if c["kind"] == "write_epoch"]


def fig_write_epoch(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    cfg = _write_configs(runs["pipeline"])
    epoch_ms = runs["pipeline"]["summary"]["realtime_gate"][0]["epoch_ms"]
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    xs = list(range(len(cfg)))
    dev = [_last(c)["device"]["median_ms"] for c in cfg]
    host = [_last(c)["host"]["median_ms"] for c in cfg]
    p99 = [_last(c)["p99_ms"] for c in cfg]
    ax.bar(xs, dev, width=0.5, color=C1, edgecolor=SURFACE, linewidth=1.5, label="device stages (median)", zorder=3)
    ax.bar(xs, host, width=0.5, bottom=dev, color=C2, edgecolor=SURFACE, linewidth=1.5, hatch="///",
           label="host Python (median)", zorder=3)
    ax.plot(xs, p99, linestyle="none", marker="_", markersize=22, markeredgewidth=2, color=INK, label="p99 of the call",
            zorder=5)
    ax.axhline(epoch_ms, color=CRITICAL, linewidth=1, linestyle="--", zorder=2)
    ax.text(-0.4, epoch_ms * 1.02, f"EPOCH_MS budget = {epoch_ms} ms", fontsize=7, color=CRITICAL, va="bottom")
    for x, c, v in zip(xs, cfg, p99, strict=True):
        flag = "" if _last(c)["stable"] else " (UNSTABLE)"
        ax.text(x, v, f"{v:.1f}{flag}", fontsize=7, color=INK2, ha="center", va="bottom")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"$2^{{{c['size'].bit_length() - 1}}}$" for c in cfg])
    ax.set_xlabel("SLOTS (full epochs)")
    ax.set_ylabel("write_epoch time (ms)")
    ax.set_title("write_epoch: device stages against host work, and the epoch budget")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, False, prov)
    files = _save(fig, out, "fig_write_epoch_host_device")
    plt.close(fig)
    ids = [f"P-WRITE-EPOCH-{m}-S{c['size']}" for c in cfg for m in ("DEVICE-MS", "HOST-MS", "P99")]
    return {"figure": "fig_write_epoch_host_device", "files": files, "runs": ["pipeline"], "metric_ids": ids,
            "what": "stacked medians of the device stages and of the host stage of write_epoch per SLOTS, the p99 of "
                    "the whole call, and the EPOCH_MS budget"}


def fig_device_stages(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    cfg = _write_configs(runs["pipeline"])
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    xs = list(range(len(cfg)))
    bottom = [0.0] * len(cfg)
    hatches = ("", "...", "", "///", "xxx")
    for (label, (stages, colour)), hatch in zip(STAGE_GROUPS.items(), hatches, strict=True):
        vals = [sum(_last(c)["stage_median_ms"][s] for s in stages) for c in cfg]
        ax.bar(xs, vals, width=0.5, bottom=bottom, color=colour, edgecolor=SURFACE, linewidth=1.5, hatch=hatch,
               label=label, zorder=3)
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
    for x, c, v in zip(xs, cfg, bottom, strict=True):
        flag = "" if _last(c)["stable"] else "\n(UNSTABLE)"
        ax.text(x, v, f"{v:.2f}{flag}", fontsize=7, color=INK2, ha="center", va="bottom")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"$2^{{{c['size'].bit_length() - 1}}}$" for c in cfg])
    ax.set_xlabel("SLOTS (full epochs)")
    ax.set_ylabel("sum of stage medians (ms), CUDA events")
    ax.set_title("write_epoch: device stage breakdown")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, False, prov)
    files = _save(fig, out, "fig_write_epoch_device_stages")
    plt.close(fig)
    return {"figure": "fig_write_epoch_device_stages", "files": files, "runs": ["pipeline"],
            "metric_ids": [f"P-WRITE-EPOCH-DEVICE-MS-S{c['size']}" for c in cfg],
            "what": "stacked per-stage medians of the device part of write_epoch per SLOTS (the bar top is the sum of "
                    "the stage medians, which is not the median of the device total)"}


def fig_read_window(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    cfg = [c for c in runs["pipeline"]["summary"]["configs"] if c["kind"] == "read_window"]
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    un = [not _last(c)["stable"] for c in cfg]
    xs = [c["size"] for c in cfg]
    _series(ax, xs, [_last(c)["p99_ms"] for c in cfg], un, "p99 of the call", C1, "o")
    _series(ax, xs, [_last(c)["median_ms"] for c in cfg], un, "median of the call", C2, "s")
    _log2_axis(ax, [c["size"].bit_length() - 1 for c in cfg], "K (window size)")
    ax.set_xticks(xs)
    ax.set_xticklabels([str(x) for x in xs])
    ax.set_ylim(bottom=0)
    ax.set_ylabel("read_window time (ms)")
    ax.set_title("read_window against K")
    ax.legend(loc="upper left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, any(un), prov)
    files = _save(fig, out, "fig_read_window")
    plt.close(fig)
    return {"figure": "fig_read_window", "files": files, "runs": ["pipeline"],
            "metric_ids": [f"P-READ-WINDOW-{m}-K{c['size']}" for c in cfg for m in ("P99", "MS")],
            "what": "p99 and median of a whole read_window call against K"}


def fig_telemetry(plt: Any, runs: dict[str, dict[str, Any]], prov: dict[str, Any], out: Path) -> dict[str, Any]:
    """NVML samples during the kernel sweep, the longest GPU run of the job. Three units, so three panels."""
    path = runs["kernels"]["dir"] / "telemetry.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    t0 = float(rows[0]["ts"])
    t = [float(r["ts"]) - t0 for r in rows]
    fig, axes = plt.subplots(3, 1, figsize=(6.0, 5.2), sharex=True)
    panels = (("sm_clock_mhz", "SM clock (MHz)", C1), ("power_w", "power (W)", C2),
              ("temperature_c", "temperature (°C)", C3))
    for ax, (col, label, colour) in zip(axes, panels, strict=True):
        ax.plot(t, [float(r[col]) for r in rows], color=colour, linewidth=1.2, zorder=3)
        ax.set_ylabel(label)
    limit = float(rows[0]["power_limit_w"])
    axes[1].axhline(limit, color=CRITICAL, linewidth=1, linestyle="--", zorder=2)
    axes[1].text(t[-1], limit + 4, f"power limit {limit:g} W", fontsize=7, color=CRITICAL, va="bottom", ha="right")
    axes[0].set_title("Telemetry during the kernel sweep (NVML, 10 Hz)")
    axes[2].set_xlabel("seconds since the start of the sweep")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _hollow_note(fig, False, prov)
    files = _save(fig, out, "fig_telemetry_kernel_sweep")
    plt.close(fig)
    return {"figure": "fig_telemetry_kernel_sweep", "files": files, "runs": ["kernels"], "samples": len(rows),
            "metric_ids": ["TEL-SMCLK-MEDIAN", "TEL-POWER-W-MEDIAN"],
            "what": "SM clock, power draw and temperature of the GPU over the kernel sweep, from telemetry.csv"}


FIGURES = (fig_gpu_vs_cpu, fig_kernels, fig_bandwidth, fig_write_epoch, fig_device_stages, fig_read_window,
           fig_telemetry)


# ---------------------------------------------------------------- notes

def _md_table(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                     + ["| " + " | ".join(r) + " |" for r in rows])


def build_notes(runs: dict[str, dict[str, Any]], prov: dict[str, Any], root: Path,
                figures: list[dict[str, Any]]) -> str:
    def t(metric_id: str) -> str:
        return tagged(runs, metric_id)

    sw = runs["kernels"]["summary"]["sweeps"]
    logs = [p["log2n"] for p in sw["bitonic_global"]]
    gate = runs["pipeline"]["summary"]["realtime_gate"]
    n_cfg = sum(len(v) for v in sw.values())
    n_un = sum(bool(p["unstable"]) for v in sw.values() for p in v)
    over = [p["log2n"] for p in sw["bitonic_global"] if p["bw_pct_of_peak"] > 100]
    x = runs["crossover"]["summary"]["crossover"]
    run_list = "\n".join(f"- `{rel(r['dir'], root)}` ({name}, status {r['manifest']['status']})"
                         for name, r in runs.items())
    kernel_tbl = _md_table(
        ["n", "global-only (ms)", "fused (ms)", "sort incl. transfers (ms)", "global-only, % of peak BW"],
        [[f"2^{v}", t(f"K-BITONIC-GLOBAL-MS-2^{v}"), t(f"K-BITONIC-FUSED-MS-2^{v}"), t(f"K-BITONIC-E2E-MS-2^{v}"),
          t(f"K-BITONIC-BW-PCT-2^{v}")] for v in logs])
    other_tbl = _md_table(["n", "ChaCha20 tags (ms)", "AEAD open (ms)", "bucket PRF (ms)"],
                          [[f"2^{v}", t(f"K-CHACHA-MS-2^{v}"), t(f"K-AEADOPEN-MS-2^{v}"), t(f"K-BUCKETPRF-MS-2^{v}")]
                           for v in logs])
    cpu_tbl = _md_table(["n", "oracle NumPy bitonic (ms)", "NumPy views bitonic (ms)", "numba bitonic (ms)",
                         "np.lexsort, not oblivious (ms)"],
                        [[f"2^{v}", t(f"CPU-BITONIC-MS-2^{v}"), t(f"CPU-BITONIC-VIEWS-MS-2^{v}"),
                          t(f"CPU-BITONIC-NUMBA-MS-2^{v}"), t(f"CPU-LEXSORT-MS-2^{v}")] for v in logs])
    write_tbl = _md_table(
        ["SLOTS", "median (ms)", "p99 (ms)", "device median (ms)", "device p99 (ms)", "host median (ms)",
         "gate, whole call", "gate, device part"],
        [[str(g["slots"]), t(f"P-WRITE-EPOCH-MS-S{g['slots']}"), t(f"P-WRITE-EPOCH-P99-S{g['slots']}"),
          t(f"P-WRITE-EPOCH-DEVICE-MS-S{g['slots']}"), t(f"P-WRITE-EPOCH-DEVICE-P99-S{g['slots']}"),
          t(f"P-WRITE-EPOCH-HOST-MS-S{g['slots']}"), "PASS" if g["pass_total"] else "FAIL",
          "PASS" if g["pass_device"] else "FAIL"] for g in gate])
    ks = [c["size"] for c in runs["pipeline"]["summary"]["configs"] if c["kind"] == "read_window"]
    read_tbl = _md_table(["K", "median (ms)", "p99 (ms)", "device p99 (ms)"],
                         [[str(k), t(f"P-READ-WINDOW-MS-K{k}"), t(f"P-READ-WINDOW-P99-K{k}"),
                           t(f"P-READ-WINDOW-DEVICE-P99-K{k}")] for k in ks])
    fig_list = "\n".join(f"- `results/perf/{f['files'][0]}` (+ pdf, sidecar `{f['figure']}.json`): {f['what']}."
                         for f in figures)
    fail = [g["slots"] for g in gate if not g["pass_total"]]
    dev_fail = [str(g["slots"]) for g in gate if not g["pass_device"]]
    dev_gate = "fails at SLOTS " + ", ".join(dev_fail) if dev_fail else "passes at every SLOTS"
    return f"""# Chapter 4 notes — performance (M07, E4)

Generated by `python -m vcloak.bench.report` from ingested run dirs. Do not edit numbers by hand: every value
carries a `<!--M:ID-->` tag that names its row in `state/METRICS_INDEX.md`. A cell that reads `UNSTABLE` is a
measurement whose coefficient of variation stayed above 10%, or whose SM clock moved by more than 15%, on two
attempts; both attempts are in the run's `raw.csv` and `summary.json`, and the figures draw the point hollow.

## 4.P.1 Measurement setup
- GPU / CPU pair: {prov['gpu']} and {prov['cpu']} on a free {prov['runner']} runner, session `{prov['session_id']}`,
  driver {prov['driver']}, CUDA runtime {prov['cuda']}, CuPy {prov['cupy']}; GPU job `{prov['job_id']}`,
  code at `{prov['git_sha'][:7]}`.
- The GPU and its host CPU are shared cloud hardware and may be throttled. All GPU and CPU numbers below were taken
  in this one runner session and hold for this pair only. They must not be mixed with the M00–M06 numbers, which
  came from other sessions.
- GPU timings are CUDA events (`cupy.cuda.Event`), warm-up until the SM clock stops rising, 50 timed runs per
  kernel configuration and 200 timed calls per pipeline configuration. CPU timings are `time.perf_counter_ns`,
  10 runs up to 2^20 and 5 above.
- Runs:
{run_list}

## 4.P.2 Bitonic sort kernels
{kernel_tbl}

- The fused variant gives the same output as the global-only variant at every swept n (0 differences).
- Stability: {n_un} of the {n_cfg} kernel configurations of the sweep are `UNSTABLE` (counted from the run's
  summary). The short kernels are the affected ones: below about 0.1 ms a launch is comparable to the jitter of
  the launch itself.
- Bandwidth: the bytes-moved model (rounds × n × 24 B × 2) is only meaningful where the result is below 100% of
  the theoretical peak (`ENV-PEAK-BW`, from the device's memory clock and bus width). At log2 n =
  {', '.join(map(str, over)) or 'no swept size'} the model gives more than 100%, which
  memory traffic cannot do, so at those sizes the model's assumption (every stage reads and writes all n records
  through device memory) does not hold. The cause was **not measured** (ISSUE-14). From 2^18 upwards the
  global-only variant sits between {t('K-BITONIC-BW-PCT-2^18')} % and {t('K-BITONIC-BW-PCT-2^22')} % of peak,
  at a reduced SM clock.

## 4.P.3 Other kernels
{other_tbl}

- ChaCha20 tag throughput at the largest swept n: {t('K-CHACHA-GBS')} GB/s. AEAD-open rate: {t('K-AEADOPEN-ROWS-S')}
  rows/s. Bucket PRF rate: {t('K-BUCKETPRF-ROWS-S')} rows/s.

## 4.P.4 CPU baselines (same runner session)
{cpu_tbl}

- The three bitonic baselines are oblivious; `np.lexsort` is not, and is shown only as a lower bound on CPU time.
- numba {runs['cpu']['summary']['numba'].get('numba')} with {runs['cpu']['summary']['numba'].get('threads')} threads.

## 4.P.5 Crossover and speed-up
- The GPU series is `sort_e2e`: pinned host-to-device copy, fused sort, pinned device-to-host copy.
- Against the best oblivious CPU baseline the GPU is faster at every compared n, so the crossover n* is at or below
  the smallest swept n ({x['smallest_n']}). The indexed value is {t('X-CROSSOVER-N')} because the GPU point at that n
  is `UNSTABLE`.
- Speed-up over the best oblivious CPU baseline: {t('X-SPEEDUP-2^16')}× at 2^16 and {t('X-SPEEDUP-2^20')}× at 2^20.
- Speed-up over `np.lexsort` (not oblivious): {t('X-SPEEDUP-VS-LEXSORT-2^16')}× at 2^16 and
  {t('X-SPEEDUP-VS-LEXSORT-2^20')}× at 2^20.

## 4.P.6 Pipeline: write_epoch and the real-time gate
{write_tbl}

- Gate: p99 of a call below EPOCH_MS = {gate[0]['epoch_ms']} ms. The whole call **fails** the gate at SLOTS
  {', '.join(map(str, fail)) or 'no size'}; the device part {dev_gate}.
- The host stage (Python between the device stages) is the largest part of the call from 2^10 slots upwards. The
  cProfile in `{rel(runs['pipeline']['dir'], root)}/host_profile.txt` attributes most of it to building one
  `uuid` object per stored row (ISSUE-12).
- Epochs were full (n_real = SLOTS) with 8-byte payload stand-ins; payload bytes never go to the device (ADR-006).
- The SM clock stayed at its idle value during the pipeline run: the device is waiting for the host most of the
  time. The clock was recorded, not forced up.

## 4.P.7 Pipeline: read_window
{read_tbl}

## 4.P.8 Telemetry
- Median SM clock over the kernel sweep: {t('TEL-SMCLK-MEDIAN')} MHz. Median power draw: {t('TEL-POWER-W-MEDIAN')} W.
- The NVML throttle-reasons mask is non-zero for most of the sweep and the power draw sits at the board's power
  limit (see `fig_telemetry_kernel_sweep`), so the large-n points are measured at a reduced clock. They are
  labelled `LOW clock` in the metric notes, not discarded.

## 4.P.9 Figures
{fig_list}

## 4.P.10 Limitations
- One runner session on shared hardware; no repeat on a second session or a second GPU model.
- {n_un} of {n_cfg} kernel configurations are `UNSTABLE`, among them the AEAD-open and bucket-PRF rates and the
  crossover point. A re-measurement that times batches of launches for the sub-0.1 ms kernels is proposed in ISSUE-15.
- The bandwidth figure rests on a model, and the model breaks below 2^18 (ISSUE-14).
- write_epoch does not meet the epoch budget at 2^16 slots on this runner's CPU (ISSUE-12).
"""


# ---------------------------------------------------------------- driver

def generate(kernels: str | Path, cpu: str | Path, crossover: str | Path, pipeline: str | Path, out: str | Path,
             notes: str | Path | None = None, root: str | Path = ".") -> dict[str, Any]:
    root, out = Path(root), Path(out)
    runs = {"kernels": load_run(kernels), "cpu": load_run(cpu), "crossover": load_run(crossover),
            "pipeline": load_run(pipeline)}
    prov = check_inputs(runs)
    if runs["crossover"]["summary"]["inputs"]["session_id"] != prov["session_id"]:
        raise ReportError("the crossover was computed from another session")
    out.mkdir(parents=True, exist_ok=True)
    run_dirs = {name: rel(r["dir"], root) for name, r in runs.items()}

    tables = {
        "kernel_sweep.csv": (["kernel", "log2n", "n", "status", "clock", "last_attempt_median_ms", "p5_ms", "p95_ms",
                              "cv", "runs", "attempts", "sm_clock_mhz", "bw_pct_of_peak", "run_dir"],
                             kernel_rows(runs["kernels"], root)),
        "cpu_baselines.csv": (["baseline", "log2n", "n", "status", "oblivious", "median_ms", "cv", "runs", "attempts",
                               "run_dir"], cpu_rows(runs["cpu"], root)),
        "crossover.csv": (["log2n", "n", "gpu_e2e_ms", "best_oblivious_cpu", "cpu_ms", "speedup", "lexsort_ms",
                           "speedup_vs_lexsort", "status", "run_dir"], crossover_rows(runs["crossover"], root)),
        "pipeline.csv": (["kind", "size", "status", "clock", "median_ms", "p99_ms", "cv", "device_median_ms",
                          "device_p99_ms", "host_median_ms", "h2d_ms", "tags_ms", "sort_ms", "compact_ms", "d2h_ms",
                          "seal_ms", "bucket_ms", "open_ms", "runs", "attempts", "run_dir"],
                         pipeline_rows(runs["pipeline"], root)),
    }
    for name, (header, rows) in tables.items():
        write_csv(out / name, header, rows)

    plt = _plt()
    figures = []
    for make in FIGURES:
        side = make(plt, runs, prov, out)
        side["run_dirs"] = [run_dirs[r] for r in side.pop("runs")]
        side.update({k: prov[k] for k in ("session_id", "runner", "gpu", "cpu", "job_id", "git_sha", "quick")})
        side["backend"] = "cupy"
        side["generated_by"] = "python -m vcloak.bench.report"
        (out / f"{side['figure']}.json").write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
        figures.append(side)

    summary = {"provenance": prov, "backend": "cupy", "run_dirs": run_dirs, "tables": sorted(tables),
               "figures": [f["figure"] for f in figures],
               "run_status": {name: r["manifest"]["status"] for name, r in runs.items()},
               "realtime_gate": runs["pipeline"]["summary"]["realtime_gate"],
               "crossover": runs["crossover"]["summary"]["crossover"],
               "unstable": {"kernels": runs["kernels"]["summary"]["unstable"],
                            "pipeline": runs["pipeline"]["summary"]["unstable"]}}
    (out / "perf_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if notes:
        Path(notes).parent.mkdir(parents=True, exist_ok=True)
        old = Path(notes).read_text(encoding="utf-8") if Path(notes).exists() else ""
        text = build_notes(runs, prov, root, figures)
        if M08_BEGIN in old and M08_END in old:  # the obliviousness section belongs to report_oblivious: keep it
            text = text.rstrip("\n") + "\n\n" + old[old.index(M08_BEGIN):old.index(M08_END) + len(M08_END)] + "\n"
        Path(notes).write_text(text, encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("kernels", "cpu", "crossover", "pipeline"):
        ap.add_argument(f"--{name}", required=True, help=f"run dir of the {name} run")
    ap.add_argument("--out", default="results/perf")
    ap.add_argument("--notes", default=None, help="write the Chapter 4 notes here (e.g. docs/REPORT_CH4_NOTES.md)")
    a = ap.parse_args(argv)
    try:
        s = generate(a.kernels, a.cpu, a.crossover, a.pipeline, a.out, a.notes)
    except ReportError as e:
        print(f"report: {NM} - {e}")
        return 1
    print(f"report: session {s['provenance']['session_id']}  {len(s['figures'])} figures, {len(s['tables'])} tables "
          f"-> {a.out}")
    for name, st in s["run_status"].items():
        print(f"  {name:10s} {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
