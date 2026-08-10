#!/usr/bin/env python3
"""Build the downloadable release package.

Produces releases/opnsense-haproxy-<version>.zip with exactly the files a user
needs, unpacking into one clearly named folder. The version is read from
opnsense_haproxy.py, so there is only ever one place to bump it.

Files go in byte for byte -- HAProxy-Starter.bat has to keep its CRLF line
endings, which cmd.exe relies on.
"""

import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENTS = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
            "portainer_gui.py", "adguard_gui.py", "catalog.py", "catalog.json",
            "HAProxy-Starter.bat",
            "icon.png", "icon.ico", "README.md", "CHANGELOG.md",
            "config.example.json")


def version():
    with open(os.path.join(HERE, "opnsense_haproxy.py")) as handle:
        found = re.search(r'^VERSION = "([^"]+)"', handle.read(), re.M)
    if not found:
        raise SystemExit("error: no VERSION found in opnsense_haproxy.py")
    return found.group(1)


def build():
    tag = version()
    folder = f"opnsense-haproxy-{tag}"
    target = os.path.join(HERE, "releases", f"{folder}.zip")
    os.makedirs(os.path.dirname(target), exist_ok=True)

    missing = [n for n in CONTENTS if not os.path.exists(os.path.join(HERE, n))]
    if missing:
        raise SystemExit(f"error: missing {', '.join(missing)}")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in CONTENTS:
            archive.write(os.path.join(HERE, name), f"{folder}/{name}")

    print(f"{target}  ({os.path.getsize(target)} bytes)")
    with zipfile.ZipFile(target) as archive:
        broken = archive.testzip()
        if broken:
            raise SystemExit(f"error: {broken} is damaged in the archive")
        for entry in archive.infolist():
            print(f"  {entry.filename:46s} {entry.file_size:7d}")
    return target


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
