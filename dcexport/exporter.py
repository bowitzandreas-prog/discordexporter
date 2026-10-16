"""Ablaufsteuerung: Kanäle ermitteln, Nachrichten holen, Medien sichern, Dateien schreiben."""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .api import Cancelled, DiscordAPIError, DiscordClient
from .html_writer import write_html
from .markdown import Resolver, _EMOJI
from .media import MediaStore, short_hash
from .model import (THREAD_ONLY_TYPES, ChannelInfo, ExportOptions, MESSAGE_CHANNEL_TYPES, display_name,
                    emoji_url, guild_icon_url, normalize_api_message, normalize_user)
from .package import DataPackage, PackageConversation
from .protocol import channel_entry, message_link, sha256_file, write_protocol
from .util import datetime_to_snowflake, parse_timestamp, sanitize_filename, snowflake_to_datetime
from .writers import FORMATS, RenderContext, write_csv, write_json, write_markdown, write_raw_json, write_txt

WRITERS = {
    "html": write_html, "json": write_json, "rawjson": write_raw_json,
    "csv": write_csv, "txt": write_txt, "md": write_markdown,
}
MEDIA_DIR = "_Medien"
DM_GUILD_ID = "@me"  # Pseudo-Server für Direktnachrichten (Benutzer-Token)

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, float, str], None]


@dataclass
class Summary:
    channels: int = 0
    skipped: int = 0
    messages: int = 0
    files: list[str] = field(default_factory=list)
    media_ok: int = 0       # in diesem Lauf neu geladen
    media_failed: int = 0
    media_total: int = 0    # alle lokal gesicherten Medien dieses Laufs (auch wiederverwendete)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    channel_log: list[dict] = field(default_factory=list)
    skipped_items: list[str] = field(default_factory=list)
    protocol_files: list[str] = field(default_factory=list)

    def result_text(self) -> str:
        def n(count: int, one: str, many: str) -> str:
            return f"{count} {one if count == 1 else many}"
        return ", ".join([n(self.channels, "Kanal", "Kanäle"), n(self.messages, "Nachricht", "Nachrichten"),
                          n(len(self.files), "Datei", "Dateien")])

    def text(self) -> str:
        parts = [self.result_text()]
        if self.media_total or self.media_failed:
            parts.append(f"{self.media_total} Medien" + (f" ({self.media_failed} fehlgeschlagen)" if self.media_failed else ""))
        if self.skipped:
            parts.append(f"{self.skipped} übersprungen")
        return ("Abgebrochen nach " if self.cancelled else "Fertig: ") + ", ".join(parts) + "."


@dataclass
class GuildData:
    guild: dict
    channels: list[ChannelInfo]
    all_channels: dict[str, str]  # id -> Name, auch Kategorien, für #Erwähnungen
    roles: dict[str, tuple[str, int | None]] | None = None
    active_threads: list[dict] | None = None
    loaded: bool = True  # False: Kanäle noch nicht geholt (Benutzerkonto, Laden beim Aufklappen)


def base_name(ch: ChannelInfo) -> str:
    name = f"{ch.parent_name} - {ch.name}" if ch.is_thread and ch.parent_name else ch.name
    if ch.category:
        name = f"{ch.category} - {name}"
    return sanitize_filename(f"{name} [{ch.id}]", max_len=110)


def write_outputs(ctx: RenderContext, folder: Path, name: str) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in FORMATS:
        if fmt in ctx.options.formats:
            path = folder / (name + FORMATS[fmt][1])
            WRITERS[fmt](ctx, path)
            written.append(str(path))
    return written


