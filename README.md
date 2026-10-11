# Discord-Export

Lokales Werkzeug mit Oberfläche, das Discord-Kanäle als Datei sichert. Läuft
auf dem eigenen PC, braucht nur Python (keine Zusatzpakete) und schickt nichts
an Dritte; es spricht nur mit `discord.com` und dem Discord-CDN.

Ausgabeformate, frei kombinierbar:

| Format | Datei | Wofür |
|---|---|---|
| HTML | `.html` | Lesen im Browser, Discord-Optik, Suche, Hell/Dunkel |
| JSON | `.json` | Weiterverarbeitung, einheitliches Schema für beide Quellen |
| JSON (Rohdaten) | `.raw.json` | Originalantwort der API bzw. Originalzeilen des Datenpakets |
| CSV (Excel) | `.csv` | Auswertung in Excel, UTF-8 mit BOM, Trennzeichen `;` |
| Text | `.txt` | Schlichtes Protokoll |
| Markdown | `.md` | Notizen, Wiki, Git |

Dazu bei jedem Lauf ein Exportprotokoll und SHA-256-Prüfsummen, siehe
[Beweissicherung](#beweissicherung).

## Drei Wege

**Server-Kanäle per Bot-Token.** Ein eigener Bot wird auf den Server
eingeladen und liest Text-, Ankündigungs-, Sprach- und Forenkanäle samt
Threads. Erfasst werden Inhalte, Anhänge, Embeds, Reaktionen, Antworten,
Sticker, Umfragen, weitergeleitete Nachrichten, Spitznamen und Rollenfarben.

**Eigenes Konto per Benutzer-Token.** Liest alles, was du in Discord selbst
siehst: Direktnachrichten und Gruppen **mit beiden Seiten** sowie Server ohne
Bot. **Risiko:** Discord verbietet das Automatisieren von Benutzerkonten
(„Self-Bot“) und kann das Konto dafür sperren. Das Werkzeug fragt vor der
ersten Nutzung nach und speichert den Token nicht. Siehe
[Eigenes Konto](#eigenes-konto-benutzer-token).

**Eigene DMs aus dem Datenpaket.** Der regelkonforme Weg für Direktnachrichten.
Discord stellt ein Datenpaket bereit (Einstellungen → Daten & Privatsphäre →
„Alle meine Daten anfordern“). Das Werkzeug liest die `package.zip` direkt, alte
und neue Paketstruktur. Das Paket enthält nur die eigenen Nachrichten, nie die
der Gegenseite.

## Einmalig einrichten

Python 3.10 oder neuer für Windows, z. B. von python.org oder per
`winget install Python.Python.3.12`. Tkinter ist dort enthalten.

Repo holen und einmal die Tests laufen lassen:

```powershell
git clone https://github.com/bowitzandreas-prog/discordexporter.git C:\discordexporter
cd C:\discordexporter
py -3 -m unittest discover -s tests     # endet mit OK
```

Ohne Git: auf GitHub „Code“ → „Download ZIP“ und nach `C:\discordexporter`
entpacken.

Danach reicht ein Doppelklick auf `Start-DiscordExport.bat`.

### Bot anlegen (für Server-Kanäle)

1. https://discord.com/developers/applications → „New Application“.
2. Links „Bot“ → „Reset Token“ → Token kopieren.
3. Ebenfalls unter „Bot“ den **Message Content Intent** einschalten. Ohne ihn
   liefert Discord leere Nachrichtentexte; das Werkzeug warnt dann im Log.
4. „OAuth2“ → „URL Generator“: Scope `bot`, Rechte „View Channels“ und
   „Read Message History“. Link öffnen, Bot auf den Server einladen (dafür ist
   „Server verwalten“ nötig).

Private Threads braucht zusätzlich „Manage Threads“. Kanäle ohne Leserecht
werden übersprungen und im Log genannt.

Der Token wird nicht gespeichert. Steht er in der Umgebungsvariablen
`DISCORD_BOT_TOKEN`, ist das Feld beim Start gefüllt:

```powershell
[Environment]::SetEnvironmentVariable("DISCORD_BOT_TOKEN", "<token>", "User")
```

## Bedienung

Reiter „Discord-API“: oben Bot-Token oder eigenes Konto wählen, Token eintragen,
„Verbinden“, Kanäle anhaken. Ein Haken an Server oder Kategorie wählt alles
darunter; mit eigenem Konto stehen die Direktnachrichten ganz oben, neueste
zuerst, und die Kanäle eines Servers werden erst beim Aufklappen geladen. Reiter „Datenpaket“: `package.zip` wählen, Unterhaltungen anhaken, mit
dem Filter lassen sich lange DM-Listen eingrenzen.

Unten Formate, Zeitraum (`TT.MM.JJJJ`, das Enddatum zählt mit) und Zielordner
wählen, dann „Export starten“. Exportiert wird immer der gerade offene Reiter.
Formate, Zielordner und Optionen merkt sich das Programm in
`%APPDATA%\DiscordExport\settings.json`.

Ablage im Zielordner:

```
Discord-Export\
  CollectnTrade Community\
    Allgemein - handel [123456789].html
    Allgemein - handel [123456789].json
    Allgemein - handel - Tausch Glurak [234567890].html   (Thread)
    _Medien\                                             (Anhänge, Avatare, Emojis)
  Direktnachrichten\                                    (eigenes Konto)
    DM mit misty (@misty) [456789012].html
  Datenpaket andi\
    DM mit misty#0 [345678901].html
```

**Medien herunterladen** sollte für ein dauerhaftes Archiv an bleiben.
Discord versieht Anhang-Links seit 2024 mit einem Ablaufdatum (etwa 24
Stunden); ohne lokale Kopie zeigt die HTML-Datei später leere Bilder. Bilder
aus Embeds (Link-Vorschauen) bleiben Verweise ins Netz. Wer eine HTML-Datei
weitergibt, gibt den Ordner `_Medien` mit.

Ein zweiter Export in denselben Ordner überschreibt die Dateien und lädt nur
fehlende Medien nach.

## Eigenes Konto (Benutzer-Token)

Discord verbietet das Automatisieren von Benutzerkonten. Das Konto kann dafür
gesperrt werden, auch dauerhaft. Wer diesen Weg wählt, trägt das Risiko selbst.
Das Werkzeug versucht nicht, sich zu tarnen: Es meldet sich mit eigenem
User-Agent und hält die Rate-Limits ein.

Token holen (im Browser, nicht in der Discord-App):

1. https://discord.com/app öffnen und anmelden.
2. F12 → Reiter „Netzwerk“ → im Filter `api` eingeben.
3. In Discord einen Kanal anklicken, links eine Anfrage wählen (z. B. `messages?limit=50`).
4. Unter „Anfrage-Header“ den Wert von `authorization` kopieren.

Der Token gibt vollen Zugriff auf das Konto: nie weitergeben, nicht in Skripte
schreiben. Abmelden im Browser oder ein Passwortwechsel macht ihn ungültig.
Für die Kommandozeile kann er in der Umgebungsvariablen `DISCORD_USER_TOKEN`
stehen.

## Beweissicherung

Jeder Export schreibt zusätzlich zwei Dateien in den Zielordner:

- `Exportprotokoll_<Datum_Zeit>.txt`: wann, von wem (Windows-Benutzer, Rechner), aus welcher Quelle
  (Bot oder Konto mit ID bzw. Datenpaket mit SHA-256), welcher Zeitraum, je Kanal Anzahl sowie erste und letzte
  Nachricht mit ID, übersprungene Kanäle mit Grund.
- `Pruefsummen_<Datum_Zeit>.sha256`: SHA-256 jeder erzeugten Datei samt Medien. Damit lässt sich
  später zeigen, dass seit dem Export nichts verändert wurde. Der Prüfbefehl für PowerShell steht im
  Protokoll; ohne Ausgabe ist alles unverändert, sonst erscheint `ABWEICHUNG: <Datei>`.

Jede Nachricht trägt ihre Discord-ID und einen Link `https://discord.com/channels/…` (HTML: Klick auf
die Uhrzeit, CSV: Spalte „Link“, JSON: Feld `link`). Darüber lässt sie sich im Discord-Client
nachprüfen, solange sie existiert. Im Text-Export stehen zusätzlich Nutzername und Nutzer-ID.

Was das Werkzeug nicht kann: Bearbeitete Nachrichten gibt Discord nur im letzten Stand heraus,
gelöschte gar nicht. Bei Direktnachrichten enthält das Datenpaket nur die eigene Seite.

Vorgehen, das sich bewährt hat (keine Rechtsberatung):

1. Früh sichern. Löscht die Gegenseite Nachrichten, sind sie auch im Export weg.
2. Server-Kanal: per Bot exportieren, das enthält beide Seiten.
3. Direktnachrichten: Mit eigenem Konto (Benutzer-Token, Risiko siehe oben) kommen beide Seiten
   in den Export. Regelkonform ist nur das Datenpaket, das enthält aber nur die eigene Seite; die
   Gegenseite dann im Discord-Client mit Bildschirmfotos oder einer Bildschirmaufnahme sichern, mit
   sichtbarem Datum. In jedem Fall die Nutzer-ID der Gegenseite notieren (Einstellungen → Erweitert →
   Entwicklermodus, dann Rechtsklick auf den Namen → „Nutzer-ID kopieren“). Der Anzeigename lässt
   sich ändern, die ID nicht.
4. Exportordner nicht mehr bearbeiten, eine Kopie auf einen zweiten Datenträger legen.
   Protokoll und Prüfsummendatei per Mail an sich selbst oder an den Anwalt schicken; das belegt,
   dass der Stand zu diesem Zeitpunkt existierte.
5. Je nach Fall den Nutzer bei Discord melden (Rechtsklick → „Melden“) oder Anzeige erstatten.
   Strafverfolgungsbehörden können Daten direkt bei Discord anfordern, auch die der Gegenseite.

## Kommandozeile

Für die Aufgabenplanung oder Skripte. Ohne Argument startet die Oberfläche.

```powershell
cd C:\discordexporter

# Server und Kanal-IDs anzeigen
py -3 discord_export.py list

# Zwei Kanäle als HTML + CSV, ab 1. Januar
py -3 discord_export.py export --channel 123456789 --channel 987654321 `
    --format html,csv --from 01.01.2026 --out D:\Archiv\Discord

# Ganzen Server inkl. Threads
py -3 discord_export.py export --guild 111222333 --out D:\Archiv\Discord

# Eigenes Konto: DMs auflisten, alle DMs exportieren (Token aus DISCORD_USER_TOKEN)
py -3 discord_export.py list --user
py -3 discord_export.py export --user --all-dms --format html,json,txt --out D:\Archiv\DMs

# Datenpaket: Unterhaltungen auflisten, dann alles exportieren
py -3 discord_export.py package C:\Users\Andreas\Downloads\package.zip --list
py -3 discord_export.py package C:\Users\Andreas\Downloads\package.zip --all --out D:\Archiv\DMs
```

Formate für `--format`: `html, json, rawjson, csv, txt, md`. Weitere Schalter:
`--to`, `--no-media`, `--no-threads`, `--csv-delimiter tab`, `--user`, `--all-dms`.
Der Token kommt aus `--token` oder `DISCORD_BOT_TOKEN` (mit `--user`: `DISCORD_USER_TOKEN`). Rückgabewert 0 = ok, 1 = Fehler,
2 = nichts gefunden.

## Grenzen

- Rate-Limits von Discord werden eingehalten; große Kanäle (100.000+
  Nachrichten) dauern entsprechend. Abbrechen ist jederzeit möglich.
- Eine HTML-Datei pro Kanal, ohne Aufteilung. Sehr große Kanäle ergeben große
  Dateien, die der Browser aber lädt.
- Sprachkanäle haben einen Text-Chat, der mit exportiert wird; Sprache selbst
  nicht.
- Datenpaket: nur eigene Nachrichten, keine Reaktionen, Embeds oder Antworten.
  Anhang-Links im Paket sind oft schon abgelaufen; fehlgeschlagene Downloads
  stehen im Log, die HTML-Datei verweist dann auf den alten Link.

## Aufbau

| Datei | Inhalt |
|---|---|
| `discord_export.py` | Einstieg: GUI ohne Argumente, sonst Kommandozeile |
| `dcexport/api.py` | REST-Client, Rate-Limits, Seitenweise Abfrage |
| `dcexport/package.py` | Leser für das Datenpaket (ZIP oder Ordner) |
| `dcexport/model.py` | Einheitliches Nachrichtenformat |
| `dcexport/markdown.py` | Discord-Markdown nach HTML bzw. Klartext |
| `dcexport/exporter.py` | Ablauf: Kanäle, Threads, Mitglieder, Medien, Ausgabe |
| `dcexport/html_writer.py`, `writers.py` | Ausgabeformate |
| `dcexport/gui.py`, `cli.py` | Oberfläche (Tkinter) und Kommandozeile |
| `tests/` | Tests gegen eine nachgebaute Discord-API (`mock_discord.py`) |
