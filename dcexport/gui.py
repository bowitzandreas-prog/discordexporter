"""Tkinter-Oberfläche. Arbeit läuft in Hintergrund-Threads, Meldungen kommen über eine Queue."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

from . import APP_NAME, __version__
from .api import DiscordClient
from .exporter import DM_GUILD_ID, ApiExporter, PackageExporter, Summary
from .model import CHANNEL_TYPES, ExportOptions
from .package import DataPackage
from .util import date_range_to_utc, parse_date_input
from .writers import FORMATS

BOX = {0: "☐", 1: "☑", 2: "▣"}

HELP_BOT = """So richtest du einen Bot zum Exportieren ein (einmalig, ca. 5 Minuten):

1. https://discord.com/developers/applications öffnen → „New Application“.
2. Links „Bot“ → „Reset Token“ → Token kopieren und hier eintragen.
3. Ebenfalls unter „Bot“: „Message Content Intent“ einschalten.
   Ohne diesen Schalter liefert Discord leere Nachrichtentexte.
4. Links „OAuth2“ → „URL Generator“: Scope „bot“, Rechte
   „View Channels“ und „Read Message History“ anhaken.
   Den erzeugten Link öffnen und den Bot auf deinen Server einladen
   (dafür brauchst du dort „Server verwalten“).
5. Hier „Verbinden“ klicken.

Der Bot sieht nur Kanäle, für die er Leserechte hat.
Private Threads brauchen zusätzlich „Manage Threads“.

Der Token wird nicht gespeichert. Tipp: Umgebungsvariable
DISCORD_BOT_TOKEN setzen, dann ist das Feld beim Start schon gefüllt."""

HELP_PACKAGE = """Direktnachrichten (DMs) kann ein Bot nicht lesen. Dafür gibt es das offizielle Datenpaket:

1. Discord → Einstellungen → Daten & Privatsphäre
   → „Alle meine Daten anfordern“ (mindestens „Nachrichten“ auswählen).
2. Discord schickt eine Mail mit Download-Link (meist nach 1–3 Tagen,
   laut Discord bis zu 30 Tage).
3. package.zip herunterladen und hier laden – entpacken ist nicht nötig.

Wichtig: Das Paket enthält nur DEINE eigenen Nachrichten,
nicht die Antworten der anderen Seite. Anhang-Links im Paket
sind oft schon abgelaufen; der Download wird trotzdem versucht."""

HELP_USERTOKEN = """Eigenes Konto (Benutzer-Token)

Damit liest das Tool alles, was du in Discord selbst siehst: Direktnachrichten
und Gruppen mit beiden Seiten sowie Server, auf denen kein Bot ist.

RISIKO: Discord verbietet das Automatisieren von Benutzerkonten („Self-Bot“)
und kann das Konto dafür sperren. Das Risiko trägst du.

Token holen (im Browser, nicht in der Discord-App):
1. https://discord.com/app öffnen und anmelden.
2. F12 drücken → Reiter „Netzwerk“ → oben im Filter „api“ eingeben.
3. In Discord einen Kanal anklicken, dann links eine Anfrage wählen
   (z. B. „messages?limit=50“).
4. Unter „Anfrage-Header“ den Wert von „authorization“ kopieren.

Der Token ist so viel wert wie dein Passwort: nie weitergeben.
Das Tool speichert ihn nicht. Abmelden im Browser oder ein
Passwortwechsel macht ihn ungültig."""

USER_MODE_WARNING = """Achtung: Export mit deinem eigenen Konto

Discord verbietet das Automatisieren von Benutzerkonten. Das Konto kann
dafür gesperrt werden – auch dauerhaft. Das Risiko trägst du.

Den Token nie an andere weitergeben: Er erlaubt vollen Zugriff auf dein Konto.

