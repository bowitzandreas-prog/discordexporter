"""Schlanker Discord-REST-Client für Bot-Tokens (nur Standardbibliothek).

Beachtet Rate-Limits (429 + X-RateLimit-*), wiederholt bei 5xx und lässt sich
über ein threading.Event abbrechen.
"""

from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable, Iterator

from . import __version__
from .util import datetime_to_snowflake

API_BASE = "https://discord.com/api/v10"
USER_AGENT = f"DiscordBot (https://github.com/bowitzandreas-prog/discordexporter, {__version__})"
USER_MODE_AGENT = f"DiscordExport/{__version__} (+https://github.com/bowitzandreas-prog/discordexporter)"
RESET_MARGIN = 0.05  # Sekunden Puffer nach dem Bucket-Reset

ERROR_HINTS = {
    401: "Token ungültig. Erwartet wird ein Bot-Token aus dem Developer Portal (Bot → Reset Token).",
    403: "Kein Zugriff. Dem Bot fehlen Rechte (Kanal ansehen / Nachrichtenverlauf lesen).",
    404: "Nicht gefunden (gelöscht oder Bot nicht auf dem Server).",
}
USER_ERROR_HINTS = {
    401: "Benutzer-Token ungültig oder abgelaufen (nach Abmelden oder Passwortwechsel neu holen).",
    403: "Kein Zugriff auf diesen Kanal mit deinem Konto.",
    404: "Nicht gefunden (gelöscht oder kein Zugriff).",
}


class Cancelled(Exception):
    pass


_ID_SEGMENT = re.compile(r"/\d{5,}(?=/|$)")


def route_key(path: str) -> str:
    """Routen-Schablone für Rate-Limits: /guilds/123/channels -> /guilds/:id/channels.

    Bewusst ohne Unterscheidung nach Server/Kanal: Discord begrenzt manche Routen
    (vor allem bei Benutzerkonten) über alle IDs gemeinsam. Lieber kurz zu früh warten
    als in eine Sperre laufen; 429-Antworten zählen bei Discord als ungültige Anfragen.
    """
    return _ID_SEGMENT.sub("/:id", path.split("?")[0])


class DiscordAPIError(Exception):
    def __init__(self, status: int, message: str, code: int | None = None, path: str = "",
                 hints: dict | None = None):
        self.status, self.code, self.path = status, code, path
        hint = (hints or ERROR_HINTS).get(status)
        prefix = f"HTTP {status}: " if status else ""
        super().__init__(prefix + message + (f" – {hint}" if hint else ""))


def normalize_token(token: str) -> str:
    token = (token or "").strip().strip('"').strip("'")
    if token.lower().startswith("bot "):
        token = token[4:].strip()
    return token


