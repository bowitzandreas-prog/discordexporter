"""Discord-Markdown nach HTML bzw. lesbarem Klartext.

Reihenfolge: Codeblöcke, Inline-Code, Links, Erwähnungen und Emojis werden zuerst
als Platzhalter geparkt, dann wird der Rest HTML-escaped und formatiert. So bleiben
URLs mit Unterstrichen heil und Code wird nicht formatiert.
"""

from __future__ import annotations

import html
import re
from typing import Callable

from .model import emoji_url
from .util import fmt_discord_timestamp


class Resolver:
    """Löst IDs aus Erwähnungen in Namen auf."""

    def __init__(self, users: dict | None = None, channels: dict | None = None,
                 roles: dict | None = None,
                 emoji_src: Callable[[str, bool], str] | None = None):
        self.users = users if users is not None else {}        # id -> Anzeigename
        self.channels = channels if channels is not None else {}  # id -> Kanalname
        self.roles = roles if roles is not None else {}        # id -> (Name, Farbe als int oder None)
        self.emoji_src = emoji_src or emoji_url

    def user(self, uid: str) -> str:
        return self.users.get(uid) or f"Nutzer {uid}"

    def channel(self, cid: str) -> str:
        return self.channels.get(cid) or "unbekannter-kanal"

    def role(self, rid: str) -> tuple[str, int | None]:
        return self.roles.get(rid) or ("unbekannte-rolle", None)


class _Stash:
    _RE = re.compile("\x00(\\d+)\x00")

    def __init__(self) -> None:
        self.items: list[str] = []

    def put(self, value: str) -> str:
        self.items.append(value)
        return f"\x00{len(self.items) - 1}\x00"

    def restore(self, text: str) -> str:
        for _ in range(8):
            new = self._RE.sub(lambda m: self.items[int(m.group(1))], text)
            if new == text:
                break
            text = new
        return text


_CODEBLOCK = re.compile(r"```(?:([\w+\-.#]+)?\n)?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"``(.+?)``|`([^`]+?)`", re.S)
_ESCAPED = re.compile(r"\\([\\*_~|`>#\-\[\]()<:@])")
_MASKED_LINK = re.compile(r"\[([^\]\n]+)\]\(\s*<?(https?://[^\s)>]+)>?\s*\)")
_ANGLE_LINK = re.compile(r"<(https?://[^\s>]+)>")
_URL = re.compile(r"https?://[^\s<>\"\x00]+[^\s<>\"\x00.,:;'!?)\]]")
_USER = re.compile(r"<@!?(\d+)>")
_ROLE = re.compile(r"<@&(\d+)>")
_CHANNEL = re.compile(r"<#(\d+)>")
_COMMAND = re.compile(r"</([\w\- ]+):(\d+)>")
_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")
_TIMESTAMP = re.compile(r"<t:(-?\d+)(?::([tTdDfFR]))?>")
_EVERYONE = re.compile(r"@(everyone|here)\b")

_UNICODE_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍"
    "\U0001F1E6-\U0001F1FF\U0001F3FB-\U0001F3FF⃣©®‼⁉™ℹ]"
)

_INLINE_RULES = [
    (re.compile(r"\*\*\*(.+?)\*\*\*", re.S), r"<strong><em>\1</em></strong>"),
    (re.compile(r"___(.+?)___", re.S), r"<u><em>\1</em></u>"),
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"<strong>\1</strong>"),
    (re.compile(r"__(.+?)__", re.S), r"<u>\1</u>"),
    (re.compile(r"\*(?![\s*])(.+?)(?<![\s*])\*", re.S), r"<em>\1</em>"),
    (re.compile(r"(?<![\w])_(?!_)(.+?)(?<!_)_(?![\w])", re.S), r"<em>\1</em>"),
    (re.compile(r"~~(.+?)~~", re.S), r"<s>\1</s>"),
    (re.compile(r"\|\|(.+?)\|\|", re.S), r'<span class="spoiler" title="Spoiler">\1</span>'),
]


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _link(url: str, label: str | None = None) -> str:
    return f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(label or url)}</a>'


def is_emoji_only(text: str) -> bool:
    """True, wenn die Nachricht nur aus Emojis besteht (Discord zeigt die dann groß)."""
    if not text or not text.strip():
        return False
    rest = _EMOJI.sub("", text)
    count = len(_EMOJI.findall(text)) + len(_UNICODE_EMOJI.findall(rest))
    rest = _UNICODE_EMOJI.sub("", rest)
    return not rest.strip() and 0 < count <= 30