Trotzdem mit dem eigenen Konto fortfahren?"""


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "DiscordExport" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def open_path(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class CheckTree(ttk.Frame):
    """Treeview mit Kästchen zum Anhaken; Eltern zeigen Teilauswahl."""

    def __init__(self, master, columns: list[tuple[str, str, int]], first_heading: str):
        super().__init__(master)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], selectmode="browse")
        self.tree.heading("#0", text=first_heading, anchor="w")
        self.tree.column("#0", width=380, stretch=True)
        for key, title, width in columns:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.state: dict[str, int] = {}
        self.labels: dict[str, str] = {}
        self.payload: dict[str, object] = {}
        self.order: list[tuple[str, str]] = []  # (iid, parent) in Einfügereihenfolge
        self.tree.bind("<Button-1>", self._on_click, add=True)
        self.tree.bind("<space>", self._on_space)

    def remove_children(self, iid: str) -> None:
        """Kinder eines Knotens entfernen (z. B. Platzhalter vor dem Nachladen)."""
        gone = set()

        def collect(node: str) -> None:
            for child in self.tree.get_children(node):
                gone.add(child)
                collect(child)

        collect(iid)
        for child in self.tree.get_children(iid):
            self.tree.delete(child)
        for child in gone:
            self.state.pop(child, None)
            self.labels.pop(child, None)
            self.payload.pop(child, None)
        self.order = [(i, p) for i, p in self.order if i not in gone]

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children(""))
        self.state.clear()
        self.labels.clear()
        self.payload.clear()
        self.order.clear()

    def insert(self, parent: str, label: str, payload=None, values=(), open_: bool = False) -> str:
        iid = self.tree.insert(parent, "end", text=f"{BOX[0]} {label}", values=values, open=open_)
        self.state[iid] = 0
        self.labels[iid] = label
        if payload is not None:
            self.payload[iid] = payload
        self.order.append((iid, parent))
        return iid

    def _render(self, iid: str) -> None:
        self.tree.item(iid, text=f"{BOX[self.state[iid]]} {self.labels[iid]}")

    def _on_click(self, event) -> str | None:
        if self.tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return None
        if "indicator" in self.tree.identify_element(event.x, event.y):
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            self.toggle(iid)
            self.tree.focus(iid)
            self.tree.selection_set(iid)
            return "break"
        return None

    def _on_space(self, _event) -> str:
        iid = self.tree.focus()
        if iid:
            self.toggle(iid)
        return "break"

    def toggle(self, iid: str) -> None:
        self._set_subtree(iid, 0 if self.state[iid] == 1 else 1)
        parent = self.tree.parent(iid)
        while parent:
            states = {self.state[c] for c in self.tree.get_children(parent)}
            self.state[parent] = states.pop() if len(states) == 1 and 2 not in states else 2
            self._render(parent)
            parent = self.tree.parent(parent)

    def _set_subtree(self, iid: str, value: int) -> None:
        self.state[iid] = value
        self._render(iid)
        for child in self.tree.get_children(iid):
            self._set_subtree(child, value)

    def set_all(self, value: int) -> None:
        for iid in self.state:
            self.state[iid] = value
            self._render(iid)

    def checked(self) -> list:
        return [self.payload[i] for i, _p in self.order if self.state.get(i) == 1 and i in self.payload]

    def apply_filter(self, term: str) -> None:
        term = term.strip().lower()
        visible_parents = set()
        for iid, parent in self.order:
            if iid in self.payload:
                show = not term or term in self.labels[iid].lower() or term in self.labels.get(parent, "").lower()
                if show:
                    self.tree.move(iid, parent, "end")
                    visible_parents.add(parent)
                else:
                    self.tree.detach(iid)
        for iid, parent in self.order:
            if iid not in self.payload:
                if iid in visible_parents or not term:
                    self.tree.move(iid, parent, "end")
                else:
                    self.tree.detach(iid)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1040x820")
        self.minsize(860, 640)
        self.settings = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.api_exporter: ApiExporter | None = None
        self.package: DataPackage | None = None
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_id = self.after(100, self._poll)

    # ------------------------------------------------------------- Aufbau

    def _style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24)
        self.bold_font = tkfont.nametofont("TkDefaultFont").copy()
        self.bold_font.configure(weight="bold")
        style.configure("Accent.TButton", font=self.bold_font)
        style.configure("Hint.TLabel", foreground="#666666")

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=3)
        outer.rowconfigure(3, weight=1)

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.add(self._build_api_tab(self.notebook), text="  Discord-API (Bot oder eigenes Konto)  ")
        self.notebook.add(self._build_package_tab(self.notebook), text="  Datenpaket (offline)  ")

        self._build_options(outer).grid(row=1, column=0, sticky="ew", pady=(10, 0))

        prog = ttk.Frame(outer)
        prog.grid(row=2, column=0, sticky="ew", pady=(8, 4))
        prog.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog, maximum=1000)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(prog, textvariable=self.status).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.log_box = ScrolledText(outer, height=9, wrap="word", state="disabled",
                                    font=("Consolas", 9) if sys.platform.startswith("win") else ("TkFixedFont", 9))
        self.log_box.grid(row=3, column=0, sticky="nsew")

    def _build_api_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)

        mode = ttk.Frame(tab)
        mode.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(mode, text="Anmelden mit:").pack(side="left")
        self.token_mode = tk.StringVar(value="bot")
        self.user_mode_ok = False
        ttk.Radiobutton(mode, text="Bot-Token (Server-Kanäle)", value="bot", variable=self.token_mode,
                        command=self._mode_changed).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(mode, text="Eigenes Konto (Benutzer-Token, inkl. DMs)", value="user",
                        variable=self.token_mode, command=self._mode_changed).pack(side="left", padx=(12, 0))

        self.token_label = tk.StringVar(value="Bot-Token:")
        ttk.Label(tab, textvariable=self.token_label).grid(row=1, column=0, sticky="w")
        self.token = tk.StringVar(value=os.environ.get("DISCORD_BOT_TOKEN", ""))
        self.token_entry = ttk.Entry(tab, textvariable=self.token, show="•")
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=6)
        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="anzeigen", variable=self.show_token,
                        command=lambda: self.token_entry.configure(show="" if self.show_token.get() else "•")
                        ).grid(row=1, column=2)
        self.connect_btn = ttk.Button(tab, text="Verbinden", command=self._connect)
        self.connect_btn.grid(row=1, column=3, padx=(6, 0))
        self.token_entry.bind("<Return>", lambda _e: self._connect())

        self.api_status = tk.StringVar(value="Nicht verbunden. Bot-Token eintragen und „Verbinden“ klicken.")
        ttk.Label(tab, textvariable=self.api_status, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 6))

        self.api_tree = CheckTree(tab, [("type", "Typ", 130), ("id", "ID", 170)], "Server / Kanal")
        self._pending_guilds: dict[str, str] = {}
        self.api_tree.tree.bind("<<TreeviewOpen>>", self._on_tree_open, add=True)
        self.api_tree.grid(row=3, column=0, columnspan=4, sticky="nsew")

        bar = ttk.Frame(tab)
        bar.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Alle", command=lambda: self.api_tree.set_all(1)).pack(side="left")
        ttk.Button(bar, text="Keine", command=lambda: self.api_tree.set_all(0)).pack(side="left", padx=4)
        ttk.Button(bar, text="Eigenes Konto – Anleitung & Risiko",
                   command=lambda: messagebox.showinfo("Benutzer-Token", HELP_USERTOKEN)).pack(side="right")
        ttk.Button(bar, text="Bot einrichten – Anleitung", command=self._help_bot).pack(side="right", padx=4)
        return tab

    def _build_package_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)

        ttk.Label(tab, text="Datenpaket:").grid(row=0, column=0, sticky="w")
        self.pkg_path = tk.StringVar(value=self.settings.get("package_path", ""))
        ttk.Entry(tab, textvariable=self.pkg_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(tab, text="ZIP wählen …", command=self._pick_zip).grid(row=0, column=2)
        ttk.Button(tab, text="Ordner wählen …", command=self._pick_pkg_dir).grid(row=0, column=3, padx=4)
        self.pkg_btn = ttk.Button(tab, text="Laden", command=self._load_package)
        self.pkg_btn.grid(row=0, column=4)

        self.pkg_status = tk.StringVar(value="Kein Paket geladen. Enthält nur deine eigenen Nachrichten.")
        ttk.Label(tab, textvariable=self.pkg_status, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(6, 4))

        flt = ttk.Frame(tab)
        flt.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(0, 4))
        ttk.Label(flt, text="Filter:").pack(side="left")
        self.pkg_filter = tk.StringVar()
        self.pkg_filter.trace_add("write", lambda *_: self.pkg_tree.apply_filter(self.pkg_filter.get()))
        ttk.Entry(flt, textvariable=self.pkg_filter, width=40).pack(side="left", padx=6)

        self.pkg_tree = CheckTree(tab, [("count", "Nachrichten", 110), ("id", "ID", 170)], "Unterhaltung")
        self.pkg_tree.grid(row=3, column=0, columnspan=5, sticky="nsew")

        bar = ttk.Frame(tab)
        bar.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Alle", command=lambda: self.pkg_tree.set_all(1)).pack(side="left")
        ttk.Button(bar, text="Keine", command=lambda: self.pkg_tree.set_all(0)).pack(side="left", padx=4)
        ttk.Button(bar, text="Datenpaket anfordern – Anleitung",
                   command=lambda: messagebox.showinfo("Datenpaket", HELP_PACKAGE)).pack(side="right")
        return tab

    def _build_options(self, parent) -> ttk.LabelFrame:
        box = ttk.LabelFrame(parent, text="Export", padding=10)
        box.columnconfigure(1, weight=1)
        s = self.settings

        ttk.Label(box, text="Formate:").grid(row=0, column=0, sticky="w")
        fmts = ttk.Frame(box)
        fmts.grid(row=0, column=1, columnspan=3, sticky="w")
        chosen = set(s.get("formats") or ["html", "json"])
        self.format_vars = {}
        for key, (label, _ext) in FORMATS.items():
            var = tk.BooleanVar(value=key in chosen)
            self.format_vars[key] = var
            ttk.Checkbutton(fmts, text=label, variable=var).pack(side="left", padx=(0, 12))

        ttk.Label(box, text="Zeitraum:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        rng = ttk.Frame(box)
        rng.grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(rng, text="von").pack(side="left")
        self.date_from = tk.StringVar()
        ttk.Entry(rng, textvariable=self.date_from, width=12).pack(side="left", padx=4)
        ttk.Label(rng, text="bis").pack(side="left")
        self.date_to = tk.StringVar()
        ttk.Entry(rng, textvariable=self.date_to, width=12).pack(side="left", padx=4)
        ttk.Label(rng, text="TT.MM.JJJJ, leer = alles", style="Hint.TLabel").pack(side="left", padx=6)

        opts = ttk.Frame(box)
        opts.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.download_media = tk.BooleanVar(value=s.get("download_media", True))
        ttk.Checkbutton(opts, text="Medien herunterladen (Anhänge, Avatare, Emojis)",
                        variable=self.download_media).pack(side="left")
        self.include_threads = tk.BooleanVar(value=s.get("include_threads", True))
        ttk.Checkbutton(opts, text="Threads mitexportieren", variable=self.include_threads).pack(side="left", padx=12)
        ttk.Label(opts, text="CSV-Trennzeichen:").pack(side="left", padx=(12, 4))
        self.csv_delim = tk.StringVar(value=s.get("csv_delimiter", "; (Excel DE)"))
        ttk.Combobox(opts, textvariable=self.csv_delim, width=12, state="readonly",
                     values=["; (Excel DE)", ", (Komma)", "Tab"]).pack(side="left")
        ttk.Label(box, text="Discord-Links zu Anhängen laufen nach ca. 24 h ab – für ein dauerhaftes Archiv "
                            "Medien mit herunterladen.", style="Hint.TLabel").grid(
            row=3, column=1, columnspan=3, sticky="w")

        ttk.Label(box, text="Zielordner:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        default_out = str(Path.home() / "Documents" / "Discord-Export")
        self.out_dir = tk.StringVar(value=s.get("out_dir", default_out))
        ttk.Entry(box, textvariable=self.out_dir).grid(row=4, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(box, text="…", width=3, command=self._pick_out).grid(row=4, column=2, pady=(8, 0))
        ttk.Button(box, text="Öffnen", command=self._open_out).grid(row=4, column=3, padx=(4, 0), pady=(8, 0))

        actions = ttk.Frame(box)
        actions.grid(row=5, column=0, columnspan=4, sticky="e", pady=(10, 0))
        self.export_btn = ttk.Button(actions, text="Export starten", style="Accent.TButton", command=self._export)
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(actions, text="Abbrechen", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(6, 0))
        return box

    # -------------------------------------------------------------- Helfer

    def log(self, msg: str) -> None:
        self.events.put(("log", msg))

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for btn in (self.export_btn, self.connect_btn, self.pkg_btn):
            btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    def _run(self, target, *args) -> None:
        self.cancel.clear()
        self._busy(True)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                getattr(self, f"_on_{kind}")(payload)
        except queue.Empty:
            pass
        self._poll_id = self.after(100, self._poll)

    def _help_bot(self) -> None:
        if messagebox.askyesno("Bot einrichten", HELP_BOT + "\n\nDeveloper Portal jetzt im Browser öffnen?"):
            webbrowser.open("https://discord.com/developers/applications")

    def _pick_zip(self) -> None:
        path = filedialog.askopenfilename(title="Discord-Datenpaket wählen",
                                          filetypes=[("ZIP-Archiv", "*.zip"), ("Alle Dateien", "*.*")])
        if path:
            self.pkg_path.set(path)
            self._load_package()

    def _pick_pkg_dir(self) -> None:
        path = filedialog.askdirectory(title="Entpacktes Datenpaket wählen")
        if path:
            self.pkg_path.set(path)
            self._load_package()

    def _pick_out(self) -> None:
        path = filedialog.askdirectory(title="Zielordner wählen", initialdir=self.out_dir.get() or None)
        if path:
            self.out_dir.set(path)

    def _open_out(self) -> None:
        path = Path(self.out_dir.get())
        path.mkdir(parents=True, exist_ok=True)
        open_path(str(path))

    def _persist(self) -> None:
        self.settings.update({
            "out_dir": self.out_dir.get(),
            "formats": [k for k, v in self.format_vars.items() if v.get()],
            "download_media": self.download_media.get(),
            "include_threads": self.include_threads.get(),
            "csv_delimiter": self.csv_delim.get(),
            "package_path": self.pkg_path.get(),
        })
        save_settings(self.settings)

    # ----------------------------------------------------------- Verbinden

    def _mode_changed(self) -> None:
        user = self.token_mode.get() == "user"
        if user and not self.user_mode_ok:
            if not messagebox.askyesno("Eigenes Konto", USER_MODE_WARNING, icon="warning"):
                self.token_mode.set("bot")
                return
            self.user_mode_ok = True
        self.token_label.set("Benutzer-Token:" if user else "Bot-Token:")
        env = os.environ.get("DISCORD_USER_TOKEN" if user else "DISCORD_BOT_TOKEN", "")
        other = os.environ.get("DISCORD_BOT_TOKEN" if user else "DISCORD_USER_TOKEN", "")
        if not self.token.get().strip() or self.token.get().strip() == other:
            self.token.set(env)
        self.api_status.set("Nicht verbunden. " + ("Benutzer-Token" if user else "Bot-Token")
                            + " eintragen und „Verbinden“ klicken.")

    def _connect(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        token = self.token.get().strip()
        user = self.token_mode.get() == "user"
        if not token:
            if user:
                messagebox.showwarning("Token fehlt", "Bitte deinen Benutzer-Token eintragen.\n\n" + HELP_USERTOKEN)
            else:
                messagebox.showwarning("Bot-Token fehlt", "Bitte einen Bot-Token eintragen.\n\n" + HELP_BOT)
            return
        self.api_status.set("Verbinde …")
        self._run(self._connect_worker, token, user)

    def _connect_worker(self, token: str, user: bool = False) -> None:
        try:
            client = DiscordClient(token, user_token=user, log=self.log, cancel=self.cancel)
            exporter = ApiExporter(client, log=self.log)
            guilds = exporter.connect(load_channels=not user)
            self.events.put(("api_loaded", (exporter, guilds)))
        except Exception as err:  # noqa: BLE001
            self.events.put(("failed", f"Verbindung fehlgeschlagen: {err}"))

    def _on_api_loaded(self, payload) -> None:
        exporter, guilds = payload
        self.api_exporter = exporter
        self._busy(False)
        tree = self.api_tree
        tree.clear()
        self._pending_guilds = {}
        channel_count = 0
        for gd in guilds:
            is_dm = gd.guild["id"] == DM_GUILD_ID
            g = tree.insert("", gd.guild.get("name", "?"), values=("Direktnachrichten" if is_dm else "Server",
                                                                  "" if is_dm else gd.guild["id"]),
                            open_=len(guilds) == 1 or is_dm)
            if gd.loaded:
                channel_count += self._fill_guild(g, gd)
            else:
                tree.insert(g, "Kanäle werden beim Aufklappen geladen …", values=("", ""))
                self._pending_guilds[g] = gd.guild["id"]
        bot = (exporter.bot_user or {}).get("username", "?")
        servers = sum(1 for gd in guilds if gd.guild["id"] != DM_GUILD_ID)
        dms = sum(len(gd.channels) for gd in guilds if gd.guild["id"] == DM_GUILD_ID)
        if exporter.client.is_user:
            self.api_status.set(f"Verbunden als {bot} – {dms} Direktnachrichten, {servers} Server "
                                f"(Kanäle laden beim Aufklappen). Anhaken und unten exportieren.")
        else:
            self.api_status.set(f"Verbunden als {bot} – {servers} Server, {channel_count} Kanäle. "
                                f"Kanäle anhaken und unten exportieren.")
        if not guilds:
            self.api_status.set(f"Verbunden als {bot}, aber der Bot ist auf keinem Server. Erst einladen "
                                f"(siehe Anleitung).")
        self.log(f"Verbunden als {bot}: {len(guilds)} Server, {channel_count} Kanäle.")

    def _fill_guild(self, node: str, gd) -> int:
        """Kanäle eines Servers (oder die DMs) unter den Knoten hängen."""
        tree = self.api_tree
        cats: dict[str, str] = {}
        for ch in gd.channels:
            parent = node
            if ch.category:
                if ch.category not in cats:
                    cats[ch.category] = tree.insert(node, ch.category.upper(), values=("Kategorie", ""), open_=True)
                parent = cats[ch.category]
            prefix = "🔊 " if ch.type in (2, 13) else ("🗂 " if ch.type in (15, 16) else
                                                      ("@ " if ch.is_dm else "# "))
            tree.insert(parent, prefix + ch.name, payload=ch,
                        values=(CHANNEL_TYPES.get(ch.type, str(ch.type)), ch.id))
        if tree.state.get(node) == 1:
            tree._set_subtree(node, 1)
        return len(gd.channels)

    def _on_tree_open(self, _event=None) -> None:
        node = self.api_tree.tree.focus()
        if node not in self._pending_guilds or not self.api_exporter:
            return
        if self.worker and self.worker.is_alive():
            self.status.set("Bitte warten, bis der laufende Vorgang fertig ist, dann erneut aufklappen.")
            return
        self.status.set("Lade Kanäle …")
        self._run(self._guild_worker, node, self._pending_guilds[node])

    def _guild_worker(self, node: str, guild_id: str) -> None:
        try:
            gd = self.api_exporter.load_guild(guild_id)
            self.events.put(("guild_loaded", (node, gd)))
        except Exception as err:  # noqa: BLE001
            self.events.put(("guild_failed", f"Kanäle nicht ladbar: {err}"))

    def _on_guild_loaded(self, payload) -> None:
        node, gd = payload
        self._busy(False)
        self._pending_guilds.pop(node, None)
        self.api_tree.remove_children(node)
        count = self._fill_guild(node, gd)
        self.api_tree.tree.item(node, open=True)
        self.status.set(f"{gd.guild.get('name', 'Server')}: {count} Kanäle geladen.")

    def _on_guild_failed(self, msg: str) -> None:
        self._busy(False)
        self.status.set(msg)
        self.log(msg)

    # ---------------------------------------------------------- Datenpaket

    def _load_package(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        path = self.pkg_path.get().strip()
        if not path:
            messagebox.showwarning("Datenpaket", "Bitte package.zip oder den entpackten Ordner wählen.")
            return
        self.pkg_status.set("Lese Datenpaket …")
        self._run(self._package_worker, path)

    def _package_worker(self, path: str) -> None:
        try:
            pkg = DataPackage(path)
            convs = pkg.conversations()
            self.events.put(("pkg_loaded", (pkg, convs)))
        except Exception as err:  # noqa: BLE001
            self.events.put(("failed", f"Datenpaket nicht lesbar: {err}"))

    def _on_pkg_loaded(self, payload) -> None:
        pkg, convs = payload
        if self.package:
            self.package.close()
        self.package = pkg
        self._busy(False)
        tree = self.pkg_tree
        tree.clear()
        groups: dict[str, str] = {}
        total = 0
        for conv in convs:
            if conv.group not in groups:
                groups[conv.group] = tree.insert("", conv.group, values=("", ""),
                                                 open_=conv.group in ("Direktnachrichten", "Gruppen"))
            tree.insert(groups[conv.group], conv.info.name, payload=conv,
                        values=(fmt_int(conv.message_count), conv.info.id))
            total += conv.message_count
        self.pkg_status.set(f"Konto: {pkg.author['display_name']} – {fmt_int(len(convs))} Unterhaltungen, "
                            f"{fmt_int(total)} eigene Nachrichten.")
        self.log(f"Datenpaket geladen: {len(convs)} Unterhaltungen.")
        self._persist()

    # -------------------------------------------------------------- Export

    def _collect_options(self) -> ExportOptions | None:
        formats = {k for k, v in self.format_vars.items() if v.get()}
        if not formats:
            messagebox.showwarning("Export", "Bitte mindestens ein Format wählen.")
            return None
        try:
            after, before = date_range_to_utc(parse_date_input(self.date_from.get()),
                                              parse_date_input(self.date_to.get()))
        except ValueError as err:
            messagebox.showwarning("Zeitraum", str(err))
            return None
        out = self.out_dir.get().strip()
        if not out:
            messagebox.showwarning("Export", "Bitte einen Zielordner wählen.")
            return None
        delim = {"; (Excel DE)": ";", ", (Komma)": ",", "Tab": "\t"}.get(self.csv_delim.get(), ";")
        return ExportOptions(out_dir=out, formats=formats, after=after, before=before,
                             download_media=self.download_media.get(),
                             include_threads=self.include_threads.get(), csv_delimiter=delim)

    def _export(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        options = self._collect_options()
        if not options:
            return
        api_tab = self.notebook.index(self.notebook.select()) == 0
        if api_tab:
            selected = self.api_tree.checked()
            if not self.api_exporter or not selected:
                messagebox.showinfo("Export", "Erst verbinden und mindestens einen Kanal anhaken.")
                return
            exporter = self.api_exporter
            exporter.client.cancel = self.cancel
        else:
            selected = self.pkg_tree.checked()
            if not self.package or not selected:
                messagebox.showinfo("Export", "Erst ein Datenpaket laden und mindestens eine Unterhaltung anhaken.")
                return
            exporter = PackageExporter(self.package, log=self.log)
        self._persist()
        self.progress["value"] = 0
        self.status.set(f"Exportiere {len(selected)} Auswahl(en) …")
        self._run(self._export_worker, exporter, selected, options)

    def _export_worker(self, exporter, selected, options: ExportOptions) -> None:
        def progress(index: int, total: int, fraction: float, label: str) -> None:
            self.events.put(("progress", (index, total, fraction, label)))
        try:
            summary = exporter.export(selected, options, progress=progress, cancel=self.cancel)
        except Exception as err:  # noqa: BLE001
            summary = Summary(errors=[str(err)])
            self.log(f"Fehler: {err}")
        self.events.put(("done", (summary, options.out_dir)))

    def _on_progress(self, payload) -> None:
        index, total, fraction, label = payload
        overall = (index + fraction) / total if total else 1.0
        self.progress["value"] = overall * 1000
        if label:
            self.status.set(f"Kanal {min(index + 1, total)}/{total}: {label}")

    def _on_done(self, payload) -> None:
        summary, out_dir = payload
        self._busy(False)
        self.progress["value"] = 1000 if not summary.cancelled else self.progress["value"]
        self.status.set(summary.text())
        self.log(summary.text())
        if summary.errors:
            messagebox.showerror("Export", "Export mit Fehlern beendet:\n\n" + "\n".join(summary.errors[:5]))
        elif not summary.cancelled and summary.files:
            proto = ""
            if summary.protocol_files:
                proto = ("\n\nExportprotokoll und SHA-256-Prüfsummen:\n"
                         + "\n".join(Path(p).name for p in summary.protocol_files))
            if messagebox.askyesno("Export fertig", summary.text() + proto + "\n\nZielordner öffnen?"):
                try:
                    open_path(out_dir)
                except OSError:
                    pass

    def _on_failed(self, msg: str) -> None:
        self._busy(False)
        self.log(msg)
        self.status.set(msg)
        if "Verbindung" in msg:
            self.api_status.set(msg)
        else:
            self.pkg_status.set(msg)
        messagebox.showerror(APP_NAME, msg)

    def _on_log(self, msg: str) -> None:
        self._append_log(msg)

    def _cancel(self) -> None:
        self.cancel.set()
        self.status.set("Breche ab …")

    def destroy(self) -> None:
        # Ausstehenden Poll abbrechen, sonst meldet Tk "invalid command name …_poll"
        try:
            self.after_cancel(self._poll_id)
        except (AttributeError, tk.TclError):
            pass
        super().destroy()

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Es läuft noch ein Vorgang. Abbrechen und beenden?"):
                return
            self.cancel.set()
        self._persist()
        self.destroy()


def main() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # scharfe Schrift bei Skalierung > 100 %
        except (AttributeError, OSError):
            pass
    App().mainloop()
