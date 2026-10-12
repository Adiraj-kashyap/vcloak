"""M13 S6: does the epoch on the live strip follow the server's epochs, and does it stay with them?

    python scripts/strip_drift.py --run runs/<dir> [--seconds 120] [--every 2] [--epoch-ms 200]

Starts its own `vcloak serve --dev --sessions --store sqlite` on a loopback port, opens the page in headless
Chrome or Edge and, every `--every` seconds, asks the server for its epoch from inside the page and reads the
strip in the same breath. The difference between the two is written per sample to `strip_drift.json` in the
run directory, with the largest one and the difference between the first and the last sample (the drift).

This is a correctness check of the page, on the numpy engine: it measures no kernel and no service latency,
and none of its numbers is a performance result. Exit status 1 when a sample is further than `--tolerance`
epochs from the server or the server wrote no epochs while the strip counted.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The server's epoch and the strip, read in one expression: the answer arrives, then the strip is read.
# `shown` is what is on screen (repainted every 50 ms), `counted` what the page would paint at that instant.
SAMPLE_JS = """VC.api.raw('GET', '/v1/stats/live').then(r => ({
    server: r.body.epoch, last_written: r.body.last_epoch, epochs_written: r.body.epochs,
    counted: VC.strip.epoch(), shown: document.getElementById('ls-epoch').textContent,
    page_ms: performance.now()}))"""


def sample(page: Any) -> dict[str, Any]:
    return dict(page.evaluate(SAMPLE_JS))


def summarize(samples: list[dict[str, Any]], epoch_ms: int) -> dict[str, Any]:
    """Differences in epochs, strip minus server. A negative one is the strip behind the server: the
    answer was read after the server had made it."""
    diffs = [int(s["shown"]) - s["server"] for s in samples]
    counted = [s["counted"] - s["server"] for s in samples]
    first, last = samples[0], samples[-1]
    return {
        "samples": len(samples),
        "epoch_ms": epoch_ms,
        "span_page_s": round((last["page_ms"] - first["page_ms"]) / 1000, 3),
        "server_epochs_passed": last["server"] - first["server"],
        "strip_epochs_passed": int(last["shown"]) - int(first["shown"]),
        "epochs_written_meanwhile": last["epochs_written"] - first["epochs_written"],
        "shown_minus_server": {"min": min(diffs), "max": max(diffs), "first": diffs[0], "last": diffs[-1]},
        "counted_minus_server": {"min": min(counted), "max": max(counted)},
        "drift_epochs": diffs[-1] - diffs[0],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, type=Path, help="run directory to write strip_drift.json into")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--epoch-ms", type=int, default=200)
    ap.add_argument("--tolerance", type=int, default=3, help="epochs a sample may be away from the server")
    a = ap.parse_args(argv)

    from demo_two_users import LocalServer
    from headless import Browser

    serve = ["--dev", "--sessions", "--store", "sqlite", "--epoch-ms", str(a.epoch_ms)]
    samples: list[dict[str, Any]] = []
    with Browser() as browser, LocalServer(serve) as server:
        page = browser.page(server.base + "/app/")
        try:
            page.wait_for("document.readyState === 'complete' && !!(window.VC && VC.strip && VC.strip.epoch())",
                          timeout=30)
            end = time.monotonic() + a.seconds
            while True:
                samples.append(sample(page))
                if time.monotonic() >= end:
                    break
                time.sleep(a.every)
            errors = page.errors()
        finally:
            page.close()
        version = browser.version

    out = {"serve_argv": serve, "browser": version, "backend": "numpy", "tolerance_epochs": a.tolerance,
           "summary": summarize(samples, a.epoch_ms), "page_errors": errors, "samples": samples}
    s = out["summary"]
    ok = (max(abs(s["shown_minus_server"]["min"]), abs(s["shown_minus_server"]["max"])) <= a.tolerance
          and s["epochs_written_meanwhile"] > 0 and not errors)
    out["passed"] = ok
    a.run.mkdir(parents=True, exist_ok=True)
    (a.run / "strip_drift.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"passed": ok, **s}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
