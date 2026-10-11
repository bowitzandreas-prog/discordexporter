"""Tests: python -m unittest discover -s tests   (im Ordner tools/discord-export)"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from dcexport import model  # noqa: E402
from dcexport.api import DiscordAPIError, DiscordClient, normalize_token  # noqa: E402
from dcexport.exporter import ApiExporter, PackageExporter  # noqa: E402
from dcexport.markdown import Resolver, is_emoji_only, render_html, render_plain  # noqa: E402
from dcexport.model import ExportOptions  # noqa: E402
from dcexport.package import DataPackage  # noqa: E402
from dcexport.util import (date_range_to_utc, datetime_to_snowflake, parse_date_input,  # noqa: E402
                           parse_timestamp, sanitize_filename, snowflake_to_datetime)
from dcexport.protocol import sha256_file  # noqa: E402
from dcexport.writers import FORMATS  # noqa: E402
from mock_discord import START, TOKEN, MockDiscord, sf  # noqa: E402

ALL_FORMATS = set(FORMATS)


class UtilTests(unittest.TestCase):
    def test_snowflake_roundtrip(self):
        dt = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(snowflake_to_datetime(datetime_to_snowflake(dt)), dt)
        self.assertEqual(snowflake_to_datetime("175928847299117063").year, 2016)

    def test_parse_timestamp_variants(self):
        expected = datetime(2021, 3, 4, 12, 34, 56, 789000, tzinfo=timezone.utc)
        for raw in ("2021-03-04T12:34:56.789000+00:00", "2021-03-04 12:34:56.789+00:00",
                    "2021-03-04T12:34:56.789Z", "2021-03-04 12:34:56.789"):
            self.assertEqual(parse_timestamp(raw), expected, raw)
        self.assertEqual(parse_timestamp("2021-03-04T14:34:56.789+02:00"), expected)
        self.assertIsNone(parse_timestamp("Unsinn"))

    def test_date_input(self):
        self.assertEqual(parse_date_input("31.03.2024"), parse_date_input("2024-03-31"))
        self.assertIsNone(parse_date_input(" "))
        with self.assertRaises(ValueError):
            parse_date_input("31/03/2024")
        after, before = date_range_to_utc(parse_date_input("01.03.2024"), parse_date_input("01.03.2024"))
        self.assertEqual(before - after, timedelta(days=1))
        with self.assertRaises(ValueError):
            date_range_to_utc(parse_date_input("02.03.2024"), parse_date_input("01.03.2024"))

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename('a<b>:c"/d|e?*'), "a_b__c__d_e__")
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("  name. "), "name")
        long = sanitize_filename("x" * 300 + ".png", max_len=50)
        self.assertEqual(len(long), 50)
        self.assertTrue(long.endswith(".png"))

    def test_token_normalize(self):
        self.assertEqual(normalize_token(' "Bot abc.def" '), "abc.def")


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.r = Resolver(users={"1": "Andi"}, channels={"2": "handel"}, roles={"3": ("Mod", 0xFF0000)})

    def test_basic_formatting(self):
        out = render_html("**fett** *kursiv* __unter__ ~~weg~~ ||geheim||", self.r)
        for tag in ("<strong>fett</strong>", "<em>kursiv</em>", "<u>unter</u>", "<s>weg</s>", 'class="spoiler"'):
            self.assertIn(tag, out)

    def test_escaping(self):
        out = render_html("<script>alert('x')</script> & <b>", self.r)
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp;", out)

    def test_code_is_not_formatted(self):
        out = render_html("```py\nx = '**a**' <i>\n```", self.r)
        self.assertIn('<pre class="codeblock"><code data-lang="py">', out)
        self.assertIn("**a**", out)
        self.assertIn("&lt;i&gt;", out)
        self.assertIn("<code class=\"inline\">__init__</code>", render_html("`__init__`", self.r))

    def test_links_keep_underscores(self):
        out = render_html("siehe https://example.com/a_b_c_d?x=1. und [Shop](https://collectntrade.de)", self.r)
        self.assertIn('href="https://example.com/a_b_c_d?x=1"', out)
        self.assertIn('>Shop</a>', out)
        self.assertNotIn("<em>", out)

    def test_mentions_emoji_timestamp(self):
        out = render_html("<@1> <@!9> <#2> <@&3> <:pika:55> <t:0:d> @everyone", self.r)
        self.assertIn("@Andi", out)
        self.assertIn("@Nutzer 9", out)
        self.assertIn("#handel", out)
        self.assertIn("color:#ff0000", out)
        self.assertIn("emojis/55.png", out)
        self.assertIn("1970", out)
        self.assertIn("@everyone", out)
        plain = render_plain("<@1> sagt <:pika:55> in <#2>", self.r)
        self.assertEqual(plain, "@Andi sagt :pika: in #handel")

    def test_blocks(self):
        out = render_html("> zitat\n# Titel\n- punkt\ntext", self.r)
        self.assertIn("<blockquote>zitat</blockquote>", out)
        self.assertIn("<h3>Titel</h3>", out)
        self.assertIn("• punkt", out)
        out = render_html("vorher\n>>> alles\nzitiert", self.r)
        self.assertIn("<blockquote>alles<br>zitiert</blockquote>", out)

    def test_emoji_only(self):
        self.assertTrue(is_emoji_only("<:a:1> <a:b:2>"))
        self.assertTrue(is_emoji_only("👍🔥"))
        self.assertFalse(is_emoji_only("ok 👍"))


def build_package_zip(path: Path, attachment_url: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Account/user.json", json.dumps({
            "id": "4001", "username": "andi", "global_name": "Andi", "avatar_hash": None, "discriminator": "0",
            "relationships": [{"id": "4002", "type": 1, "nickname": None,
                               "user": {"id": "4002", "username": "misty", "global_name": "Misty"}}]}))
        z.writestr("Servers/index.json", json.dumps({"1000": "CollectnTrade Community"}))
        z.writestr("Messages/index.json", json.dumps({
            "111": "Direct Message with misty#0", "222": "handel in CollectnTrade Community", "333": None}))
        z.writestr("Messages/c111/channel.json", json.dumps({"id": "111", "type": "DM",
                                                             "recipients": ["4001", "4002"]}))
        z.writestr("Messages/c111/messages.json", json.dumps([
            {"ID": int(sf(60 * 24 * 32)), "Timestamp": "2024-04-02 09:00:00",
             "Contents": "<@4002> hast du noch Booster?", "Attachments": attachment_url},
            {"ID": int(sf(1)), "Timestamp": "2024-03-01 09:01:00", "Contents": "Hallo **Misty**",
             "Attachments": ""},
        ]))
        z.writestr("Messages/c222/channel.json", json.dumps({
            "id": "222", "type": "GUILD_TEXT", "name": "handel",
            "guild": {"id": "1000", "name": "CollectnTrade Community"}}))
        z.writestr("Messages/c222/messages.json", json.dumps([
            {"ID": int(sf(5)), "Timestamp": "2024-03-01 09:05:00", "Contents": "Suche <#222>", "Attachments": ""}]))


def build_old_package_dir(root: Path) -> None:
    base = root / "package"
    (base / "account").mkdir(parents=True)
    (base / "account" / "user.json").write_text(json.dumps({"id": "4001", "username": "andi"}), "utf-8")
    ch = base / "messages" / "555"
    ch.mkdir(parents=True)
    (base / "messages" / "index.json").write_text(json.dumps({"555": "Sammler-Runde"}), "utf-8")
    (ch / "channel.json").write_text(json.dumps({"id": "555", "type": 3, "name": "Sammler-Runde"}), "utf-8")
    (ch / "messages.csv").write_text(
        'ID,Timestamp,Contents,Attachments\n'
        f'{sf(2)},2024-03-01 09:02:00.123000+00:00,"Hallo, Welt\r\nZeile 2",\r\n'
        f'{sf(1)},2024-03-01 09:01:00.000000+00:00,Erste,\r\n', "utf-8", newline="")


class PackageTests(unittest.TestCase):
    def test_new_zip_format_export(self):
        with MockDiscord() as mock, tempfile.TemporaryDirectory() as tmp:
            self.addCleanup(setattr, model, "CDN", model.CDN)
            model.CDN = mock.base
            tmp = Path(tmp)
            zpath = tmp / "package.zip"
            build_package_zip(zpath, f"{mock.base}/attachments/1/2/foto.png?ex=1&is=2&hm=3")
            pkg = DataPackage(zpath)
            convs = pkg.conversations()
            self.assertEqual([c.info.name for c in convs], ["DM mit misty#0", "handel"])
            self.assertEqual(convs[0].group, "Direktnachrichten")
            self.assertEqual(convs[1].group, "Server: CollectnTrade Community")
            self.assertEqual(convs[0].message_count, 2)
            msgs = pkg.messages(convs[0])
            self.assertEqual(msgs[0]["content"], "Hallo **Misty**")  # aufsteigend sortiert
            self.assertEqual(msgs[1]["attachments"][0]["filename"], "foto.png")

            opts = ExportOptions(out_dir=str(tmp / "out"), formats=ALL_FORMATS, download_media=True)
            summary = PackageExporter(pkg, log=lambda m: None).export(convs, opts)
            self.assertFalse(summary.errors, summary.errors)
            self.assertEqual(summary.channels, 2)
            self.assertEqual(summary.messages, 3)
            self.assertEqual(summary.media_ok, 2)  # Anhang + Standard-Avatar
            out = tmp / "out" / "Datenpaket andi"
            html = (out / "DM mit misty#0 [111].html").read_text("utf-8")
            self.assertIn("@Misty", html)
            self.assertIn("<strong>Misty</strong>", html)
            self.assertIn("_Medien/", html)
            self.assertTrue((out / "CollectnTrade Community - handel [222].json").exists())
            data = json.loads((out / "DM mit misty#0 [111].json").read_text("utf-8"))
            self.assertEqual(data["message_count"], 2)
            local = data["messages"][1]["attachments"][0]["local_path"]
            self.assertTrue(local.startswith("_Medien/") and local.endswith("_foto.png"), local)
            self.assertTrue((out / local).is_file())
            raw = json.loads((out / "DM mit misty#0 [111].raw.json").read_text("utf-8"))
            self.assertEqual(raw["messages"][0]["Contents"], "Hallo **Misty**")
            self.assertTrue(data["messages"][0]["link"].startswith("https://discord.com/channels/@me/111/"))
            proto = Path(summary.protocol_files[0]).read_text("utf-8")
            self.assertIn(f"SHA-256 des Pakets: {sha256_file(zpath)}", proto)
            self.assertIn("nur die eigenen Nachrichten", proto)
            pkg.close()

    def test_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            build_package_zip(tmp / "p.zip", "")
            pkg = DataPackage(tmp / "p.zip")
            after, before = date_range_to_utc(parse_date_input("01.04.2024"), None)
            opts = ExportOptions(out_dir=str(tmp / "out"), formats={"json"}, after=after, download_media=False)
            summary = PackageExporter(pkg).export([pkg.conversations()[0]], opts)
            self.assertEqual(summary.messages, 1)
            pkg.close()

    def test_old_folder_format_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            build_old_package_dir(tmp)
            pkg = DataPackage(tmp)
            convs = pkg.conversations()
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0].group, "Gruppen")
            msgs = pkg.messages(convs[0])
            self.assertEqual([m["content"] for m in msgs], ["Erste", "Hallo, Welt\nZeile 2"])
            opts = ExportOptions(out_dir=str(tmp / "out"), formats={"txt", "md", "csv"}, download_media=False)
            summary = PackageExporter(pkg).export(convs, opts)
            self.assertEqual(summary.messages, 2)
            txt = (tmp / "out" / "Datenpaket andi" / "Sammler-Runde [555].txt").read_text("utf-8")
            self.assertIn("Zeile 2", txt)

    def test_not_a_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                DataPackage(tmp)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.mock = MockDiscord().__enter__()
        self._cdn = (model.CDN, model.MEDIA_CDN)
        model.CDN = model.MEDIA_CDN = self.mock.base
        self.logs: list[str] = []
        self.client = DiscordClient(TOKEN, base_url=self.mock.api, log=self.logs.append)

    def tearDown(self):
        model.CDN, model.MEDIA_CDN = self._cdn
        self.mock.__exit__(None, None, None)

    def test_bad_token(self):
        with self.assertRaises(DiscordAPIError) as ctx:
            DiscordClient("falsch", base_url=self.mock.api).me()
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("Bot-Token", str(ctx.exception))

    def test_pagination_order_and_rate_limit(self):
        msgs = list(self.client.iter_messages("2001"))
        self.assertEqual(len(msgs), 252)
        ids = [int(m["id"]) for m in msgs]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(self.mock.rate_limited_once)
        self.assertTrue(any("Rate-Limit" in line for line in self.logs))

    def test_date_window(self):
        msgs = list(self.client.iter_messages("2001", START + timedelta(minutes=25), START + timedelta(minutes=30)))
        self.assertEqual([m["content"] for m in msgs], [f"Nachricht Nummer {i}" for i in range(5, 10)])

    def test_full_export(self):
        exporter = ApiExporter(self.client, log=self.logs.append)
        guilds = exporter.connect()
        self.assertEqual(len(guilds), 1)
        names = [c.name for c in guilds[0].channels]
        self.assertEqual(names, ["fragen", "geheim", "Talk", "willkommen", "handel"])
        with tempfile.TemporaryDirectory() as tmp:
            opts = ExportOptions(out_dir=tmp, formats=ALL_FORMATS, include_threads=True, download_media=True)
            progress = []
            summary = exporter.export(guilds[0].channels, opts, progress=lambda *a: progress.append(a))
            self.assertFalse(summary.errors, summary.errors)
            self.assertEqual(summary.skipped, 1)       # geheim: kein Zugriff
            self.assertEqual(summary.channels, 5)      # willkommen, handel, Talk, 2 Threads
            self.assertEqual(summary.messages, 255)
            self.assertEqual(summary.media_failed, 1)  # abgelaufener PDF-Link
            self.assertEqual(progress[-1][2], 1.0)

            out = Path(tmp) / "CollectnTrade Community"
            base = out / "Allgemein - willkommen [2001]"
            data = json.loads(base.with_suffix(".json").read_text("utf-8"))
            self.assertEqual(data["message_count"], 252)
            self.assertEqual(data["guild"]["name"], "CollectnTrade Community")
            first, welcome = data["messages"][0], data["messages"][1]
            self.assertEqual(first["type"], 7)
            self.assertEqual(welcome["author"]["nickname"], "Andi (CnT)")
            self.assertEqual(welcome["author"]["color"], 0xE74C3C)
            pull = next(m for m in data["messages"] if m["content"] == "Mein Pull:")
            self.assertEqual(pull["attachments"][0]["local_path"], "_Medien/7001_glurak.png")
            self.assertIsNone(pull["attachments"][1]["local_path"])

            html = base.with_suffix(".html").read_text("utf-8")
            for needle in ("Andi (CnT)", "<strong>CollectnTrade</strong>", "&lt;script&gt;alert(1)",
                           "ist dem Server beigetreten", "#handel", "@Mod", "Weitergeleitet", "Nächstes Set?",
                           "Preis-Update", f'href="#m-{sf(2)}"', "_Medien/7001_glurak.png", "class=\"spoiler\"",
                           "content jumbo", "(bearbeitet)", "Thread: Tausch: Glurak", "BOT", "liste.pdf"):
                self.assertIn(needle, html)
            self.assertNotIn("<script>alert", html)

            with open(base.with_suffix(".csv"), encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh, delimiter=";"))
            self.assertEqual(len(rows), 253)
            self.assertEqual(rows[0][0], "Nachrichten-ID")
            raw = json.loads((out / "Allgemein - willkommen [2001].raw.json").read_text("utf-8"))
            self.assertEqual(len(raw["messages"]), 252)

            self.assertTrue((out / "Allgemein - handel - Tausch_ Glurak [2101].html").exists())
            self.assertTrue((out / "fragen - Wie lagere ich Karten_ [2102].md").exists())
            self.assertTrue((out / "Talk [2004].html").exists())
            media = {p.name for p in (out / "_Medien").iterdir()}
            self.assertIn("emoji_5001.png", media)
            self.assertIn("sticker_8001.png", media)
            self.assertTrue(any(n.startswith("icon_1000_") for n in media))
            self.assertTrue(any(n.startswith("avatar_4001_") for n in media))

            # Beweissicherung: Links, IDs, Protokoll, Prüfsummen
            self.assertEqual(rows[0][-1], "Link")
            self.assertEqual(rows[1][-1], f"https://discord.com/channels/1000/2001/{rows[1][0]}")
            self.assertEqual(welcome["link"], f"https://discord.com/channels/1000/2001/{welcome['id']}")
            self.assertIn(f'href="https://discord.com/channels/1000/2001/{welcome["id"]}"', html)
            txt = base.with_suffix(".txt").read_text("utf-8")
            self.assertIn(f"[ID {welcome['id']}]", txt)
            self.assertIn("Nutzer-ID 4001", txt)
            self.assertEqual(len(summary.protocol_files), 2)
            proto_path, sums_path = (Path(p) for p in summary.protocol_files)
            proto = proto_path.read_text("utf-8")
            for needle in ("Bot „ExportBot“ (ID 9999)", "Status:        vollständig", "Kanal-ID 2001",
                           "Nachrichten: 252", "geheim (Kanal-ID 2005)", sums_path.name,
                           f"SHA-256 der Prüfsummendatei: {sha256_file(sums_path)}"):
                self.assertIn(needle, proto)
            sums = sums_path.read_text("utf-8").splitlines()
            listed = {line.split(" *", 1)[1] for line in sums}
            self.assertIn("CollectnTrade Community/Allgemein - willkommen [2001].html", listed)
            self.assertIn("CollectnTrade Community/_Medien/7001_glurak.png", listed)
            for line in sums:
                digest, rel = line.split(" *", 1)
                self.assertEqual(sha256_file(Path(tmp) / rel), digest, rel)

    def test_cancel(self):
        exporter = ApiExporter(self.client)
        guilds = exporter.connect()
        self.client.cancel.set()
        with tempfile.TemporaryDirectory() as tmp:
            summary = exporter.export(guilds[0].channels, ExportOptions(out_dir=tmp))
        self.assertTrue(summary.cancelled)


def _tk_available() -> bool:
    if not os.environ.get("DISPLAY") and not sys.platform.startswith("win"):
        return False
    try:
        import tkinter
        tkinter.Tk().destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_tk_available(), "keine Anzeige / kein Tkinter")
class GuiSmokeTest(unittest.TestCase):
    def test_connect_select_export(self):
        from tkinter import messagebox

        from dcexport import gui

        with MockDiscord() as mock, tempfile.TemporaryDirectory() as tmp:
            os.environ["APPDATA"] = tmp
            cdn = (model.CDN, model.MEDIA_CDN)
            model.CDN = model.MEDIA_CDN = mock.base
            patched = {name: getattr(messagebox, name) for name in ("askyesno", "showinfo", "showerror",
                                                                    "showwarning")}
            for name in patched:
                setattr(messagebox, name, lambda *a, **k: False)
            try:
                app = gui.App()
                client = DiscordClient(TOKEN, base_url=mock.api, log=app.log, cancel=app.cancel)
                exporter = ApiExporter(client, log=app.log)
                app._on_api_loaded((exporter, exporter.connect()))
                tree = app.api_tree
                labels = list(tree.labels.values())
                self.assertIn("# willkommen", labels)
                target = next(i for i, label in tree.labels.items() if label == "# willkommen")
                tree.toggle(target)
                self.assertEqual(len(tree.checked()), 1)
                parent = tree.tree.parent(target)
                self.assertEqual(tree.state[parent], 2)  # Kategorie teilweise ausgewählt
                app.out_dir.set(str(Path(tmp) / "out"))
                app.format_vars["csv"].set(True)
                app._export()
                deadline = time.time() + 60
                while (app.worker and app.worker.is_alive()) or not app.events.empty():
                    app.update()
                    time.sleep(0.02)
                    self.assertLess(time.time(), deadline)
                app.update()
                self.assertTrue(app.status.get().startswith("Fertig"), app.status.get())
                files = list((Path(tmp) / "out" / "CollectnTrade Community").glob("*willkommen*"))
                self.assertEqual({f.suffix for f in files}, {".html", ".json", ".csv"})
                app.destroy()
            finally:
                model.CDN, model.MEDIA_CDN = cdn
                for name, fn in patched.items():
                    setattr(messagebox, name, fn)


if __name__ == "__main__":
    unittest.main()