def _localize(messages: list[dict], media: MediaStore, extra_users: list[dict] | None = None) -> None:
    """Medien laden und lokale Pfade (relativ zur Exportdatei) eintragen."""

    def rel(path: Path | None) -> str | None:
        return f"{MEDIA_DIR}/{path.name}" if path else None

    def avatar(user: dict) -> None:
        if not user or user.get("avatar_local") is not None:
            return
        url = user.get("avatar_url") or ""
        hint = f"avatar_{user['id']}_{short_hash(url)}.png"
        user["avatar_local"] = rel(media.fetch(url, hint)) or ""

    def attachments(items: list[dict]) -> None:
        for a in items:
            a["local_path"] = rel(media.fetch(a.get("url"), f"{a['id']}_{a['filename']}"))

    for m in messages:
        avatar(m["author"])
        if m.get("referenced_message"):
            avatar(m["referenced_message"]["author"])
        attachments(m["attachments"])
        for fw in m.get("forwarded") or []:
            attachments(fw["attachments"])
        for s in m["stickers"]:
            ext = ".gif" if s.get("format_type") == 4 else ".png"
            s["local_path"] = rel(media.fetch(s.get("url"), f"sticker_{s['id']}{ext}"))
        for r in m["reactions"]:
            e = r["emoji"]
            if e.get("id"):
                ext = ".gif" if e.get("animated") else ".png"
                r["local_path"] = rel(media.fetch(emoji_url(e["id"], e.get("animated")), f"emoji_{e['id']}{ext}"))
        texts = [m["content"]] + [fw["content"] for fw in m.get("forwarded") or []]
        for text in texts:
            for animated, _name, eid in _EMOJI.findall(text or ""):
                ext = ".gif" if animated else ".png"
                media.fetch(emoji_url(eid, bool(animated)), f"emoji_{eid}{ext}")
    for user in extra_users or []:
        avatar(user)


def _emoji_resolver(media: MediaStore | None) -> Callable[[str, bool], str]:
    def resolve(eid: str, animated: bool) -> str:
        local = media.local(emoji_url(eid, animated)) if media else None
        return f"{MEDIA_DIR}/{local.name}" if local else emoji_url(eid, animated)
    return resolve


# ======================================================================= API


