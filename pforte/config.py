"""Einstellungen: ein paar Profile in einer Datei, die nur dem Nutzer gehört.

Ein Profil ist eine OPNsense samt der Dienste, die dazugehören (AdGuard und
Portainer, beide optional). Wer nur eine OPNsense hat, sieht davon nichts.
"""

import json
import os
import sys
import tempfile

OLD_CONFIG = os.path.expanduser("~/.config/opnsense-haproxy/config.json")


def config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "pforte")


def config_path():
    return os.environ.get("PFORTE_CONFIG") or os.path.join(config_dir(),
                                                          "config.json")


def empty():
    return {"version": 4, "active": "", "profiles": []}


def load(path=None):
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        return empty()
    return data


def save(data, path=None):
    path = path or config_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".config-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.remove(temp)
        raise


def find(data, name=None):
    """Das gewünschte Profil, sonst das aktive, sonst das erste."""
    profiles = data.get("profiles") or []
    for wanted in (name, data.get("active")):
        for profile in profiles:
            if wanted and profile.get("name") == wanted:
                return profile
    return profiles[0] if profiles else None


def put(data, profile):
    """Ein Profil anlegen oder ersetzen und aktiv setzen."""
    profiles = data.setdefault("profiles", [])
    for index, existing in enumerate(profiles):
        if existing.get("name") == profile["name"]:
            profiles[index] = profile
            break
    else:
        profiles.append(profile)
    data["active"] = profile["name"]
    return data


def drop(data, name):
    data["profiles"] = [p for p in data.get("profiles", []) if p.get("name") != name]
    if data.get("active") == name:
        data["active"] = data["profiles"][0]["name"] if data["profiles"] else ""
    return data


def public(profile):
    """Das Profil ohne Geheimnisse, für die Oberfläche."""
    def strip(section, secrets):
        if not section:
            return None
        return {k: ("" if k in secrets else v) for k, v in section.items()} | {
            "has_secret": any(section.get(k) for k in secrets)}
    return {"name": profile.get("name", ""),
            "opnsense": strip(profile.get("opnsense"), ("key", "secret")),
            "adguard": strip(profile.get("adguard"), ("password",)),
            "portainer": strip(profile.get("portainer"), ("api_key",))}


# --------------------------------------------------------------------------
# Übernahme aus Version 3
# --------------------------------------------------------------------------


def importable(path=OLD_CONFIG):
    """Die Profile der alten Einstellungsdatei, falls es sie gibt."""
    try:
        with open(path, encoding="utf-8") as handle:
            old = json.load(handle)
    except (OSError, ValueError):
        return []
    named = lambda kind, name: next(  # noqa: E731
        (e for e in old.get(kind, []) if e.get("name") == name), None)
    profiles = []
    for entry in old.get("opnsense", []):
        if not (entry.get("url") and entry.get("key") and entry.get("secret")):
            continue
        profile = {"name": entry.get("name") or entry["url"],
                   "opnsense": {"url": entry["url"], "key": entry["key"],
                                "secret": entry["secret"],
                                "verify": entry.get("verify_ssl", True) is not False},
                   "adguard": None, "portainer": None}
        active = entry.get("name") == (old.get("active") or {}).get("opnsense")
        fallback = old.get("active") or {} if active else {}
        guard = named("adguard", entry.get("adguard") or fallback.get("adguard"))
        if guard and guard.get("url"):
            profile["adguard"] = {
                "url": guard["url"], "username": guard.get("username", ""),
                "password": guard.get("password", ""),
                "target": guard.get("target") or entry.get("haproxy_ip", ""),
                "verify": guard.get("verify_ssl", True) is not False}
        docker = named("portainer", entry.get("portainer") or fallback.get("portainer"))
        if docker and docker.get("url") and docker.get("api_key"):
            profile["portainer"] = {
                "url": docker["url"], "api_key": docker["api_key"],
                "verify": docker.get("verify_ssl", True) is not False}
        profiles.append(profile)
    return profiles
