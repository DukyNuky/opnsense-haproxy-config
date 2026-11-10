#!/usr/bin/env bash
# Pforte (opnsense-haproxy) unter Linux installieren.
#
#   bash install.sh              aus dem entpackten Archiv, oder
#   curl -fsSL https://raw.githubusercontent.com/DukyNuky/opnsense-haproxy-config/main/install.sh | bash
#
# Installiert nach ~/.local/share/opnsense-haproxy, legt einen Eintrag im
# Startmenü und den Befehl "pforte" an. Braucht keine Root-Rechte.
set -eu

REPO="DukyNuky/opnsense-haproxy-config"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
TARGET="${PFORTE_DIR:-$DATA/opnsense-haproxy}"
BIN="${PFORTE_BIN:-$HOME/.local/bin}"
DESKTOP="$DATA/applications/opnsense-haproxy.desktop"
PACKAGES="python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
DEPS=0 MENU=1 UNINSTALL=0

usage() {
  cat <<'TEXT'
Pforte installieren.

  install.sh               installieren oder auf den Stand dieses Archivs bringen
  install.sh --deps        fehlende Pakete für das eigene Fenster mit sudo apt nachinstallieren
  install.sh --no-menu     keinen Eintrag im Startmenü anlegen
  install.sh --dir=ORDNER  anderer Zielordner (Vorgabe ~/.local/share/opnsense-haproxy)
  install.sh --uninstall   Programm, Menüeintrag und Befehl entfernen (Zugangsdaten bleiben)
TEXT
}

for arg in "$@"; do
  case "$arg" in
    --deps) DEPS=1 ;;
    --no-menu) MENU=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --dir=*) TARGET="${arg#--dir=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekannte Option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
fail() { printf 'Fehler: %s\n' "$*" >&2; exit 1; }

if [ "$UNINSTALL" = 1 ]; then
  [ -f "$TARGET/haproxy_gui.py" ] || [ ! -e "$TARGET" ] || fail "$TARGET sieht nicht nach Pforte aus, nichts entfernt."
  [ -d "$TARGET/.git" ] && fail "$TARGET ist eine Git-Arbeitskopie, nichts entfernt."
  rm -rf "$TARGET"
  rm -f "$DESKTOP" "$BIN/pforte"
  say "Entfernt. Die Zugangsdaten liegen weiter in ${XDG_CONFIG_HOME:-$HOME/.config}/pforte."
  exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "python3 fehlt. Unter Mint/Ubuntu/Debian: sudo apt install python3"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || fail "Python ist zu alt, gebraucht wird 3.9 oder neuer."

# Quelle: der Ordner, in dem dieses Skript liegt, sonst das neueste Release
SOURCE=""
SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ] && [ -f "$SELF" ]; then
  HERE="$(cd "$(dirname "$SELF")" && pwd)"
  [ -f "$HERE/haproxy_gui.py" ] && [ -d "$HERE/pforte" ] && SOURCE="$HERE"
fi
TEMP=""
cleanup() { [ -n "$TEMP" ] && rm -rf "$TEMP"; return 0; }
trap cleanup EXIT

if [ -z "$SOURCE" ]; then
  say "Lade die neueste Version von GitHub …"
  TEMP="$(mktemp -d)"
  python3 -I - "$REPO" "$TEMP" <<'PY' || fail "Der Download hat nicht geklappt."
