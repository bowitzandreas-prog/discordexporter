"""Lokale Kopien von Anhängen, Avataren, Emojis und Stickern.

Discord signiert Anhang-Links seit 2024 mit Ablaufdatum (~24 h). Wer ein dauerhaftes
Archiv will, muss die Dateien beim Export mitnehmen.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .api import USER_AGENT, Cancelled
from .util import sanitize_filename


class MediaStore:
    def __init__(self, folder: Path, log: Callable[[str], None] | None = None,
                 cancel: threading.Event | None = None, timeout: float = 60.0,
                 ssl_context: ssl.SSLContext | None = None):
        self.folder = Path(folder)
        self.log = log or (lambda msg: None)
        self.cancel = cancel or threading.Event()
        self.timeout = timeout
        self.ssl_context = ssl_context
        self._done: dict[str, Path | None] = {}
        self._names: set[str] = set()
        self.downloaded = 0
        self.failed = 0
        self.bytes = 0

    @staticmethod
    def _key(url: str) -> str:
        p = urlparse(url)
        # Signatur-Parameter (ex/is/hm) ändern sich, die Datei nicht
        if p.netloc.endswith(("discordapp.com", "discordapp.net")) and "/attachments/" in p.path:
            return p.netloc + p.path
        return url

    def _target(self, url: str, hint: str) -> Path:
        name = sanitize_filename(hint, max_len=80)
        if "." not in name:
            ext = os.path.splitext(urlparse(url).path)[1][:6]
            name += ext or ".bin"
        candidate = name
        stem, ext = os.path.splitext(name)
        n = 1
        while candidate.lower() in self._names:
            n += 1
            candidate = f"{stem}_{n}{ext}"
        self._names.add(candidate.lower())
        return self.folder / candidate

    def local(self, url: str) -> Path | None:
        """Bereits geladene Datei zu einer URL, ohne Download."""
        return self._done.get(self._key(url))

    def fetch(self, url: str | None, hint: str) -> Path | None:
        """Lädt die Datei (einmal pro URL) und gibt den lokalen Pfad zurück, sonst None."""
        if not url or not url.startswith(("http://", "https://")):
            return None
        key = self._key(url)
        if key in self._done:
            return self._done[key]
        if self.cancel.is_set():
            raise Cancelled()
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self._target(url, hint)
        # Gleiche Datei aus einem früheren Lauf wiederverwenden
        if target.exists() and target.stat().st_size > 0:
            self._done[key] = target
            return target
        part = target.with_name(target.name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as resp, \
                    open(part, "wb") as fh:
                while True:
                    if self.cancel.is_set():
                        raise Cancelled()
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    self.bytes += len(chunk)
            os.replace(part, target)
            self.downloaded += 1
            self._done[key] = target
            return target
        except Cancelled:
            part.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, OSError, ValueError) as err:
            part.unlink(missing_ok=True)
            self.failed += 1
            reason = getattr(err, "code", None) or getattr(err, "reason", None) or err
            self.log(f"  Download fehlgeschlagen ({reason}): {hint}")
            self._done[key] = None
            return None


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
