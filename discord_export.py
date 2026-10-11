"""Discord-Export – Start ohne Argumente öffnet die GUI, sonst Kommandozeile (--help)."""

import os
import sys

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 oder neuer nötig.")

# Auch mit "python -I" (isoliert) das eigene Paket neben dieser Datei finden
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dcexport.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
