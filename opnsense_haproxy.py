#!/usr/bin/env python3
"""Zweiter alter Einstiegspunkt (Kommandozeile bis Version 3).

Ein Updater aus Version 1 bis 3 verlangt diese Datei im Archiv und liest die
Versionsnummer aus der Zeile ``VERSION`` weiter unten. Beides bleibt, auch
wenn die Kommandozeile selbst seit Version 4 nicht mehr existiert.
"""
VERSION = "4.1.0"

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pforte.launcher import main  # noqa: E402

if __name__ == "__main__":
    if sys.argv[1:] and not sys.argv[1].startswith("--"):
        print("Die Kommandozeile gibt es seit Version 4 nicht mehr — das "
              "Fenster wird gestartet.", file=sys.stderr)
        sys.argv[1:] = []
    sys.exit(main())
