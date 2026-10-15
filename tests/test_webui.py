"""Tests der Weboberfläche: lokaler Server, Sicherheit (Schlüssel/Host), Export über HTTP."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from dcexport import model  # noqa: E402
from dcexport.webui import WebApp  # noqa: E402
from mock_discord import TOKEN, USER_TOKEN, MockDiscord  # noqa: E402


class WebClient:
    def __init__(self, app: WebApp):
        self.base = f"http://127.0.0.1:{app.port}"
        self.key = app.key

    def request(self, method: str, path: str, body=None, key=None, host=None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-DCE-Key": self.key if key is None else key}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if host:
            headers["Host"] = host
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else {}
        except (urllib.error.URLError, OSError) as err:
            if not isinstance(err, urllib.error.HTTPError):
                raise

            raw = err.read()
            try:
                return err.code, json.loads(raw) if raw else {}
            except ValueError:
                return err.code, {"_raw": raw[:200]}

    def wait_idle(self, timeout=30) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, state = self.request("GET", "/api/state?log_since=0")
            if not state.get("busy"):
                return state
            time.sleep(0.05)
        raise AssertionError("Vorgang wurde nicht fertig")


class WebTests(unittest.TestCase):
    def setUp(self):
        self.mock = MockDiscord().__enter__()
        self._cdn = (model.CDN, model.MEDIA_CDN)
        model.CDN = model.MEDIA_CDN = self.mock.base
        os.environ["APPDATA"] = tempfile.mkdtemp()
        self.app = WebApp(port=0, api_base=self.mock.api)
        import threading
        self.thread = threading.Thread(target=lambda: self.app.serve(open_browser=False, watchdog=False),
                                       daemon=True)
        self.thread.start()
        self.c = self.client()
        for _ in range(200):
            try:
                status, _ = self.c.request("GET", "/api/state?log_since=0")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.02)

    def tearDown(self):
        self.app.httpd.shutdown()
        model.CDN, model.MEDIA_CDN = self._cdn
        self.mock.__exit__(None, None, None)

    def client(self) -> WebClient:
        return WebClient(self.app)

    # -------------------------------------------------------- Sicherheit

    def test_requires_session_key(self):
        status, body = self.c.request("GET", "/api/state", key="falsch")
        self.assertEqual(status, 403)
        self.assertIn("Sitzung", body["error"])

    def test_rejects_foreign_host(self):
        # DNS-Rebinding: fremder Host-Header wird abgewiesen
        status, _ = self.c.request("GET", "/api/state", host="angreifer.example")
        self.assertEqual(status, 403)
        status, _ = self.c.request("GET", "/api/state", host=f"127.0.0.1:{self.app.port}")
        self.assertEqual(status, 200)

    def test_ping_alive(self):
        status, _ = self.c.request("POST", "/api/ping", {})
        self.assertEqual(status, 200)

    # ------------------------------------------------------------ Ablauf

    def test_connect_user_lists_dms(self):
        status, _ = self.c.request("POST", "/api/connect",
                                   {"mode": "user", "token": USER_TOKEN, "accepted_risk": True})
        self.assertEqual(status, 200)
        self.c.wait_idle()
        _, tree = self.c.request("GET", "/api/tree")
        names = {n["name"] for n in tree["api"]}
        self.assertIn("Direktnachrichten", names)
        dm = next(n for n in tree["api"] if n["name"] == "Direktnachrichten")
        self.assertTrue(any("misty" in c["name"] for c in dm["children"]))

    def test_user_risk_must_be_accepted(self):
        status, body = self.c.request("POST", "/api/connect",
                                      {"mode": "user", "token": USER_TOKEN, "accepted_risk": False})
        self.assertEqual(status, 400)
        self.assertIn("eigenen Konto", body["error"])

    def test_full_export_flow(self):
        out = Path(tempfile.mkdtemp()) / "export"
        self.c.request("POST", "/api/connect", {"mode": "bot", "token": TOKEN, "accepted_risk": False})
        self.c.wait_idle()
        _, tree = self.c.request("GET", "/api/tree")
        guild = next(n for n in tree["api"] if n["kind"] == "guild")
        channel_ids = [c["id"] for c in _flatten(guild) if c["kind"] == "channel"]
        self.assertTrue(channel_ids)
        status, _ = self.c.request("POST", "/api/export", {
            "source": "api", "ids": channel_ids,
            "options": {"formats": ["html", "json"], "out_dir": str(out), "download_media": True,
                        "include_threads": True, "from": "", "to": "", "csv_delimiter": ";"},
        })
        self.assertEqual(status, 200)
        state = self.c.wait_idle(60)
        result = state["result"]
        self.assertIsNotNone(result)
        self.assertFalse(result["errors"], result["errors"])
        self.assertGreater(result["messages"], 200)
        self.assertEqual(len(result["protocol"]), 2)
        self.assertTrue(result["sums_hash"])
        self.assertTrue((out / "CollectnTrade Community").is_dir())
        # Öffnen ist nur für Dateien aus dem Export erlaubt
        status, _ = self.c.request("POST", "/api/open", {"path": result["protocol"][0]})
        self.assertIn(status, (200, 500))  # 500 nur, wenn kein Dateimanager vorhanden (headless)
        status, body = self.c.request("POST", "/api/open", {"path": "/etc/passwd"})
        self.assertEqual(status, 403)

    def test_export_needs_selection(self):
        self.c.request("POST", "/api/connect", {"mode": "bot", "token": TOKEN})
        self.c.wait_idle()
        status, body = self.c.request("POST", "/api/export", {
            "source": "api", "ids": [], "options": {"formats": ["json"], "out_dir": "/tmp/x"}})
        self.assertEqual(status, 400)


def _flatten(node) -> list:
    out = [node]
    for child in node.get("children") or []:
        out += _flatten(child)
    return out


if __name__ == "__main__":
    unittest.main()
