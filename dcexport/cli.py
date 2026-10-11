"""Kommandozeile für Automatisierung (z. B. Aufgabenplanung unter Windows)."""

from __future__ import annotations

import argparse
import os
import sys

from .api import DiscordAPIError, DiscordClient
from .exporter import ApiExporter, PackageExporter
from .model import CHANNEL_TYPES, ExportOptions
from .package import DataPackage
from .util import date_range_to_utc, parse_date_input
from .writers import FORMATS


def _print(msg: str) -> None:
    print(msg, flush=True)


def _options(args) -> ExportOptions:
    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    unknown = formats - set(FORMATS)
    if unknown:
        raise SystemExit(f"Unbekanntes Format: {', '.join(sorted(unknown))}. Erlaubt: {', '.join(FORMATS)}")
    after, before = date_range_to_utc(parse_date_input(args.date_from), parse_date_input(args.date_to))
    delim = {"tab": "\t", "\\t": "\t"}.get(args.csv_delimiter.lower(), args.csv_delimiter)
    return ExportOptions(out_dir=args.out, formats=formats, after=after, before=before,
                         download_media=not args.no_media, include_threads=not args.no_threads,
                         csv_delimiter=delim)


def _client(args) -> DiscordClient:
    token = args.token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Kein Token: --token angeben oder DISCORD_BOT_TOKEN setzen.")
    return DiscordClient(token, log=_print)


def _progress(index: int, total: int, fraction: float, label: str) -> None:
    pass  # Fortschritt steht schon im Log


def cmd_list(args) -> int:
    exporter = ApiExporter(_client(args), log=_print)
    for gd in exporter.connect():
        print(f"\n{gd.guild['name']}  [Server {gd.guild['id']}]")
        for ch in gd.channels:
            cat = f"{ch.category} / " if ch.category else ""
            print(f"  {ch.id}  {CHANNEL_TYPES.get(ch.type, ch.type):<14} {cat}{ch.name}")
    return 0


def cmd_export(args) -> int:
    options = _options(args)
    exporter = ApiExporter(_client(args), log=_print)
    guilds = exporter.connect()
    wanted_channels = set(args.channel or [])
    wanted_guilds = set(args.guild or [])
    selected = [ch for gd in guilds for ch in gd.channels
                if ch.id in wanted_channels or gd.guild["id"] in wanted_guilds]
    missing = wanted_channels - {ch.id for ch in selected}
    if missing:
        _print(f"Nicht gefunden oder kein Zugriff: {', '.join(sorted(missing))}")
    if not selected:
        _print("Nichts zu exportieren. Mit 'list' die IDs anzeigen.")
        return 2
    summary = exporter.export(selected, options, progress=_progress)
    _print(summary.text())
    for path in summary.protocol_files:
        _print(f"Protokoll: {path}")
    return 1 if summary.errors else 0


def cmd_package(args) -> int:
    pkg = DataPackage(args.path)
    convs = pkg.conversations()
    if args.list or (not args.channel and not args.all):
        for conv in convs:
            print(f"{conv.info.id}  {conv.message_count:>7}  {conv.group} / {conv.info.name}")
        return 0
    options = _options(args)
    selected = convs if args.all else [c for c in convs if c.info.id in set(args.channel)]
    if not selected:
        _print("Keine passende Unterhaltung gefunden.")
        return 2
    summary = PackageExporter(pkg, log=_print).export(selected, options, progress=_progress)
    _print(summary.text())
    for path in summary.protocol_files:
        _print(f"Protokoll: {path}")
    return 1 if summary.errors else 0


def _add_export_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", required=True, help="Zielordner")
    p.add_argument("--format", default="html,json",
                   help=f"Komma-getrennt: {', '.join(FORMATS)} (Standard: html,json)")
    p.add_argument("--from", dest="date_from", default="", help="Startdatum, z. B. 2024-01-31 oder 31.01.2024")
    p.add_argument("--to", dest="date_to", default="", help="Enddatum (einschließlich)")
    p.add_argument("--no-media", action="store_true", help="Anhänge/Avatare nicht herunterladen")
    p.add_argument("--csv-delimiter", default=";", help="Trennzeichen für CSV (Standard ';', 'tab' für Tab)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="discord_export.py",
                                     description="Discord-Kanäle exportieren. Ohne Befehl startet die GUI.")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="Server und Kanäle mit IDs auflisten (Bot-Token)")
    p.add_argument("--token", help="Bot-Token (sonst Umgebungsvariable DISCORD_BOT_TOKEN)")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("export", help="Kanäle per Bot-Token exportieren")
    p.add_argument("--token", help="Bot-Token (sonst Umgebungsvariable DISCORD_BOT_TOKEN)")
    p.add_argument("--channel", action="append", help="Kanal-ID (mehrfach möglich)")
    p.add_argument("--guild", action="append", help="Server-ID: alle Kanäle des Servers (mehrfach möglich)")
    p.add_argument("--no-threads", action="store_true", help="Threads nicht mitexportieren")
    _add_export_args(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("package", help="Datenpaket (package.zip oder Ordner) exportieren")
    p.add_argument("path", help="package.zip oder entpackter Ordner")
    p.add_argument("--list", action="store_true", help="Nur Unterhaltungen auflisten")
    p.add_argument("--channel", action="append", help="Kanal-ID (mehrfach möglich)")
    p.add_argument("--all", action="store_true", help="Alle Unterhaltungen exportieren")
    p.add_argument("--out", default=None, help="Zielordner")
    p.add_argument("--format", default="html,json")
    p.add_argument("--from", dest="date_from", default="")
    p.add_argument("--to", dest="date_to", default="")
    p.add_argument("--no-media", action="store_true")
    p.add_argument("--csv-delimiter", default=";")
    p.set_defaults(func=cmd_package, no_threads=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.cmd:
        from .gui import main as gui_main
        gui_main()
        return 0
    if args.cmd == "package" and not args.list and (args.channel or args.all) and not args.out:
        raise SystemExit("--out fehlt.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _print("Abgebrochen.")
        return 130
    except (DiscordAPIError, ValueError, OSError) as err:
        _print(f"Fehler: {err}")
        return 1
