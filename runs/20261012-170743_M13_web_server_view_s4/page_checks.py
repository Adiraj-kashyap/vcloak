"""M13 S4: the server view of the live page, in the installed browser. Run from the repository root:

    python runs/<dir>/page_checks.py runs/<dir>

A short conversation in one 5 s window, then one message in the next; after the first window closed the
panel is read with the reveal switch on, and photographed in both themes. Nothing is measured.
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
argv = ["--dev", "--sessions", "--store", "sqlite", "--window-s", str(WINDOW_S), "--epoch-ms", "200"]
talk = [("A", "are we still on for the rehearsal?"), ("B", "yes, 6 pm"), ("A", "bring the laptop"),
        ("B", "which one"), ("A", "the one with the demo"), ("B", "ok"), ("A", "did the kernel job come back?"),
        ("B", "ingested this morning"), ("A", "this one comes after the window closed")]
with Browser() as b, LocalServer(argv) as s:
    out["browser"] = b.version
    p = b.page(s.base + "/app/")
    p.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.ready)")
    out["live_ready"] = p.evaluate("VC.chat.ready()")
    # start right after a window boundary, so that the first eight messages share a window
    while time.time() % WINDOW_S > 0.5:
        time.sleep(0.05)
    for i, (u, t) in enumerate(talk):
        if i == len(talk) - 1:
            time.sleep(WINDOW_S + 0.5)
        p.evaluate(f"VC.chat.send({json.dumps(u)}, {json.dumps(t)})")
    p.wait_for(f"VC.chat.transcript('A').length >= {len(talk)} && VC.chat.transcript('B').length >= {len(talk)}")
    p.evaluate("(document.getElementById('revealSwitch').click(), true)")
    p.wait_for(f"""(() => {{ const v = VC.chat.serverView();
        return v.rows.length === {len(talk)} && v.rows.every(r => r.n) &&
               v.rows.filter(r => r.state === 'reshuffled').length === {len(talk) - 1}; }})()""", timeout=30)
    view = p.evaluate("VC.chat.serverView()")
    first = view["rows"][0]["win"]
    stored = [r for w in view["windows"] for r in s.backend.repo.window_rows(w["win"])]
    out["view"] = {
        "mode": view["mode"],
        "windows_with_rows": [{"win": w["win"] - first, "state": w["state"], "rows": w["rows"]}
                              for w in view["windows"] if w["rows"]],
        "rows_physical_order": [{"pos": r["pos"], "win": r["win"] - first, "state": r["state"],
                                 "row_id": r["row_id"][:8], "revealed": f"#{r['n']} {r['who']}"} for r in view["rows"]],
        "revealed_order": [r["n"] for r in view["rows"]],
        "send_order": list(range(1, len(talk) + 1)),
    }
    order = out["view"]["revealed_order"]
    texts = p.evaluate("VC.chat.transcript('A').map(m => m.text)")
    out["checks"] = {
        "the panel shows the rows of the store in the store's order":
            [r["row_id"] for r in view["rows"]] == [str(r.row_id) for r in stored],
        "every row is matched to a message by the panes": sorted(order) == list(range(1, len(talk) + 1)),
        "the panes read the conversation in the order sent": texts == [t for _, t in talk],
        "the displayed order differs from the send order": order != sorted(order),
        "no message text is in the table": not any(
            t in p.evaluate("document.getElementById('dumpTable').textContent") for _, t in talk),
        "the reveal column is visible": p.evaluate(
            "getComputedStyle(document.querySelector('th.reveal-col')).display") == "table-cell",
    }
    out["note"] = p.evaluate("document.getElementById('serverNote').textContent")
    out["table"] = p.evaluate("""Array.from(document.querySelectorAll('#dumpBody tr')).map(tr =>
        Array.from(tr.cells).map(td => td.textContent).join(' | '))""")
    out["switches"] = p.evaluate("""({reveal_disabled: document.getElementById('revealSwitch').disabled,
        mode_disabled: document.getElementById('modeSwitch').disabled})""")
    out["errors"] = p.errors()
    p.set_viewport(1440, 900)
    for theme in ("light", "dark"):
        p.evaluate(f"(document.documentElement.setAttribute('data-theme', '{theme}'), true)")
        time.sleep(0.5)
        p.screenshot(run / f"server_view_reveal_{theme}.png")
    p.evaluate("(document.getElementById('revealSwitch').click(), true)")
    p.evaluate("(document.documentElement.setAttribute('data-theme', 'light'), true)")
    time.sleep(0.5)
    p.screenshot(run / "server_view_light.png")
    p.close()
out["ok"] = out["live_ready"] is True and all(out["checks"].values()) and out["errors"] == []
(run / "page_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("checks", "errors", "ok")}, indent=1))
print(out["view"]["revealed_order"])
sys.exit(0 if out["ok"] else 1)
