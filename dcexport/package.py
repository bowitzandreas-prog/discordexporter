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


# Discord übersetzt die Ordnernamen des Pakets in die Kontosprache („Nachrichten“,
# „Server“ …). Die Namen sind nur ein Hinweis; erkannt wird über die Struktur.
MESSAGES_DIRS = {
    "messages", "nachrichten", "mensajes", "messaggi", "berichten", "wiadomości", "wiadomosci",
    "mensagens", "сообщения", "повідомлення", "meddelelser", "meddelanden", "meldinger", "viestit",
    "zprávy", "üzenetek", "mesajlar", "mesaje", "μηνύματα", "メッセージ", "메시지", "消息", "訊息",
}
SERVERS_DIRS = {
    "servers", "server", "servidores", "serveurs", "serwery", "servere", "sunucular", "сервери",
    "серверы", "palvelimet", "szerverek", "サーバー", "서버", "服务器", "伺服器",
}
ACCOUNT_DIRS = {"account", "konto", "compte", "cuenta", "conta", "tili", "fiók", "hesap", "аккаунт",
                "акаунт", "アカウント", "계정", "账户", "帳號"}
DM_PREFIXES = ("Direct Message with ", "Direktnachricht mit ", "Direktnachrichten mit ")

# Kanalordner im neuen Format: c<Kanal-ID>; im alten nur <Kanal-ID>
_CHANNEL_DIR = re.compile(r"^c?\d{3,}$", re.I)
_KNOWN_FILES = ("channel.json", "messages.json", "messages.csv")


