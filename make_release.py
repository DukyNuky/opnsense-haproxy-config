#!/usr/bin/env python3
"""Build the downloadable release package.

Produces releases/opnsense-haproxy-<version>.zip with exactly the files a user
needs, unpacking into one clearly named folder. The version is read from
opnsense_haproxy.py, so there is only ever one place to bump it.

What goes in is decided by the same rule an update goes by -- `program_files`
in opnsense_haproxy.py -- and not by a list here. A list is what broke 1.4.0
and 2.3.0 from the other side, and it would have broken this package the
moment the program grew an app/ folder: the names were written down when there
was nothing but the top level, and a list cannot know about a file that did
not exist when it was written.

Files go in byte for byte -- HAProxy-Starter.bat has to keep its CRLF line
endings, which cmd.exe relies on.
"""

import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import opnsense_haproxy as core  # noqa: E402 - after sys.path, on purpose


def build():
    tag = core.VERSION
    folder = f"opnsense-haproxy-{tag}"
    target = os.path.join(HERE, "releases", f"{folder}.zip")
    os.makedirs(os.path.dirname(target), exist_ok=True)

    contents = core.program_files(HERE)
    missing = [name for name in core.ESSENTIAL_FILES if name not in contents]
    if missing:
        raise SystemExit(f"error: missing {', '.join(missing)}")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in contents:
            archive.write(os.path.join(HERE, name.replace("/", os.sep)),
                          f"{folder}/{name}")

    print(f"{target}  ({os.path.getsize(target)} bytes)")
    with zipfile.ZipFile(target) as archive:
        broken = archive.testzip()
        if broken:
            raise SystemExit(f"error: {broken} is damaged in the archive")
        for entry in archive.infolist():
            print(f"  {entry.filename:52s} {entry.file_size:7d}")
    return target


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
