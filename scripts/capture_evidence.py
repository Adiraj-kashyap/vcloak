#!/usr/bin/env python3
"""Capture the app's views into evidence/screens/ and index them with their provenance (ai/EVIDENCE.md).

    python scripts/capture_evidence.py --module M13 [--run runs/<dir>] [--views chat,dashboard] [--tag S5b]
                                       [--terminal "runs/<dir>/pytest.txt=what it shows"] [--owner NAME]

It serves the app in this process (`vcloak serve --dev --compare --sessions --store sqlite`, the backend
this machine has), opens it in the installed Chrome or Edge (scripts/headless.py) at 1440x900 and
photographs, full page and in both themes:

- the chat with the server-view panel and "reveal true order" on, once in V-cloak mode and once in
  baseline mode: the same short conversation, sent by the two panes of the page while the script runs;
- the dashboard, the experiments, the logs and the architecture view, as the page shows them.

The PNGs go to `evidence/screens/<Mxx>_<view>_<light|dark>_<YYYYMMDD>.png` and one row per file goes to
`evidence/INDEX.md`, with the run directory, its git sha and the data state. The data state is read from
the page, never assumed: a view that shows the bundled sample data is `seed`, whatever the server is.
A second run on the same day overwrites the files and replaces the rows; a row whose file name changed
has its old file moved to `evidence/superseded/`. Nothing is written to `evidence/` unless every check
passed. `--terminal` copies a file of a run directory to `evidence/terminal/` and indexes it under the
git sha of that run.

Nothing is measured here: the pictures show what is stored, not how fast.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

WIDTH, HEIGHT = 1440, 900
THEMES = ("light", "dark")
WINDOW_S = 5
SERVE_ARGV = ["--dev", "--compare", "--sessions", "--store", "sqlite", "--window-s", str(WINDOW_S), "--epoch-ms", "200"]
TALK = (("A", "are we still on for the rehearsal?"), ("B", "yes, 6 pm"), ("A", "bring the laptop"),
        ("B", "which one"), ("A", "the one with the demo"), ("B", "ok"), ("A", "did the kernel job come back?"),
        ("B", "ingested this morning"))
CHAT_MODES = ("vcloak", "baseline")
PLAIN_VIEWS = {"dashboard": "the dashboard", "experiments": "the experiments view",
               "logs": "the logs view", "arch": "the architecture view"}
VIEWS = ("chat", *PLAIN_VIEWS)
DATA_STATES = ("measured", "seed", "quick")
INDEX_HEAD = "| ID | What it shows | Module | Date | Source run | Data state | Used in |"


# ── the index ────────────────────────────────────────────────────────────────
def cell(text: str) -> str:
    """One table cell: a single line without the column separator."""
    return " ".join(str(text).split()).replace("|", "/")


def index_row(*, id: str, file: str, what: str, module: str, date: str, source: str, state: str,
              used: str = "—") -> str:
    if state not in DATA_STATES:
        raise ValueError(f"data state {state!r} is not one of {DATA_STATES}")
    if not source.startswith(("runs/", "gpujobs/")):
        raise ValueError(f"{id}: a row with no run dir is not evidence ({source!r})")
    return f"| {id} | {file} — {cell(what)} | {module} | {date} | {cell(source)} | {state} | {cell(used)} |"


def row_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def row_file(line: str) -> str:
    """The file a row is about: the first word of its second cell."""
    cells = row_cells(line)
    return cells[1].split(" ", 1)[0] if len(cells) > 1 else ""


KEPT = re.compile(r"; the earlier picture \(runs/[^)\s]+\) is kept as superseded/\S+")


def run_of(source: str) -> str:
    """`runs/<dir>` of a source cell (`runs/<dir> (git 1234567[, dirty])`)."""
    return source.split(" ", 1)[0]


def kept_name(file: str, run: str) -> str:
    """The name under superseded/ of `file` as the run `run` left it: the file name with the time of that run
    (after a dot: one long word of letters, digits, `_` and `-` reads as a key to scripts/check_secrets.py)."""
    p = Path(file)
    return f"{p.stem}.{Path(run).name.split('_', 1)[0]}{p.suffix}"


def upsert_rows(text: str, rows: list[dict[str, str]]) -> tuple[str, list[tuple[str, str, str]]]:
    """`text` of the index with `rows` in it: a row whose ID exists takes the place of the old one and
    keeps its "Used in" cell, a new one goes to the end. Returns the new text and, for every replaced
    row whose file has to be kept, `(id, old file, name under superseded/)`: a row that pointed at
    another file, and a row of another run that pointed at the same file (the same day), which the new
    picture would otherwise overwrite. A second call of the same run overwrites its own pictures."""
    if INDEX_HEAD not in text:
        raise ValueError("evidence/INDEX.md has no table head")
    lines = text.rstrip("\n").split("\n")
    at = {row_cells(line)[0]: i for i, line in enumerate(lines) if line.startswith("| ") and line != INDEX_HEAD}
    replaced: list[tuple[str, str, str]] = []
    for r in rows:
        r = dict(r)
        old = lines[at[r["id"]]] if r["id"] in at else None
        if old is not None:
            cells = row_cells(old)
            r["used"] = cells[6] if len(cells) > 6 else "—"
            earlier = run_of(cells[4]) if len(cells) > 4 else ""
            r["what"] += "".join(KEPT.findall(old))  # what earlier runs left stays on record
            if row_file(old) != r["file"]:
                replaced.append((r["id"], row_file(old), Path(row_file(old)).name))
                r["what"] += f"; supersedes {row_file(old)}, kept in superseded/"
            elif earlier != run_of(r["source"]):
                name = kept_name(r["file"], earlier)
                replaced.append((r["id"], row_file(old), name))
                r["what"] += f"; the earlier picture ({earlier}) is kept as superseded/{name}"
            lines[at[r["id"]]] = index_row(**r)
        else:
            at[r["id"]] = len(lines)
            lines.append(index_row(**r))
    return "\n".join(lines) + "\n", replaced


def source_of(run_dir: Path) -> str:
    """`runs/<dir> (git 1234567[, dirty])` from the manifest of the run."""
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    rel = run_dir.resolve().relative_to(ROOT).as_posix()
    return f"{rel} (git {str(m['git_sha'])[:7]}{', dirty' if m.get('dirty') else ''})"


def tree_source(run_dir: Path) -> str:
    """As `source_of`, with the commit and the state of the tree as they are now: a picture shows the
    files of the working tree, which may have changed since the run directory was made."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()

    rel = run_dir.resolve().relative_to(ROOT).as_posix()
    return f"{rel} (git {git('rev-parse', 'HEAD')[:7]}{', dirty' if git('status', '--porcelain') else ''})"


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


