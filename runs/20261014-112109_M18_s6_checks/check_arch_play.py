"""M18 S6: press Play on the architecture view and record where the message token goes (a UI check, no metric)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_evidence import SERVE_ARGV  # noqa: E402
from demo_two_users import LocalServer  # noqa: E402
from headless import Browser  # noqa: E402

with Browser() as browser, LocalServer(SERVE_ARGV) as server:
    page = browser.page(server.base + "/app/")
    page.wait_for("document.readyState === 'complete' && !!(window.VC && VC.arch)", timeout=30)
    page.evaluate("(document.querySelector('.tab[data-view=arch]').click(), true)")
    page.wait_for("document.querySelectorAll('#flow .flownode').length > 0", timeout=30)
    page.evaluate("""(window.__seen = [], window.__cap = [], window.__iv = setInterval(() => {
        const on = document.querySelector('#flow .flownode.on');
        const id = on && on.dataset.id;
        if (id && window.__seen[window.__seen.length - 1] !== id) {
          window.__seen.push(id);
          window.__cap.push(document.getElementById('flowCaption').querySelector('b').textContent);
        }
      }, 50), document.getElementById('flowPlay').click(), true)""")
    page.wait_for("document.getElementById('flowPlay').textContent === 'Play again'", timeout=60)
    out = page.evaluate("({seen: window.__seen, captions: window.__cap, "
                        "dot_hidden: +document.querySelector('#flow .flowmsg').getAttribute('cx') < 0})")
    out["errors"] = page.errors()
    expected = [n for n in ["S%d" % i for i in range(11)] + ["R%d" % i for i in range(1, 6)]]
    out["order_is_the_flow"] = out["seen"] == expected
    out["captions_follow"] = all(c.startswith(i + " ") for i, c in zip(out["seen"], out["captions"]))
print(json.dumps(out, indent=1, ensure_ascii=False))
sys.exit(0 if out["order_is_the_flow"] and out["captions_follow"] and not out["errors"] else 1)
