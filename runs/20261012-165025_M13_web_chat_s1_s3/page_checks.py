import json, sys, time
from pathlib import Path
sys.path[:0] = ["src", "scripts"]
from demo_two_users import LocalServer
from headless import Browser
run = Path(sys.argv[1]); out = {}
argv = ["--dev", "--sessions", "--store", "sqlite", "--window-s", "5", "--epoch-ms", "200"]
with Browser() as b, LocalServer(argv) as s:
    out["browser"] = b.version
    p = b.page(s.base + "/app/")
    p.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.ready)")
    out["live_ready"] = p.evaluate("VC.chat.ready()")
    talk = [("A", "are we still on for the rehearsal?"), ("B", "yes, 6 pm"), ("A", "bring the laptop"),
            ("B", "which one"), ("A", "the one with the demo"), ("B", "ok"), ("A", "this one comes after a pause")]
    for i, (u, t) in enumerate(talk):
        if i == len(talk) - 1:
            time.sleep(5.2)
        p.evaluate(f"VC.chat.send({json.dumps(u)}, {json.dumps(t)})")
    p.wait_for(f"VC.chat.transcript('A').length >= {len(talk)} && VC.chat.transcript('B').length >= {len(talk)}")
    out["live"] = p.evaluate("""({conn: document.getElementById('conn').textContent,
        keyA: document.getElementById('keyA').textContent, keyB: document.getElementById('keyB').textContent,
        fingerprint: document.getElementById('fingerprint').textContent,
        a: VC.chat.transcript('A').map(m => [m.sender.split('_')[0], m.number, m.win - VC.chat.panes.A.client.conv.firstWin, m.text]),
        same: JSON.stringify(VC.chat.transcript('A').map(m => m.text)) === JSON.stringify(VC.chat.transcript('B').map(m => m.text)),
        note: document.getElementById('serverNote').textContent,
        rows: document.getElementById('dumpBody').children.length})""")
    out["live_errors"] = p.errors()
    p.set_viewport(1440, 900)
    for theme in ("light", "dark"):
        p.evaluate(f"(document.documentElement.setAttribute('data-theme', '{theme}'), true)")
        time.sleep(0.5)
        p.screenshot(run / f"chat_live_{theme}.png")
    out["stored_rows"] = len(s.backend.repo.dump())
    p.close()
    # A4: the same files from file://, no backend
    f = b.page((Path("web") / "index.html").resolve().as_uri())
    f.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.ready)")
    f.wait_for("document.querySelectorAll('#msgsA .bub').length > 0")
    f.evaluate("(document.getElementById('inA').value = 'typed in demo mode', document.querySelector('#formA button').click(), true)")
    out["file"] = f.evaluate("""({protocol: location.protocol, conn: document.getElementById('conn').textContent,
        live: VC.state.live, bubblesA: document.querySelectorAll('#msgsA .bub').length,
        bubblesB: document.querySelectorAll('#msgsB .bub').length, keyA: document.getElementById('keyA').textContent,
        rows: document.getElementById('dumpBody').children.length,
        tiles: document.querySelectorAll('#tiles > *').length})""")
    out["file_errors"] = f.errors()
    f.set_viewport(1440, 900)
    f.evaluate("(document.documentElement.setAttribute('data-theme', 'light'), true)")
    time.sleep(0.5)
    f.screenshot(run / "chat_file_demo.png")
    f.close()
(run / "page_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=True)[:2600])
