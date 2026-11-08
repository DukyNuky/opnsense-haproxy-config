#!/usr/bin/env python3
"""Die Weboberfläche als Python-Modul einbetten: ``python3 tests/build_web.py``.

Ein Updater aus Version 3 nimmt nur ``.py``, ``.json``, ``.md``, ``.bat``,
``.png`` und ``.ico`` aus einem Archiv mit. Damit die Oberfläche auch auf
diesem Weg ankommt, liegt sie zusätzlich in ``pforte/_web.py``. Nach jeder
Änderung unter ``pforte/web`` neu erzeugen; ein Test schlägt sonst an.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(HERE, "pforte", "web")


def collect():
    files = {}
    for name in sorted(os.listdir(WEB)):
        with open(os.path.join(WEB, name), encoding="utf-8") as handle:
            files[name] = handle.read()
    return files


def render(files):
    lines = ['"""Erzeugt von tests/build_web.py — nicht von Hand ändern."""', "",
             "FILES = {"]
    for name, text in files.items():
        lines.append(f"    {name!r}: {text!r},")
    lines.append("}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    target = os.path.join(HERE, "pforte", "_web.py")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(collect()))
    print(target)
    sys.exit(0)
