"""Einrichten und Prüfen ohne Fenster, für Skripte und Assistenten.

``--check`` prüft die gespeicherten Zugänge Punkt für Punkt, ``--configure``
legt ein Profil aus Umgebungsvariablen an. Geheimnisse stehen nie in der
Befehlszeile und werden nie ausgegeben.
"""

import os
import re
import sys

from . import NAME, VERSION, config, opnsense
from .net import PforteError
from .server import App, adguard_client, opnsense_client, portainer_client

COMMANDS = ("--check", "--configure", "--version", "--help", "-h")
MARK = {"ok": "[ok]    ", "warn": "[offen] ", "fail": "[FEHLT] "}

HELP = f"""{NAME} {VERSION}

  haproxy_gui.py               Fenster öffnen
  haproxy_gui.py --browser     im Browser statt im eigenen Fenster
  haproxy_gui.py --check       gespeicherte Zugänge prüfen (ohne Fenster)
  haproxy_gui.py --configure   Profil aus Umgebungsvariablen anlegen
  haproxy_gui.py --version

--check endet mit 0 (alles bereit), 1 (etwas fehlt) oder 2 (nichts
eingerichtet). Mit --profile=NAME wird ein bestimmtes Profil geprüft.

--configure liest:
  OPNSENSE_URL       Adresse der OPNsense, z. B. https://192.168.1.1
  OPNSENSE_KEYFILE   die von OPNsense geladene Datei mit key=… und secret=…
  OPNSENSE_KEY, OPNSENSE_SECRET   statt der Datei
  ADGUARD_URL, ADGUARD_USER, ADGUARD_PASSWORD, ADGUARD_TARGET   (optional)
  PORTAINER_URL, PORTAINER_TOKEN                                (optional)
  PFORTE_INSECURE=1  Zertifikate nicht prüfen (selbst signiert)
  PFORTE_PROFILE     Name des Profils (sonst aus der Adresse)
Gespeichert wird nur, wenn jeder angegebene Zugang funktioniert.
"""


def read_keyfile(path):
    """``key=…`` und ``secret=…`` aus der Schlüsseldatei der OPNsense."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise PforteError(f"Schlüsseldatei nicht lesbar: {exc}") from None
    key = re.search(r"^\s*key\s*=\s*(\S+)", text, re.M)
    secret = re.search(r"^\s*secret\s*=\s*(\S+)", text, re.M)
    if not (key and secret):
        raise PforteError("In der Schlüsseldatei fehlen key=… und secret=…")
    return key.group(1), secret.group(1)


def show(checks, out):
    for item in checks:
        line = MARK[item["state"]] + item["title"]
        if item.get("text"):
            line += ": " + item["text"]
        print(line, file=out)
        if item["state"] != "ok":
            for number, step in enumerate(item.get("steps") or [], 1):
                print(f"           {number}. {step}", file=out)


def service(title, call):
    try:
        call()
    except PforteError as exc:
        return {"id": title.lower(), "state": "fail", "title": title,
                "text": str(exc), "steps": []}
    return {"id": title.lower(), "state": "ok", "title": title, "text": "",
            "steps": []}


def profile_checks(profile):
    try:
        checks = opnsense.diagnose(opnsense_client(profile))
    except PforteError as exc:
        text = str(exc)
        if exc.code == "tls":
            text += " Mit PFORTE_INSECURE=1 neu einrichten oder in den " \
                    "Einstellungen „Trotzdem verbinden“ wählen."
        checks = [{"id": "login", "state": "fail", "title": "Verbindung",
                   "text": text, "steps": []}]
    guard = adguard_client(profile)
    if guard:
        checks.append(service("AdGuard Home", guard.check))
    docker = portainer_client(profile)
    if docker:
        checks.append(service("Portainer", docker.check))
    return checks


def check(argv, out):
    wanted = next((a.split("=", 1)[1] for a in argv
                   if a.startswith("--profile=")), None)
    data = config.load()
    profiles = data.get("profiles") or []
    if wanted:
        profiles = [p for p in profiles if p.get("name") == wanted]
    if not profiles:
        print("Noch nichts eingerichtet." if not wanted
              else f"Das Profil {wanted} gibt es nicht.", file=out)
        return 2
    worst = 0
    for profile in profiles:
        print(f"{profile['name']} ({profile['opnsense'].get('url', '')})", file=out)
        checks = profile_checks(profile)
        show(checks, out)
        if any(c["state"] == "fail" for c in checks):
            worst = 1
    return worst


def configure(env, out):
    url = env.get("OPNSENSE_URL", "").strip()
    if not url:
        raise PforteError("OPNSENSE_URL fehlt.")
    if env.get("OPNSENSE_KEYFILE"):
        key, secret = read_keyfile(env["OPNSENSE_KEYFILE"])
    else:
        key, secret = env.get("OPNSENSE_KEY", ""), env.get("OPNSENSE_SECRET", "")
    if not (key and secret):
        raise PforteError("OPNSENSE_KEYFILE oder OPNSENSE_KEY und "
                          "OPNSENSE_SECRET fehlen.")
    verify = env.get("PFORTE_INSECURE", "") not in ("1", "true", "yes")
    body = {"name": env.get("PFORTE_PROFILE", ""),
            "opnsense": {"url": url, "key": key, "secret": secret,
                         "verify": verify}}
    app = App()
    report = app.diagnose({"settings": body["opnsense"]})
    show(report["checks"], out)
    if not report["ready"]:
        raise PforteError("Nicht gespeichert: die OPNsense ist so nicht "
                          "benutzbar.")
    if env.get("ADGUARD_URL"):
        body["adguard"] = {"url": env["ADGUARD_URL"],
                           "username": env.get("ADGUARD_USER", ""),
                           "password": env.get("ADGUARD_PASSWORD", ""),
                           "target": env.get("ADGUARD_TARGET", "")
                           or report.get("address", ""),
                           "verify": verify}
        app.test({"kind": "adguard", "settings": body["adguard"]})
        print(MARK["ok"] + "AdGuard Home", file=out)
    if env.get("PORTAINER_URL"):
        body["portainer"] = {"url": env["PORTAINER_URL"],
                             "api_key": env.get("PORTAINER_TOKEN", ""),
                             "verify": verify}
        app.test({"kind": "portainer", "settings": body["portainer"]})
        print(MARK["ok"] + "Portainer", file=out)
    existing = {p["name"] for p in app.data()["profiles"]}
    if body["name"] in existing:
        body["previous"] = body["name"]
    state = app.save_profile(body)
    print(f"Gespeichert als Profil {state['active']} in {app.path or config.config_path()}", file=out)
    return 0


def main(argv, env=None, out=None):
    out = out or sys.stdout
    env = os.environ if env is None else env
    if "--help" in argv or "-h" in argv:
        print(HELP, file=out)
        return 0
    if "--version" in argv:
        print(VERSION, file=out)
        return 0
    try:
        if "--configure" in argv:
            return configure(env, out)
        return check(argv, out)
    except PforteError as exc:
        print(f"Fehler: {exc}", file=out)
        return 1
