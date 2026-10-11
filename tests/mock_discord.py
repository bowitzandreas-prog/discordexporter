"""Nachgebaute Discord-API für Tests: ein Server, mehrere Kanäle, Threads, Rate-Limit, CDN."""

from __future__ import annotations

import json
import re
import struct
import threading
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dcexport.util import datetime_to_snowflake

def _png(size: int = 16, rgb: tuple = (88, 101, 242)) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()
START = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)
TOKEN = "TEST.TOKEN.123"
USER_TOKEN = "USER.TOKEN.456"

USERS = {
    "4001": {"id": "4001", "username": "andi", "global_name": "Andi", "avatar": "a1b2c3", "discriminator": "0"},
    "4002": {"id": "4002", "username": "misty", "global_name": None, "avatar": None, "discriminator": "0"},
    "4003": {"id": "4003", "username": "oldschool", "global_name": "Old School", "avatar": None,
             "discriminator": "1234"},
    "4004": {"id": "4004", "username": "PreisBot", "global_name": None, "avatar": "b0b", "bot": True,
             "discriminator": "0"},
}


def sf(minutes: float, seq: int = 0) -> str:
    return str(datetime_to_snowflake(START + timedelta(minutes=minutes)) + seq)


def ts(minutes: float) -> str:
    return (START + timedelta(minutes=minutes)).isoformat()


