"""Ausgabeformate: JSON, JSON (roh), CSV, TXT, Markdown. HTML liegt in html_writer.py."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__
from .markdown import Resolver, render_plain
from .model import ChannelInfo, ExportOptions, display_name
from .util import fmt_datetime, human_size, iso, parse_timestamp

FORMATS = {
    "html": ("HTML", ".html"),
    "json": ("JSON", ".json"),
    "rawjson": ("JSON (Rohdaten)", ".raw.json"),
    "csv": ("CSV (Excel)", ".csv"),
    "txt": ("Text", ".txt"),
    "md": ("Markdown", ".md"),
}

NORMAL_TYPES = {0, 19, 20, 21, 23}


@dataclass
class RenderContext:
    channel: ChannelInfo
    messages: list[dict]
    resolver: Resolver
    options: ExportOptions
    source_label: str
    exported_at: datetime
    raw_messages: list[dict] | None = None
    guild_icon_local: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def date_range_text(self) -> str:
        a, b = self.options.after, self.options.before
        if not a and not b:
            return "gesamter Verlauf"
        left = fmt_datetime(a) if a else "Anfang"
        right = fmt_datetime(b) if b else "heute"
        return f"{left} bis {right}"


def system_text(msg: dict, resolver: Resolver) -> str | None:
    """Text für Systemnachrichten (Beitritt, Anheften, …); None bei normalen Nachrichten."""
    t = msg.get("type", 0)
    if t in NORMAL_TYPES:
        return None
    who = display_name(msg["author"])
    content = render_plain(msg.get("content") or "", resolver)
    target = display_name(msg["mentions"][0]) if msg.get("mentions") else "jemanden"
    texts = {
        1: f"{who} hat {target} zur Gruppe hinzugefügt.",
        2: (f"{who} hat die Gruppe verlassen." if target == who
            else f"{who} hat {target} aus der Gruppe entfernt."),
        3: f"{who} hat einen Anruf gestartet.",
        4: f"{who} hat den Kanalnamen geändert: {content}",
        5: f"{who} hat das Gruppensymbol geändert.",
        6: f"{who} hat eine Nachricht an diesen Kanal angeheftet.",
        7: f"{who} ist dem Server beigetreten.",
        8: f"{who} hat den Server geboostet.",
        9: f"{who} hat den Server geboostet. Stufe 1 erreicht!",
        10: f"{who} hat den Server geboostet. Stufe 2 erreicht!",
        11: f"{who} hat den Server geboostet. Stufe 3 erreicht!",
        12: f"{who} hat {content} zu diesem Kanal hinzugefügt.",
        18: f"{who} hat einen Thread gestartet: {content}",
        24: "AutoMod hat eine Nachricht blockiert.",
        27: f"{who} hat die Stage gestartet: {content}",
        28: f"{who} hat die Stage beendet: {content}",
        46: "Umfrage beendet.",
    }
    return texts.get(t) or (content or f"Systemnachricht (Typ {t})")


def reaction_label(reaction: dict) -> str:
    e = reaction["emoji"]
    return e["name"] if not e.get("id") else f":{e.get('name') or 'emoji'}:"


def attachment_ref(att: dict) -> str:
    return att.get("local_path") or att.get("url") or att.get("filename") or ""


def _envelope(ctx: RenderContext, messages: list) -> dict:
    ch = ctx.channel
    return {
        "exporter": {
            "name": APP_NAME, "version": __version__, "exported_at": iso(ctx.exported_at),
            "source": ch.source, "source_label": ctx.source_label,
        },
        "guild": {"id": ch.guild_id, "name": ch.guild_name, "icon_url": ch.guild_icon_url}
        if ch.guild_id else None,
        "channel": ch.as_dict(),
        "date_range": {"after": iso(ctx.options.after), "before": iso(ctx.options.before)},
        "note": ch.note,
        "message_count": len(messages),
        "messages": messages,
    }


def write_json(ctx: RenderContext, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_envelope(ctx, ctx.messages), fh, ensure_ascii=False, indent=2)


def write_raw_json(ctx: RenderContext, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_envelope(ctx, ctx.raw_messages or []), fh, ensure_ascii=False, indent=2)


CSV_COLUMNS = [
    "Nachrichten-ID", "Zeitstempel (UTC)", "Datum (lokal)", "Autor-ID", "Benutzername", "Anzeigename",
    "Bot", "Inhalt", "Anhänge", "Embeds", "Reaktionen", "Antwort auf", "Bearbeitet (UTC)", "Angeheftet",
    "Typ", "Link",
]


def write_csv(ctx: RenderContext, path: Path) -> None:
    # utf-8-sig, damit Excel Umlaute und Emojis richtig erkennt
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=ctx.options.csv_delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_COLUMNS)
        for m in ctx.messages:
            ts = parse_timestamp(m["timestamp"])
            text = system_text(m, ctx.resolver) or render_plain(m["content"], ctx.resolver)
            for fw in m.get("forwarded") or []:
                text += ("\n" if text else "") + "[Weitergeleitet] " + render_plain(fw["content"], ctx.resolver)
            writer.writerow([
                m["id"], m["timestamp"], fmt_datetime(ts, seconds=True) if ts else "",
                m["author"]["id"], m["author"]["username"], display_name(m["author"]),
                "ja" if m["author"].get("is_bot") else "",
                text,
                " | ".join(attachment_ref(a) for a in m["attachments"]),
                " | ".join(e.get("title") or e.get("url") or e.get("type", "embed") for e in m["embeds"]),
                ", ".join(f"{reaction_label(r)} {r['count']}" for r in m["reactions"]),
                (m.get("reference") or {}).get("message_id") or "",
                m.get("edited_timestamp") or "",
                "ja" if m.get("pinned") else "",
                m.get("type", 0),
                m.get("link") or "",
            ])


def _header_lines(ctx: RenderContext) -> list[str]:
    ch = ctx.channel
    lines = []
    if ch.guild_name:
        lines.append(f"Server:    {ch.guild_name}")
    lines.append(f"Kanal:     {ch.title}" + (f"  (Kategorie: {ch.category})" if ch.category else ""))
    if ch.topic:
        lines.append(f"Thema:     {ch.topic}")
    lines.append(f"Zeitraum:  {ctx.date_range_text}")
    lines.append(f"Quelle:    {ctx.source_label}")
    lines.append(f"Exportiert: {fmt_datetime(ctx.exported_at)} · {len(ctx.messages)} Nachrichten")
    if ch.note:
        lines.append(f"Hinweis:   {ch.note}")
    return lines


def _embed_plain(embed: dict, resolver: Resolver) -> list[str]:
    out = []
    if embed.get("author", {}).get("name"):
        out.append(embed["author"]["name"])
    if embed.get("title"):
        out.append(embed["title"])
    if embed.get("url"):
        out.append(embed["url"])
    if embed.get("description"):
        out.append(render_plain(embed["description"], resolver))
    for f in embed.get("fields") or []:
        out.append(f"{f.get('name', '')}: {render_plain(f.get('value', ''), resolver)}")
    if embed.get("footer", {}).get("text"):
        out.append(embed["footer"]["text"])
    return out


def write_txt(ctx: RenderContext, path: Path) -> None:
    sep = "=" * 70
    lines = [sep, *_header_lines(ctx), sep, ""]
    for m in ctx.messages:
        ts = parse_timestamp(m["timestamp"])
        stamp = fmt_datetime(ts) if ts else ""
        sys_text = system_text(m, ctx.resolver)
        if sys_text:
            lines += [f"[{stamp}] *** {sys_text}  [ID {m['id']}]", ""]
            continue
        head = f"[{stamp}] {display_name(m['author'])} (@{m['author']['username']}, Nutzer-ID {m['author']['id']})"
        if m.get("edited_timestamp"):
            head += " (bearbeitet)"
        if m.get("pinned"):
            head += " (angeheftet)"
        lines.append(head + f"  [ID {m['id']}]")
        ref = m.get("referenced_message")
        if ref:
            preview = render_plain(ref["content"], ctx.resolver).replace("\n", " ")[:80]
            lines.append(f"  ↳ Antwort auf {display_name(ref['author'])}: {preview}")
        if m.get("interaction"):
            lines.append(f"  ↳ {display_name(m['interaction']['user'])} hat /{m['interaction']['name']} verwendet")
        if m["content"]:
            lines.append(render_plain(m["content"], ctx.resolver))
        for fw in m.get("forwarded") or []:
            lines.append("[Weitergeleitet] " + render_plain(fw["content"], ctx.resolver))
            for a in fw["attachments"]:
                lines.append(f"  📎 {a['filename']}: {attachment_ref(a)}")
        for a in m["attachments"]:
            size = f" ({human_size(a['size'])})" if a.get("size") else ""
            lines.append(f"📎 {a['filename']}{size}: {attachment_ref(a)}")
        for e in m["embeds"]:
            lines += ["[Embed] " + x for x in _embed_plain(e, ctx.resolver)]
        for s in m["stickers"]:
            lines.append(f"[Sticker] {s['name']}")
        if m.get("poll"):
            lines += _poll_plain(m["poll"])
        if m["reactions"]:
            lines.append("Reaktionen: " + ", ".join(f"{reaction_label(r)} {r['count']}" for r in m["reactions"]))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _poll_plain(poll: dict) -> list[str]:
    counts = {c.get("id"): c.get("count", 0) for c in (poll.get("results") or {}).get("answer_counts") or []}
    out = [f"[Umfrage] {(poll.get('question') or {}).get('text', '')}"]
    for ans in poll.get("answers") or []:
        out.append(f"  – {(ans.get('poll_media') or {}).get('text', '')} ({counts.get(ans.get('answer_id'), 0)})")
    return out


def _md_escape_link(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def write_markdown(ctx: RenderContext, path: Path) -> None:
    ch = ctx.channel
    title = f"{ch.title} – {ch.guild_name}" if ch.guild_name else ch.title
    lines = [f"# {title}", ""]
    lines += [f"> {line}" for line in _header_lines(ctx)] + [""]
    last_day = None
    for m in ctx.messages:
        ts = parse_timestamp(m["timestamp"])
        day = ts.astimezone().date() if ts else None
        if day and day != last_day:
            lines += [f"## {day.strftime('%d.%m.%Y')}", ""]
            last_day = day
        sys_text = system_text(m, ctx.resolver)
        stamp = ts.astimezone().strftime("%H:%M") if ts else ""
        if sys_text:
            lines += [f"*{stamp} · {sys_text}*", ""]
            continue
        flags = (" *(bearbeitet)*" if m.get("edited_timestamp") else "") + (" 📌" if m.get("pinned") else "")
        lines.append(f"**{display_name(m['author'])}** · {stamp}{flags}  ")
        ref = m.get("referenced_message")
        if ref:
            preview = render_plain(ref["content"], ctx.resolver).replace("\n", " ")[:80]
            lines.append(f"↳ *Antwort auf {display_name(ref['author'])}:* {preview}  ")
        if m["content"]:
            lines.append(render_plain(m["content"], ctx.resolver))
        for fw in m.get("forwarded") or []:
            lines += ["", "> *Weitergeleitet:* " + render_plain(fw["content"], ctx.resolver).replace("\n", "\n> "), ""]
        for a in m["attachments"]:
            ref_path = attachment_ref(a).replace(" ", "%20")
            ctype = a.get("content_type") or ""
            bang = "!" if ctype.startswith("image/") or ref_path.lower().split("?")[0].endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp")) else ""
            lines.append(f"{bang}[{_md_escape_link(a['filename'])}]({ref_path})  ")
        for e in m["embeds"]:
            lines += [""] + ["> " + x.replace("\n", "\n> ") + "  " for x in _embed_plain(e, ctx.resolver)] + [""]
        if m.get("poll"):
            lines += _poll_plain(m["poll"])
        if m["reactions"]:
            lines.append(" ".join(f"`{reaction_label(r)} {r['count']}`" for r in m["reactions"]))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
