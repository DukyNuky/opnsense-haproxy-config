#!/usr/bin/env python3
"""Doppelklick-Einstieg: ``python3 pforte.py``."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pforte.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