class MockDiscord:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.requests: list[str] = []
        self.rate_limited_once = False
        self.user_forbidden = 0
        self.auth_headers: set[str] = set()
        self.messages = self._build_messages()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "MockDiscord":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def api(self) -> str:
        return self.base + "/api/v10"

    # ------------------------------------------------------------------ Daten

    def _msg(self, channel: str, minute: float, author: str, content: str = "", seq: int = 0, **extra) -> dict:
        mid = sf(minute, seq)
        msg = {"id": mid, "channel_id": channel, "type": 0, "content": content, "timestamp": ts(minute),
               "edited_timestamp": None, "pinned": False, "author": USERS[author], "attachments": [],
               "embeds": [], "mentions": [], "mention_roles": []}
        msg.update(extra)
        return msg

    def _build_messages(self) -> dict[str, list[dict]]:
        b = self.base
        ch = "2001"
        special = [
            self._msg(ch, 0, "4003", "", type=7),
            self._msg(ch, 1, "4001", "Willkommen bei **CollectnTrade**! Regeln in <#2002>, Fragen an <@&3001>."),
            self._msg(ch, 1.5, "4001", "Code: `npm run build` und\n```py\nprint('*nicht fett*')\n```",
                      pinned=True, edited_timestamp=ts(3)),
            self._msg(ch, 2, "4002", "Hi <@4001> :) Link: https://example.com/a_b_c?x=1 ||Spoiler||",
                      mentions=[USERS["4001"]],
                      reactions=[{"emoji": {"id": None, "name": "👍"}, "count": 3},
                                 {"emoji": {"id": "5001", "name": "pika", "animated": False}, "count": 1}]),
            self._msg(ch, 3, "4001", "Danke!", type=19,
                      message_reference={"message_id": sf(2), "channel_id": ch, "guild_id": "1000"},
                      referenced_message={"id": sf(2), "author": USERS["4002"], "content": "Hi <@4001> :)"}),
            self._msg(ch, 4, "4002", "Mein Pull:", attachments=[
                {"id": "7001", "filename": "glurak.png", "size": 70, "content_type": "image/png", "width": 16,
                 "height": 16, "url": f"{b}/attachments/2001/7001/glurak.png?ex=1&is=2&hm=3"},
                {"id": "7002", "filename": "liste.pdf", "size": 2048, "content_type": "application/pdf",
                 "url": f"{b}/attachments/2001/7002/liste.pdf?ex=1&is=2&hm=3"}]),
            self._msg(ch, 5, "4004", "", embeds=[{
                "type": "rich", "title": "Preis-Update", "url": "https://collectntrade.de", "color": 0x5865F2,
                "description": "Glurak ex **steigt**", "fields": [
                    {"name": "Alt", "value": "12,00 €", "inline": True},
                    {"name": "Neu", "value": "14,50 €", "inline": True}],
                "footer": {"text": "JustTCG"}, "timestamp": ts(5)}]),
            self._msg(ch, 6, "4001", "<:pika:5001><:pika:5001>"),
            self._msg(ch, 7, "4002", "> Zitat\nAntwort <t:1709290800:F> <script>alert(1)</script>",
                      sticker_items=[{"id": "8001", "name": "Wave", "format_type": 1}]),
            self._msg(ch, 8, "4001", "", message_reference={"type": 1, "message_id": "1", "channel_id": "9"},
                      message_snapshots=[{"message": {"content": "Weitergeleitet: Booster-Box da!",
                                                      "timestamp": ts(7), "attachments": []}}]),
            self._msg(ch, 9, "4004", "", poll={
                "question": {"text": "Nächstes Set?"},
                "answers": [{"answer_id": 1, "poll_media": {"text": "Lorcana"}},
                            {"answer_id": 2, "poll_media": {"text": "One Piece"}}],
                "results": {"answer_counts": [{"id": 1, "count": 5}, {"id": 2, "count": 7}]}}),
            self._msg(ch, 10, "4002", "Thread dazu", thread={"id": "2101", "name": "Tausch: Glurak"}),
        ]
        filler = [self._msg(ch, 20 + i, "4001" if i % 3 else "4002", f"Nachricht Nummer {i}") for i in range(240)]
        return {
            "2001": special + filler,
            "2002": [self._msg("2002", 30, "4001", "Regel 1: fair handeln.")],
            "2101": [self._msg("2101", 40, "4002", "Biete Glurak, suche Mew.")],
            "2102": [self._msg("2102", 50, "4003", "Hüllen + Toploader.")],
            "6001": [self._msg("6001", 60, "4002", "Zahlung kommt morgen, versprochen."),
                     self._msg("6001", 61, "4001", "Ok, Karte geht nach Zahlungseingang raus."),
                     self._msg("6001", 62, "4002", "Hab bezahlt, Screenshot folgt")],
            "6002": [self._msg("6002", 70, "4003", "Wer bringt die Booster mit?")],
        }

    # ---------------------------------------------------------------- Routen

    def _route(self, path: str, query: dict, user: bool = False) -> tuple[int, object, dict]:
        g = {"id": "1000", "name": "CollectnTrade Community", "icon": "ic0n"}
        if path == "/api/v10/users/@me":
            if user:
                return 200, USERS["4001"], {}
            return 200, {"id": "9999", "username": "ExportBot", "bot": True}, {}
        if path == "/api/v10/users/@me/channels":
            if not user:
                return 403, {"message": "Bots cannot use this endpoint", "code": 20001}, {}
            return 200, [
                {"id": "6002", "type": 3, "name": None, "recipients": [USERS["4002"], USERS["4003"]],
                 "last_message_id": self.messages["6002"][-1]["id"]},
                {"id": "6001", "type": 1, "recipients": [USERS["4002"]],
                 "last_message_id": self.messages["6001"][-1]["id"]},
            ], {}
        if user and (path.endswith("/threads/active") or "/members/" in path):
            self.user_forbidden += 1
            return 403, {"message": "Missing Access", "code": 50001}, {}
        if path == "/api/v10/users/@me/guilds":
            return 200, [g], {}
        if path == "/api/v10/guilds/1000/channels":
            return 200, [
                {"id": "2000", "type": 4, "name": "Allgemein", "position": 0},
                {"id": "2001", "type": 0, "name": "willkommen", "parent_id": "2000", "position": 0,
                 "topic": "Hallo **alle**", "last_message_id": self.messages["2001"][-1]["id"]},
                {"id": "2002", "type": 0, "name": "handel", "parent_id": "2000", "position": 1,
                 "last_message_id": self.messages["2002"][-1]["id"]},
                {"id": "2003", "type": 15, "name": "fragen", "position": 2},
                {"id": "2004", "type": 2, "name": "Talk", "position": 3},
                {"id": "2005", "type": 0, "name": "geheim", "position": 4},
            ], {}
        if path == "/api/v10/guilds/1000/roles":
            return 200, [{"id": "1000", "name": "@everyone", "color": 0, "position": 0},
                         {"id": "3001", "name": "Mod", "color": 0xE74C3C, "position": 2},
                         {"id": "3002", "name": "Händler", "color": 0x3498DB, "position": 1}], {}
        if path == "/api/v10/guilds/1000/threads/active":
            return 200, {"threads": [{"id": "2101", "type": 11, "name": "Tausch: Glurak", "parent_id": "2002",
                                      "last_message_id": self.messages["2101"][-1]["id"]}], "members": []}, {}
        m = re.fullmatch(r"/api/v10/channels/(\d+)/threads/archived/(public|private)", path)
        if m:
            if m.group(1) == "2003" and m.group(2) == "public":
                return 200, {"threads": [{"id": "2102", "type": 11, "name": "Wie lagere ich Karten?",
                                          "parent_id": "2003",
                                          "last_message_id": self.messages["2102"][-1]["id"],
                                          "thread_metadata": {"archive_timestamp": ts(60)}}],
                             "has_more": False}, {}
            if m.group(2) == "private":
                return 403, {"message": "Missing Permissions", "code": 50013}, {}
            return 200, {"threads": [], "has_more": False}, {}
        m = re.fullmatch(r"/api/v10/guilds/1000/members/(\d+)", path)
        if m:
            members = {"4001": {"nick": "Andi (CnT)", "roles": ["3001"]}, "4002": {"nick": None, "roles": ["3002"]}}
            if m.group(1) in members:
                return 200, {"user": USERS[m.group(1)], **members[m.group(1)]}, {}
            return 404, {"message": "Unknown Member", "code": 10007}, {}
        m = re.fullmatch(r"/api/v10/channels/(\d+)/messages", path)
        if m:
            cid = m.group(1)
            if cid == "2005":
                return 403, {"message": "Missing Access", "code": 50001}, {}
            if cid == "2001" and not self.rate_limited_once:
                self.rate_limited_once = True
                return 429, {"message": "You are being rate limited.", "retry_after": 0.05, "global": False}, {}
            after = int(query.get("after", ["0"])[0])
            limit = int(query.get("limit", ["50"])[0])
            items = sorted((x for x in self.messages.get(cid, []) if int(x["id"]) > after), key=lambda x: int(x["id"]))
            page = list(reversed(items[:limit]))  # Discord liefert neueste zuerst
            return 200, page, {"X-RateLimit-Remaining": "4", "X-RateLimit-Reset-After": "0.01"}
        return 404, {"message": "Unknown route " + path, "code": 0}, {}

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                url = urlparse(self.path)
                mock.requests.append(self.path)
                if url.path.startswith(("/attachments/", "/avatars/", "/emojis/", "/icons/", "/embed/",
                                        "/stickers/")):
                    if "/7002/" in url.path:  # PDF-Anhang: abgelaufener Link
                        self.send_response(404)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(PNG)))
                    self.end_headers()
                    self.wfile.write(PNG)
                    return
                auth = self.headers.get("Authorization")
                mock.auth_headers.add(auth or "")
                if auth not in (f"Bot {TOKEN}", USER_TOKEN):
                    status, body, headers = 401, {"message": "401: Unauthorized", "code": 0}, {}
                else:
                    status, body, headers = mock._route(url.path, parse_qs(url.query), user=auth == USER_TOKEN)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        return Handler
