"""Der lokale Webserver hinter dem Fenster.

Er lauscht nur auf 127.0.0.1, verlangt einen Zufallsschlüssel (Cookie) und
prüft den Host-Header. Das Fenster ist eine Webseite; alles, was sie tut,
läuft über die kleine JSON-Schnittstelle in diesem Modul.
"""

import json
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid as uuidlib
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import VERSION, config, opnsense, update
from .adguard import AdGuard
from .net import ApiError, PforteError, base_url
from .portainer import Portainer

try:
    from . import _web
except ImportError:      # nur im Entwicklungsordner, vor dem ersten Bauen
    _web = None

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
IDLE_SECONDS = 150     # Browser bremsen Hintergrund-Tabs stark; also großzügig
BYE_SECONDS = 8        # nach „Fenster zu“ so lange auf einen Neuladen warten
OVERVIEW_TTL = 30       # Sekunden, die eine gelesene Übersicht frisch genug ist
GRACE_SECONDS = 180    # Zeit bis zum ersten Lebenszeichen des Fensters


# --------------------------------------------------------------------------
# Clients aus einem Profil
# --------------------------------------------------------------------------


def opnsense_client(profile):
    section = profile.get("opnsense") or {}
    return opnsense.Client(section.get("url", ""), section.get("key", ""),
                           section.get("secret", ""),
                           verify=section.get("verify", True))


def adguard_client(profile):
    section = profile.get("adguard")
    if not section or not section.get("url"):
        return None
    return AdGuard(section["url"], section.get("username", ""),
                   section.get("password", ""),
                   verify=section.get("verify", True))


def portainer_client(profile):
    section = profile.get("portainer")
    if not section or not section.get("url") or not section.get("api_key"):
        return None
    return Portainer(section["url"], section["api_key"],
                     verify=section.get("verify", True))


SECRETS = {"opnsense": ("key", "secret"), "adguard": ("password",),
           "portainer": ("api_key",)}


def merge_secrets(kind, settings, stored):
    """Leer gelassene Geheimnisfelder aus dem gespeicherten Profil füllen."""
    merged = dict(settings or {})
    old = (stored or {}).get(kind) or {}
    for field in SECRETS[kind]:
        if not merged.get(field):
            merged[field] = old.get(field, "")
    return merged


def guess_address(url):
    """Die IP-Adresse hinter einer Adresse, für den DNS-Vorschlag."""
    try:
        host = urlparse(base_url(url)).hostname or ""
        return socket.gethostbyname(host) if host else ""
    except (OSError, PforteError):
        return ""


def profile_name(settings, taken):
    host = urlparse(base_url(settings.get("url", ""))).hostname or "OPNsense"
    name, number = host, 2
    while name in taken:
        name, number = f"{host} ({number})", number + 1
    return name


# --------------------------------------------------------------------------
# Aufträge, die ein paar Sekunden dauern
# --------------------------------------------------------------------------


