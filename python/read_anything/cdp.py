"""Minimal Chrome DevTools Protocol client.

Why this exists: everything interesting (Handshake, LinkedIn in-app search) sits
behind a login. Instead of copying cookies or reverse-engineering CSRF, we drive
a real Chrome that is already logged in, and run fetch() *inside the page* so the
request carries the browser's own cookies, headers and CSRF token.

Dependencies: websocket-client (pip install websocket-client).
"""

from __future__ import annotations

import itertools
import json
import time
import urllib.parse
import urllib.request

import websocket


class CDPError(RuntimeError):
    pass


class Chrome:
    """Talks to a Chrome started with --remote-debugging-port."""

    def __init__(self, port: int = 9222, host: str = "127.0.0.1", timeout: int = 30):
        self.port = port
        self.host = host
        self.timeout = timeout
        self.ws = None
        self.events: list[dict] = []
        self._ids = itertools.count(1)

    # ---------------------------------------------------------------- HTTP side
    def _request(self, path: str, method: str = "GET"):
        url = f"http://{self.host}:{self.port}{path}"
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}

    def version(self) -> dict:
        return self._request("/json/version")

    def targets(self) -> list[dict]:
        return self._request("/json/list")

    def pages(self) -> list[dict]:
        return [t for t in self.targets() if t.get("type") == "page"]

    def wait_ready(self, tries: int = 60) -> dict:
        last = None
        for _ in range(tries):
            try:
                return self.version()
            except Exception as exc:  # port not open yet
                last = exc
                time.sleep(0.25)
        raise CDPError(f"Chrome debug port {self.port} is not responding: {last}")

    def new_tab(self, url: str = "about:blank") -> dict:
        # Newer Chrome only allows PUT on /json/new.
        return self._request("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")

    def close_tab(self, target_id: str) -> None:
        try:
            self._request(f"/json/close/{target_id}", method="PUT")
        except Exception:
            pass

    # ------------------------------------------------------------ websocket side
    def connect(self, ws_url: str | None = None) -> "Chrome":
        if ws_url is None:
            pages = self.pages()
            if not pages:
                raise CDPError("no page target to attach to")
            ws_url = pages[0]["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(
            ws_url,
            timeout=self.timeout,
            max_size=64 * 1024 * 1024,
            suppress_origin=True,  # Chrome rejects foreign Origin headers by default
        )
        return self

    def call(self, method: str, params: dict | None = None) -> dict:
        if self.ws is None:
            raise CDPError("not connected; call .connect() first")
        msg_id = next(self._ids)
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv()
            if not raw:
                raise CDPError("websocket closed")
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise CDPError(f"{method}: {data['error']}")
                return data.get("result", {})
            # anything else is an event: keep it, the caller may want it
            if "method" in data:
                self.events.append(data)
                if len(self.events) > 20000:
                    del self.events[:10000]

    # ------------------------------------------------------------------ helpers
    def goto(self, url: str, wait: str = "complete", timeout_s: float = 30.0) -> bool:
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url})
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if self.eval("document.readyState") == wait:
                    return True
            except CDPError:
                pass
            time.sleep(0.3)
        return False

    def eval(self, expression: str, await_promise: bool = True):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
                "timeout": 30_000,
            },
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            desc = (details.get("exception") or {}).get("description") or json.dumps(details)
            raise CDPError(desc)
        return result.get("result", {}).get("value")

    def fetch_text(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str | None = None,
    ) -> dict:
        """Run fetch() in the page context: same origin, real cookies, no CORS."""
        opts = {
            "method": method,
            "credentials": "include",
            "headers": headers or {},
        }
        if body is not None:
            opts["body"] = body
        script = (
            "(async () => {"
            f"  const r = await fetch({json.dumps(url)}, {json.dumps(opts)});"
            "  const text = await r.text();"
            "  return {status: r.status, url: r.url, body: text.slice(0, 500000)};"
            "})()"
        )
        return self.eval(script)

    def fetch_json(self, url: str, method: str = "GET", headers: dict | None = None,
                   body: str | None = None) -> dict:
        out = self.fetch_text(url, method=method, headers=headers, body=body)
        try:
            out["json"] = json.loads(out["body"])
        except Exception:
            out["json"] = None
        return out

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            finally:
                self.ws = None
