"""Exportprotokoll und SHA-256-Prüfsummen für die Beweissicherung.

Je Lauf entstehen zwei Dateien im Zielordner:
  Exportprotokoll_<Zeit>.txt   wer, wann, womit, was exportiert wurde
  Pruefsummen_<Zeit>.sha256    SHA-256 jeder Datei dieses Laufs (sha256sum-Format)
"""

from __future__ import annotations

import getpass
import hashlib
import platform
from datetime import datetime, timezone
from pathlib import Path

from . import APP_NAME, __version__
from .util import fmt_datetime, parse_timestamp

NOTES = [
    "Bearbeitete Nachrichten stehen im letzten Stand; frühere Fassungen liefert Discord nicht.",
    "Gelöschte Nachrichten sind nicht enthalten.",
    "Jede Nachricht trägt ihre Discord-ID und einen Link (https://discord.com/channels/...). "
    "Darüber lässt sie sich im Discord-Client nachprüfen, solange sie dort noch existiert.",
    "Die Discord-ID enthält den Sendezeitpunkt (Snowflake) und ist von Discord vergeben, nicht vom Werkzeug.",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def message_link(guild_id: str | None, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id or '@me'}/{channel_id}/{message_id}"


def channel_entry(title: str, channel_id: str, messages: list[dict], files: list[str]) -> dict:
    entry = {"title": title, "id": channel_id, "count": len(messages), "files": files,
             "first": None, "last": None}
    if messages:
        entry["first"] = (messages[0]["id"], messages[0]["timestamp"])
        entry["last"] = (messages[-1]["id"], messages[-1]["timestamp"])
    return entry


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _stamp(value: tuple[str, str | None] | None) -> str:
    if not value:
        return "–"
    mid, ts = value
    dt = parse_timestamp(ts)
    return f"{fmt_datetime(dt, seconds=True) if dt else '?'} (ID {mid})"


def write_protocol(out_dir: Path, *, started: datetime, summary, options, source_lines: list[str],
                   media_files: list[Path], extra_notes: list[str] | None = None) -> list[str]:
    """Schreibt Prüfsummen und Protokoll; gibt die beiden Pfade zurück."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.astimezone().strftime("%Y-%m-%d_%H%M%S")
    sums_path = out_dir / f"Pruefsummen_{stamp}.sha256"
    proto_path = out_dir / f"Exportprotokoll_{stamp}.txt"

    files = sorted({Path(f) for f in summary.files} | {Path(p) for p in media_files},
                   key=lambda p: _rel(p, out_dir).lower())
    sum_lines = [f"{sha256_file(p)} *{_rel(p, out_dir)}" for p in files if p.is_file()]
    sums_path.write_text("\n".join(sum_lines) + "\n", encoding="utf-8", newline="\n")

    ended = datetime.now(timezone.utc)
    if summary.errors:
        status = "mit Fehlern beendet"
    elif summary.cancelled:
        status = "vom Benutzer abgebrochen (unvollständig)"
    else:
        status = "vollständig"
    a, b = options.after, options.before
    zeitraum = "gesamter Verlauf" if not a and not b else \
        f"{fmt_datetime(a) if a else 'Anfang'} bis {fmt_datetime(b) if b else 'heute'} (Ende ausschließlich)"
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "?"

    lines = [
        f"EXPORTPROTOKOLL – {APP_NAME} {__version__}",
        "=" * 60,
        f"Beginn:        {fmt_datetime(started, seconds=True)} Ortszeit ({started.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S} UTC)",
        f"Ende:          {fmt_datetime(ended, seconds=True)} Ortszeit ({ended:%Y-%m-%d %H:%M:%S} UTC)",
        f"Ausgeführt:    Benutzer {user} auf {platform.node() or '?'} ({platform.platform()})",
        *[f"Quelle:        {line}" if i == 0 else f"               {line}" for i, line in enumerate(source_lines)],
        f"Zeitraum:      {zeitraum}",
        f"Formate:       {', '.join(sorted(options.formats))}",
        f"Medien:        {'heruntergeladen' if options.download_media else 'nicht heruntergeladen'}"
        + (f" ({getattr(summary, 'media_total', summary.media_ok)} gesichert, davon {summary.media_ok} neu geladen,"
           f" {summary.media_failed} fehlgeschlagen)" if options.download_media else ""),
        f"Status:        {status}",
        f"Ergebnis:      {summary.result_text()}",
        "",
        "Exportierte Kanäle",
        "-" * 60,
    ]
    for i, entry in enumerate(summary.channel_log, 1):
        lines.append(f"{i}. {entry['title']} (Kanal-ID {entry['id']})")
        lines.append(f"   Nachrichten: {entry['count']}")
        lines.append(f"   Erste:  {_stamp(entry['first'])}")
        lines.append(f"   Letzte: {_stamp(entry['last'])}")
        for f in entry["files"]:
            lines.append(f"   Datei:  {_rel(Path(f), out_dir)}")
    if not summary.channel_log:
        lines.append("(keine)")
    if summary.skipped_items:
        lines += ["", "Übersprungen", "-" * 60, *summary.skipped_items]
    if summary.errors:
        lines += ["", "Fehler", "-" * 60, *summary.errors]
    lines += ["", "Hinweise", "-" * 60, *[f"- {n}" for n in NOTES + (extra_notes or [])]]
    lines += [
        "",
        "Prüfsummen",
        "-" * 60,
        f"SHA-256 aller {len(sum_lines)} Dateien dieses Laufs: {sums_path.name}",
        f"SHA-256 der Prüfsummendatei: {sha256_file(sums_path)}",
        "Prüfen unter Windows (PowerShell, im Zielordner ausführen; keine Ausgabe = alles unverändert):",
        f"  Get-Content -Encoding UTF8 .\\{sums_path.name} | ForEach-Object {{ $h, $f = $_ -split ' \\*', 2; "
        "if ((Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash -ne $h) { \"ABWEICHUNG: $f\" } }",
        "Prüfen unter Linux/macOS:",
        f"  sha256sum -c {sums_path.name}",
        "",
    ]
    proto_path.write_text("\n".join(lines), encoding="utf-8")
    return [str(proto_path), str(sums_path)]