import io, json, os, sys, urllib.request, zipfile
repo, temp = sys.argv[1], sys.argv[2]
def get(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "opnsense-haproxy-install"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return reply.read()
release = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
blob = get(release["zipball_url"])
root = os.path.realpath(os.path.join(temp, "src"))
with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    for entry in archive.infolist():
        inner = "/".join(entry.filename.split("/")[1:])
        if entry.is_dir() or not inner:
            continue
        path = os.path.realpath(os.path.join(root, inner))
        if not path.startswith(root + os.sep):
            raise SystemExit("Unerwarteter Pfad im Archiv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(archive.read(entry))
PY
  SOURCE="$TEMP/src"
  [ -f "$SOURCE/haproxy_gui.py" ] || fail "Das geladene Archiv ist unvollständig."
fi

if [ "$(cd "$SOURCE" && pwd -P)" = "$(mkdir -p "$TARGET" && cd "$TARGET" && pwd -P)" ]; then
  say "Dieser Ordner ist schon der Installationsordner, Dateien bleiben wie sie sind."
else
  [ -d "$TARGET/.git" ] && fail "$TARGET ist eine Git-Arbeitskopie. Dort bitte git pull verwenden."
  # dieselben Regeln wie der eingebaute Updater: nur Programmdateien, und
  # eine Aufzeichnung, damit spätere Updates Überholtes entfernen können
  python3 -I - "$SOURCE" "$TARGET" <<'PY' || fail "Die Dateien ließen sich nicht schreiben."
import os, shutil, sys
source, target = sys.argv[1], sys.argv[2]
sys.path.insert(0, source)
from pforte import VERSION, update
files = update.program_files(source)
missing = [name for name in update.ESSENTIAL if name not in files]
if missing:
    raise SystemExit("Es fehlt: " + ", ".join(missing))
known = update.record(target)["installed"]["files"]
for name in files:
    goal = os.path.join(target, name)
    os.makedirs(os.path.dirname(goal), exist_ok=True)
    shutil.copyfile(os.path.join(source, name), goal + ".new")
    os.replace(goal + ".new", goal)
for name in known:
    old = os.path.join(target, name)
    if name not in files and os.path.isfile(old):
        os.remove(old)
update.write_record({"channel": "stable", "installed": {
    "channel": "stable", "ref": "", "version": VERSION, "files": files}}, target)
print(f"Pforte {VERSION} liegt in {target}")
PY
fi
chmod +x "$TARGET/haproxy_gui.py"

mkdir -p "$BIN"
cat > "$BIN/pforte" <<EOF
#!/bin/sh
exec python3 "$TARGET/haproxy_gui.py" "\$@"
EOF
chmod +x "$BIN/pforte"

if [ "$MENU" = 1 ]; then
  mkdir -p "$(dirname "$DESKTOP")"
  cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Pforte
GenericName=Reverse Proxy
Comment=Neue Hosts hinter HAProxy auf OPNsense anlegen
Exec=python3 "$TARGET/haproxy_gui.py"
Icon=$TARGET/icon.png
Terminal=false
Categories=Network;
Keywords=HAProxy;OPNsense;Proxy;Reverse Proxy;AdGuard;DNS;Pforte;
StartupWMClass=opnsense-haproxy
EOF
  command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$(dirname "$DESKTOP")" >/dev/null 2>&1 || true
fi

# Eigenes Fenster: GTK und WebKit. Ohne sie nimmt Pforte Chrome/Edge oder den Browser.
if python3 -c 'import gi
gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2' >/dev/null 2>&1; then
  WINDOW="eigenes Fenster"
elif [ "$DEPS" = 1 ] && command -v apt-get >/dev/null 2>&1; then
  say "Installiere $PACKAGES (fragt nach dem sudo-Passwort) …"
  # shellcheck disable=SC2086
  sudo apt-get install -y $PACKAGES && WINDOW="eigenes Fenster" || WINDOW="Browser"
else
  WINDOW="Browser"
  say ""
  say "Hinweis: Für ein eigenes Programmfenster fehlen GTK/WebKit. Ohne sie öffnet"
  say "sich Pforte in Chrome/Edge oder im Browser. Nachinstallieren mit:"
  if command -v apt-get >/dev/null 2>&1; then
    say "  sudo apt install $PACKAGES"
  else
    say "  PyGObject, GTK 3 und WebKit2GTK 4.1 über die Paketverwaltung"
  fi
fi

say ""
say "Fertig. Start über das Startmenü (Pforte) oder mit: $BIN/pforte"
case ":$PATH:" in *":$BIN:"*) ;; *) say "($BIN liegt nicht im PATH, daher der volle Pfad.)" ;; esac
say "Anzeige: $WINDOW. Beim ersten Start führt ein Assistent durch die Einrichtung."
say "Prüfen ohne Fenster: $BIN/pforte --check"
