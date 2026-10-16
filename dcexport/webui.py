"""Lokale Weboberfläche: kleiner HTTP-Server nur auf 127.0.0.1, die Oberfläche läuft im Browser.

Sicherheit: Jede API-Anfrage braucht den Sitzungsschlüssel aus der Start-URL (Kopfzeile
X-DCE-Key) und einen Host-Header 127.0.0.1/localhost mit dem richtigen Port. Andere
Webseiten im selben Browser kommen so nicht an die API (kein CORS, Schutz gegen
DNS-Rebinding). Tokens bleiben nur im Speicher dieses Prozesses.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import APP_NAME, __version__
from .api import DiscordClient
from .exporter import DM_GUILD_ID, ApiExporter, GuildData, PackageExporter, Summary
from .model import CHANNEL_TYPES, ExportOptions, guild_icon_url
from .package import DataPackage
from .protocol import sha256_file
from .settings import default_out_dir, load_settings, open_path, save_settings
from .util import date_range_to_utc, parse_date_input
from .writers import FORMATS

DIST = Path(__file__).resolve().parent / "web_dist"
MAX_BODY = 1024 * 1024
IDLE_SHUTDOWN = 180  # Sekunden ohne Lebenszeichen der Oberfläche → Server beendet sich
CSV_DELIMS = {";": ";", ",": ",", "tab": "\t"}

DIALOG_SCRIPT = r"""
import sys, tkinter as tk
from tkinter import filedialog
kind, initial = sys.argv[1], sys.argv[2]
root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True); root.update()
opts = {"parent": root, "initialdir": initial or None}
if kind == "zip":
    path = filedialog.askopenfilename(title="Discord-Datenpaket wählen",
                                      filetypes=[("ZIP-Archiv", "*.zip"), ("Alle Dateien", "*.*")], **opts)
elif kind == "package_dir":
    path = filedialog.askdirectory(title="Entpacktes Datenpaket wählen", **opts)
else:
    path = filedialog.askdirectory(title="Zielordner wählen", **opts)
