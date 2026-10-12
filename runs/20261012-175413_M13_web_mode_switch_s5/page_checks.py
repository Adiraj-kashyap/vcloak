"""M13 S5: the mode switch of the live page, in the installed browser. Run from the repository root:

    python runs/<dir>/page_checks.py runs/<dir>

A short conversation in one 5 s window on `serve --dev --compare`; after the window closed the panel is
read with the reveal switch on, in V-cloak mode and in baseline mode, and photographed in both themes.
Nothing is measured.
"""
import json
import sys
import time
from pathlib import Path

sys.path[:0] = ["src", "scripts"]
from demo_two_users import LocalServer  # noqa: E402
from headless import Browser  # noqa: E402

run = Path(sys.argv[1])
out = {}
WINDOW_S = 5
argv = ["--dev", "--compare", "--sessions", "--store", "sqlite", "--window-s", str(WINDOW_S), "--epoch-ms", "200"]
talk = [("A", "are we still on for the rehearsal?"), ("B", "yes, 6 pm"), ("A", "bring the laptop"),
        ("B", "which one"), ("A", "the one with the demo"), ("B", "ok"), ("A", "did the kernel job come back?"),
        ("B", "ingested this morning")]
N = len(talk)


def monotonic(order):
    return all(a < b for a, b in zip(order, order[1:], strict=False))


with Browser() as b, LocalServer(argv) as s:
    out["browser"] = b.version
    out["serve_argv"] = argv
    p = b.page(s.base + "/app/")
    p.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.panes.A)", timeout=20)
    out["live_ready"] = p.evaluate("VC.chat.ready()")
    out["switch_enabled"] = p.evaluate("!document.getElementById('modeSwitch').disabled && VC.state.switchable")
    # start right after a window boundary, so that the messages share a window
    while time.time() % WINDOW_S > 0.5:
        time.sleep(0.05)
    for u, t in talk:
        p.evaluate(f"VC.chat.send({json.dumps(u)}, {json.dumps(t)})")
    p.wait_for(f"VC.chat.transcript('A').length >= {N} && VC.chat.transcript('B').length >= {N}")
    p.evaluate("(document.getElementById('revealSwitch').click(), true)")
    p.wait_for(f"""(() => {{ const v = VC.chat.serverView();
        return v.mode === 'vcloak' && v.rows.length === {N} && v.rows.every(r => r.n && r.state === 'reshuffled'); }})()""",
               timeout=30)
    p.set_viewport(1440, 900)

    def capture(name):
        view = p.evaluate("VC.chat.serverView()")
        first = view["rows"][0]["win"]
        shot = {
            "mode": view["mode"],
            "revealed_order": [r["n"] for r in view["rows"]],
            "rows_physical_order": [{"pos": r["pos"], "win": r["win"] - first, "state": r["state"],
                                     "row_id": r["row_id"][:8], "ts": r["ts"], "conv": r["conv"],
                                     "revealed": f"#{r['n']} {r['who']}"} for r in view["rows"]],
            "payloads": sorted(r["payload_b64"][:16] for r in view["rows"]),
            "columns_shown": p.evaluate("""Array.from(document.querySelectorAll('#dumpTable th'))
                .filter(th => getComputedStyle(th).display !== 'none').map(th => th.textContent)"""),
            "table": p.evaluate("""Array.from(document.querySelectorAll('#dumpBody tr')).map(tr =>
                Array.from(tr.cells).filter(td => getComputedStyle(td).display !== 'none')
                     .map(td => td.textContent).join(' | '))"""),
            "note": p.evaluate("document.getElementById('serverNote').textContent"),
            "strip_mode": p.evaluate("document.getElementById('ls-mode').textContent"),
        }
        for theme in ("light", "dark"):
            p.evaluate(f"(document.documentElement.setAttribute('data-theme', '{theme}'), true)")
            time.sleep(0.5)
            p.screenshot(run / f"server_view_{name}_reveal_{theme}.png")
        p.evaluate("(document.documentElement.setAttribute('data-theme', 'light'), true)")
        return shot

    out["vcloak"] = capture("vcloak")
    p.evaluate("(document.getElementById('modeSwitch').click(), true)")
    p.wait_for(f"(v => v.mode === 'baseline' && v.rows.length === {N} && v.rows.every(r => r.n))(VC.chat.serverView())",
               timeout=20)
    time.sleep(1.2)  # one more tick of the strip
    out["baseline"] = capture("baseline")
    out["mode_route_in_baseline"] = p.evaluate("VC.api.raw('GET', '/v1/mode').then(r => r.body)")
    p.evaluate("(document.getElementById('modeSwitch').click(), true)")
    p.wait_for(f"(v => v.mode === 'vcloak' && v.rows.length === {N} && v.rows.every(r => r.n))(VC.chat.serverView())",
               timeout=20)
    back = [r["n"] for r in p.evaluate("VC.chat.serverView()")["rows"]]
    texts = {u: p.evaluate(f"VC.chat.transcript('{u}').map(m => m.text)") for u in "AB"}
    table_text = p.evaluate("document.getElementById('dumpTable').textContent")
    out["stores"] = {"vcloak_rows": len(s.backend.vcloak.repo.dump()), "baseline_rows": len(s.backend.baseline.store.dump())}
    v, bl = out["vcloak"], out["baseline"]
    out["checks"] = {
        "the switch is enabled on a --compare server": out["switch_enabled"] is True,
        "V-cloak: the revealed order is not monotonic": sorted(v["revealed_order"]) == list(range(1, N + 1))
            and not monotonic(v["revealed_order"]),
        "baseline: the revealed order is monotonic": bl["revealed_order"] == list(range(1, N + 1)),
        "both panels hold the same ciphertexts": v["payloads"] == bl["payloads"] and len(v["payloads"]) == N,
        "baseline rows carry ts and conv, V-cloak rows do not":
            all(r["ts"] and r["conv"] for r in bl["rows_physical_order"])
            and all(r["ts"] is None and r["conv"] is None for r in v["rows_physical_order"]),
        "the caption changes with the mode": "Unprotected baseline" in bl["note"] and bl["note"] != v["note"],
        "the caption says the server stores both layouts": "--compare" in v["note"] and "--compare" in bl["note"],
        "the strip follows the server": (v["strip_mode"], bl["strip_mode"]) == ("vcloak", "baseline"),
        "switching back gives the V-cloak order again": back == v["revealed_order"],
        "the panes read the conversation once, in the order sent":
            texts["A"] == texts["B"] == [t for _, t in talk],
        "no pane stopped": p.evaluate("['A','B'].every(u => !VC.chat.panes[u].halted && !VC.chat.panes[u].alert)"),
        "no message text is in the table": not any(t in table_text for _, t in talk),
        "both stores hold every message": out["stores"] == {"vcloak_rows": N, "baseline_rows": N},
    }
    out["errors"] = p.errors()
    p.close()
out["ok"] = out["live_ready"] is True and all(out["checks"].values()) and out["errors"] == []
(run / "page_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("checks", "errors", "ok")}, indent=1))
print("vcloak  ", out["vcloak"]["revealed_order"])
print("baseline", out["baseline"]["revealed_order"])
sys.exit(0 if out["ok"] else 1)
