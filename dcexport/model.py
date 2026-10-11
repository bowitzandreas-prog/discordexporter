"""Einheitliches Nachrichtenformat für beide Quellen (Bot-API und Datenpaket).

Nachrichten sind schlichte dicts, damit der JSON-Export sie unverändert schreiben kann.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlparse

from .util import iso, parse_timestamp, snowflake_to_datetime

CDN = "https://cdn.discordapp.com"
MEDIA_CDN = "https://media.discordapp.net"

CHANNEL_TYPES = {
    0: "Textkanal", 1: "Direktnachricht", 2: "Sprachkanal", 3: "Gruppen-DM", 4: "Kategorie",
    5: "Ankündigungen", 10: "Thread", 11: "Thread", 12: "Privater Thread", 13: "Stage",
    15: "Forum", 16: "Medienkanal",
}
# Kanäle mit eigener Nachrichtenliste
MESSAGE_CHANNEL_TYPES = {0, 1, 2, 3, 5, 10, 11, 12, 13}
# Kanäle, deren Inhalt nur in Threads liegt
THREAD_ONLY_TYPES = {15, 16}
THREAD_TYPES = {10, 11, 12}

PACKAGE_CHANNEL_TYPES = {
    "GUILD_TEXT": 0, "DM": 1, "GUILD_VOICE": 2, "GROUP_DM": 3, "GUILD_CATEGORY": 4,
    "GUILD_ANNOUNCEMENT": 5, "GUILD_NEWS": 5, "ANNOUNCEMENT_THREAD": 10, "PUBLIC_THREAD": 11,
    "PRIVATE_THREAD": 12, "GUILD_STAGE_VOICE": 13, "GUILD_FORUM": 15, "GUILD_MEDIA": 16,
}


@dataclass
class ChannelInfo:
    id: str
    name: str
    type: int = 0
    topic: str | None = None
    category: str | None = None
    guild_id: str | None = None
    guild_name: str | None = None
    guild_icon_url: str | None = None
    parent_id: str | None = None
    parent_name: str | None = None
    last_message_id: str | None = None
    source: str = "api"  # "api" oder "package"
    note: str | None = None

    @property
    def is_thread(self) -> bool:
        return self.type in THREAD_TYPES

    @property
    def is_dm(self) -> bool:
        return self.type in (1, 3)

    @property
    def title(self) -> str:
        if self.is_dm:
            return self.name
        if self.is_thread and self.parent_name:
            return f"#{self.parent_name} › {self.name}"
        return f"#{self.name}"

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "type_name": CHANNEL_TYPES.get(self.type, str(self.type)),
            "topic": self.topic, "category": self.category,
            "parent": {"id": self.parent_id, "name": self.parent_name} if self.parent_id else None,
        }


@dataclass
class ExportOptions:
    out_dir: str
    formats: set = field(default_factory=lambda: {"html", "json"})
    after: datetime | None = None
    before: datetime | None = None
    download_media: bool = True
    include_threads: bool = True
    csv_delimiter: str = ";"


def default_avatar_url(user_id: str, discriminator: str | None = None) -> str:
    if discriminator and discriminator not in ("0", "0000"):
        index = int(discriminator) % 5
    else:
        index = (int(user_id) >> 22) % 6 if str(user_id).isdigit() else 0
    return f"{CDN}/embed/avatars/{index}.png"


def avatar_url(user: dict) -> str:
    uid = str(user.get("id", "0"))
    av = user.get("avatar")
    if av:
        return f"{CDN}/avatars/{uid}/{av}.png?size=128"
    return default_avatar_url(uid, user.get("discriminator"))


def emoji_url(emoji_id: str, animated: bool = False) -> str:
    return f"{CDN}/emojis/{emoji_id}.{'gif' if animated else 'png'}?size=96"


def guild_icon_url(guild: dict) -> str | None:
    if guild.get("icon"):
        return f"{CDN}/icons/{guild['id']}/{guild['icon']}.png?size=128"
    return None


def sticker_url(sticker: dict) -> str | None:
    fmt = sticker.get("format_type")
    if fmt in (1, 2):
        return f"{MEDIA_CDN}/stickers/{sticker['id']}.png?size=160"
    if fmt == 4:
        return f"{MEDIA_CDN}/stickers/{sticker['id']}.gif?size=160"
    return None  # 3 = Lottie, lässt sich ohne Player nicht anzeigen


def normalize_user(user: dict | None) -> dict:
    user = user or {}
    uid = str(user.get("id", "0"))
    username = user.get("username") or "Unbekannt"
    disc = user.get("discriminator")
    if disc and disc not in ("0", "0000"):
        username = f"{username}#{disc}"
    global_name = user.get("global_name")
    return {
        "id": uid,
        "username": username,
        "global_name": global_name,
        "nickname": None,
        "display_name": global_name or username,
        "avatar_url": avatar_url(user) if user else default_avatar_url(uid),
        "is_bot": bool(user.get("bot")),
        "color": None,
    }


def _attachment(a: dict) -> dict:
    return {
        "id": str(a.get("id", "")),
        "filename": a.get("filename") or "datei",
        "url": a.get("url"),
        "size": a.get("size"),
        "content_type": a.get("content_type"),
        "width": a.get("width"),
        "height": a.get("height"),
        "description": a.get("description"),
        "spoiler": (a.get("filename") or "").startswith("SPOILER_"),
        "local_path": None,
    }


def _reaction(r: dict) -> dict:
    e = r.get("emoji") or {}
    return {
        "emoji": {"id": e.get("id"), "name": e.get("name"), "animated": bool(e.get("animated"))},
        "count": r.get("count", 0),
        "local_path": None,
    }


def _sticker(s: dict) -> dict:
    return {"id": str(s.get("id")), "name": s.get("name"), "format_type": s.get("format_type"),
            "url": sticker_url(s), "local_path": None}


def _snapshot(snap: dict) -> dict:
    m = snap.get("message") or {}
    return {
        "timestamp": iso(parse_timestamp(m.get("timestamp"))),
        "content": m.get("content") or "",
        "attachments": [_attachment(a) for a in m.get("attachments") or []],
        "embeds": m.get("embeds") or [],
        "stickers": [_sticker(s) for s in m.get("sticker_items") or []],
    }


def _reply_preview(ref: dict | None) -> dict | None:
    if not ref:
        return None
    return {
        "id": str(ref.get("id")),
        "author": normalize_user(ref.get("author")),
        "content": ref.get("content") or "",
        "has_attachments": bool(ref.get("attachments") or ref.get("embeds")),
    }


def normalize_api_message(raw: dict) -> dict:
    ts = parse_timestamp(raw.get("timestamp")) or snowflake_to_datetime(raw["id"])
    ref = raw.get("message_reference")
    interaction = raw.get("interaction_metadata") or raw.get("interaction")
    thread = raw.get("thread")
    return {
        "id": str(raw["id"]),
        "type": raw.get("type", 0),
        "timestamp": iso(ts),
        "edited_timestamp": iso(parse_timestamp(raw.get("edited_timestamp"))),
        "pinned": bool(raw.get("pinned")),
        "author": normalize_user(raw.get("author")),
        "content": raw.get("content") or "",
        "attachments": [_attachment(a) for a in raw.get("attachments") or []],
        "embeds": raw.get("embeds") or [],
        "stickers": [_sticker(s) for s in raw.get("sticker_items") or []],
        "reactions": [_reaction(r) for r in raw.get("reactions") or []],
        "mentions": [normalize_user(u) for u in raw.get("mentions") or []],
        "mention_roles": [str(r) for r in raw.get("mention_roles") or []],
        "mention_everyone": bool(raw.get("mention_everyone")),
        "reference": {
            "message_id": str(ref["message_id"]) if ref.get("message_id") else None,
            "channel_id": str(ref["channel_id"]) if ref.get("channel_id") else None,
            "guild_id": str(ref["guild_id"]) if ref.get("guild_id") else None,
            "type": ref.get("type", 0),
        } if ref else None,
        "referenced_message": _reply_preview(raw.get("referenced_message")),
        "forwarded": [_snapshot(s) for s in raw.get("message_snapshots") or []],
        "interaction": {
            "name": interaction.get("name"),
            "user": normalize_user(interaction.get("user")),
        } if interaction else None,
        "poll": raw.get("poll"),
        "thread": {"id": str(thread["id"]), "name": thread.get("name")} if thread else None,
        "call": raw.get("call"),
    }


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    return unquote(path.rsplit("/", 1)[-1]) or "datei"


def normalize_package_message(row: dict, author: dict) -> dict | None:
    """Zeile aus messages.json/messages.csv des Datenpakets (ID, Timestamp, Contents, Attachments)."""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    mid = lowered.get("id")
    if mid in (None, ""):
        return None
    mid = str(mid).strip()
    ts = parse_timestamp(lowered.get("timestamp"))
    if ts is None and mid.isdigit():
        ts = snowflake_to_datetime(mid)
    if ts is None:
        return None
    raw_att = lowered.get("attachments") or ""
    urls = raw_att if isinstance(raw_att, list) else str(raw_att).split()
    attachments = []
    for i, url in enumerate(u for u in urls if str(u).startswith("http")):
        name = _filename_from_url(url)
        attachments.append({
            "id": f"{mid}-{i}", "filename": name, "url": url, "size": None,
            "content_type": None, "width": None, "height": None, "description": None,
            "spoiler": name.startswith("SPOILER_"), "local_path": None,
        })
    return {
        "id": mid, "type": 0, "timestamp": iso(ts), "edited_timestamp": None, "pinned": False,
        "author": dict(author),
        "content": str(lowered.get("contents") or "").replace("\r\n", "\n"),
        "attachments": attachments, "embeds": [], "stickers": [], "reactions": [], "mentions": [],
        "mention_roles": [], "mention_everyone": False, "reference": None, "referenced_message": None,
        "forwarded": [], "interaction": None, "poll": None, "thread": None, "call": None,
    }


def display_name(user: dict) -> str:
    return user.get("nickname") or user.get("display_name") or user.get("username") or "Unbekannt"