class Jobs:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    def start(self, work):
        job_id = uuidlib.uuid4().hex[:12]
        job = {"steps": [], "done": False, "ok": False, "error": "",
               "result": None}
        with self.lock:
            self.items[job_id] = job

        def say(text, level="info"):
            job["steps"].append({"text": text, "level": level})

        def run():
            try:
                job["result"] = work(say)
                job["ok"] = True
            except (PforteError, ApiError) as exc:
                job["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001 - dem Nutzer sagen, nicht abstürzen
                job["error"] = f"Unerwarteter Fehler: {exc}"
            job["done"] = True

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def get(self, job_id):
        with self.lock:
            return self.items.get(job_id)


# --------------------------------------------------------------------------
# Die Anwendung
# --------------------------------------------------------------------------


class App:
    def __init__(self, path=None):
        self.path = path
        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs()
        self.lock = threading.Lock()
        self.last_ping = None
        self.bye_at = None
        self._update = None
        self._release = None
        self._overviews = {}
        self.started = time.time()

    # -- Einstellungen -------------------------------------------------

    def data(self):
        return config.load(self.path)

    def state(self):
        data = self.data()
        return {"version": VERSION,
                "active": (config.find(data) or {}).get("name", ""),
                "profiles": [config.public(p) for p in data["profiles"]],
                "importable": [p["name"] for p in config.importable()
                               if p["name"] not in
                               {x["name"] for x in data["profiles"]}]}

    def profile(self, name=None):
        profile = config.find(self.data(), name)
        if profile is None:
            raise PforteError("Noch nichts eingerichtet.")
        return profile

    def test(self, body):
        kind = body.get("kind")
        stored = None
        if body.get("profile"):
            stored = config.find(self.data(), body["profile"])
        if kind not in SECRETS:
            raise PforteError("Unbekannter Dienst")
        settings = merge_secrets(kind, body.get("settings"), stored)
        verify = settings.get("verify", True) is not False
        if kind == "opnsense":
            if not (settings.get("key") and settings.get("secret")):
                raise PforteError("Key und Secret fehlen noch.")
            client = opnsense.Client(settings.get("url", ""), settings["key"],
                                     settings["secret"], verify=verify)
            info = opnsense.check(client)
            info["address"] = guess_address(settings["url"])
            return info
        if kind == "adguard":
            return AdGuard(settings.get("url", ""), settings.get("username", ""),
                           settings.get("password", ""), verify=verify).check()
        if not settings.get("api_key"):
            raise PforteError("Der Zugriffstoken fehlt noch.")
        return Portainer(settings.get("url", ""), settings["api_key"],
                         verify=verify).check()

    def save_profile(self, body):
        data = self.data()
        name = (body.get("name") or "").strip()
        previous = next((p for p in data["profiles"]
                         if p.get("name") == body.get("previous")), None)
        sections = {}
        for kind in SECRETS:
            raw = body.get(kind)
            if raw and raw.get("url"):
                section = merge_secrets(kind, raw, previous)
                section.pop("has_secret", None)
                sections[kind] = section
            else:
                sections[kind] = None
        if not sections["opnsense"] or not sections["opnsense"].get("key"):
            raise PforteError("Die OPNsense-Zugangsdaten fehlen.")
        taken = {p["name"] for p in data["profiles"]
                 if not previous or p["name"] != previous["name"]}
        profile = {"name": name or (previous or {}).get("name")
                   or profile_name(sections["opnsense"], taken),
                   **sections}
        if previous and previous["name"] != profile["name"]:
            config.drop(data, previous["name"])
        config.put(data, profile)
        config.save(data, self.path)
        return self.state()

    def import_old(self):
        data = self.data()
        known = {p["name"] for p in data["profiles"]}
        added = 0
        for profile in config.importable():
            if profile["name"] not in known:
                config.put(data, profile)
                added += 1
        if added:
            config.save(data, self.path)
        return self.state()

    def delete_profile(self, name):
        data = config.drop(self.data(), name)
        config.save(data, self.path)
        return self.state()

    def set_active(self, name):
        data = self.data()
        if not any(p.get("name") == name for p in data["profiles"]):
            raise PforteError("Dieses Profil gibt es nicht.")
        data["active"] = name
        config.save(data, self.path)
        return self.state()

    # -- Übersicht -----------------------------------------------------

    def overview(self, name=None, fresh=False):
        """Die Übersicht eines Profils; bis 30 s alte Antworten sind erlaubt.

        Der Start wärmt sie vor, während das Fenster noch aufgebaut wird.
        Nach jedem Anlegen oder Entfernen wird sie verworfen.
        """
        profile = self.profile(name)
        key = profile["name"]
        with self.lock:
            hit = self._overviews.get(key)
        if hit and not fresh and time.time() - hit[0] < OVERVIEW_TTL:
            return hit[1]
        result = self._read_overview(profile)
        with self.lock:
            self._overviews[key] = (time.time(), result)
        return result

    def warm(self):
        try:
            self.overview()
        except Exception:  # noqa: BLE001 - Vorwärmen darf nie stören
            pass

    def forget(self, name):
        with self.lock:
            self._overviews.pop(name, None)

    def _read_overview(self, profile):
        client = opnsense_client(profile)
        guard = adguard_client(profile)
        docker = portainer_client(profile)
        problems = {}

        with ThreadPoolExecutor(max_workers=3) as pool:
            future_listeners = pool.submit(opnsense.listeners, client)
            future_docker = pool.submit(docker.published) if docker else None
            listeners = future_listeners.result()  # ohne sie geht nichts
            future_hosts = pool.submit(opnsense.hosts, client, listeners)
            try:
                hosts = future_hosts.result()
            except ApiError as exc:
                hosts, problems["hosts"] = [], str(exc)
            suggestions = []
            if future_docker:
                try:
                    suggestions = future_docker.result()
                except ApiError as exc:
                    problems["portainer"] = str(exc)
        domains = opnsense.domains(client, [h["host"] for h in hosts])

        section = profile.get("adguard") or {}
        dns_target = section.get("target") or ""
        if not dns_target and listeners:
            specific = [a for a in listeners[0]["addresses"]
                        if a not in ("0.0.0.0", "::", "*")]
            dns_target = specific[0] if specific else guess_address(
                profile["opnsense"]["url"])
        return {"profile": profile["name"], "listeners": listeners,
                "hosts": hosts, "domains": domains,
                "suggestions": suggestions,
                "dns": {"enabled": guard is not None, "target": dns_target},
                "docker": docker is not None, "problems": problems}

    # -- Updates -------------------------------------------------------

    def update_info(self, force=False):
        """Gibt es eine neuere Version? Fehler werden gemeldet, nie geworfen."""
        with self.lock:
            cached = self._update
            if cached and not force and time.time() - cached["at"] < 6 * 3600:
                return cached["info"]
        info = {"current": VERSION, "available": False, "error": ""}
        release = None
        try:
            release = update.check(VERSION)
        except PforteError as exc:
            info["error"] = str(exc)
        if release:
            info.update(available=True, version=release["version"],
                        notes=release["notes"][:1500], page=release["page"])
            why = update.blocked()
            info["blocked"] = update.BLOCKED[why] if why else ""
        with self.lock:
            self._release = release
            self._update = {"at": time.time(), "info": info}
        return info

    def install_update(self):
        release = self._release
        if not release:
            raise PforteError("Es gibt nichts zu installieren — bitte erst "
                              "nach Updates suchen.")

        def work(say):
            result = update.install(release, say=say)
            self._update = None
            return {"version": result["version"]}
        return self.jobs.start(work)

    def restart(self):
        """Das Programm neu starten (nach einem Update)."""
        argv = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        if os.name == "nt":
            subprocess.Popen(argv, close_fds=True, creationflags=0x00000008 | 0x00000200)
        else:
            subprocess.Popen(argv, close_fds=True, start_new_session=True)
        threading.Timer(0.6, os._exit, [0]).start()
        return {"ok": True}

    # -- Aufträge ------------------------------------------------------

    def create(self, body):
        profile = self.profile(body.get("profile"))
        client = opnsense_client(profile)
        guard = adguard_client(profile)
        label, domain = body.get("label", ""), (body.get("domain") or "").strip()
        listener = body.get("listener") or ""
        if not listener:
            raise PforteError("Bitte einen Listener wählen.")
        target = body.get("target", "")
        dns_target = (body.get("dns_target")
                      or (profile.get("adguard") or {}).get("target") or "")

        def work(say):
            entry = next((d for d in opnsense.domains(client)
                          if d["domain"] == domain.lower()), None)
            try:
                return opnsense.create_host(
                    client, label=label, domain=domain, target=target,
                    listener_uuid=listener, domain_entry=entry, adguard=guard,
                    dns_target=dns_target, say=say)
            finally:
                self.forget(profile["name"])
        return self.jobs.start(work)

    def edit(self, body):
        profile = self.profile(body.get("profile"))
        client, guard = opnsense_client(profile), adguard_client(profile)
        dns_target = (body.get("dns_target")
                      or (profile.get("adguard") or {}).get("target") or "")
        args = dict(label=body.get("label", ""), domain=(body.get("domain") or "").strip(),
                    target=body.get("target", ""), listener_uuid=body.get("listener") or "",
                    adguard=guard, dns_target=dns_target)
        action = body.get("uuid", "")
        if not args["listener_uuid"]:
            raise PforteError("Bitte einen Listener wählen.")

        def work(say):
            try:
                return opnsense.update_host(client, action, say=say, **args)
            finally:
                self.forget(profile["name"])
        return self.jobs.start(work)

    def remove(self, body):
        profile = self.profile(body.get("profile"))
        client, guard = opnsense_client(profile), adguard_client(profile)
        action = body.get("uuid", "")

        def work(say):
            try:
                return opnsense.remove_host(client, action, adguard=guard, say=say)
            finally:
                self.forget(profile["name"])
        return self.jobs.start(work)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def make_handler(app, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Pforte"

        def log_message(self, *args):  # Konsole ruhig halten
            pass

        # -- Hilfen -----------------------------------------------

        def send(self, status, body, ctype="application/json", headers=()):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                return False
            cookies = self.headers.get("Cookie", "")
            return f"pforte={app.token}" in [c.strip() for c in cookies.split(";")]

        def read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise PforteError("Anfrage zu groß")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                raise PforteError("Anfrage nicht lesbar") from None

        def api(self, method, path, query):
            body = self.read_json() if method in ("POST", "PUT") else {}
            parts = [unquote(p) for p in path.strip("/").split("/")][1:]
            route = (method, *parts[:1])
            if route == ("GET", "state"):
                return app.state()
            if route == ("GET", "ping"):
                app.last_ping = time.time()
                app.bye_at = None
                return {"ok": True}
            if route == ("POST", "bye"):
                app.bye_at = time.time()
                return {"ok": True}
            if route == ("POST", "test"):
                return app.test(body)
            if route == ("POST", "profile"):
                return app.save_profile(body)
            if route == ("POST", "import"):
                return app.import_old()
            if route == ("POST", "active"):
                return app.set_active(body.get("name", ""))
            if method == "DELETE" and parts[:1] == ["profile"] and len(parts) == 2:
                return app.delete_profile(parts[1])
            if route == ("GET", "update"):
                return app.update_info(force=bool(query.get("force")))
            if route == ("POST", "update") and parts[1:] == ["install"]:
                return {"job": app.install_update()}
            if route == ("POST", "restart"):
                return app.restart()
            if route == ("GET", "overview"):
                return app.overview((query.get("profile") or [None])[0],
                                    fresh=bool(query.get("fresh")))
            if route == ("POST", "hosts"):
                return {"job": app.create(body)}
            if route == ("POST", "edit"):
                return {"job": app.edit(body)}
            if route == ("POST", "remove"):
                return {"job": app.remove(body)}
            if route == ("GET", "jobs") and len(parts) == 2:
                job = app.jobs.get(parts[1])
                if job is None:
                    raise PforteError("Auftrag unbekannt")
                return job
            return None

        # -- Verteilung -------------------------------------------

        def handle_any(self, method):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if self.headers.get("Host", "") not in allowed_hosts:
                return self.send(403, {"error": "Host nicht erlaubt"})
            if url.path == "/" and (query.get("t") or [""])[0] == app.token:
                return self.send(
                    302, b"", "text/plain",
                    [("Location", "/"),
                     ("Set-Cookie", f"pforte={app.token}; HttpOnly; "
                                    "SameSite=Strict; Path=/")])
            if not self.authorized():
                return self.send(
                    401, "Bitte das Fenster über Pforte selbst öffnen.".encode(),
                    "text/plain; charset=utf-8")
            if url.path.startswith("/api/"):
                try:
                    result = self.api(method, url.path, query)
                except PforteError as exc:
                    return self.send(400, {"error": str(exc),
                                           "code": exc.code})
                except Exception as exc:  # noqa: BLE001
                    return self.send(500, {"error": f"Unerwarteter Fehler: {exc}"})
                if result is None:
                    return self.send(404, {"error": "unbekannt"})
                return self.send(200, result)
            if method != "GET":
                return self.send(405, {"error": "nicht erlaubt"})
            return self.static(url.path)

        def static(self, path):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB, name))
            if os.path.isfile(full) and full.startswith(WEB + os.sep):
                with open(full, "rb") as handle:
                    data = handle.read()
            elif _web is not None and name in _web.FILES:
                # eingebettete Fassung: so kommt die Oberfläche über einen
                # Updater an, der nur .py-Dateien mitnimmt
                data = _web.FILES[name].encode("utf-8")
            else:
                return self.send(404, b"nicht gefunden", "text/plain")
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
                ctype += "; charset=utf-8"
            self.send(200, data, ctype)

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_DELETE(self):
            self.handle_any("DELETE")

    return Handler


def make_server(app, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    # der Handler braucht den echten Port, wenn 0 (frei wählen) verlangt war
    real = server.server_address[1]
    if port == 0:
        server.RequestHandlerClass = make_handler(app, real)
    return server


def watch_window(app, server):
    """Beenden, wenn das Fenster zu ist (es meldet sich regelmäßig)."""
    def loop():
        while True:
            time.sleep(2)
            now = time.time()
            if app.last_ping is None:
                if now - app.started > GRACE_SECONDS:
                    break
            elif now - app.last_ping > IDLE_SECONDS:
                break
            elif app.bye_at and now - app.bye_at > BYE_SECONDS:
                break
        server.shutdown()
    threading.Thread(target=loop, daemon=True).start()