def shot_id(module: str, view: str, theme: str) -> str:
    return f"SCR-{module}-{view.replace('_', '-').upper()}-{theme.upper()}"


def terminal_rows(specs: list[str], *, module: str, tag: str, date: str) -> list[tuple[Path, dict[str, str]]]:
    """`SRC=what it shows` -> (source file, index row). The row names the run directory SRC lies in."""
    out = []
    for spec in specs:
        src_text, sep, what = spec.partition("=")
        src = (ROOT / src_text).resolve()
        if not sep or not what.strip():
            raise ValueError(f"--terminal {spec!r}: write SRC=what it shows")
        if not src.is_file() or not src.is_relative_to(ROOT / "runs") or not (src.parent / "manifest.json").is_file():
            raise ValueError(f"--terminal {src_text}: not a file of a run directory")
        name = re.sub(r"[^A-Za-z0-9]+", "_", src.stem).strip("_")
        mid = "_".join(x for x in (module, tag, name) if x)
        out.append((src, {"id": "TERM-" + mid.replace("_", "-").upper(), "file": f"terminal/{mid}{src.suffix}",
                          "what": what, "module": module, "date": date, "source": source_of(src.parent),
                          "state": "measured"}))
    return out


# ── the page ─────────────────────────────────────────────────────────────────
def js(value: Any) -> str:
    return json.dumps(value)