root.destroy()
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class State:
    """Alles, was die Oberfläche sieht. Zugriff nur unter self.lock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.settings = load_settings()
        self.logs: list[tuple[int, str]] = []
        self.log_seq = 0
        self.busy: str | None = None
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: dict | None = None
        self.cancel = threading.Event()
        self.api: ApiExporter | None = None
        self.api_mode: str | None = None
        self.package: DataPackage | None = None
        self.tree_rev = 0
        self.last_ping = time.monotonic()
        self.allowed_open: set[str] = set()

    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            for line in str(text).splitlines() or [""]:
                self.log_seq += 1
                self.logs.append((self.log_seq, f"{stamp}  {line}"))
            del self.logs[:-2000]

    # ------------------------------------------------------------- Ausgabe

    def snapshot(self, log_since: int) -> dict:
        with self.lock:
            api = None
            if self.api and self.api.bot_user:
                me = self.api.bot_user
                api = {"mode": self.api_mode, "name": me.get("global_name") or me.get("username"),
                       "username": me.get("username"), "id": me.get("id")}
            package = None
            if self.package:
                convs = self.package.conversations()
                package = {"name": self.package.author["display_name"], "path": str(self.package.path),
                           "conversations": len(convs), "messages": sum(c.message_count for c in convs)}
            return {
                "app": APP_NAME, "version": __version__,
                "busy": self.busy, "progress": self.progress,
                "logs": [{"seq": s, "text": t} for s, t in self.logs if s > log_since],
                "log_seq": self.log_seq, "tree_rev": self.tree_rev,
                "api": api, "package": package,
                "result": self.result, "error": self.error,
                "settings": self.public_settings(),
                "formats": [{"key": k, "label": v[0], "ext": v[1]} for k, v in FORMATS.items()],
            }

    def public_settings(self) -> dict:
        s = self.settings
        return {
            "out_dir": s.get("out_dir") or default_out_dir(),
            "formats": s.get("formats") or ["html", "json", "txt"],
            "download_media": s.get("download_media", True),
            "include_threads": s.get("include_threads", True),
            "csv_delimiter": s.get("csv_delimiter_key", ";"),
            "package_path": s.get("package_path", ""),
        }

    def tree(self) -> dict:
        with self.lock:
            return {"rev": self.tree_rev, "api": self._api_tree(), "package": self._package_tree()}

    def _api_tree(self) -> list[dict]:
        if not self.api:
            return []
        nodes = []
        for gd in self.api.guilds.values():
            if gd.guild["id"] == DM_GUILD_ID:
                nodes.append({"key": "dm", "kind": "dms", "name": "Direktnachrichten", "loaded": True,
                              "children": [_channel_node(ch) for ch in gd.channels]})
                continue
            children: list[dict] = []
            cats: dict[str, dict] = {}
            for ch in gd.channels:
                if ch.category:
                    if ch.category not in cats:
                        cats[ch.category] = {"key": f"cat:{gd.guild['id']}:{ch.category}", "kind": "category",
                                             "name": ch.category, "children": []}
                        children.append(cats[ch.category])
                    cats[ch.category]["children"].append(_channel_node(ch))
                else:
                    children.append(_channel_node(ch))
            nodes.append({"key": f"g:{gd.guild['id']}", "id": gd.guild["id"], "kind": "guild",
                          "name": gd.guild.get("name") or gd.guild["id"], "icon": guild_icon_url(gd.guild),
                          "loaded": gd.loaded, "children": children})
        return nodes

    def _package_tree(self) -> list[dict]:
        if not self.package:
            return []
        groups: dict[str, dict] = {}
        for conv in self.package.conversations():
            if conv.group not in groups:
                groups[conv.group] = {"key": f"pg:{conv.group}", "kind": "group", "name": conv.group,
                                      "loaded": True, "children": []}
            groups[conv.group]["children"].append({
                "key": f"p:{conv.info.id}", "id": conv.info.id, "kind": "channel", "name": conv.info.name,
                "type_label": CHANNEL_TYPES.get(conv.info.type, ""), "dm": conv.info.is_dm,
                "count": conv.message_count,
            })
        return list(groups.values())


def _channel_node(ch) -> dict:
    return {"key": f"c:{ch.id}", "id": ch.id, "kind": "channel", "name": ch.name, "type": ch.type,
            "type_label": CHANNEL_TYPES.get(ch.type, str(ch.type)), "dm": ch.is_dm,
            "forum": ch.type in (15, 16), "voice": ch.type in (2, 13), "icon": ch.icon_url}


class Backend:
    """Führt die Aufträge der Oberfläche in Hintergrund-Threads aus (immer nur einer zugleich)."""

    def __init__(self, state: State, api_base: str | None = None):
        self.s = state
        self.api_base = api_base

    def _start(self, kind: str, target, *args) -> None:
        with self.s.lock:
            if self.s.busy:
                raise ApiError("Es läuft bereits ein Vorgang.", 409)
            self.s.busy = kind
            self.s.error = None
            self.s.progress = {}
            self.s.cancel.clear()

        def run() -> None:
            try:
                target(*args)
            except Exception as err:  # noqa: BLE001 – Fehler gehen an die Oberfläche
                message = str(err) or err.__class__.__name__
                if err.__class__.__name__ == "Cancelled":
                    message = "Abgebrochen."
                self.s.log(f"Fehler: {message}")
                if not isinstance(err, (ValueError, OSError)) and err.__class__.__name__ not in (
                        "DiscordAPIError", "Cancelled"):
                    self.s.log(traceback.format_exc())
                with self.s.lock:
                    self.s.error = {"kind": kind, "message": message}
            finally:
                with self.s.lock:
                    self.s.busy = None

        threading.Thread(target=run, daemon=True, name=f"dce-{kind}").start()

    # ----------------------------------------------------------- Aufträge

    def connect(self, body: dict) -> None:
        mode = body.get("mode")
        token = str(body.get("token") or "").strip()
        if mode not in ("bot", "user"):
            raise ApiError("Unbekannter Anmeldemodus.")
        if not token:
            raise ApiError("Bitte einen Token eintragen.")
        if mode == "user" and body.get("accepted_risk") is not True:
            raise ApiError("Der Hinweis zum eigenen Konto muss bestätigt werden.")
        self._start("connect", self._connect, mode, token)

    def _connect(self, mode: str, token: str) -> None:
        kwargs = {"base_url": self.api_base} if self.api_base else {}
        client = DiscordClient(token, user_token=mode == "user", log=self.s.log, cancel=self.s.cancel, **kwargs)
        exporter = ApiExporter(client, log=self.s.log)
        self.s.log("Verbinde mit Discord …")
        exporter.connect(load_channels=mode == "bot")
        me = exporter.bot_user or {}
        with self.s.lock:
            self.s.api, self.s.api_mode = exporter, mode
            self.s.tree_rev += 1
        dms = len(exporter.guilds.get(DM_GUILD_ID, GuildData({}, [], {})).channels)
        servers = sum(1 for gid in exporter.guilds if gid != DM_GUILD_ID)
        self.s.log(f"Verbunden als {me.get('username', '?')}: {servers} Server"
                   + (f", {dms} Direktnachrichten" if mode == "user" else "") + ".")

    def disconnect(self) -> None:
        with self.s.lock:
            if self.s.busy:
                raise ApiError("Erst den laufenden Vorgang abwarten.", 409)
            self.s.api, self.s.api_mode = None, None
            self.s.tree_rev += 1
        self.s.log("Abgemeldet. Der Token ist aus dem Speicher entfernt.")

    def load_guild(self, body: dict) -> None:
        gid = str(body.get("guild_id") or "")
        if not self.s.api or gid not in self.s.api.guilds:
            raise ApiError("Server unbekannt.")
        self._start("load_guild", self._load_guild, gid)

    def _load_guild(self, gid: str) -> None:
        gd = self.s.api.load_guild(gid)
        with self.s.lock:
            self.s.tree_rev += 1
        self.s.log(f"{gd.guild.get('name', gid)}: {len(gd.channels)} Kanäle geladen.")

    def load_package(self, body: dict) -> None:
        path = str(body.get("path") or "").strip().strip('"')
        if not path:
            raise ApiError("Bitte package.zip oder den entpackten Ordner wählen.")
        self._start("package", self._load_package, path)

    def _load_package(self, path: str) -> None:
        self.s.log(f"Lese Datenpaket {path} …")
        pkg = DataPackage(path)
        convs = pkg.conversations()
        with self.s.lock:
            if self.s.package:
                self.s.package.close()
            self.s.package = pkg
            self.s.settings["package_path"] = path
            self.s.tree_rev += 1
        save_settings(self.s.settings)
        self.s.log(f"Datenpaket geladen: {len(convs)} Unterhaltungen von {pkg.author['display_name']}.")

    def export(self, body: dict) -> None:
        source = body.get("source")
        ids = [str(i) for i in body.get("ids") or []]
        options = self._options(body.get("options") or {})
        if not ids:
            raise ApiError("Bitte mindestens einen Kanal oder eine Unterhaltung anhaken.")
        if source == "api":
            if not self.s.api:
                raise ApiError("Nicht verbunden.")
            known = {ch.id: ch for gd in self.s.api.guilds.values() for ch in gd.channels}
            selected = [known[i] for i in ids if i in known]
            exporter = self.s.api
        elif source == "package":
            if not self.s.package:
                raise ApiError("Kein Datenpaket geladen.")
            known = {c.info.id: c for c in self.s.package.conversations()}
            selected = [known[i] for i in ids if i in known]
            exporter = PackageExporter(self.s.package, log=self.s.log)
        else:
            raise ApiError("Unbekannte Quelle.")
        if not selected:
            raise ApiError("Die Auswahl passt nicht mehr zur Liste. Bitte neu auswählen.")
        with self.s.lock:
            self.s.result = None
        self._start("export", self._export, exporter, selected, options)

    def _options(self, raw: dict) -> ExportOptions:
        formats = {f for f in raw.get("formats") or [] if f in FORMATS}
        if not formats:
            raise ApiError("Bitte mindestens ein Format wählen.")
        try:
            after, before = date_range_to_utc(parse_date_input(raw.get("from") or ""),
                                              parse_date_input(raw.get("to") or ""))
        except ValueError as err:
            raise ApiError(str(err)) from err
        out_dir = str(raw.get("out_dir") or "").strip().strip('"')
        if not out_dir:
            raise ApiError("Bitte einen Zielordner wählen.")
        delim_key = raw.get("csv_delimiter") if raw.get("csv_delimiter") in CSV_DELIMS else ";"
        options = ExportOptions(out_dir=out_dir, formats=formats, after=after, before=before,
                                download_media=bool(raw.get("download_media", True)),
                                include_threads=bool(raw.get("include_threads", True)),
                                csv_delimiter=CSV_DELIMS[delim_key])
        with self.s.lock:
            self.s.settings.update({"out_dir": out_dir, "formats": sorted(formats),
                                    "download_media": options.download_media,
                                    "include_threads": options.include_threads,
                                    "csv_delimiter_key": delim_key})
        save_settings(self.s.settings)
        return options

    def _export(self, exporter, selected, options: ExportOptions) -> None:
        if isinstance(exporter, ApiExporter):
            exporter.client.cancel = self.s.cancel

        def progress(index: int, total: int, fraction: float, label: str) -> None:
            with self.s.lock:
                self.s.progress = {"index": index, "total": total, "fraction": fraction, "label": label,
                                   "overall": (index + fraction) / total if total else 1.0}

        self.s.log(f"Export von {len(selected)} Auswahl(en) nach {options.out_dir} …")
        summary: Summary = exporter.export(selected, options, progress=progress, cancel=self.s.cancel)
        self.s.log(summary.text())
        html = [f for f in summary.files if f.endswith(".html")]
        sums_hash = None
        if len(summary.protocol_files) == 2:
            try:
                sums_hash = sha256_file(Path(summary.protocol_files[1]))
            except OSError:
                pass
        allowed = {str(Path(options.out_dir).resolve())} | {str(Path(f).resolve()) for f in
                                                            summary.files + summary.protocol_files}
        with self.s.lock:
            self.s.allowed_open |= allowed
            self.s.result = {
                "text": summary.text(), "channels": summary.channels, "messages": summary.messages,
                "files": len(summary.files), "media_ok": summary.media_ok, "media_total": summary.media_total, "media_failed": summary.media_failed,
                "skipped": summary.skipped_items, "errors": summary.errors, "cancelled": summary.cancelled,
                "out_dir": options.out_dir, "protocol": summary.protocol_files, "html": html[:50],
                "sums_hash": sums_hash,
            }

    def cancel(self) -> None:
        self.s.cancel.set()
        self.s.log("Breche ab …")

    # --------------------------------------------------------------- Helfer

    def dialog(self, body: dict) -> dict:
        kind = body.get("kind") if body.get("kind") in ("zip", "package_dir", "out_dir") else "out_dir"
        initial = str(body.get("initial") or "")
        flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
        try:
            done = subprocess.run([sys.executable, "-c", DIALOG_SCRIPT, kind, initial], capture_output=True,
                                  timeout=900, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise ApiError(f"Dateiauswahl nicht möglich: {err}") from err
        path = done.stdout.decode("utf-8", errors="replace").strip()
        return {"path": path or None}

    def open(self, body: dict) -> None:
        raw = str(body.get("path") or "")
        target = Path(raw).resolve()
        with self.s.lock:
            allowed = set(self.s.allowed_open)
            allowed.add(str(Path(self.s.public_settings()["out_dir"]).resolve()))
        if not any(target == Path(a) or target.is_relative_to(Path(a)) for a in allowed):
            raise ApiError("Nur Dateien und Ordner aus dem Export lassen sich öffnen.", 403)
        if not target.exists():
            if str(target) in allowed:
                target.mkdir(parents=True, exist_ok=True)
            else:
                raise ApiError("Nicht gefunden.", 404)
        try:
            open_path(str(target))
        except OSError as err:
            raise ApiError(f"Konnte nicht geöffnet werden: {err}", 500) from err


class Handler(BaseHTTPRequestHandler):
    server_version = f"DiscordExport/{__version__}"
    app: "WebApp"

    def log_message(self, *args) -> None:  # kein Zugriffslog in der Konsole
        pass

    # ---------------------------------------------------------------- Kern

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _host_ok(self) -> bool:
        port = self.app.port
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _authorized(self) -> bool:
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-DCE-Key", ""), self.app.key)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError("Anfrage zu groß.", 413)
        if not length:
            return {}
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError("Nur JSON.", 415)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as err:
            raise ApiError("Ungültiges JSON.") from err
        if not isinstance(data, dict):
            raise ApiError("Ungültige Anfrage.")
        return data

    # ------------------------------------------------------------- Routen

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            return self._api("GET", url)
        if not self._host_ok():
            return self._send(421, b"Falscher Host", "text/plain; charset=utf-8")
        return self._static(url.path)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._send(404, b"", "text/plain")
        return self._api("POST", url)

    def _api(self, method: str, url) -> None:
        if not self._authorized():
            return self._json(403, {"error": "Sitzung ungültig. Bitte das Programm neu starten."})
        app, state, backend = self.app, self.app.state, self.app.backend
        state.last_ping = time.monotonic()
        try:
            route = (method, url.path)
            if route == ("GET", "/api/state"):
                since = int((parse_qs(url.query).get("log_since") or ["0"])[0] or 0)
                return self._json(200, state.snapshot(since))
            if route == ("GET", "/api/tree"):
                return self._json(200, state.tree())
            body = self._body() if method == "POST" else {}
            actions = {
                "/api/connect": lambda: backend.connect(body),
                "/api/disconnect": backend.disconnect,
                "/api/load-guild": lambda: backend.load_guild(body),
                "/api/package": lambda: backend.load_package(body),
                "/api/export": lambda: backend.export(body),
                "/api/cancel": backend.cancel,
                "/api/open": lambda: backend.open(body),
                "/api/ping": lambda: None,
                "/api/quit": app.request_shutdown,
            }
            if method == "POST" and url.path == "/api/dialog":
                return self._json(200, backend.dialog(body))
            if method == "POST" and url.path in actions:
                actions[url.path]()
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "Unbekannte Aktion."})
        except ApiError as err:
            return self._json(err.status, {"error": str(err)})

    def _static(self, path: str) -> None:
        if not DIST.is_dir():
            msg = ("<h1>Oberfläche nicht gefunden</h1><p>Der Ordner dcexport/web_dist fehlt. "
                   "Alternative: <code>py -3 discord_export.py tk</code></p>")
            return self._send(500, msg.encode("utf-8"), "text/html; charset=utf-8")
        rel = path.lstrip("/") or "index.html"
        target = (DIST / rel).resolve()
        if DIST not in target.parents and target != DIST or not target.is_file():
            target = DIST / "index.html"
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        extra = {"Cache-Control": "no-cache"}
        if target.name == "index.html":
            extra["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https://cdn.discordapp.com; font-src 'self'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self._send(200, target.read_bytes(), ctype, extra)


class WebApp:
    def __init__(self, port: int = 0, api_base: str | None = None):
        self.state = State()
        self.backend = Backend(self.state, api_base=api_base)
        self.key = secrets.token_urlsafe(32)
        handler = type("BoundHandler", (Handler,), {"app": self})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#k={self.key}"

    def request_shutdown(self) -> None:
        self.state.log("Programm wird beendet.")
        threading.Thread(target=self._shutdown_soon, daemon=True).start()

    def _shutdown_soon(self) -> None:
        time.sleep(0.3)
        self.httpd.shutdown()

    def _watchdog(self) -> None:
        while not self._stop.wait(5):
            idle = time.monotonic() - self.state.last_ping
            if idle > IDLE_SHUTDOWN and not self.state.busy:
                print("Keine Verbindung zur Oberfläche mehr – beende.", flush=True)
                self.httpd.shutdown()
                return

    def serve(self, open_browser: bool = True, watchdog: bool = True) -> None:
        if watchdog:
            threading.Thread(target=self._watchdog, daemon=True).start()
        if open_browser:
            threading.Timer(0.4, lambda: webbrowser.open(self.url)).start()
        try:
            self.httpd.serve_forever(poll_interval=0.3)
        finally:
            self._stop.set()
            self.httpd.server_close()
            if self.state.package:
                self.state.package.close()


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            return 0


def main(port: int | None = None, open_browser: bool = True) -> int:
    app = WebApp(port=_free_port(8765) if port is None else port)
    line = "=" * 64
    print(f"{line}\n {APP_NAME} {__version__}\n{line}")
    print(" Die Oberfläche öffnet sich im Browser. Falls nicht, diese Adresse öffnen:")
    print(f"   {app.url}")
    print(" Dieses Fenster offen lassen, solange du das Programm nutzt.")
    print(" Beenden: im Browser oben rechts „Beenden“ oder hier Strg+C.")
    print(line, flush=True)
    try:
        app.serve(open_browser=open_browser)
    except KeyboardInterrupt:
        pass
    print("Beendet.")
    return 0