def render_html(text: str, resolver: Resolver) -> str:
    if not text:
        return ""
    stash = _Stash()
    text = text.replace("\x00", "").replace("\r\n", "\n")

    def codeblock(m: re.Match) -> str:
        lang, body = m.group(1), m.group(2)
        if body.endswith("\n"):
            body = body[:-1]
        attr = f' data-lang="{_esc(lang)}"' if lang else ""
        return stash.put(f'<pre class="codeblock"><code{attr}>{_esc(body)}</code></pre>')

    text = _CODEBLOCK.sub(codeblock, text)
    text = _INLINE_CODE.sub(
        lambda m: stash.put(f'<code class="inline">{_esc(m.group(1) or m.group(2))}</code>'), text)
    text = _ESCAPED.sub(lambda m: stash.put(_esc(m.group(1))), text)
    text = _MASKED_LINK.sub(lambda m: stash.put(_link(m.group(2), m.group(1))), text)
    text = _ANGLE_LINK.sub(lambda m: stash.put(_link(m.group(1))), text)
    text = _URL.sub(lambda m: stash.put(_link(m.group(0))), text)

    text = _USER.sub(lambda m: stash.put(
        f'<span class="mention" title="{m.group(1)}">@{_esc(resolver.user(m.group(1)))}</span>'), text)

    def role(m: re.Match) -> str:
        name, color = resolver.role(m.group(1))
        style = ""
        if color:
            hexc = f"#{color:06x}"
            style = f' style="color:{hexc};background:{hexc}26"'
        return stash.put(f'<span class="mention"{style}>@{_esc(name)}</span>')

    text = _ROLE.sub(role, text)
    text = _CHANNEL.sub(lambda m: stash.put(
        f'<span class="mention">#{_esc(resolver.channel(m.group(1)))}</span>'), text)
    text = _COMMAND.sub(lambda m: stash.put(f'<span class="mention">/{_esc(m.group(1))}</span>'), text)
    text = _EMOJI.sub(lambda m: stash.put(
        f'<img class="emoji" src="{_esc(resolver.emoji_src(m.group(3), bool(m.group(1))))}" '
        f'alt=":{_esc(m.group(2))}:" title=":{_esc(m.group(2))}:" loading="lazy">'), text)

    def timestamp(m: re.Match) -> str:
        unix, style = int(m.group(1)), m.group(2) or "f"
        try:
            shown, full = fmt_discord_timestamp(unix, style), fmt_discord_timestamp(unix, "F")
        except (OverflowError, OSError, ValueError):
            return stash.put(_esc(m.group(0)))
        return stash.put(f'<span class="timestamp" title="{_esc(full)}">{_esc(shown)}</span>')

    text = _TIMESTAMP.sub(timestamp, text)
    text = _EVERYONE.sub(lambda m: stash.put(f'<span class="mention">@{m.group(1)}</span>'), text)

    text = html.escape(text, quote=False)
    for pattern, repl in _INLINE_RULES:
        text = pattern.sub(repl, text)

    return stash.restore(_blocks(text))


def _blocks(text: str) -> str:
    """Zeilenweise Blöcke: Zitate, Überschriften, Kleintext, Listen."""
    out: list[str] = []
    quote: list[str] = []
    lines = text.split("\n")

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>" + "<br>".join(quote) + "</blockquote>")
            quote.clear()

    for i, line in enumerate(lines):
        if line.startswith("&gt;&gt;&gt; "):
            flush_quote()
            rest = [line[len("&gt;&gt;&gt; "):]] + lines[i + 1:]
            out.append("<blockquote>" + "<br>".join(rest) + "</blockquote>")
            return "".join(_join(out))
        if line.startswith("&gt; ") or line == "&gt;":
            quote.append(line[5:])
            continue
        flush_quote()
        m = re.match(r"^(#{1,3}) (.+)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level + 2}>{m.group(2)}</h{level + 2}>")
            continue
        if line.startswith("-# "):
            out.append(f'<div class="subtext">{line[3:]}</div>')
            continue
        m = re.match(r"^(\s*)[-*] (.+)$", line)
        if m:
            indent = len(m.group(1).replace("\t", "  ")) // 2
            out.append(f'<div class="li" style="margin-left:{indent * 1.2 + 0.4:.1f}em">• {m.group(2)}</div>')
            continue
        out.append(line)
    flush_quote()
    return "".join(_join(out))


_BLOCK_START = ("<blockquote", "<h3", "<h4", "<h5", '<div class="subtext"', '<div class="li"')


def _join(parts: list[str]):
    """Zeilen mit <br> verbinden, aber nicht direkt vor/nach Blockelementen."""
    prev_block = True
    for i, part in enumerate(parts):
        block = part.startswith(_BLOCK_START)
        if i > 0 and not block and not prev_block:
            yield "<br>"
        yield part
        prev_block = block


def render_plain(text: str, resolver: Resolver) -> str:
    """Erwähnungen, Emojis und Zeitstempel lesbar machen; Markdown bleibt stehen."""
    if not text:
        return ""
    text = _USER.sub(lambda m: "@" + resolver.user(m.group(1)), text)
    text = _ROLE.sub(lambda m: "@" + resolver.role(m.group(1))[0], text)
    text = _CHANNEL.sub(lambda m: "#" + resolver.channel(m.group(1)), text)
    text = _COMMAND.sub(lambda m: "/" + m.group(1), text)
    text = _EMOJI.sub(lambda m: f":{m.group(2)}:", text)

    def timestamp(m: re.Match) -> str:
        try:
            return fmt_discord_timestamp(int(m.group(1)), m.group(2) or "f")
        except (OverflowError, OSError, ValueError):
            return m.group(0)

    return _TIMESTAMP.sub(timestamp, text)