def set_theme(page: Any, theme: str) -> None:
    # what the theme button does, without storing the choice; the charts redraw on the event
    page.evaluate(f"""(document.documentElement.setAttribute('data-theme', {js(theme)}),
                      document.dispatchEvent(new CustomEvent('vc:theme')), true)""")
    time.sleep(0.5)


def settle(page: Any, selector: str, quiet_s: float = 1.0, timeout: float = 30.0) -> None:
    """Wait until the markup under `selector` has stopped changing (an animation, a late answer)."""
    deadline = time.monotonic() + timeout
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        now = page.evaluate(f"document.querySelector({js(selector)}).innerHTML")
        if now != last:
            last, since = now, time.monotonic()
        elif time.monotonic() - since >= quiet_s:
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} kept changing for {timeout:.0f} s")


def shoot(page: Any, tmp: Path, module: str, view: str, date: str) -> dict[str, dict[str, Any]]:
    files = {}
    for theme in THEMES:
        set_theme(page, theme)
        name = f"{module}_{view}_{theme}_{date}.png"
        path = page.screenshot(tmp / name)
        w, h = png_size(path)
        files[theme] = {"file": f"screens/{name}", "width": w, "height": h, "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    set_theme(page, THEMES[0])
    return files


def panel(page: Any) -> dict[str, Any]:
    view = page.evaluate("VC.chat.serverView()")
    return {
        "mode": view["mode"],
        "revealed_order": [r["n"] for r in view["rows"]],
        "windows": len({r["win"] for r in view["rows"]}),
        "states": sorted({r["state"] for r in view["rows"]}),
        "payloads": sorted(r["payload_b64"][:16] for r in view["rows"]),
        "columns_shown": page.evaluate("""Array.from(document.querySelectorAll('#dumpTable th'))
            .filter(th => getComputedStyle(th).display !== 'none').map(th => th.textContent)"""),
        "note": page.evaluate("document.getElementById('serverNote').textContent"),
        "strip_mode": page.evaluate("document.getElementById('ls-mode').textContent"),
        # the strip at the moment of the picture, beside what the server said at that moment
        "strip": page.evaluate("""VC.api.raw('GET', '/v1/stats/live').then(r => ({
            epoch: document.getElementById('ls-epoch').textContent,
            backend: document.getElementById('ls-backend').textContent,
            slots: document.getElementById('ls-slots').textContent,
            fill_hidden: document.getElementById('ls-fillnote').hidden,
            no_epoch_hidden: document.getElementById('ls-noepoch').hidden,
            server_epoch: r.body.epoch, server_gpu: r.body.gpu, server_slots: r.body.slots}))"""),
        "reveal_on": page.evaluate("document.getElementById('revealSwitch').checked"),
    }


def strip_agrees(s: dict[str, Any], epochs: int = 3) -> bool:
    """The strip of a V-cloak picture: the server's epoch (the two were read a moment apart), slots, backend."""
    gpu = s["server_gpu"]
    return (s["epoch"].isdigit() and abs(int(s["epoch"]) - s["server_epoch"]) <= epochs
            and s["slots"] == str(s["server_slots"]) and not s["fill_hidden"] and s["no_epoch_hidden"]
            and gpu is not None and s["backend"] == f'{gpu["backend"]} · {gpu["runner"]}')


def monotonic(order: list[int]) -> bool:
    return all(a < b for a, b in zip(order, order[1:], strict=False))


def capture_chat(page: Any, tmp: Path, module: str, date: str) -> tuple[dict[str, Any], dict[str, bool]]:
    n = len(TALK)
    both = f"(v => v.rows.length === {n} && v.rows.every(r => r.n))(VC.chat.serverView())"
    out: dict[str, Any] = {"messages": n}
    # start right after a window boundary, so that the conversation is in a window that closes soon
    while time.time() % WINDOW_S > 0.5:
        time.sleep(0.05)
    for user, text in TALK:
        page.evaluate(f"VC.chat.send({js(user)}, {js(text)})")
    page.wait_for(f"VC.chat.transcript('A').length >= {n} && VC.chat.transcript('B').length >= {n}")
    page.evaluate("(document.getElementById('revealSwitch').click(), true)")
    # only a closed window is shuffled: wait until every row of the conversation is in one
    page.wait_for(f"VC.chat.serverView().mode === 'vcloak' && {both} && "
                  "VC.chat.serverView().rows.every(r => r.state === 'reshuffled')", timeout=60)
    for mode in CHAT_MODES:
        if mode == "baseline":
            page.evaluate("(document.getElementById('modeSwitch').click(), true)")
            page.wait_for(f"VC.chat.serverView().mode === 'baseline' && {both}", timeout=30)
            time.sleep(1.2)  # one more tick of the strip
        out[mode] = panel(page)
        out[mode]["files"] = shoot(page, tmp, module, f"chat_{mode}_reveal", date)
    # back to the mode the server starts in, so that the other views are photographed in it
    page.evaluate("(document.getElementById('modeSwitch').click(), true)")
    page.wait_for(f"VC.chat.serverView().mode === 'vcloak' && {both}", timeout=30)
    out["order_after_switching_back"] = [r["n"] for r in page.evaluate("VC.chat.serverView()")["rows"]]
    texts = {u: page.evaluate(f"VC.chat.transcript({js(u)}).map(m => m.text)") for u in "AB"}
    table_text = page.evaluate("document.getElementById('dumpTable').textContent")
    out["footer"] = page.evaluate("document.getElementById('footProv').textContent")
    v, b = out["vcloak"], out["baseline"]
    return out, {
        "chat: V-cloak rows are of closed windows and their revealed order is not monotonic":
            v["states"] == ["reshuffled"] and sorted(v["revealed_order"]) == list(range(1, n + 1))
            and not monotonic(v["revealed_order"]),
        "chat: the baseline revealed order is monotonic": b["revealed_order"] == list(range(1, n + 1)),
        "chat: both panels hold the same ciphertexts": v["payloads"] == b["payloads"] and len(v["payloads"]) == n,
        "chat: reveal was on and the strip showed the mode in both pictures":
            v["reveal_on"] and b["reveal_on"] and (v["strip_mode"], b["strip_mode"]) == CHAT_MODES,
        "chat: the strip showed the server's epoch and backend in V-cloak mode, and no epoch in baseline mode":
            strip_agrees(v["strip"]) and b["strip"]["epoch"] == "—" and b["strip"]["server_epoch"] is None
            and b["strip"]["fill_hidden"] and not b["strip"]["no_epoch_hidden"],
        "chat: switching back gives the V-cloak order again": out["order_after_switching_back"] == v["revealed_order"],
        "chat: the panes read the conversation in the order sent": texts["A"] == texts["B"] == [t for _, t in TALK],
        "chat: no pane stopped":
            page.evaluate("['A','B'].every(u => !VC.chat.panes[u].halted && !VC.chat.panes[u].alert)"),
        "chat: no message text is in the table": not any(t in table_text for _, t in TALK),
    }


def view_state(page: Any, view: str) -> dict[str, Any]:
    """What `view` shows and where it says its data comes from."""
    dash = page.evaluate("""(d => d ? {source: d.source || null, session: (d.provenance || {}).session_id || null,
        quick: (d.tiles || []).some(t => t.quick), tiles: (d.tiles || []).length, charts: (d.charts || []).length,
        not_measured: document.querySelectorAll('#tiles .tile.na').length,
        chip: (document.querySelector('#provbar .chip') || {}).textContent || null} : null)(VC.dashboard.data())""")
    from_dash = "seed" if not dash or dash["source"] == "seed-oracle" else "quick" if dash["quick"] else "measured"
    if view == "dashboard":
        return {"state": from_dash, "dashboard": dash}
    if view == "experiments":
        # M18 S4: the first line of the first panel says whether the number is a live run or the stored one
        source = page.evaluate("(document.querySelector('#attackStats .bigstat .k') || {}).textContent || null")
        live = source is not None and "live run" in source
        match = page.evaluate("""(b => b ? {identical: b.classList.contains('match'), text: b.innerText} : null)
            (document.querySelector('#attackStats .bigstat.match, #attackStats .bigstat.nomatch'))""")
        return {"state": from_dash, "source_line": source, "live": live, "match": match,
                "layout": page.evaluate("document.getElementById('expW').value"),
                "dashboard_source": dash and dash["source"]}
    if view == "logs":
        # M18 S5: live, the lines are state/ through the server's redaction, and the note above them says so
        demo = page.evaluate("VC.api.logs('session', 5).then(r => !!r.demo)")
        return {"state": "seed" if demo else "measured", "demo_lines": demo,
                "lines": page.evaluate("document.getElementById('logBox').children.length"),
                "note": page.evaluate("document.getElementById('logNote').textContent")}
    # the architecture view is a drawing: it holds no result, so it is filed with the samples
    return {"state": "seed", "static": True}


def describe_chat(mode: str, chat: dict[str, Any], backend: str) -> str:
    p = chat[mode]
    order = " ".join(str(x) for x in p["revealed_order"])
    what = ("V-cloak mode" if mode == "vcloak" else "baseline mode") + ', "reveal true order" on'
    text = (f"the chat with the server-view panel on a live `serve {' '.join(SERVE_ARGV[:2])}` ({backend} engine, "
            f"SQLite), {what}: {chat['messages']} messages sent by the two panes, the stored rows in physical order "
            f"with the revealed send order {order} (the same ciphertexts in both modes). Correctness, no result")
    s = p["strip"]
    # the epoch on the strip moves on while the page is photographed: the row gives the one read just before
    text += (f'; the strip shows the server\'s open epoch (it read {s["epoch"]}, as the server did, just before the '
             f'picture, and counts on) and the backend "{s["backend"]}"'
             if mode == "vcloak" else "; the strip shows no epoch and no backend, as the baseline has neither")
    if chat["footer"]:
        text += f'; the page footer reads "{chat["footer"]}", the provenance of the dashboard view'
    return text


def describe_view(view: str, info: dict[str, Any]) -> str:
    if view == "arch":
        return f"{PLAIN_VIEWS[view]}: the data-state flow and the leakage table, a drawing with no data in it"
    if view == "experiments" and info.get("live"):
        m = info.get("match") or {}
        return (f"{PLAIN_VIEWS[view]} after a live run of the attack on layout {info['layout']} through "
                f"/v1/eval/attack (numpy backend, new SQLite store), compared with the stored value: "
                f"{'identical' if m.get('identical') else 'NOT identical'}")
    if view == "logs" and not info.get("demo_lines"):
        return (f"{PLAIN_VIEWS[view]} tailing state/SESSION_LOG.md through /v1/logs and its redaction; "
                f"the page reads: \"{info.get('note')}\"")
    if info["state"] == "seed":
        return (f"{PLAIN_VIEWS[view]} as the page shows it with the bundled sample data (SEED DATA): "
                "the interface, never a result")
    return f"{PLAIN_VIEWS[view]} as the page shows it from generated data"


LIVE_LAYOUT = "W300"  # the layout the picture of the experiments view is taken on


def live_attack(page: Any, timeout: float = 300) -> None:
    """Press Run attack on LIVE_LAYOUT and wait for the live result and its comparison with the stored one."""
    page.evaluate(f"(document.getElementById('expW').value = {js(LIVE_LAYOUT)}, "
                  "document.getElementById('runAttack').click(), true)")
    page.wait_for("!!document.querySelector('#attackStats .bigstat.match, #attackStats .bigstat.nomatch') "
                  "&& !document.getElementById('runAttack').disabled", timeout=timeout)
    settle(page, "#view-experiments")


def capture(module: str, views: list[str], tmp: Path, date: str) -> dict[str, Any]:
    from demo_two_users import LocalServer
    from headless import Browser

    out: dict[str, Any] = {"serve_argv": SERVE_ARGV, "viewport": [WIDTH, HEIGHT], "views": {}, "checks": {}}
    with Browser(width=WIDTH, height=HEIGHT) as browser, LocalServer(SERVE_ARGV) as server:
        out["browser"] = browser.version
        page = browser.page(server.base + "/app/")
        try:
            page.set_viewport(WIDTH, HEIGHT)
            page.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.panes.A)",
                          timeout=30)
            out["live_ready"] = page.evaluate("VC.chat.ready()")
            out["conn"] = page.evaluate("document.getElementById('conn').textContent")
            out["stats_live"] = page.evaluate("VC.api.raw('GET', '/v1/stats/live').then(r => r.body)")
            out["checks"]["the page is live, in dev mode, with a mode switch"] = (
                out["live_ready"] is True
                and page.evaluate("VC.state.live && VC.state.dev && VC.state.switchable") is True)
            if "chat" in views:
                if not out["live_ready"]:
                    raise RuntimeError("the panes did not sign in: no chat to photograph")
                out["views"]["chat"], checks = capture_chat(page, tmp, module, date)
                out["checks"].update(checks)
            for view in (v for v in views if v in PLAIN_VIEWS):
                page.evaluate(f"(document.querySelector('.tab[data-view={view}]').click(), true)")
                page.wait_for(f"!document.getElementById('view-{view}').hidden")
                settle(page, f"#view-{view}")
                if view == "experiments":
                    live_attack(page)
                info = view_state(page, view)
                info["files"] = shoot(page, tmp, module, view, date)
                out["views"][view] = info
                out["checks"][f"{view}: the view was the one on screen"] = page.evaluate(
                    f"document.querySelector('.tab[aria-selected=true]').dataset.view === {js(view)}")
            out["errors"] = page.errors()
        finally:
            page.close()
    out["checks"]["no exception, console error or blocked request in the page"] = out["errors"] == []
    return out


