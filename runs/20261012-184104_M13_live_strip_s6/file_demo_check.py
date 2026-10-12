"""M13 A4 after S6: the page opened from file:// (no backend) still shows the bundled sample rows,
and its strip runs on the demo clock and says that it is demo data.

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
    strip = """({epoch: document.getElementById('ls-epoch').textContent,
        backend: document.getElementById('ls-backend').textContent, demo: VC.strip.last().demo === true})"""
    out["strip_first"] = f.evaluate(strip)
    time.sleep(1.2)
    out["strip_later"] = f.evaluate(strip)
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
a, b = out["strip_first"], out["strip_later"]
out["strip_ok"] = (a["demo"] and b["demo"] and a["backend"] == b["backend"] == "demo"
                   and int(b["epoch"]) > int(a["epoch"]))
out["ok"] = (out["strip_ok"] and out["protocol"] == "file:" and out["live"] is False and out["rows"] == 8 and out["errors"] == []
             and out["revealed_vcloak"] != sorted(out["revealed_vcloak"])
             and out["revealed_baseline"] == sorted(out["revealed_baseline"]))
(run / "file_demo_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=True))
sys.exit(0 if out["ok"] else 1)
