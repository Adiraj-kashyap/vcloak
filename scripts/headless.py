"""A headless browser for the web app: Chrome or Edge, driven over the DevTools protocol.

No Playwright and no download: it starts the browser that is already installed, with a throw-away
profile, and talks to it over its debugging socket (`websockets` is already a dependency of the
service). Used by tests/integration/test_web_app.py and by scripts/capture_evidence.py.

    with Browser() as browser:
        page = browser.page("http://127.0.0.1:8000/app/")
        page.wait_for("document.readyState === 'complete'")
        page.evaluate("VC.chat.send('A', 'hi')")     # a promise is awaited; the value comes back as JSON
        page.screenshot("chat.png")

`VCLOAK_BROWSER` names another executable. `find_browser()` is None when there is none.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
ON_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")


class PageError(RuntimeError):
    """The page threw, or an expression did not become true in time."""


def find_browser() -> Path | None:
    named = os.environ.get("VCLOAK_BROWSER")
    if named:
        return Path(named) if Path(named).is_file() else None
    for c in CANDIDATES:
        if Path(c).is_file():
            return Path(c)
    for name in ON_PATH:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


class Page:
    def __init__(self, ws_url: str) -> None:
        from websockets.sync.client import connect

        self._conn = connect(ws_url, max_size=None, open_timeout=30)
        self._ws = self._conn.__enter__()
        self._id = 0
        self.problems: list[str] = []  # uncaught exceptions, console errors, blocked requests, CSP reports
        for domain in ("Runtime", "Log", "Page", "Network"):
            self.call(f"{domain}.enable")

    def _note(self, msg: dict[str, Any]) -> None:
        method, p = msg.get("method"), msg.get("params", {})
        if method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.problems.append("exception: " + str(d.get("exception", {}).get("description") or d.get("text")))
        elif method == "Runtime.consoleAPICalled" and p.get("type") == "error":
            self.problems.append("console.error: " + " ".join(str(a.get("value", a.get("description", "")))
                                                              for a in p.get("args", [])))
        elif method == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            e = p["entry"]
            self.problems.append(f"log: {e.get('text')} {e.get('url', '')}".strip())

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
        self._id += 1
        mine = self._id
        self._ws.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise PageError(f"{method}: no answer in {timeout:.0f} s")
            try:
                msg = json.loads(self._ws.recv(timeout=left))
            except TimeoutError:
                continue
            if msg.get("id") == mine:
                if "error" in msg:
                    raise PageError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            self._note(msg)

    def evaluate(self, expression: str, timeout: float = 60.0) -> Any:
        """The JSON value of `expression`; a promise is awaited. A rejection or a throw raises PageError."""
        r = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True,
                                           "userGesture": True}, timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise PageError(str(d.get("exception", {}).get("description") or d.get("text")))
        return r.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 30.0, poll_s: float = 0.1) -> Any:
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            try:
                last = self.evaluate(expression, timeout=max(1.0, deadline - time.monotonic()))
            except PageError as e:
                last = e
            else:
                if last:
                    return last
            time.sleep(poll_s)
        raise PageError(f"not true after {timeout:.0f} s: {expression} (last: {last!r})")

    def set_viewport(self, width: int, height: int) -> None:
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def screenshot(self, path: str | Path, *, full_page: bool = True) -> Path:
        r = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full_page})
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(r["data"]))
        return out

    def close(self) -> None:
        try:
            self.call("Page.close", timeout=5)
        except Exception:  # noqa: BLE001 - the socket may already be gone
            pass
        self._conn.__exit__(None, None, None)

    def errors(self) -> list[str]:
        """`problems` without the browser's note of an HTTP status the page handled ("Failed to load
        resource: … 401"): what is left is an exception, a console error or a request the CSP blocked."""
        return [p for p in self.problems if not p.startswith("log: Failed to load resource: the server responded")]


class Browser:
    def __init__(self, executable: Path | None = None, *, width: int = 1440, height: int = 900) -> None:
        exe = executable or find_browser()
        if exe is None:
            raise FileNotFoundError("no Chrome or Edge found; set VCLOAK_BROWSER")
        self.executable = exe
        self._profile = Path(tempfile.mkdtemp(prefix="vcloak-browser-"))
        self._proc = subprocess.Popen(  # noqa: S603 - the installed browser, fixed arguments
            [str(exe), "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self._profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-gpu",
             "--disable-background-networking", "--hide-scrollbars", f"--window-size={width},{height}",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = self._profile / "DevToolsActivePort"
        deadline = time.monotonic() + 60
        while not port_file.is_file() or not port_file.read_text().strip():
            if self._proc.poll() is not None or time.monotonic() > deadline:
                self.close()
                raise RuntimeError("the browser did not open its debugging port")
            time.sleep(0.05)
        self.port = int(port_file.read_text().split()[0])
        self.version = self._get("/json/version").get("Browser", "")

    def _get(self, path: str, method: str = "GET") -> dict[str, Any]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)  # noqa: S310 - loopback
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read())

    def page(self, url: str = "about:blank") -> Page:
        target = self._get("/json/new?" + url, method="PUT")
        return Page(target["webSocketDebuggerUrl"])

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        for _ in range(20):  # the profile is released a moment after the process ends
            shutil.rmtree(self._profile, ignore_errors=True)
            if not self._profile.exists():
                break
            time.sleep(0.1)

    def __enter__(self) -> Browser:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
