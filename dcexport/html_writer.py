"""Eigenständige HTML-Datei im Discord-Look (Dunkel/Hell, Suche, Spoiler zum Aufdecken)."""

from __future__ import annotations

import html
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from . import APP_NAME, __version__
from .markdown import Resolver, is_emoji_only, render_html, render_plain
from .model import display_name, emoji_url
from .util import fmt_datetime, fmt_day_long, fmt_time, human_size, parse_timestamp
from .writers import RenderContext, reaction_label, system_text

GROUP_GAP = timedelta(minutes=7)

SYSTEM_ICONS = {1: "→", 2: "←", 3: "☎", 4: "✎", 5: "✎", 6: "📌", 7: "→", 8: "◆", 9: "◆", 10: "◆",
                11: "◆", 12: "↪", 18: "🧵", 24: "⛔", 27: "🎙", 28: "🎙", 46: "📊"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def web(url) -> str:
    """Nur http(s)-Adressen in Attribute übernehmen (kein javascript: aus Embeds)."""
    url = "" if url is None else str(url)
    return esc(url) if url.lower().startswith(("https://", "http://")) else ""


def src(local: str | None, remote: str | None) -> str:
    """Lokaler Pfad (URL-kodiert) oder entfernte URL, fertig für ein Attribut."""
    if local:
        return esc(quote(local.replace("\\", "/"), safe="/"))
    return esc(remote or "")


def _color(value: int | None) -> str:
    return f"#{value:06x}" if value else ""


CSS = r"""
:root{--bg:#313338;--bg2:#2b2d31;--bg3:#1e1f22;--text:#dbdee1;--head:#f2f3f5;--muted:#949ba4;
--link:#00a8fc;--mention:rgba(88,101,242,.3);--mention-text:#c9cdfb;--border:#3f4147;--hover:rgba(0,0,0,.08);
--code:#2b2d31;--embed:#2b2d31;--reaction:#2b2d31;--blurple:#5865f2;--green:#23a559}
:root[data-theme=light]{--bg:#fff;--bg2:#f2f3f5;--bg3:#e3e5e8;--text:#313338;--head:#060607;--muted:#5c5e66;
--link:#006ce7;--mention:rgba(88,101,242,.15);--mention-text:#505cdc;--border:#e1e2e4;--hover:rgba(6,6,7,.03);
--code:#f2f3f5;--embed:#f2f3f5;--reaction:#f2f3f5}
@media (prefers-color-scheme:light){:root:not([data-theme=dark]){--bg:#fff;--bg2:#f2f3f5;--bg3:#e3e5e8;--text:#313338;
--head:#060607;--muted:#5c5e66;--link:#006ce7;--mention:rgba(88,101,242,.15);--mention-text:#505cdc;--border:#e1e2e4;
--hover:rgba(6,6,7,.03);--code:#f2f3f5;--embed:#f2f3f5;--reaction:#f2f3f5}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font:16px/1.375 "gg sans","Segoe UI","Noto Sans",-apple-system,Helvetica,Arial,sans-serif;overflow-wrap:anywhere}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;background:var(--bg2);border-bottom:1px solid var(--bg3);
box-shadow:0 1px 2px rgba(0,0,0,.2)}
.top-inner{display:flex;align-items:center;gap:12px;padding:10px 16px}
.gicon{width:44px;height:44px;border-radius:14px;flex:none;object-fit:cover;background:var(--blurple);color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:700;font-size:18px}
.top-text{min-width:0;flex:1}
.top .guild{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top h1{margin:0;font-size:18px;color:var(--head);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top .topic{font-size:13px;color:var(--muted);max-height:2.8em;overflow:hidden}
.tools{display:flex;gap:8px;align-items:center;flex:none}
#q{background:var(--bg3);color:var(--text);border:0;border-radius:4px;padding:6px 8px;width:220px;font:inherit;font-size:14px}
#hits{font-size:12px;color:var(--muted);min-width:4em;text-align:right}
.btn{background:var(--bg3);color:var(--text);border:0;border-radius:4px;padding:6px 9px;cursor:pointer;font-size:14px}
.meta{padding:0 16px 8px;font-size:12px;color:var(--muted)}
.note{margin:0 16px 10px;padding:6px 10px;border-radius:4px;background:rgba(250,168,26,.12);
border-left:3px solid #faa81a;font-size:13px}
main{padding:8px 0 24px}
.day{display:flex;align-items:center;margin:24px 16px 8px;color:var(--muted);font-size:12px;font-weight:600}
.day::before,.day::after{content:"";flex:1;height:1px;background:var(--border)}
.day span{padding:0 8px}
.group{padding:2px 16px 2px 72px;margin-top:17px;position:relative}
.msg:hover{background:var(--hover)}
.avatar{position:absolute;left:16px;width:40px;height:40px;border-radius:50%;object-fit:cover;margin-top:2px}
.head{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.name{font-weight:600;color:var(--head)}
.tag{background:var(--blurple);color:#fff;font-size:10px;font-weight:600;padding:1px 4px;border-radius:3px;
position:relative;top:-2px}
.head time{font-size:12px;color:var(--muted)}
.msg{position:relative;margin:0 -16px 0 -72px;padding:1px 16px 1px 72px}
.msg .side{position:absolute;left:0;width:64px;text-align:right;font-size:11px;color:var(--muted);visibility:hidden;
top:4px}
.msg:hover .side{visibility:visible}
.content{white-space:normal}
.content.jumbo{font-size:44px;line-height:1.2}
.content.jumbo .emoji{width:48px;height:48px}
.edited{font-size:10px;color:var(--muted);margin-left:3px}
.pin{font-size:12px;margin-left:4px}
.emoji{width:22px;height:22px;vertical-align:bottom;object-fit:contain}
.mention{background:var(--mention);color:var(--mention-text);border-radius:3px;padding:0 2px;font-weight:500}
.timestamp{background:var(--bg3);border-radius:3px;padding:0 2px}
code.inline{background:var(--code);border:1px solid var(--bg3);border-radius:4px;padding:0 .2em;font-size:85%;
font-family:Consolas,"Cascadia Mono",Menlo,monospace}
pre.codeblock{background:var(--code);border:1px solid var(--bg3);border-radius:4px;padding:8px;margin:4px 0;
white-space:pre-wrap;font-size:14px;font-family:Consolas,"Cascadia Mono",Menlo,monospace;max-width:90ch}
blockquote{margin:2px 0;padding:0 8px 0 12px;border-left:4px solid var(--border)}
h3,h4,h5{margin:8px 0 4px;color:var(--head)}h3{font-size:24px}h4{font-size:20px}h5{font-size:16px}
.subtext{font-size:12px;color:var(--muted)}
.spoiler{background:var(--bg3);color:transparent;border-radius:3px;cursor:pointer}
.spoiler *{visibility:hidden}.spoiler.on{color:inherit;background:var(--hover)}.spoiler.on *{visibility:visible}
.reply,.interaction{display:flex;align-items:center;gap:4px;font-size:13px;color:var(--muted);margin:0 0 2px;
position:relative;min-width:0}
.reply::before,.interaction::before{content:"";position:absolute;left:-36px;top:9px;width:30px;height:10px;
border-left:2px solid var(--border);border-top:2px solid var(--border);border-top-left-radius:6px}
.reply img{width:16px;height:16px;border-radius:50%;flex:none}
.reply .rname,.interaction .rname{font-weight:600;color:var(--head);flex:none}
.reply a,.reply .rtext{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.attachments{display:flex;flex-direction:column;gap:4px;margin:4px 0}
.att-img{max-width:min(400px,100%);max-height:350px;width:auto;height:auto;border-radius:6px;display:block;cursor:zoom-in}
.att-spoiler{filter:blur(40px);cursor:pointer}
video.att{max-width:min(480px,100%);max-height:360px;border-radius:6px}
audio.att{max-width:min(400px,100%)}
.file{display:flex;align-items:center;gap:10px;background:var(--bg2);border:1px solid var(--bg3);border-radius:8px;
padding:10px;max-width:min(430px,100%)}
.file .ficon{font-size:28px}.file .fsize{font-size:12px;color:var(--muted)}
.embed{display:flex;gap:12px;background:var(--embed);border-left:4px solid var(--bg3);border-radius:4px;
padding:8px 12px 12px;margin:4px 0;max-width:520px}
.embed .emain{min-width:0;flex:1;font-size:14px}
.e-author{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:600;margin-top:4px;color:var(--head)}
.e-author img{width:24px;height:24px;border-radius:50%}
.e-provider{font-size:12px;color:var(--muted);margin-top:4px}
.e-title{font-weight:600;margin-top:4px;color:var(--head)}
.e-desc{margin-top:4px}
.e-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}
.e-field{grid-column:1/-1}.e-field.inline{grid-column:auto}
.e-fname{font-weight:600;color:var(--head)}
.e-image{max-width:100%;max-height:300px;border-radius:4px;margin-top:12px;display:block}
.e-thumb{width:80px;height:80px;object-fit:contain;border-radius:4px;flex:none;margin-top:8px}
.e-footer{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-top:8px}
.e-footer img{width:20px;height:20px;border-radius:50%}
.e-media{max-width:min(400px,100%);border-radius:6px;display:block}
.sticker{width:160px;height:160px;object-fit:contain}
.reactions{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
.reaction{display:inline-flex;align-items:center;gap:4px;background:var(--reaction);border:1px solid var(--bg3);
border-radius:8px;padding:1px 6px;font-size:14px}
.reaction .emoji{width:18px;height:18px}
.reaction .count{font-size:13px;font-weight:600;color:var(--muted)}
.system{display:flex;gap:10px;align-items:baseline;padding:4px 16px 4px 28px;margin-top:8px;color:var(--muted);
font-size:15px}
.system .sicon{width:32px;text-align:center;color:var(--green)}
.system time{font-size:12px}
.forward{border-left:4px solid var(--border);padding-left:10px;margin:4px 0}
.forward .flabel{font-size:12px;color:var(--muted);font-style:italic}
.thread-chip{display:inline-block;background:var(--bg2);border-radius:6px;padding:4px 8px;margin:4px 0;font-size:13px}
.poll{background:var(--bg2);border:1px solid var(--bg3);border-radius:8px;padding:10px;max-width:440px;margin:4px 0}
.poll .pq{font-weight:600;color:var(--head);margin-bottom:6px}
.poll .pa{display:flex;justify-content:space-between;gap:8px;padding:4px 8px;border-radius:6px;background:var(--bg3);
margin-top:4px;font-size:14px}
.empty{padding:48px 16px;text-align:center;color:var(--muted)}
footer{padding:16px;text-align:center;font-size:12px;color:var(--muted);border-top:1px solid var(--border)}
.hidden{display:none!important}
mark{background:#faa81a66;color:inherit;border-radius:2px}
@media (max-width:640px){.top-inner{flex-wrap:wrap}.tools{width:100%}#q{flex:1;width:auto}
.e-fields{grid-template-columns:1fr}}
"""

JS = r"""
(function(){
var root=document.documentElement;
try{var t=localStorage.getItem('dce-theme');if(t)root.setAttribute('data-theme',t);}catch(e){}
var btn=document.getElementById('theme');
function isDark(){return getComputedStyle(root).getPropertyValue('--bg').trim()!=='#fff';}
function label(){btn.textContent=isDark()?'☀ Hell':'☾ Dunkel';}
label();
btn.addEventListener('click',function(){
 var next=isDark()?'light':'dark';root.setAttribute('data-theme',next);label();
 try{localStorage.setItem('dce-theme',next);}catch(e){}
});
document.addEventListener('click',function(e){
 var s=e.target.closest('.spoiler,.att-spoiler');
 if(s&&!s.classList.contains('on')){s.classList.add('on');s.classList.remove('att-spoiler');e.preventDefault();}
});
var q=document.getElementById('q'),hits=document.getElementById('hits'),timer;
var msgs=[].slice.call(document.querySelectorAll('.msg,.system'));
var blocks=[].slice.call(document.querySelectorAll('.group,.day'));
q.addEventListener('input',function(){clearTimeout(timer);timer=setTimeout(run,150);});
function run(){
 var term=q.value.trim().toLowerCase(),n=0;
 msgs.forEach(function(m){
  var ok=!term||m.textContent.toLowerCase().indexOf(term)>=0||(m.dataset.author||'').toLowerCase().indexOf(term)>=0;
  m.classList.toggle('hidden',!ok);if(ok&&term)n++;
 });
 blocks.forEach(function(b){
  if(b.classList.contains('day')){b.classList.toggle('hidden',!!term);return;}
  b.classList.toggle('hidden',!b.querySelector('.msg:not(.hidden)'));
 });
 hits.textContent=term?n+' Treffer':'';
}
if(location.hash){var el=document.querySelector(location.hash);if(el)el.scrollIntoView();}
})();
"""


class HtmlRenderer:
    def __init__(self, ctx: RenderContext):
        self.ctx = ctx
        self.r: Resolver = ctx.resolver
        self.ids = {m["id"] for m in ctx.messages}

    # ----------------------------------------------------------- Bausteine

    def md(self, text: str) -> str:
        return render_html(text or "", self.r)

    def avatar(self, user: dict) -> str:
        return src(user.get("avatar_local"), user.get("avatar_url"))

    def attachment(self, att: dict) -> str:
        url = src(att.get("local_path"), att.get("url"))
        name = esc(att.get("filename"))
        ctype = (att.get("content_type") or "").lower()
        lower = (att.get("filename") or "").lower()
        alt = esc(att.get("description") or att.get("filename"))
        if ctype.startswith("image/") or lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")):
            cls = "att-img att-spoiler" if att.get("spoiler") else "att-img"
            dims = ""
            if att.get("width") and att.get("height"):
                dims = f' width="{int(att["width"])}" height="{int(att["height"])}"'
            return (f'<a href="{url}" target="_blank" rel="noopener"><img class="{cls}" src="{url}" alt="{alt}"'
                    f'{dims} loading="lazy"></a>')
        if ctype.startswith("video/") or lower.endswith((".mp4", ".webm", ".mov", ".m4v")):
            return f'<video class="att" controls preload="metadata" src="{url}"></video>'
        if ctype.startswith("audio/") or lower.endswith((".mp3", ".ogg", ".wav", ".m4a", ".flac", ".opus")):
            return (f'<div class="file"><span class="ficon">🎵</span><div><a href="{url}" target="_blank" '
                    f'rel="noopener">{name}</a><br><audio class="att" controls preload="none" src="{url}"></audio>'
                    f'</div></div>')
        size = esc(human_size(att.get("size")))
        return (f'<div class="file"><span class="ficon">📄</span><div><a href="{url}" target="_blank" rel="noopener">'
                f'{name}</a><div class="fsize">{size}</div></div></div>')

    def embed(self, e: dict) -> str:
        etype = e.get("type", "rich")
        thumb = e.get("thumbnail") or {}
        video = e.get("video") or {}
        if etype == "gifv" and video.get("url"):
            poster = web(thumb.get("proxy_url") or thumb.get("url") or "")
            vsrc = web(video.get("proxy_url") or video.get("url"))
            return f'<video class="e-media" autoplay loop muted playsinline poster="{poster}" src="{vsrc}"></video>'
        if etype == "image" and (thumb.get("url") or thumb.get("proxy_url")):
            img = web(thumb.get("proxy_url") or thumb.get("url"))
            link = web(e.get("url") or thumb.get("url"))
            return f'<a href="{link}" target="_blank" rel="noopener"><img class="e-media" src="{img}" loading="lazy" alt=""></a>'
        color = _color(e.get("color"))
        style = f' style="border-left-color:{color}"' if color else ""
        parts = []
        provider = e.get("provider") or {}
        if provider.get("name"):
            parts.append(f'<div class="e-provider">{esc(provider["name"])}</div>')
        author = e.get("author") or {}
        if author.get("name"):
            icon = author.get("proxy_icon_url") or author.get("icon_url")
            img = f'<img src="{web(icon)}" alt="" loading="lazy">' if icon else ""
            name = esc(author["name"])
            if author.get("url"):
                name = f'<a href="{web(author["url"])}" target="_blank" rel="noopener">{name}</a>'
            parts.append(f'<div class="e-author">{img}{name}</div>')
        if e.get("title"):
            title = self.md(e["title"])
            if e.get("url"):
                title = f'<a href="{web(e["url"])}" target="_blank" rel="noopener">{title}</a>'
            parts.append(f'<div class="e-title">{title}</div>')
        if e.get("description"):
            parts.append(f'<div class="e-desc">{self.md(e["description"])}</div>')
        fields = e.get("fields") or []
        if fields:
            items = "".join(
                f'<div class="e-field{" inline" if f.get("inline") else ""}"><div class="e-fname">'
                f'{self.md(f.get("name", ""))}</div><div class="e-fval">{self.md(f.get("value", ""))}</div></div>'
                for f in fields)
            parts.append(f'<div class="e-fields">{items}</div>')
        image = e.get("image") or {}
        if image.get("url") or image.get("proxy_url"):
            parts.append(f'<img class="e-image" src="{web(image.get("proxy_url") or image.get("url"))}" '
                         f'loading="lazy" alt="">')
        elif etype == "video" and (thumb.get("url") or thumb.get("proxy_url")):
            link = web(e.get("url") or video.get("url") or "")
            parts.append(f'<a href="{link}" target="_blank" rel="noopener"><img class="e-image" '
                         f'src="{web(thumb.get("proxy_url") or thumb.get("url"))}" loading="lazy" alt="Video"></a>')
            thumb = {}
        footer = e.get("footer") or {}
        ts = parse_timestamp(e.get("timestamp"))
        if footer.get("text") or ts:
            icon = footer.get("proxy_icon_url") or footer.get("icon_url")
            img = f'<img src="{web(icon)}" alt="" loading="lazy">' if icon else ""
            bits = [esc(footer.get("text"))] if footer.get("text") else []
            if ts:
                bits.append(esc(fmt_datetime(ts)))
            parts.append(f'<div class="e-footer">{img}<span>{" · ".join(bits)}</span></div>')
        thumb_html = ""
        if (thumb.get("url") or thumb.get("proxy_url")) and etype != "video":
            thumb_html = f'<img class="e-thumb" src="{web(thumb.get("proxy_url") or thumb.get("url"))}" loading="lazy" alt="">'
        if not parts and not thumb_html:
            return ""
        return f'<div class="embed"{style}><div class="emain">{"".join(parts)}</div>{thumb_html}</div>'

    def reactions(self, reactions: list[dict]) -> str:
        if not reactions:
            return ""
        out = []
        for r in reactions:
            e = r["emoji"]
            if e.get("id"):
                face = (f'<img class="emoji" src="{src(r.get("local_path"), emoji_url(e["id"], e.get("animated")))}"'
                        f' alt="{esc(reaction_label(r))}" title="{esc(reaction_label(r))}">')
            else:
                face = esc(e.get("name"))
            out.append(f'<span class="reaction">{face}<span class="count">{int(r.get("count", 0))}</span></span>')
        return f'<div class="reactions">{"".join(out)}</div>'

    def stickers(self, stickers: list[dict]) -> str:
        out = []
        for s in stickers:
            if s.get("local_path") or s.get("url"):
                out.append(f'<img class="sticker" src="{src(s.get("local_path"), s.get("url"))}" '
                           f'alt="{esc(s.get("name"))}" title="Sticker: {esc(s.get("name"))}">')
            else:
                out.append(f'<div class="thread-chip">Sticker: {esc(s.get("name"))}</div>')
        return "".join(out)

    def poll(self, poll: dict | None) -> str:
        if not poll:
            return ""
        counts = {c.get("id"): c.get("count", 0)
                  for c in (poll.get("results") or {}).get("answer_counts") or []}
        answers = "".join(
            f'<div class="pa"><span>{esc((a.get("poll_media") or {}).get("emoji", {}).get("name") or "")} '
            f'{esc((a.get("poll_media") or {}).get("text", ""))}</span><span>{counts.get(a.get("answer_id"), 0)}</span></div>'
            for a in poll.get("answers") or [])
        question = esc((poll.get("question") or {}).get("text", ""))
        return f'<div class="poll"><div class="pq">📊 {question}</div>{answers}</div>'

    def body(self, m: dict) -> str:
        """Inhalt einer Nachricht ohne Kopfzeile."""
        out = []
        if m["content"]:
            jumbo = " jumbo" if is_emoji_only(m["content"]) else ""
            edited = ""
            if m.get("edited_timestamp"):
                ets = parse_timestamp(m["edited_timestamp"])
                edited = f'<span class="edited" title="Bearbeitet: {esc(fmt_datetime(ets) if ets else "")}">(bearbeitet)</span>'
            pin = '<span class="pin" title="Angeheftet">📌</span>' if m.get("pinned") else ""
            out.append(f'<div class="content{jumbo}">{self.md(m["content"])}{edited}{pin}</div>')
        elif m.get("pinned"):
            out.append('<span class="pin" title="Angeheftet">📌</span>')
        for fw in m.get("forwarded") or []:
            inner = ['<div class="flabel">↪ Weitergeleitet</div>']
            if fw.get("content"):
                inner.append(f'<div class="content">{self.md(fw["content"])}</div>')
            if fw.get("attachments"):
                inner.append('<div class="attachments">' + "".join(self.attachment(a) for a in fw["attachments"]) + "</div>")
            inner += [self.embed(e) for e in fw.get("embeds") or []]
            inner.append(self.stickers(fw.get("stickers") or []))
            out.append(f'<div class="forward">{"".join(inner)}</div>')
        if m["attachments"]:
            out.append('<div class="attachments">' + "".join(self.attachment(a) for a in m["attachments"]) + "</div>")
        out += [self.embed(e) for e in m["embeds"]]
        out.append(self.stickers(m["stickers"]))
        out.append(self.poll(m.get("poll")))
        if m.get("thread"):
            out.append(f'<div class="thread-chip">🧵 Thread: {esc(m["thread"].get("name"))}</div>')
        out.append(self.reactions(m["reactions"]))
        return "".join(out)

    def reply_bar(self, m: dict) -> str:
        ref = m.get("referenced_message")
        if m.get("interaction"):
            who = esc(display_name(m["interaction"]["user"]))
            return f'<div class="interaction"><span class="rname">{who}</span> hat <b>/{esc(m["interaction"]["name"])}</b> verwendet</div>'
        if not m.get("reference") or (m["reference"].get("type") == 1):
            return ""
        if not ref:
            return '<div class="reply"><i>Ursprüngliche Nachricht wurde gelöscht oder liegt außerhalb des Exports.</i></div>'
        preview = render_plain(ref["content"], self.r).replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:120] + "…"
        if not preview:
            preview = "Klicken, um den Anhang zu sehen" if ref.get("has_attachments") else "…"
        target = f'#m-{esc(ref["id"])}' if ref["id"] in self.ids else None
        text = f'<a href="{target}">{esc(preview)}</a>' if target else f'<span class="rtext">{esc(preview)}</span>'
        avatar = src(ref["author"].get("avatar_local"), ref["author"].get("avatar_url"))
        return (f'<div class="reply"><img src="{avatar}" alt="" loading="lazy"><span class="rname">'
                f'{esc(display_name(ref["author"]))}</span>{text}</div>')

    # -------------------------------------------------------------- Ablauf

    def messages_html(self) -> str:
        out: list[str] = []
        last_day = None
        prev = None  # (author_id, timestamp) der letzten normalen Nachricht
        group_open = False

        def close_group() -> None:
            nonlocal group_open
            if group_open:
                out.append("</div></article>")
                group_open = False

        for m in self.ctx.messages:
            ts = parse_timestamp(m["timestamp"])
            day = ts.astimezone().date()
            if day != last_day:
                close_group()
                out.append(f'<div class="day"><span>{esc(fmt_day_long(ts))}</span></div>')
                last_day = day
                prev = None
            sys_text = system_text(m, self.r)
            if sys_text:
                close_group()
                icon = SYSTEM_ICONS.get(m.get("type"), "•")
                out.append(f'<div class="system" id="m-{esc(m["id"])}" data-author="{esc(display_name(m["author"]))}">'
                           f'<span class="sicon">{icon}</span><span>{esc(sys_text)}</span>'
                           f'<time datetime="{esc(m["timestamp"])}">{esc(fmt_datetime(ts))}</time></div>')
                prev = None
                continue
            author = m["author"]
            starts_group = (
                prev is None or prev[0] != author["id"] or ts - prev[1] > GROUP_GAP
                or bool(m.get("reference") and m["reference"].get("type") != 1) or bool(m.get("interaction"))
            )
            name = esc(display_name(author))
            if starts_group:
                close_group()
                color = _color(author.get("color"))
                style = f' style="color:{color}"' if color else ""
                tag = '<span class="tag">BOT</span>' if author.get("is_bot") else ""
                title = esc(author.get("username"))
                out.append(
                    f'<article class="group">{self.reply_bar(m)}<img class="avatar" src="{self.avatar(author)}" '
                    f'alt="" loading="lazy"><div class="gbody"><div class="head"><span class="name"{style} '
                    f'title="{title}">{name}</span>{tag}<time datetime="{esc(m["timestamp"])}" '
                    f'title="{esc(fmt_datetime(ts, seconds=True))}">{esc(fmt_datetime(ts))}</time></div>')
                group_open = True
                side = ""
            else:
                side = f'<time class="side" title="{esc(fmt_datetime(ts, seconds=True))}">{esc(fmt_time(ts))}</time>'
            out.append(f'<div class="msg" id="m-{esc(m["id"])}" data-author="{name}">{side}{self.body(m)}</div>')
            prev = (author["id"], ts)
        close_group()
        if not self.ctx.messages:
            out.append('<div class="empty">Keine Nachrichten im gewählten Zeitraum.</div>')
        return "".join(out)

    def document(self) -> str:
        ctx, ch = self.ctx, self.ctx.channel
        guild = ch.guild_name or ("Direktnachrichten" if ch.is_dm else "")
        if ctx.guild_icon_local or ch.guild_icon_url:
            icon = f'<img class="gicon" src="{src(ctx.guild_icon_local, ch.guild_icon_url)}" alt="">'
        else:
            initial = esc((guild or ch.name or "?")[:1].upper())
            icon = f'<div class="gicon">{initial}</div>'
        topic = f'<div class="topic">{self.md(ch.topic)}</div>' if ch.topic else ""
        category = f" · {esc(ch.category)}" if ch.category else ""
        meta = (f"{len(ctx.messages)} Nachrichten · Zeitraum: {esc(ctx.date_range_text)} · "
                f"Exportiert am {esc(fmt_datetime(ctx.exported_at))} · Quelle: {esc(ctx.source_label)}")
        note = f'<div class="note">{esc(ch.note)}</div>' if ch.note else ""
        title = esc(f"{ch.title} – {guild}" if guild else ch.title)
        return (
            '<!doctype html>\n<html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="generator" content="{esc(APP_NAME)} {esc(__version__)}">'
            f"<title>{title}</title><style>{CSS}</style></head><body>"
            f'<header class="top"><div class="top-inner">{icon}<div class="top-text">'
            f'<div class="guild">{esc(guild)}{category}</div><h1>{esc(ch.title)}</h1>{topic}</div>'
            '<div class="tools"><input id="q" type="search" placeholder="Nachrichten durchsuchen …" '
            'aria-label="Nachrichten durchsuchen"><span id="hits"></span>'
            '<button class="btn" id="theme" type="button" title="Hell/Dunkel umschalten">Design</button></div></div>'
            f'<div class="meta">{meta}</div>{note}</header>'
            f'<main id="log">{self.messages_html()}</main>'
            f"<footer>Erstellt mit {esc(APP_NAME)} {esc(__version__)} am {esc(fmt_datetime(ctx.exported_at))}</footer>"
            f"<script>{JS}</script></body></html>\n"
        )


def write_html(ctx: RenderContext, path: Path) -> None:
    path.write_text(HtmlRenderer(ctx).document(), encoding="utf-8")
