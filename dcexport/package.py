"""Offizielles Discord-Datenpaket lesen (Einstellungen → Datenschutz → Daten anfordern).

Unterstützt die ZIP-Datei oder den entpackten Ordner, alte Struktur
(messages/<id>/messages.csv) und neue (Messages/c<id>/messages.json).
Das Paket enthält nur die eigenen Nachrichten – nie die der Gegenseite.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .model import PACKAGE_CHANNEL_TYPES, ChannelInfo, normalize_package_message, normalize_user


@dataclass
class PackageConversation:
    info: ChannelInfo
    folder: str          # Pfad im Paket, mit abschließendem "/"
    message_count: int
    group: str           # "Direktnachrichten", "Gruppen", "Server: <Name>", "Sonstige"


class _Source:
    """Einheitlicher Zugriff auf ZIP oder Ordner, Pfade immer mit '/'."""

    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.is_file() else None
        if self.zip:
            self.names = [n for n in self.zip.namelist() if not n.endswith("/")]
        else:
            self.names = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
        self.lower = {n.lower(): n for n in self.names}

    def read_bytes(self, name: str) -> bytes:
        if self.zip:
            return self.zip.read(name)
        return (self.path / name).read_bytes()

    def read_text(self, name: str) -> str:
        return self.read_bytes(name).decode("utf-8-sig", errors="replace")

    def read_json(self, name: str):
        return json.loads(self.read_text(name))

    def find(self, lower_name: str) -> str | None:
        return self.lower.get(lower_name)

    def close(self) -> None:
        if self.zip:
            self.zip.close()


_CHANNEL_DIR = re.compile(r"^(.*?messages/)(c?)(\d+)/channel\.json$", re.I)


class DataPackage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Nicht gefunden: {self.path}")
        self.src = _Source(self.path)
        self.root = self._find_root()
        self.account = self._read_account()
        self.author = self._account_author()
        self.known_users: dict[str, str] = {self.author["id"]: self.author["display_name"]}
        self._read_relationships()
        self.guild_names = self._read_guild_names()
        self.index = self._read_index()
        self._conversations: list[PackageConversation] | None = None

    def close(self) -> None:
        self.src.close()

    # --------------------------------------------------------------- Struktur

    def _find_root(self) -> str:
        for lower in self.src.lower:
            m = re.match(r"^(.*?)messages/(?:index\.json|c?\d+/channel\.json)$", lower)
            if m:
                return m.group(1)
        raise ValueError("Kein Discord-Datenpaket: Ordner 'messages' mit channel.json fehlt.")

    def _get(self, *relative: str) -> str | None:
        for rel in relative:
            name = self.src.find((self.root + rel).lower())
            if name:
                return name
        return None

    def _read_account(self) -> dict:
        name = self._get("account/user.json")
        if not name:
            return {}
        try:
            return self.src.read_json(name)
        except ValueError:
            return {}

    def _account_author(self) -> dict:
        acc = self.account
        user = {
            "id": str(acc.get("id", "0")), "username": acc.get("username") or "Ich",
            "discriminator": str(acc.get("discriminator", "0")),
            "global_name": acc.get("global_name"), "avatar": acc.get("avatar_hash"),
        }
        return normalize_user(user)

    def _read_relationships(self) -> None:
        for rel in self.account.get("relationships") or []:
            user = rel.get("user") or {}
            uid = str(user.get("id") or rel.get("id") or "")
            if uid:
                self.known_users[uid] = (rel.get("nickname") or user.get("global_name")
                                         or user.get("username") or uid)

    def _read_guild_names(self) -> dict[str, str]:
        name = self._get("servers/index.json")
        if not name:
            return {}
        try:
            return {str(k): v for k, v in self.src.read_json(name).items()}
        except (ValueError, AttributeError):
            return {}

    def _read_index(self) -> dict[str, str]:
        name = self._get("messages/index.json")
        if not name:
            return {}
        try:
            return {str(k): v for k, v in self.src.read_json(name).items() if v}
        except (ValueError, AttributeError):
            return {}

    # ---------------------------------------------------------- Unterhaltungen

    def conversations(self) -> list[PackageConversation]:
        if self._conversations is None:
            self._conversations = self._scan()
        return self._conversations

    def _scan(self) -> list[PackageConversation]:
        result = []
        for name in self.src.names:
            m = _CHANNEL_DIR.match(name)
            if not m:
                continue
            folder = name[: -len("channel.json")]
            cid = m.group(3)
            try:
                meta = self.src.read_json(name)
            except ValueError:
                meta = {}
            result.append(self._conversation(cid, folder, meta))
        result.sort(key=lambda c: (c.group != "Direktnachrichten", c.group != "Gruppen", c.group.lower(),
                                   c.info.name.lower()))
        return result

    def _conversation(self, cid: str, folder: str, meta: dict) -> PackageConversation:
        raw_type = meta.get("type", 0)
        ctype = raw_type if isinstance(raw_type, int) else PACKAGE_CHANNEL_TYPES.get(str(raw_type).upper(), 0)
        guild = meta.get("guild") or {}
        guild_id = str(guild["id"]) if guild.get("id") else None
        guild_name = guild.get("name") or (self.guild_names.get(guild_id) if guild_id else None)
        index_name = self.index.get(cid)
        if ctype == 1:
            others = [str(r) for r in meta.get("recipients") or [] if str(r) != self.author["id"]]
            other = self.known_users.get(others[0]) if others else None
            if index_name:
                name = index_name.replace("Direct Message with ", "DM mit ")
            elif other:
                name = f"DM mit {other}"
            else:
                name = f"DM {others[0] if others else cid}"
            group = "Direktnachrichten"
        elif ctype == 3:
            name = meta.get("name") or index_name or f"Gruppe {cid}"
            group = "Gruppen"
        else:
            name = meta.get("name") or (index_name.split(" in ")[0] if index_name else f"Kanal {cid}")
            group = f"Server: {guild_name}" if guild_name else "Sonstige"
        info = ChannelInfo(id=cid, name=name, type=ctype, guild_id=guild_id, guild_name=guild_name,
                           source="package",
                           note="Datenpaket: enthält nur die eigenen Nachrichten.")
        return PackageConversation(info=info, folder=folder, message_count=self._count(folder), group=group)

    def _messages_file(self, folder: str) -> tuple[str | None, str]:
        for fname, kind in (("messages.json", "json"), ("messages.csv", "csv")):
            name = self.src.find((folder + fname).lower())
            if name:
                return name, kind
        return None, ""

    def _rows(self, folder: str) -> list[dict]:
        name, kind = self._messages_file(folder)
        if not name:
            return []
        text = self.src.read_text(name)
        if kind == "json":
            data = json.loads(text) if text.strip() else []
            return data if isinstance(data, list) else data.get("messages", [])
        return list(csv.DictReader(io.StringIO(text, newline="")))

    def _count(self, folder: str) -> int:
        try:
            return len(self._rows(folder))
        except (ValueError, csv.Error):
            return 0

    def entries(self, conv: PackageConversation) -> list[tuple[dict, dict]]:
        """(Rohzeile, normalisierte Nachricht), älteste zuerst."""
        out = []
        for row in self._rows(conv.folder):
            msg = normalize_package_message(row, self.author)
            if msg:
                out.append((row, msg))
        out.sort(key=lambda e: int(e[1]["id"]) if e[1]["id"].isdigit() else 0)
        return out

    def messages(self, conv: PackageConversation) -> list[dict]:
        return [m for _row, m in self.entries(conv)]
