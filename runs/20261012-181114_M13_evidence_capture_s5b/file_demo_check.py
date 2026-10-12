"""M13 A4 after S4: the page opened from file:// (no backend) still shows the bundled sample rows.

    python runs/<dir>/file_demo_check.py runs/<dir>
"""
import json
import sys
import time
from pathlib import Path

sys.path[:0] = ["src", "scripts"]
from headless import Browser  # noqa: E402

run = Path(sys.argv[1])
cells = """Array.from(document.querySelectorAll('#dumpBody tr')).map(tr => tr.cells[tr.cells.length - 1].textContent)"""
with Browser() as b:
    f = b.page((Path("web") / "index.html").resolve().as_uri())
    f.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.ready)")
    f.wait_for("document.querySelectorAll('#dumpBody tr').length > 0")
    out = f.evaluate("""({protocol: location.protocol, conn: document.getElementById('conn').textContent,
        live: VC.state.live, bubblesA: document.querySelectorAll('#msgsA .bub').length,
        rows: document.getElementById('dumpBody').children.length,
        reveal_disabled: document.getElementById('revealSwitch').disabled,
        mode_disabled: document.getElementById('modeSwitch').disabled,
        note: document.getElementById('serverNote').textContent})""")
    f.evaluate("(document.getElementById('revealSwitch').click(), true)")
    time.sleep(0.3)
    out["revealed_vcloak"] = f.evaluate(cells)
    out["reveal_visible"] = f.evaluate("getComputedStyle(document.querySelector('th.reveal-col')).display")
    f.evaluate("(document.getElementById('modeSwitch').click(), true)")
    f.wait_for("document.getElementById('serverNote').textContent.indexOf('baseline') >= 0")
    out["revealed_baseline"] = f.evaluate(cells)
    out["errors"] = f.errors()
    f.set_viewport(1440, 900)
    f.evaluate("(document.documentElement.setAttribute('data-theme', 'light'), true)")
    time.sleep(0.5)
    f.screenshot(run / "chat_file_demo.png")
    f.close()
out["ok"] = (out["protocol"] == "file:" and out["live"] is False and out["rows"] == 8 and out["errors"] == []
             and out["revealed_vcloak"] != sorted(out["revealed_vcloak"])
             and out["revealed_baseline"] == sorted(out["revealed_baseline"]))
(run / "file_demo_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=True))
sys.exit(0 if out["ok"] else 1)
