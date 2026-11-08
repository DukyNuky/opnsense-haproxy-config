"""Updates von GitHub, im selben Format wie die Versionen 1 bis 3.

Das ist Absicht: Eine installierte 3.x holt Version 4 mit ihrem *eigenen*
Updater, und eine 4.x holt danach alles Weitere mit diesem hier. Beide lesen
und schreiben dieselbe ``channel.json`` (welche Dateien zuletzt geschrieben
wurden, damit der nächste Lauf Überholtes wegräumen kann) und beide laden das
Quellarchiv des neuesten Releases.

Daraus folgen Regeln, die nicht verhandelbar sind, weil der *alte* Updater sie
durchsetzt:

* ``opnsense_haproxy.py`` und ``haproxy_gui.py`` müssen im Archiv liegen, sonst
  lehnt ein 3.x den Download ab. Sie bleiben deshalb die Einstiegspunkte.
* Ein 3.x übernimmt nur Dateien mit den Endungen ``.py .json .md .bat .png
  .ico``. Die Weboberfläche liegt darum zusätzlich als ``pforte/_web.py``
  im Archiv; erst dieser Updater nimmt auch ``.js .css .html .svg`` mit.
"""

import io
import json
import os
import re
import shutil
import urllib.error
import urllib.request
import zipfile

from . import VERSION
from .net import ApiError, PforteError

REPO = "DukyNuky/opnsense-haproxy-config"
API = "https://api.github.com"

SUFFIXES = (".py", ".json", ".md", ".bat", ".png", ".ico",
            ".js", ".css", ".html", ".svg")
NEVER = ("config.json", "gui.json", "channel.json")      # gehören dem Nutzer
ESSENTIAL = ("opnsense_haproxy.py", "haproxy_gui.py")
NOT_OURS = ("__pycache__", "tests")
NAME_OK = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
MAX_DEPTH = 4
MAX_DOWNLOAD = 20 * 1024 * 1024
KEEP_BACKUPS = 3
CHANNEL_FILE = "channel.json"
# Alles, was frühere Versionen je geschrieben haben; gilt nur für Ordner ohne
# eigene Aufzeichnung (vor 2.x installiert).
LEGACY_FILES = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
                "portainer_gui.py", "adguard_gui.py", "catalog.py",
                "catalog.json", "HAProxy-Starter.bat", "icon.png", "icon.ico",
                "README.md", "CHANGELOG.md", "config.example.json")

BLOCKED = {
    "git": "Dieser Ordner ist eine Git-Arbeitskopie. Bitte mit „git pull“ "
           "aktualisieren, damit eigene Änderungen nicht überschrieben werden.",
    "readonly": "Die Programmdateien in diesem Ordner dürfen nicht geändert "
                "werden.",
}


def install_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_version(text):
    """„v1.2.3“ -> (1, 2, 3, 0); ohne Ziffern sortiert es ganz unten."""
    numbers = [int(n) for n in re.findall(r"\d+", text or "")][:4]
    return tuple(numbers + [0] * (4 - len(numbers)))


# --------------------------------------------------------------------------
# Was gehört zum Programm
# --------------------------------------------------------------------------


def updatable(name):
    """Gehört eine Datei mit diesem Pfad zum Programm selbst?

    Jedes Element des Pfads wird geprüft, kein Name aus einem Archiv baut je
    einen Pfad, der aus dem Ordner herausführt.
    """
    if not name or ":" in name:
        return False
    parts = name.replace("\\", "/").split("/")
    if not 1 <= len(parts) <= MAX_DEPTH:
        return False
    if not all(NAME_OK.match(part) for part in parts):
        return False                      # schließt "", ".", ".." und Verstecktes aus
    if any(part in NOT_OURS for part in parts[:-1]):
        return False
    leaf = parts[-1]
    return leaf not in NEVER and leaf.endswith(SUFFIXES)


def program_files(folder):
    found = []
    for root, folders, names in os.walk(folder):
        folders[:] = [n for n in folders if NAME_OK.match(n)
                      and n not in NOT_OURS and not n.startswith("backup-")]
        for name in names:
            inner = os.path.relpath(os.path.join(root, name),
                                    folder).replace(os.sep, "/")
            if updatable(inner):
                found.append(inner)
    return sorted(found)


# --------------------------------------------------------------------------
# Aufzeichnung (channel.json, kompatibel mit 1.x bis 3.x)
# --------------------------------------------------------------------------


