# Hinweise für Claude

- Commit-Nachrichten enden mit `Co-Authored-By: Claude …` (KI-Beteiligung offenlegen),
  aber **ohne** `Claude-Session:`-Zeile. Wunsch des Inhabers, das Repo ist öffentlich.
- Sprache in Code-Kommentaren, Oberfläche und Doku: Deutsch.
- Nach Änderungen an `web/src/` immer `npm run build` in `web/` und das Ergebnis in
  `dcexport/web_dist/` mit committen (Nutzer haben kein Node).
- Tests: `python -m unittest discover -s tests` (GUI-Tests brauchen ein Display).
