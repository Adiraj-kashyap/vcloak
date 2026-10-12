"""ISSUE-31 point 1: why test_a_withheld_message_is_flagged_in_the_pane fails now and then.

    python runs/<dir>/withheld_repro.py runs/<dir> [trials]

Hypothesis: the hook of the test withholds "the next message B has not seen", decided at the first fetch
that returns something new. A pane fetches its windows newest first, so when the two messages after the
first one fall into different windows and B reads them in one pass, the hook withholds the LAST message
("the one after it") and B is shown "the withheld one". A missing last message cannot be noticed until a
later one arrives, so no alert comes: the test is wrong, not the pane.

Each trial uses the hook of the test unchanged (plus a log of what it saw) and places the two sends on
either side of a window boundary; B's own timer is the page's. Nothing is measured.
"""
import json
import sys
import time
from pathlib import Path

sys.path[:0] = ["src", "scripts", "tests"]
from demo_two_users import LocalServer  # noqa: E402
from headless import Browser  # noqa: E402
from integration.test_web_app import ARGV, WINDOW_S, session_config  # noqa: E402

run = Path(sys.argv[1])
trials = int(sys.argv[2]) if len(sys.argv) > 2 else 8
HOOK = """(() => {
    const c = VC.chat.panes.B.client, fetch = c._fetch.bind(c);
    let skip = null;
    window.__seen = [];
    c._fetch = win => fetch(win).then(payloads => {
        const done = c.conv.consumed[win] || 0;
        if (!skip && payloads.length > done) { skip = {win: win, index: done}; window.__skip = skip; }
        window.__seen.push({win: win, held: payloads.length, done: done});
        return skip && skip.win === win ? payloads.filter((_, i) => i !== skip.index) : payloads;
    });
    return true; })()"""
out = {"serve_argv": ARGV, "trials": []}
with Browser() as b, LocalServer(ARGV, config=session_config()) as s:
    out["browser"] = b.version
    for _ in range(trials):
        p = b.page(s.base + "/app/")
        p.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.panes.A)", timeout=20)
        assert p.evaluate("VC.chat.ready()") is True
        p.evaluate("VC.chat.send('A', 'the first one')")
        p.wait_for("VC.chat.transcript('B').some(m => m.text === 'the first one')", timeout=20)
        p.evaluate(HOOK)
        # the second message just before a window boundary, the third just after it
        while not (WINDOW_S - 0.45 < time.time() % WINDOW_S < WINDOW_S - 0.35):
            time.sleep(0.01)
        p.evaluate("VC.chat.send('A', 'the withheld one')")
        while time.time() % WINDOW_S > WINDOW_S / 2:
            time.sleep(0.01)
        p.evaluate("VC.chat.send('A', 'the one after it')")
        p.wait_for("VC.chat.transcript('A').some(m => m.text === 'the one after it')", timeout=20)
        time.sleep(6)  # six reads of B
        wins = {m["text"]: m["win"] for m in p.evaluate("VC.chat.transcript('A')")}
        t = {
            "windows_apart": wins["the one after it"] - wins["the withheld one"],
            "hook_withheld_window": p.evaluate("window.__skip && window.__skip.win") - wins["the withheld one"],
            "first_fetches_with_something_new": [
                {"win": f["win"] - wins["the withheld one"], "held": f["held"], "done": f["done"]}
                for f in p.evaluate("window.__seen") if f["held"] > f["done"]][:3],
            "B_shows": [m["text"] for m in p.evaluate("VC.chat.transcript('B')")],
            "B_alert_shown": not p.evaluate("document.getElementById('alertB').hidden"),
        }
        t["case"] = ("the hook withheld the last message: B shows 'the withheld one', no alert"
                     if "the withheld one" in t["B_shows"] and not t["B_alert_shown"] else
                     "the hook withheld the middle message: alert" if t["B_alert_shown"] else "other")
        out["trials"].append(t)
        p.close()
straddled = [t for t in out["trials"] if t["windows_apart"] == 1]
out["summary"] = {
    "trials": trials, "sends_in_two_windows": len(straddled),
    "of_those_no_alert_and_last_message_withheld": sum(t["case"].startswith("the hook withheld the last") for t in straddled),
    "of_those_alert": sum(t["B_alert_shown"] for t in straddled),
    "same_window_trials_with_alert": sum(t["B_alert_shown"] for t in out["trials"] if t["windows_apart"] == 0),
}
(run / "withheld_repro.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out["summary"], indent=1))
for t in out["trials"]:
    print(t["windows_apart"], t["hook_withheld_window"], t["B_alert_shown"], t["B_shows"])