def record(folder=None):
    path = os.path.join(folder or install_dir(), CHANNEL_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    installed = saved.get("installed")
    installed = installed if isinstance(installed, dict) else {}
    listed = installed.get("files")
    return {"channel": "stable",
            "installed": {"channel": "stable",
                          "ref": str(installed.get("ref") or ""),
                          "version": str(installed.get("version") or VERSION),
                          # durch dieselbe Regel gefiltert: ein Name aus einer
                          # editierbaren Datei wird nie zu einem Löschpfad
                          "files": sorted(n for n in (listed if isinstance(listed, list) else [])
                                          if isinstance(n, str) and updatable(n))}}


def write_record(state, folder=None):
    path = os.path.join(folder or install_dir(), CHANNEL_FILE)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Suchen
# --------------------------------------------------------------------------


def _api(path, timeout=15):
    request = urllib.request.Request(
        f"{API}/{path}", headers={"Accept": "application/vnd.github+json",
                                  "User-Agent": f"opnsense-haproxy/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(path) from None
        if exc.code in (403, 429):
            raise ApiError("GitHub bremst diese Verbindung gerade — bitte in "
                           "einer Stunde noch einmal versuchen.") from None
        raise ApiError(f"GitHub antwortet {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"GitHub ist nicht erreichbar ({exc.reason})") from None
    except ValueError:
        raise ApiError("GitHub hat keine lesbare Antwort geschickt.") from None


def latest_release(repo=None, timeout=15):
    """Das neueste veröffentlichte Release, sonst der höchste Tag."""
    repo = repo or REPO
    try:
        data = _api(f"repos/{repo}/releases/latest", timeout)
        tag = data.get("tag_name") or data.get("name") or ""
        return {"version": tag.lstrip("vV"), "tag": tag, "ref": "",
                "notes": (data.get("body") or "").strip(),
                "zip": data.get("zipball_url") or "",
                "page": data.get("html_url") or f"https://github.com/{repo}/releases"}
    except FileNotFoundError:
        pass
    tags = _api(f"repos/{repo}/tags", timeout)
    if not isinstance(tags, list) or not tags:
        raise ApiError("Es gibt noch keine veröffentlichte Version.")
    newest = max(tags, key=lambda t: parse_version(t.get("name")))
    tag = newest.get("name", "")
    return {"version": tag.lstrip("vV"), "tag": tag, "ref": "", "notes": "",
            "zip": newest.get("zipball_url") or "",
            "page": f"https://github.com/{repo}/releases/tag/{tag}"}


def check(current=None, repo=None, timeout=15, repair=False):
    """Das Release, das jetzt installiert werden könnte, sonst None.

    ``repair`` bietet die laufende Version auch dann an, wenn sie keine
    Neuigkeit ist — für einen Ordner, in dem Dateien fehlen.
    """
    release = latest_release(repo, timeout)
    release["current"] = current or VERSION
    release["repair"] = False
    if parse_version(release["version"]) > parse_version(release["current"]):
        return release
    if repair:
        release["repair"] = True
        return release
    return None


def blocked(folder=None):
    """Warum Ersetzen hier falsch wäre, als Kürzel; leer, wenn es geht."""
    folder = folder or install_dir()
    if os.path.isdir(os.path.join(folder, ".git")):
        return "git"
    if not os.access(folder, os.W_OK):
        return "readonly"
    for name in program_files(folder):
        path = os.path.join(folder, name)
        if not os.access(path, os.W_OK) or not os.access(os.path.dirname(path), os.W_OK):
            return "readonly"
    return ""


# --------------------------------------------------------------------------
# Installieren
# --------------------------------------------------------------------------


def _download(url, timeout=60, progress=None):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"opnsense-haproxy/{VERSION}"})
    chunks, size = [], 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            try:
                total = int(reply.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            while True:
                chunk = reply.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ApiError("Der Download ist viel größer als erwartet "
                                   "und wurde abgebrochen.")
                chunks.append(chunk)
                if progress:
                    progress(size, total)
    except urllib.error.HTTPError as exc:
        raise ApiError(f"Download fehlgeschlagen ({exc.code} {exc.reason})") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"Download fehlgeschlagen ({exc.reason})") from None
    return b"".join(chunks)


def unpack(blob):
    """Die Programmdateien aus einem GitHub-Quellarchiv (ohne Wurzelordner)."""
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for entry in archive.infolist():
                parts = entry.filename.split("/")
                if entry.is_dir() or len(parts) < 2:
                    continue
                inner = "/".join(parts[1:])
                if updatable(inner):
                    files[inner] = archive.read(entry)   # prüft die CRC
    except (zipfile.BadZipFile, OSError) as exc:
        raise ApiError(f"Das Archiv ist nicht lesbar ({exc})") from None
    return files


def verify(files):
    """Unvollständiges oder Kaputtes ablehnen, bevor eine Datei ersetzt wird."""
    missing = [n for n in ESSENTIAL if n not in files]
    if missing:
        raise ApiError("Der Download ist unvollständig: "
                       + ", ".join(missing) + " fehlt.")
    for name, data in files.items():
        if name.endswith(".py"):
            try:
                compile(data.decode("utf-8"), name, "exec")
            except (UnicodeDecodeError, SyntaxError) as exc:
                raise ApiError(f"{name} im Download ist beschädigt ({exc}).") from None


def install(release, folder=None, say=None, progress=None, timeout=60):
    """Die Programmdateien durch das heruntergeladene Release ersetzen.

    Vorher wandert alles, was ersetzt oder entfernt wird, in einen
    Sicherungsordner. Das ist der Grund, warum Entfernen überhaupt gefahrlos ist.
    """
    folder = folder or install_dir()
    why = blocked(folder)
    if why:
        raise PforteError(BLOCKED[why])
    if not release.get("zip"):
        raise ApiError("Zu dieser Version gibt es kein Archiv.")
    say = say or (lambda _text: None)

    say("Lade die neue Version")
    files = unpack(_download(release["zip"], timeout, progress))
    verify(files)

    # Was die neue Version nicht mitbringt, gehört nicht mehr dazu — sonst
    # findet ein Import das alte Modul zuerst. Kandidaten kommen aus der
    # Aufzeichnung, nie aus einem Durchlauf des Ordners.
    state = record(folder)
    known = state["installed"]["files"] or LEGACY_FILES
    stale = [n for n in known if n not in files and updatable(n)
             and os.path.isfile(os.path.join(folder, n.replace("/", os.sep)))]

    backup = os.path.join(folder, f"backup-{release.get('current') or VERSION}")
    say("Sichere die jetzige Version")
    for name in sorted(set(files) | set(stale)):
        current = os.path.join(folder, name.replace("/", os.sep))
        if os.path.exists(current):
            kept = os.path.join(backup, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(kept), exist_ok=True)
            shutil.copy2(current, kept)

    say("Schreibe die neue Version")
    written = []
    for name, data in sorted(files.items()):
        target = os.path.join(folder, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        mode = os.stat(target).st_mode if os.path.exists(target) else None
        temporary = f"{target}.new"
        with open(temporary, "wb") as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(temporary, mode)            # ausführbar bleibt ausführbar
        os.replace(temporary, target)            # atomar: kein halbes Skript
        written.append(name)

    removed = []
    for name in stale:
        try:
            os.remove(os.path.join(folder, name.replace("/", os.sep)))
            removed.append(name)
        except OSError:
            pass                                 # liegt in der Sicherung
    if removed:
        _prune_empty(folder, removed)
    prune_backups(folder)

    # zuletzt: ein halb gelaufener Update hinterlässt keine falsche Notiz
    write_record({"channel": "stable",
                  "installed": {"channel": "stable", "ref": release.get("ref") or "",
                                "version": release["version"],
                                "files": sorted(written)}}, folder)
    return {"files": written, "removed": removed, "backup": backup,
            "version": release["version"]}


def prune_backups(folder, keep=KEEP_BACKUPS):
    """Nur die neuesten Sicherungsordner behalten (nach Änderungszeit)."""
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith("backup-") and os.path.isdir(path):
            found.append((os.path.getmtime(path), name))
    dropped = []
    for _when, name in sorted(found, reverse=True)[keep:]:
        try:
            shutil.rmtree(os.path.join(folder, name))
            dropped.append(name)
        except OSError:
            pass
    return dropped


def _prune_empty(folder, removed):
    """Ordner löschen, die das Entfernen geleert hat (nur per rmdir)."""
    candidates = set()
    for name in removed:
        parts = name.split("/")[:-1]
        while parts:
            candidates.add("/".join(parts))
            parts.pop()
    for inner in sorted(candidates, key=lambda p: p.count("/"), reverse=True):
        try:
            os.rmdir(os.path.join(folder, inner.replace("/", os.sep)))
        except OSError:
            pass
