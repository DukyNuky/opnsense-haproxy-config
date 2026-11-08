#!/usr/bin/env python3
"""Einstieg: ``python3 haproxy_gui.py``.

Der Dateiname stammt aus den Versionen 1 bis 3 und bleibt, damit Starter,
Menüeinträge und der Updater einer älteren Installation weiter treffen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pforte.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