class ApiExporter:
    def __init__(self, client: DiscordClient, log: LogFn | None = None):
        self.client = client
        self.log = log or (lambda msg: None)
        self.guilds: dict[str, GuildData] = {}
        self.bot_user: dict | None = None

    @property
    def source_label(self) -> str:
        name = (self.bot_user or {}).get("username", "?")
        return f"Discord-API (Konto {name})" if self.client.is_user else f"Discord-API (Bot {name})"

    @property
    def source_line(self) -> str:
        me = self.bot_user or {}
        if self.client.is_user:
            return f"Discord-API (Benutzer-Token), Konto „{me.get('username', '?')}“ (ID {me.get('id', '?')})"
        return f"Discord-API (Bot-Token), Bot „{me.get('username', '?')}“ (ID {me.get('id', '?')})"

    # ------------------------------------------------------------ Auflisten

    def connect(self, load_channels: bool = True) -> list[GuildData]:
        """Server (und mit Benutzer-Token die DMs) holen.

        load_channels=False holt nur die Serverliste; die Kanäle kommen später mit load_guild().
        Spart bei Konten mit vielen Servern viele Anfragen, wenn nur DMs gebraucht werden.
        """
        self.bot_user = self.client.me()
        self.guilds.clear()
        if self.client.is_user:
            self.guilds[DM_GUILD_ID] = self._dm_data(self.client.private_channels())
        for g in self.client.guilds():
            if load_channels:
                self.guilds[g["id"]] = self._load_guild(g)
            else:
                self.guilds[g["id"]] = GuildData(guild=g, channels=[], all_channels={}, loaded=False)
        return list(self.guilds.values())

    def load_guild(self, guild_id: str) -> GuildData:
        gd = self.guilds[guild_id]
        if not gd.loaded:
            gd = self.guilds[guild_id] = self._load_guild(gd.guild)
        return gd

    def _load_guild(self, g: dict) -> GuildData:
        try:
            raw_channels = self.client.guild_channels(g["id"])
        except DiscordAPIError as err:
            self.log(f"Server {g.get('name')}: Kanäle nicht lesbar ({err})")
            raw_channels = []
        return self._guild_data(g, raw_channels)

    @staticmethod
    def _dm_data(raw_channels: list[dict]) -> GuildData:
        """Direktnachrichten als eigener Knoten, neueste Unterhaltung zuerst."""
        channels = []
        for c in sorted(raw_channels, key=lambda c: int(c.get("last_message_id") or 0), reverse=True):
            ctype = c.get("type")
            people = [normalize_user(u) for u in c.get("recipients") or []]
            if ctype == 1:
                who = people[0] if people else None
                name = f"DM mit {display_name(who)} (@{who['username']})" if who else f"DM {c['id']}"
            elif ctype == 3:
                name = "Gruppe: " + (c.get("name") or ", ".join(display_name(p) for p in people) or c["id"])
            else:
                continue
            channels.append(ChannelInfo(id=c["id"], name=name, type=ctype, last_message_id=c.get("last_message_id"),
                                        icon_url=people[0]["avatar_url"] if ctype == 1 and people else None))
        guild = {"id": DM_GUILD_ID, "name": "Direktnachrichten"}
        return GuildData(guild=guild, channels=channels, all_channels={c.id: c.name for c in channels})

    @staticmethod
    def _guild_data(g: dict, raw_channels: list[dict]) -> GuildData:
        cats = {c["id"]: c for c in raw_channels if c.get("type") == 4}
        icon = guild_icon_url(g)

        def sort_key(c: dict):
            cat = cats.get(c.get("parent_id"))
            voice = c.get("type") in (2, 13)
            return (cat.get("position", 0) if cat else -1, cat["id"] if cat else "", voice, c.get("position", 0))

        channels = []
        for c in sorted(raw_channels, key=sort_key):
            ctype = c.get("type")
            if ctype not in MESSAGE_CHANNEL_TYPES and ctype not in THREAD_ONLY_TYPES:
                continue
            cat = cats.get(c.get("parent_id"))
            channels.append(ChannelInfo(
                id=c["id"], name=c.get("name") or c["id"], type=ctype, topic=c.get("topic"),
                category=cat.get("name") if cat else None, guild_id=g["id"], guild_name=g.get("name"),
                guild_icon_url=icon, last_message_id=c.get("last_message_id"),
            ))
        names = {c["id"]: c.get("name") or c["id"] for c in raw_channels}
        return GuildData(guild=g, channels=channels, all_channels=names)

    def _roles(self, gd: GuildData) -> dict:
        if gd.roles is None:
            try:
                roles = self.client.guild_roles(gd.guild["id"])
            except DiscordAPIError:
                roles = []
            gd.roles = {r["id"]: (r.get("name", "?"), r.get("color") or None) for r in roles}
            gd.guild["_roles_raw"] = roles
        return gd.roles

    def threads_for(self, ch: ChannelInfo, options: ExportOptions) -> list[ChannelInfo]:
        gd = self.guilds.get(ch.guild_id or "")
        if gd is None:
            return []
        if gd.active_threads is None:
            try:
                gd.active_threads = self.client.active_threads(gd.guild["id"])
            except DiscordAPIError as err:
                self.log(f"  Aktive Threads nicht lesbar ({err.status})")
                gd.active_threads = []
        found = {t["id"]: t for t in gd.active_threads if t.get("parent_id") == ch.id}
        for private in (False, True):
            if private and ch.type in THREAD_ONLY_TYPES:
                continue
            try:
                for t in self.client.archived_threads(ch.id, private=private):
                    found.setdefault(t["id"], t)
            except DiscordAPIError as err:
                if not private:
                    self.log(f"  Archivierte Threads von #{ch.name} nicht lesbar ({err.status})")
        after_sf = datetime_to_snowflake(options.after) if options.after else None
        before_sf = datetime_to_snowflake(options.before) if options.before else None
        result = []
        for t in sorted(found.values(), key=lambda t: int(t["id"])):
            last = t.get("last_message_id")
            if after_sf and last and int(last) < after_sf:
                continue
            if before_sf and int(t["id"]) >= before_sf:
                continue
            gd.all_channels[t["id"]] = t.get("name") or t["id"]
            result.append(ChannelInfo(
                id=t["id"], name=t.get("name") or t["id"], type=t.get("type", 11), category=ch.category,
                guild_id=ch.guild_id, guild_name=ch.guild_name, guild_icon_url=ch.guild_icon_url,
                parent_id=ch.id, parent_name=ch.name, last_message_id=last,
            ))
        return result

    # --------------------------------------------------------------- Export

    def export(self, selected: list[ChannelInfo], options: ExportOptions, *,
               progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> Summary:
        progress = progress or (lambda *a: None)
        cancel = cancel or self.client.cancel
        summary = Summary()
        exported_at = datetime.now(timezone.utc)
        out_root = Path(options.out_dir)
        medias: dict[str, MediaStore] = {}
        try:
            targets: list[tuple[ChannelInfo, bool]] = []  # (Kanal, ist Thread aus Erweiterung)
            for ch in selected:
                if ch.type not in THREAD_ONLY_TYPES:
                    targets.append((ch, False))
                if not ch.is_dm and (options.include_threads or ch.type in THREAD_ONLY_TYPES):
                    self.log(f"Suche Threads in #{ch.name} …")
                    targets += [(t, True) for t in self.threads_for(ch, options)]
            for index, (ch, from_expansion) in enumerate(targets):
                if cancel.is_set():
                    raise Cancelled()
                label = f"{ch.guild_name} / {ch.title}" if ch.guild_name else ch.title
                progress(index, len(targets), 0.0, label)
                self.log(f"[{index + 1}/{len(targets)}] {label}")
                try:
                    messages, files = self._export_channel(ch, options, exported_at, out_root, medias,
                                                           lambda f: progress(index, len(targets), f, label),
                                                           skip_empty=from_expansion)
                except DiscordAPIError as err:
                    summary.skipped += 1
                    summary.skipped_items.append(f"{label} (Kanal-ID {ch.id}): {err}")
                    self.log(f"  Übersprungen: {err}")
                    continue
                if files:
                    summary.channels += 1
                    summary.messages += len(messages)
                    summary.files += files
                    summary.channel_log.append(channel_entry(label, ch.id, messages, files))
                    self.log(f"  {len(messages)} Nachrichten → {len(files)} Datei(en)")
                else:
                    self.log("  Keine Nachrichten im Zeitraum – keine Datei geschrieben.")
            progress(len(targets), len(targets), 1.0, "")
        except Cancelled:
            summary.cancelled = True
            self.log("Abgebrochen.")
        except Exception as err:  # noqa: BLE001 – GUI soll weiterlaufen
            summary.errors.append(str(err))
            self.log(f"Fehler: {err}\n{traceback.format_exc()}")
        for media in medias.values():
            summary.media_ok += media.downloaded
            summary.media_failed += media.failed
            summary.media_total += len(media.files())
        _finish_protocol(self.log, out_root, exported_at, summary, options, [self.source_line],
                         [p for m in medias.values() for p in m.files()])
        return summary

    def _export_channel(self, ch: ChannelInfo, options: ExportOptions, exported_at: datetime, out_root: Path,
                        medias: dict[str, MediaStore], on_fraction: Callable[[float], None],
                        skip_empty: bool) -> tuple[list[dict], list[str]]:
        start = options.after or snowflake_to_datetime(ch.id)
        end = options.before or datetime.now(timezone.utc)
        if ch.last_message_id:
            end = min(end, snowflake_to_datetime(ch.last_message_id))
        span = max((end - start).total_seconds(), 1.0)

        raw_messages, messages = [], []
        for raw in self.client.iter_messages(ch.id, options.after, options.before):
            raw_messages.append(raw)
            msg = normalize_api_message(raw)
            msg["link"] = message_link(ch.guild_id, ch.id, msg["id"])
            messages.append(msg)
            if len(messages) % 100 == 0:
                done = (snowflake_to_datetime(raw["id"]) - start).total_seconds() / span
                on_fraction(min(max(done, 0.0), 0.99))
                self.log(f"  … {len(messages)} Nachrichten")
        if not messages and skip_empty:
            return [], []
        normal = [m for m in messages if m["type"] in (0, 19)]
        if (not self.client.is_user and len(normal) >= 5
                and not any(m["content"] or m["attachments"] or m["embeds"] for m in normal)):
            self.log("  ⚠ Alle Nachrichtentexte sind leer. Im Developer Portal unter „Bot“ den "
                     "„Message Content Intent“ einschalten und neu exportieren.")

        gd = self.guilds.get(ch.guild_id or "")
        resolver = Resolver()
        if gd:
            resolver.channels.update(gd.all_channels)
            resolver.roles.update(self._roles(gd))
            self._apply_members(gd, messages, raw_messages)
        for m in messages:
            for u in [m["author"], *m["mentions"]]:
                resolver.users.setdefault(u["id"], display_name(u))
            if m.get("referenced_message"):
                u = m["referenced_message"]["author"]
                resolver.users.setdefault(u["id"], display_name(u))

        folder = out_root / sanitize_filename(ch.guild_name or ("Direktnachrichten" if ch.is_dm else "Discord"))
        media = None
        guild_icon_local = None
        if options.download_media:
            key = str(folder)
            media = medias.setdefault(key, MediaStore(folder / MEDIA_DIR, log=self.log, cancel=self.client.cancel))
            self.log("  Lade Medien …")
            _localize(messages, media)
            if ch.guild_icon_url:
                icon = media.fetch(ch.guild_icon_url, f"icon_{ch.guild_id}_{short_hash(ch.guild_icon_url)}.png")
                guild_icon_local = f"{MEDIA_DIR}/{icon.name}" if icon else None
        resolver.emoji_src = _emoji_resolver(media)

        ctx = RenderContext(channel=ch, messages=messages, resolver=resolver, options=options,
                            source_label=self.source_label, exported_at=exported_at, raw_messages=raw_messages,
                            guild_icon_local=guild_icon_local)
        files = write_outputs(ctx, folder, base_name(ch))
        on_fraction(1.0)
        return messages, files

    def _apply_members(self, gd: GuildData, messages: list[dict], raw_messages: list[dict]) -> None:
        """Server-Spitznamen und Rollenfarbe nachladen (ein Abruf je Autor, gecacht)."""
        webhooks = {r["author"]["id"] for r in raw_messages if r.get("webhook_id") and r.get("author")}
        roles = {r["id"]: r for r in gd.guild.get("_roles_raw") or []}
        authors = {m["author"]["id"] for m in messages} - webhooks
        if len(authors) > 20:
            self.log(f"  Lade Mitgliedsdaten für {len(authors)} Autoren …")
        info: dict[str, tuple[str | None, int | None]] = {}
        for uid in authors:
            member = self.client.member(gd.guild["id"], uid)
            if not member:
                continue
            colored = [roles[r] for r in member.get("roles", []) if r in roles and roles[r].get("color")]
            color = max(colored, key=lambda r: r.get("position", 0))["color"] if colored else None
            info[uid] = (member.get("nick"), color)

        def apply(user: dict) -> None:
            nick, color = info.get(user["id"], (None, None))
            user["nickname"] = nick
            user["color"] = color

        for m in messages:
            apply(m["author"])
            for u in m["mentions"]:
                apply(u)
            if m.get("referenced_message"):
                apply(m["referenced_message"]["author"])


# ================================================================ Datenpaket


class PackageExporter:
    def __init__(self, package: DataPackage, log: LogFn | None = None):
        self.package = package
        self.log = log or (lambda msg: None)

    @property
    def source_label(self) -> str:
        return f"Discord-Datenpaket ({self.package.author['display_name']})"

    def export(self, selected: list[PackageConversation], options: ExportOptions, *,
               progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> Summary:
        progress = progress or (lambda *a: None)
        cancel = cancel or threading.Event()
        summary = Summary()
        exported_at = datetime.now(timezone.utc)
        folder = Path(options.out_dir) / sanitize_filename(f"Datenpaket {self.package.author['username']}")
        media = MediaStore(folder / MEDIA_DIR, log=self.log, cancel=cancel) if options.download_media else None
        resolver = Resolver(users=dict(self.package.known_users),
                            channels={cid: name.split(" in ")[0] for cid, name in self.package.index.items()},
                            emoji_src=_emoji_resolver(media))
        try:
            for index, conv in enumerate(selected):
                if cancel.is_set():
                    raise Cancelled()
                label = conv.info.title if not conv.info.guild_name else f"{conv.info.guild_name} / {conv.info.title}"
                progress(index, len(selected), 0.0, label)
                self.log(f"[{index + 1}/{len(selected)}] {label}")
                entries = [(row, m) for row, m in self.package.entries(conv)
                           if (not options.after or parse_timestamp(m["timestamp"]) >= options.after)
                           and (not options.before or parse_timestamp(m["timestamp"]) < options.before)]
                messages = [m for _row, m in entries]
                for m in messages:
                    m["link"] = message_link(conv.info.guild_id, conv.info.id, m["id"])
                if media:
                    self.log("  Lade Medien …")
                    _localize(messages, media)
                ctx = RenderContext(channel=conv.info, messages=messages, resolver=resolver, options=options,
                                    source_label=self.source_label, exported_at=exported_at,
                                    raw_messages=[row for row, _m in entries])
                name = base_name(conv.info)
                if conv.info.guild_name:
                    name = sanitize_filename(f"{conv.info.guild_name} - {name}", max_len=140)
                files = write_outputs(ctx, folder, name)
                summary.channels += 1
                summary.messages += len(messages)
                summary.files += files
                summary.channel_log.append(channel_entry(label, conv.info.id, messages, files))
                self.log(f"  {len(messages)} Nachrichten → {len(files)} Datei(en)")
            progress(len(selected), len(selected), 1.0, "")
        except Cancelled:
            summary.cancelled = True
            self.log("Abgebrochen.")
        except Exception as err:  # noqa: BLE001
            summary.errors.append(str(err))
            self.log(f"Fehler: {err}\n{traceback.format_exc()}")
        if media:
            summary.media_ok, summary.media_failed = media.downloaded, media.failed
            summary.media_total = len(media.files())
        pkg_path = self.package.path
        source = [f"Discord-Datenpaket, Konto „{self.package.author['username']}“ (ID {self.package.author['id']})",
                  f"Paket: {pkg_path}"]
        if pkg_path.is_file():
            source.append(f"SHA-256 des Pakets: {sha256_file(pkg_path)}")
        else:
            source.append("Paket als entpackter Ordner gelesen (keine Prüfsumme des Originals)")
        _finish_protocol(self.log, Path(options.out_dir), exported_at, summary, options, source,
                         media.files() if media else [],
                         ["Das Datenpaket enthält nur die eigenen Nachrichten des Kontos, nicht die der Gegenseite."])
        return summary


def _finish_protocol(log: LogFn, out_dir: Path, started: datetime, summary: Summary, options: ExportOptions,
                     source_lines: list[str], media_files: list[Path], extra_notes: list[str] | None = None) -> None:
    """Exportprotokoll und Prüfsummen schreiben, sobald mindestens eine Datei entstanden ist."""
    if not summary.files:
        return
    try:
        summary.protocol_files = write_protocol(out_dir, started=started, summary=summary, options=options,
                                                source_lines=source_lines, media_files=media_files,
                                                extra_notes=extra_notes)
        log(f"Exportprotokoll und Prüfsummen: {Path(summary.protocol_files[0]).name}")
    except OSError as err:
        summary.errors.append(f"Exportprotokoll nicht geschrieben: {err}")
        log(f"Fehler beim Exportprotokoll: {err}")
