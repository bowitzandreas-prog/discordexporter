# Fremdbestandteile

Der Python-Teil nutzt nur die Standardbibliothek. Die Weboberfläche
(`web/`, gebaut nach `dcexport/web_dist/`) enthält folgende Fremdbestandteile.
Die vollständigen Lizenztexte liegen im Ordner [`licenses/`](licenses/).

| Bestandteil | Wo | Lizenz | Rechteinhaber | Lizenztext |
|---|---|---|---|---|
| React, React DOM, Scheduler | im JavaScript-Bundle | MIT | Meta Platforms, Inc. and affiliates | `licenses/react-MIT.txt` |
| Motion | im JavaScript-Bundle | MIT | Motion B.V. | `licenses/motion-MIT.md` |
| Framer Motion | im JavaScript-Bundle | MIT | Framer B.V. | `licenses/framer-motion-MIT.md` |
| tslib | im JavaScript-Bundle | 0BSD | Microsoft Corporation | `licenses/tslib-0BSD.txt` |
| React Bits (DarkVeil, ShinyText, SpotlightCard, CountUp, ClickSpark, StarBorder, DecryptedText) | `web/src/bits/`, im Bundle | MIT + Commons Clause | David Haz | `licenses/react-bits-MIT-Commons-Clause.md` |
| IBM Plex Sans, IBM Plex Mono (Schriften) | `dcexport/web_dist/assets/*.woff2` | SIL Open Font License 1.1 | IBM Corp. | `licenses/IBM-Plex-Sans-OFL-1.1.txt`, `licenses/IBM-Plex-Mono-OFL-1.1.txt` |

Zu React Bits: Der Commons-Clause-Zusatz erlaubt den Einsatz als Teil einer
Anwendung, auch kommerziell, verbietet aber, die Komponenten selbst zu
verkaufen oder weiterzulizenzieren. Wer Teile dieses Projekts weiterverwendet,
muss das für die Dateien in `web/src/bits/` beachten.