def rows_of(module: str, out: dict[str, Any], date_iso: str, source: str, backend: str) -> list[dict[str, str]]:
    rows = []
    for view, info in out["views"].items():
        shots = ([(f"chat_{m}_reveal", info[m]["files"], describe_chat(m, info, backend), "measured")
                  for m in CHAT_MODES]
                 if view == "chat" else [(view, info["files"], describe_view(view, info), info["state"])])
        for name, files, what, state in shots:
            for theme in THEMES:
                f = files[theme]
                rows.append({"id": shot_id(module, name, theme), "file": f["file"], "module": module, "date": date_iso,
                             "what": f"{what}. {theme} theme, {f['width']}x{f['height']}, full page",
                             "source": source, "state": state})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", required=True, help="the module the captures belong to, e.g. M13")
    ap.add_argument("--run", default=None, help="an existing run directory to record in (default: a new one)")
    ap.add_argument("--views", default=",".join(VIEWS), help=f"comma-separated subset of {','.join(VIEWS)}, or none")
    ap.add_argument("--tag", default="", help="a step tag for the names of --terminal copies, e.g. S5b")
    ap.add_argument("--terminal", action="append", default=[], metavar="SRC=WHAT",
                    help="copy a file of a run directory to evidence/terminal/ and index it (repeatable)")
    ap.add_argument("--owner", default="unknown", help="owner of a run directory this call creates")
    ap.add_argument("--evidence", default=str(ROOT / "evidence"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not re.fullmatch(r"M\d\d", a.module):
        ap.error("--module must look like M13")
    views = [] if a.views == "none" else a.views.split(",")
    if set(views) - set(VIEWS):
        ap.error(f"--views: unknown {sorted(set(views) - set(VIEWS))}")

    from vcloak import runs

    evidence = Path(a.evidence)
    index = evidence / "INDEX.md"
    now = _dt.datetime.now()
    date, date_iso = now.strftime("%Y%m%d"), now.strftime("%Y-%m-%d")
    terminal = terminal_rows(a.terminal, module=a.module, tag=a.tag, date=date_iso)
    own_run = a.run is None
    run_dir = (runs.new_run(a.module, "capture_evidence", step=a.tag or "capture", owner=a.owner,
                            command="python scripts/capture_evidence.py " + " ".join(argv or sys.argv[1:]), root=ROOT)
               if own_run else (ROOT / a.run).resolve())
    manifest = runs.read_manifest(run_dir)
    source, backend = tree_source(run_dir), str(manifest["env"].get("backend"))
    if source.endswith(", dirty)") and not manifest.get("dirty"):  # the tree changed after the run was started
        manifest["dirty"] = True
        runs.write_manifest(run_dir, manifest)

    out: dict[str, Any] = {"module": a.module, "run": source, "date": date_iso, "views": {}, "checks": {}}
    rows: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="vcloak-capture-") as tmp_name:
        tmp = Path(tmp_name)
        if views:
            try:
                out.update(capture(a.module, views, tmp, date))
            except Exception as e:  # noqa: BLE001 - recorded, and nothing is written to evidence/
                out["failed"] = f"{type(e).__name__}: {e}"
            rows = rows_of(a.module, out, date_iso, source, backend)
        out["ok"] = "failed" not in out and all(out["checks"].values())
        if out["ok"]:
            text, replaced = upsert_rows(index.read_text(encoding="utf-8"), rows + [r for _, r in terminal])
            out["superseded"] = []
            for rid, old, name in replaced:  # the old picture is kept, never deleted (ai/EVIDENCE.md rule 2)
                if (evidence / old).is_file():
                    (evidence / "superseded").mkdir(exist_ok=True)
                    shutil.move(evidence / old, evidence / "superseded" / name)
                    out["superseded"].append({"id": rid, "file": old, "kept_as": "superseded/" + name})
            (evidence / "screens").mkdir(exist_ok=True)
            for r in rows:
                shutil.copyfile(tmp / Path(r["file"]).name, evidence / r["file"])
            for src, r in terminal:
                (evidence / "terminal").mkdir(exist_ok=True)
                shutil.copyfile(src, evidence / r["file"])
            index.write_text(text, encoding="utf-8", newline="\n")
            out["index_rows"] = [r["id"] for r in rows] + [r["id"] for _, r in terminal]
            out["files_written"] = [r["file"] for r in rows] + [r["file"] for _, r in terminal]

    # a call that only copies terminal output must not replace the record of the pictures
    record = run_dir / ("capture_evidence.json" if views else "capture_terminal.json")
    record.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    if own_run:
        runs.finish_run(run_dir, status="OK" if out["ok"] else "FAIL",
                        notes=f"capture_evidence --module {a.module}: {len(rows)} screens, {len(terminal)} terminal "
                              "copies; pictures of the app, nothing measured")
    for name, passed in out["checks"].items():
        print(("PASS  " if passed else "FAIL  ") + name)
    if "failed" in out:
        print("FAILED:", out["failed"].encode("ascii", "replace").decode())
    print(f"{len(out.get('files_written', []))} files, {len(out.get('index_rows', []))} index rows; "
          f"record: {record.relative_to(ROOT).as_posix()}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