class DataPackage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Nicht gefunden: {self.path}")
        self.src = _Source(self.path)
        self.msgdir = "messages"
        self.prefix = ""
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
        """Paketwurzel und Nachrichtenordner über die Struktur bestimmen.

        Jede Datei <ordner>/<kanalordner>/<datei.json|csv> ist eine Stimme für <ordner>. Bekannte
        (übersetzte) Ordnernamen, „c“-Kanalordner und die üblichen Dateinamen zählen; Ordner unter
        Konto/Server (dort liegen ebenfalls Ordner mit IDs) zählen nicht. Wurde der Nachrichtenordner
        selbst gewählt, ist er die Wurzel.
        """
        votes: dict[tuple[str, str], int] = {}
        for name in self.src.names:
            parts = name.split("/")
            if len(parts) < 2 or not parts[-1].lower().endswith((".json", ".csv")):
                continue
            chdir, base = parts[-2], parts[-1].lower()
            msgdir = parts[-3] if len(parts) >= 3 else ""
            low = msgdir.lower()
            if low not in MESSAGES_DIRS:
                if not _CHANNEL_DIR.match(chdir):
                    continue
                if {p.lower() for p in parts[:-2]} & (SERVERS_DIRS | ACCOUNT_DIRS):
                    continue
            weight = ((100 if low in MESSAGES_DIRS else 0) + (10 if base in _KNOWN_FILES else 0)
                      + (5 if chdir[:1].lower() == "c" and _CHANNEL_DIR.match(chdir) else 0))
            if not weight:
                continue  # nur Zahlenordner mit fremden Dateien: zu unsicher
            key = ("/".join(parts[:-3]) + "/" if len(parts) > 3 else "", msgdir)
            votes[key] = votes.get(key, 0) + weight
        if not votes:
            raise ValueError(self._diagnose())
        self.root, self.msgdir = max(votes, key=lambda k: votes[k])
        self.prefix = f"{self.root}{self.msgdir}/" if self.msgdir else self.root
        return self.root

    def _diagnose(self) -> str:
        """Fehlermeldung, die sagt, was im gewählten Ordner/ZIP tatsächlich liegt."""
        names = self.src.names
        if not names:
            return "Der gewählte Ordner ist leer. Bitte den entpackten Paketordner oder die package.zip wählen."
        dirs = sorted({n.split("/")[0] for n in names if "/" in n}, key=str.lower)
        if len(dirs) == 1:  # alles in einem Unterordner: eine Ebene tiefer zeigen
            inner = sorted({"/".join(n.split("/")[:2]) for n in names if n.count("/") >= 2}, key=str.lower)
            dirs = inner or dirs
        zips = [n for n in names if n.lower().endswith(".zip")]
        seen = ", ".join(dirs[:12]) + (" …" if len(dirs) > 12 else "") if dirs else \
            ", ".join(n for n in names[:8])
        msg = f"Kein Ordner mit Unterhaltungen gefunden. Im gewählten Pfad liegt: {seen}."
        lows = {d.lower().split("/")[-1] for d in dirs}
        if zips:
            msg += (f" Darin steckt noch eine ZIP-Datei ({zips[0].split('/')[-1]}): bitte diese direkt wählen "
                    "oder vorher entpacken.")
        elif lows & MESSAGES_DIRS:
            msg += " Der Nachrichtenordner ist da, aber leer oder unvollständig entpackt."
        elif lows & (ACCOUNT_DIRS | SERVERS_DIRS):
            msg += (" Das sieht nach einem Discord-Datenpaket ohne Nachrichten aus. Beim Anfordern in Discord "
                    "(Einstellungen → Daten & Privatsphäre → Daten anfordern) muss „Nachrichten“ angehakt sein.")
        return msg

    def _top_file(self, dirs: set[str], filename: str) -> str | None:
        """<wurzel>/<ordner>/<datei>: bekannter Ordnername zuerst, sonst irgendein anderer Ordner."""
        fallback = None
        for name in self.src.names:
            if not name.startswith(self.root):
                continue
            parts = name[len(self.root):].split("/")
            if len(parts) != 2 or parts[1].lower() != filename or parts[0] == self.msgdir:
                continue
            if parts[0].lower() in dirs:
                return name
            fallback = fallback or name
        return fallback

    def _read_json_safe(self, name: str | None):
        if not name:
            return None
        try:
            return self.src.read_json(name)
        except ValueError:
            return None

    def _read_account(self) -> dict:
        data = self._read_json_safe(self._top_file(ACCOUNT_DIRS, "user.json"))
        return data if isinstance(data, dict) else {}

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
        name = self._top_file(SERVERS_DIRS, "index.json")
        if name and name.split("/")[-2].lower() not in SERVERS_DIRS:
            return {}  # unbekannter Ordner: keine Servernamen raten
        data = self._read_json_safe(name)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _read_index(self) -> dict[str, str]:
        data = self._read_json_safe(self.src.find(f"{self.prefix}index.json".lower()))
        return {str(k): v for k, v in data.items() if v} if isinstance(data, dict) else {}

    # ---------------------------------------------------------- Unterhaltungen

    def conversations(self) -> list[PackageConversation]:
        if self._conversations is None:
            self._conversations = self._scan()
        return self._conversations

    def _scan(self) -> list[PackageConversation]:
        prefix = self.prefix
        files: dict[str, list[str]] = {}  # Kanalordner -> Dateien darin
        for name in self.src.names:
            if not name.startswith(prefix):
                continue
            parts = name[len(prefix):].split("/")
            if len(parts) == 2 and parts[1].lower().endswith((".json", ".csv")):
                files.setdefault(f"{prefix}{parts[0]}/", []).append(name)
        self._layout: dict[str, tuple[str | None, tuple[str, str] | None]] = {}
        result = []
        for folder, names in sorted(files.items()):
            meta_name, msgs = self._classify(names)
            if not msgs and not meta_name:
                continue
            self._layout[folder] = (meta_name, msgs)
            meta = self._read_json_safe(meta_name)
            meta = meta if isinstance(meta, dict) else {}
            dirname = folder.rstrip("/").rsplit("/", 1)[-1]
            digits = dirname[1:] if dirname[:1].lower() == "c" else dirname
            cid = digits if digits.isdigit() else str(meta.get("id") or dirname)
            result.append(self._conversation(cid, folder, meta))
        result.sort(key=lambda c: (c.group != "Direktnachrichten", c.group != "Gruppen", c.group.lower(),
                                   c.info.name.lower()))
        return result

    def _classify(self, names: list[str]) -> tuple[str | None, tuple[str, str] | None]:
        """Kanalinfo und Nachrichtendatei eines Ordners finden; unbekannte Namen am Inhalt erkennen."""
        meta: str | None = None
        msgs: tuple[str, str] | None = None
        rest = []
        for n in names:
            base = n.rsplit("/", 1)[-1].lower()
            if base == _KNOWN_FILES[0]:
                meta = n
            elif base in _KNOWN_FILES[1:]:
                msgs = (n, base.rsplit(".", 1)[1])
            else:
                rest.append(n)
        for n in rest:
            if meta and msgs:
                break
            if n.lower().endswith(".csv"):
                msgs = msgs or (n, "csv")
                continue
            data = self._read_json_safe(n)
            if isinstance(data, list) and not msgs:
                msgs = (n, "json")
            elif isinstance(data, dict):
                if isinstance(data.get("messages"), list) and not msgs:
                    msgs = (n, "json")
                elif not meta and any(k in data for k in ("id", "type", "recipients", "guild")):
                    meta = n
        return meta, msgs

    def _conversation(self, cid: str, folder: str, meta: dict) -> PackageConversation:
        raw_type = meta.get("type", 0)
        ctype = raw_type if isinstance(raw_type, int) else PACKAGE_CHANNEL_TYPES.get(str(raw_type).upper(), 0)
        guild = meta.get("guild") or {}
        if ctype == 0 and not guild and meta.get("recipients"):
            # Typ unbekannt (z. B. übersetzt): Empfänger ohne Server heißt DM bzw. Gruppe
            ctype = 1 if len(meta["recipients"]) <= 2 else 3
        guild_id = str(guild["id"]) if guild.get("id") else None
        guild_name = guild.get("name") or (self.guild_names.get(guild_id) if guild_id else None)
        index_name = self.index.get(cid)
        if ctype == 1:
            others = [str(r) for r in meta.get("recipients") or [] if str(r) != self.author["id"]]
            other = self.known_users.get(others[0]) if others else None
            if index_name:
                name = index_name
                for prefix in DM_PREFIXES:
                    if name.startswith(prefix):
                        name = "DM mit " + name[len(prefix):]
                        break
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
        layout = getattr(self, "_layout", {}).get(folder)
        if layout and layout[1]:
            return layout[1]
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