class DiscordClient:
    def __init__(self, token: str, *, user_token: bool = False, base_url: str = API_BASE,
                 log: Callable[[str], None] | None = None,
                 cancel: threading.Event | None = None, timeout: float = 30.0,
                 ssl_context: ssl.SSLContext | None = None):
        """user_token=True: eigenes Konto statt Bot. Verstößt gegen die Discord-Regeln (Self-Bot),
        der Nutzer muss das ausdrücklich wählen."""
        self.is_user = user_token
        self.token = normalize_token(token) if not user_token else (token or "").strip().strip('"').strip("'")
        if not self.token:
            raise ValueError("Kein Token angegeben.")
        self.base_url = base_url.rstrip("/")
        self.log = log or (lambda msg: None)
        self.cancel = cancel or threading.Event()
        self.timeout = timeout
        self.ssl_context = ssl_context
        self._bucket_wait: dict[str, float] = {}
        self._global_wait = 0.0
        self.rate_limit_hits = 0
        self._members: dict[tuple[str, str], dict | None] = {}
        self._members_off: set[str] = set()  # Server, bei denen der Endpunkt gesperrt ist

    # ------------------------------------------------------------------ Kern

    def _sleep(self, seconds: float) -> None:
        if seconds > 0 and self.cancel.wait(seconds):
            raise Cancelled()

    def request(self, path: str, params: dict | None = None) -> object:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = self.base_url + path + query
        route = route_key(path)
        attempts = 0
        while True:
            if self.cancel.is_set():
                raise Cancelled()
            wait_until = max(self._bucket_wait.get(route, 0), self._global_wait)
            if wait_until > time.monotonic():
                self._sleep(wait_until - time.monotonic())
            req = urllib.request.Request(url, headers={
                "Authorization": self.token if self.is_user else f"Bot {self.token}",
                "User-Agent": USER_MODE_AGENT if self.is_user else USER_AGENT,
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as resp:
                    body = resp.read()
                    self._note_bucket(route, resp.headers)
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as err:
                body = err.read()
                try:
                    data = json.loads(body) if body else {}
                except ValueError:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                if err.code == 429:
                    retry = float(data.get("retry_after") or err.headers.get("Retry-After") or 1)
                    until = time.monotonic() + retry + 0.1
                    if data.get("global"):
                        self._global_wait = until
                    self._bucket_wait[route] = until
                    self.rate_limit_hits += 1
                    # Kurze Pausen nicht einzeln melden, das flutet nur das Log
                    if retry >= 2 or self.rate_limit_hits == 1 or self.rate_limit_hits % 25 == 0:
                        scope = "global" if data.get("global") else "Route"
                        self.log(f"Rate-Limit ({scope}) – warte {retry:.1f} s … "
                                 f"({self.rate_limit_hits}× bisher, normal bei großen Exporten)")
                    continue
                if err.code >= 500 and attempts < 4:
                    attempts += 1
                    self._sleep(2 ** attempts)
                    continue
                raise DiscordAPIError(err.code, data.get("message") or err.reason, data.get("code"), path,
                                      hints=USER_ERROR_HINTS if self.is_user else None)
            except OSError as err:  # URLError, Timeouts, Verbindungsabbrüche
                reason = getattr(err, "reason", None) or err
                if attempts < 3:
                    attempts += 1
                    self.log(f"Netzwerkfehler ({reason}), neuer Versuch {attempts}/3 …")
                    self._sleep(2 ** (attempts - 1))
                    continue
                raise DiscordAPIError(0, f"Discord nicht erreichbar ({reason}). Internet, Proxy oder "
                                         f"Firewall prüfen.", path=path) from err

    def _note_bucket(self, route: str, headers) -> None:
        # Kleiner Puffer: unter Windows tickt time.monotonic() nur alle ~16 ms, ohne ihn kommt die
        # nächste Anfrage mitunter knapp vor dem Reset an und kassiert ein 429.
        remaining = headers.get("X-RateLimit-Remaining")
        reset_after = headers.get("X-RateLimit-Reset-After")
        if remaining is not None and reset_after is not None:
            try:
                if int(float(remaining)) <= 0:
                    self._bucket_wait[route] = time.monotonic() + float(reset_after) + RESET_MARGIN
            except ValueError:
                pass

    # ------------------------------------------------------------- Endpunkte

    def me(self) -> dict:
        return self.request("/users/@me")

    def guilds(self) -> list[dict]:
        result, after = [], None
        while True:
            batch = self.request("/users/@me/guilds", {"limit": 200, "after": after})
            result.extend(batch)
            if len(batch) < 200:
                return result
            after = batch[-1]["id"]

    def guild(self, guild_id: str) -> dict:
        return self.request(f"/guilds/{guild_id}")

    def guild_channels(self, guild_id: str) -> list[dict]:
        return self.request(f"/guilds/{guild_id}/channels")

    def guild_roles(self, guild_id: str) -> list[dict]:
        return self.request(f"/guilds/{guild_id}/roles")

    def channel(self, channel_id: str) -> dict:
        return self.request(f"/channels/{channel_id}")

    def active_threads(self, guild_id: str) -> list[dict]:
        return self.request(f"/guilds/{guild_id}/threads/active").get("threads", [])

    def archived_threads(self, channel_id: str, private: bool = False) -> Iterator[dict]:
        kind = "private" if private else "public"
        before = None
        while True:
            data = self.request(f"/channels/{channel_id}/threads/archived/{kind}",
                                {"limit": 100, "before": before})
            threads = data.get("threads", [])
            yield from threads
            if not data.get("has_more") or not threads:
                return
            before = threads[-1].get("thread_metadata", {}).get("archive_timestamp")
            if not before:
                return

    def private_channels(self) -> list[dict]:
        """Direktnachrichten und Gruppen-DMs (nur mit Benutzer-Token)."""
        return self.request("/users/@me/channels")

    def member(self, guild_id: str, user_id: str) -> dict | None:
        key = (guild_id, user_id)
        if guild_id in self._members_off:
            return None
        if key not in self._members:
            try:
                self._members[key] = self.request(f"/guilds/{guild_id}/members/{user_id}")
            except DiscordAPIError as err:
                if err.status in (401, 403, 404):
                    self._members[key] = None
                    # 401/403 gilt für den ganzen Endpunkt (z. B. nur für Bots): nicht weiter fragen
                    if err.status in (401, 403):
                        self._members_off.add(guild_id)
                else:
                    raise
        return self._members[key]

    def iter_messages(self, channel_id: str, after: datetime | None = None,
                      before: datetime | None = None) -> Iterator[dict]:
        """Nachrichten aufsteigend (älteste zuerst) im Zeitraum [after, before)."""
        # "after" ist exklusiv: -1, damit eine Nachricht genau zur Startzeit dabei ist
        cursor = str(max(datetime_to_snowflake(after) - 1, 0)) if after else "0"
        stop = datetime_to_snowflake(before) if before else None
        while True:
            batch = self.request(f"/channels/{channel_id}/messages", {"limit": 100, "after": cursor})
            if not batch:
                return
            batch.sort(key=lambda m: int(m["id"]))
            for msg in batch:
                if stop is not None and int(msg["id"]) >= stop:
                    return
                yield msg
            cursor = batch[-1]["id"]
