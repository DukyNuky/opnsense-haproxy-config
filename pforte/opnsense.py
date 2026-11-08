"""OPNsense und sein HAProxy-Plugin: lesen, Hosts anlegen, Hosts entfernen.

Ein Host sind fünf Objekte (Real Server, Backend Pool, Condition, Rule und die
Verknüpfung in einem Public Service). Dieses Modul legt sie zusammen an, prüft
nach, was OPNsense gespeichert hat, und macht bei jedem Fehler alles wieder
rückgängig, was bis dahin angelegt war.
"""

import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .net import ApiError, PforteError, base_url, request_json

MANAGED = "managed:"          # Vorspann der Beschreibung aller Objekte von hier
SNI_MODES = ("ssl", "tcp")    # Listener, die nur den TLS-Handshake sehen

SEARCH = {"server": "searchServers", "backend": "searchBackends",
          "frontend": "searchFrontends", "acl": "searchAcls",
          "action": "searchActions"}
NAME = {"server": "Server", "backend": "Backend", "frontend": "Frontend",
        "acl": "Acl", "action": "Action"}


# --------------------------------------------------------------------------
# Felder lesen
# --------------------------------------------------------------------------


def selected_value(field):
    """Der gewählte Schlüssel eines Auswahlfelds aus einer get*-Antwort."""
    if isinstance(field, dict):
        for key, value in field.items():
            if isinstance(value, dict) and str(value.get("selected", 0)) == "1":
                return key
        return ""
    return field or ""


def selected_values(field):
    if isinstance(field, dict):
        return [k for k, v in field.items()
                if isinstance(v, dict) and str(v.get("selected", 0)) == "1"]
    return [v for v in str(field or "").split(",") if v]


def bind_ports(bind):
    """Alle Ports eines Listeners; „0.0.0.0:443, [::]:443“ ergibt [443]."""
    ports = []
    for entry in str(bind or "").split(","):
        text = entry.strip()
        port = text.rsplit(":", 1)[-1] if ":" in text else ""
        if port.isdigit() and int(port) not in ports:
            ports.append(int(port))
    return ports


def bind_addresses(bind):
    found = []
    for entry in str(bind or "").split(","):
        text = entry.strip()
        if ":" not in text:
            continue
        address = text.rsplit(":", 1)[0].strip("[]")
        if address and address not in found:
            found.append(address)
    return found


# --------------------------------------------------------------------------
# Der Client
# --------------------------------------------------------------------------


class Client:
    def __init__(self, url, key, secret, verify=True, timeout=30):
        self.base = base_url(url, "OPNsense-Adresse")
        self.timeout = timeout
        self.verify = verify
        self._auth = base64.b64encode(f"{key}:{secret}".encode()).decode()

    def call(self, path, payload=None, method=None):
        return request_json(
            f"{self.base}/api/{path}",
            headers={"Authorization": f"Basic {self._auth}"},
            payload=payload, method=method, verify=self.verify,
            timeout=self.timeout, who="OPNsense")

    def search(self, kind):
        reply = self.call(f"haproxy/settings/{SEARCH[kind]}",
                          {"current": 1, "rowCount": -1, "searchPhrase": ""})
        return reply.get("rows", [])

    def find(self, kind, name):
        return next((row for row in self.search(kind)
                     if row.get("name") == name), None)

    def get(self, kind, uuid):
        return self.call(f"haproxy/settings/get{NAME[kind]}/{uuid}")[kind]

    def add(self, kind, body):
        reply = self.call(f"haproxy/settings/add{NAME[kind]}", {kind: body})
        if reply.get("result") != "saved":
            raise ApiError(f"{kind} anlegen: {validation_text(reply)}")
        return reply["uuid"]

    def update(self, kind, uuid, body):
        reply = self.call(f"haproxy/settings/set{NAME[kind]}/{uuid}", {kind: body})
        if reply.get("result") not in ("saved", "ok"):
            raise ApiError(f"{kind} ändern: {validation_text(reply)}")

    def delete(self, kind, uuid):
        reply = self.call(f"haproxy/settings/del{NAME[kind]}/{uuid}", {})
        if reply.get("result") not in ("deleted", "ok"):
            raise ApiError(f"{kind} löschen: {validation_text(reply)}")

    def configtest(self):
        return self.call("haproxy/service/configtest", method="POST").get("result", "")

    def reconfigure(self):
        return self.call("haproxy/service/reconfigure", method="POST")


def validation_text(reply):
    problems = reply.get("validations")
    if problems:
        return "; ".join(f"{k}: {v}" for k, v in problems.items())
    return json.dumps(reply)[:300]


def check(client):
    """Verbindung, Rechte und HAProxy-Plugin in einem Zug prüfen."""
    try:
        client.call("haproxy/service/status")
    except ApiError as exc:
        if "abgelehnt" in str(exc):
            raise ApiError("OPNsense hat Key und Secret abgelehnt. Hat der "
                           "Benutzer das Recht auf HAProxy?") from None
        if "404" in str(exc):
            raise ApiError("Diese OPNsense kennt HAProxy nicht — fehlt das "
                           "Plugin os-haproxy?") from None
        raise
    return {"listeners": len(client.search("frontend"))}


# --------------------------------------------------------------------------
# Domains, aus den ACME-Zertifikaten
# --------------------------------------------------------------------------


def certificate_names(row):
    names = [str(row.get("name", "")).strip()]
    alt = row.get("altNames", "")
    if isinstance(alt, dict):
        alt = ",".join(alt.keys())
    names += [part.strip() for part in re.split(r"[,\s]+", str(alt or ""))]
    return [name.lower() for name in names if name]


def domains(client, hosts=()):
    """Die Domains, unter denen ein neuer Host liegen kann.

    Ein Platzhalterzertifikat für ``*.example.com`` macht ``example.com`` für
    jeden Namen darunter brauchbar; ein Einzelzertifikat bietet nur seine
    eigenen Namen. Fehlt das ACME-Plugin, werden die Domains der vorhandenen
    Hosts angeboten.
    """
    found = {}
    try:
        reply = client.call("acmeclient/certificates/search",
                            {"current": 1, "rowCount": -1, "searchPhrase": ""})
        for row in reply.get("rows", []):
            if str(row.get("enabled", "1")) != "1":
                continue
            names = certificate_names(row)
            for name in names:
                domain = name[2:] if name.startswith("*.") else name
                if domain and domain not in found:
                    found[domain] = {"domain": domain,
                                     "wildcard": name.startswith("*."),
                                     "certificate": row.get("name", ""),
                                     "covers": names}
    except ApiError:
        pass
    if not found:
        for host in hosts:
            parent = host.partition(".")[2]
            if parent.count(".") >= 1 and parent not in found:
                found[parent] = {"domain": parent, "wildcard": False,
                                 "certificate": "", "covers": []}
    return [found[key] for key in sorted(found)]


def covered(entry, fqdn):
    """Deckt das Zertifikat hinter dieser Domain den Namen wirklich ab?"""
    if not entry or not entry.get("covers"):
        return True  # nichts bekannt, nichts zu bemängeln
    fqdn = fqdn.lower()
    for name in entry["covers"]:
        if name == fqdn:
            return True
        if name.startswith("*.") and fqdn.endswith(name[1:]):
            return fqdn.count(".") == name.count(".")
    return False


# --------------------------------------------------------------------------
# Listener
# --------------------------------------------------------------------------


def _list(value):
    """Eine Referenzliste aus einer Suchzeile: „a,b,c“ -> [a, b, c]."""
    return [v for v in str(value or "").split(",") if v]


def listeners(client):
    """Alle Public Services, der wahrscheinlichste zuerst.

    Der Listener, der auf 443 lauscht und die meisten Regeln trägt, ist fast
    immer der Eingang, an dem neue Hosts hängen sollen.
    """
    found = []
    for row in client.search("frontend"):
        if "linkedActions" not in row or "bind" not in row:  # ältere Plugins
            try:
                row = client.get("frontend", row["uuid"]) | {"uuid": row["uuid"]}
            except ApiError:
                continue
            row = {**row, "bind": ", ".join(selected_values(row.get("bind"))),
                   "mode": selected_value(row.get("mode")),
                   "linkedActions": ",".join(selected_values(row.get("linkedActions")))}
        bind = str(row.get("bind", ""))
        rules = _list(row.get("linkedActions"))
        ports = bind_ports(bind)
        found.append({
            "uuid": row["uuid"], "name": row.get("name", ""),
            "mode": row.get("mode", ""), "bind": bind, "ports": ports,
            "addresses": bind_addresses(bind),
            "enabled": str(row.get("enabled", "1")) == "1",
            "rules": rules, "rule_count": len(rules), "https": 443 in ports})
    found.sort(key=lambda i: (not i["enabled"], not i["https"],
                              -i["rule_count"], i["name"].lower()))
    if found:
        found[0]["recommended"] = True
    return found


# --------------------------------------------------------------------------
# Vorhandene Hosts
# --------------------------------------------------------------------------


def hosts(client, frontends=None):
    """Alle Hosts, die per Regel auf einen Pool zeigen.

    ``managed`` sagt, ob sie von hier (oder einem Vorgänger) stammen. Nur
    diese dürfen von hier aus wieder entfernt werden. Gelesen wird mit fünf
    Suchabfragen statt mit einer Abfrage je Objekt.
    """
    frontends = listeners(client) if frontends is None else frontends
    linked = {uuid: f for f in frontends for uuid in f["rules"]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {kind: pool.submit(client.search, kind)
                   for kind in ("action", "acl", "backend", "server")}
        actions, acls, backends, servers = (futures[k].result() for k in
                                            ("action", "acl", "backend", "server"))
    acl_by = {row["uuid"]: row for row in acls}
    backend_by = {row["uuid"]: row for row in backends}
    server_by = {row["uuid"]: row for row in servers}

    found = []
    for row in actions:
        host, path = "", ""
        for acl_uuid in _list(row.get("linkedAcls")):
            acl = acl_by.get(acl_uuid) or {}
            expression = acl.get("expression", "")
            value = acl.get(expression, "")
            if expression in ("hdr", "hdr_beg", "hdr_end", "ssl_sni"):
                host = value
            elif expression == "path_beg":
                path = value
        if not host:
            continue
        target, ssl_on = "", False
        backend = backend_by.get(row.get("use_backend", ""))
        server = server_by.get((_list(backend.get("linkedServers")) or [""])[0]) if backend else None
        if server:
            target = f"{server.get('address', '')}:{server.get('port', '')}"
            ssl_on = str(server.get("ssl", "0")) == "1"
        frontend = linked.get(row["uuid"])
        found.append({
            "uuid": row["uuid"], "host": host, "path": path, "target": target,
            "ssl": ssl_on, "name": row.get("name", ""),
            "managed": str(row.get("description", "")).startswith(MANAGED),
            "listener": frontend["name"] if frontend else ""})
    found.sort(key=lambda i: i["host"])
    return found


# --------------------------------------------------------------------------
# Namen und Eingaben
# --------------------------------------------------------------------------


def slug(text, allow_dots=True):
    keep = r"0-9a-zA-Z._\-" if allow_dots else r"0-9a-zA-Z_\-"
    return re.sub(r"_+", "_", re.sub(rf"[^{keep}]", "_", text)).strip("_")


class Names:
    """Die Objektnamen eines Hosts. Server/Backend dürfen Punkte enthalten,
    Conditions und Rules nicht — die Masken des Plugins unterscheiden sich."""

    def __init__(self, host):
        self.dotted = slug(host, True)
        self.plain = slug(host, False)

    server = property(lambda s: f"srv_{s.dotted}")
    backend = property(lambda s: f"be_{s.dotted}")
    acl = property(lambda s: f"acl_{s.plain}")
    action = property(lambda s: f"rule_{s.plain}")


HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$")
ADDRESS = re.compile(r"^[0-9a-zA-Z._\-]+$")


def build_fqdn(label, domain):
    label = (label or "").strip().strip(".").lower()
    domain = (domain or "").strip().strip(".").lower()
    if not label or label == "@":
        return domain
    if domain and (label == domain or label.endswith(f".{domain}")):
        return label
    return f"{label}.{domain}" if domain else label


def parse_target(raw):
    """``192.168.0.5``, ``host:8080`` oder ``https://host:8443`` -> (Adresse, Port, TLS)."""
    text = (raw or "").strip()
    ssl_on = False
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://(.*)$", text)
    if match:
        scheme, text = match.group(1).lower(), match.group(2)
        if scheme not in ("http", "https"):
            raise PforteError("Ziel: nur http:// oder https:// ist möglich")
        ssl_on = scheme == "https"
    text = text.split("/", 1)[0]
    address, _, port = text.partition(":")
    if not address or not ADDRESS.match(address):
        raise PforteError("Ziel: bitte eine Adresse wie 192.168.0.5:8080 angeben")
    if port:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise PforteError(f"Ziel: {port!r} ist kein Port")
        port = int(port)
    else:
        port = 443 if ssl_on else 80
    return address, port, ssl_on


def check_label(label):
    label = (label or "").strip().lower()
    if not label:
        raise PforteError("Bitte einen Namen für den Host eingeben")
    for part in label.split("."):
        if not HOSTNAME.match(part):
            raise PforteError("Der Name darf nur Buchstaben, Ziffern und "
                              "Bindestriche enthalten")
    return label


# --------------------------------------------------------------------------
# Anlegen
# --------------------------------------------------------------------------


def _check_stored(client, kind, uuid, wanted):
    """Zurücklesen: OPNsense ignoriert unbekannte Felder stillschweigend."""
    written = client.get(kind, uuid)
    problems = []
    for field, expected in wanted.items():
        actual = selected_value(written.get(field))
        if str(actual) != str(expected):
            problems.append(f"{field} ist {actual or '?'}, nicht {expected}")
    if problems:
        raise ApiError(f"{kind} wurde nicht wie verlangt gespeichert: "
                       + "; ".join(problems))


def link_rules(client, frontend_uuid, action_uuids):
    """Nur die Regelliste eines Listeners schreiben, nichts sonst."""
    client.update("frontend", frontend_uuid,
                  {"linkedActions": ",".join(action_uuids)})


def rollback(client, created, say, adguard=None):
    for kind, ref in reversed(created):
        try:
            if kind == "dns":
                adguard.delete_rewrite(*ref)
            elif kind == "link":
                link_rules(client, ref[0], ref[1])
            else:
                client.delete(kind, ref)
        except (ApiError, PforteError, AttributeError) as exc:
            say(f"Aufräumen: {kind} blieb stehen ({exc})", "warn")


def apply(client, say):
    """Konfiguration prüfen und HAProxy neu laden. True, wenn es geklappt hat."""
    say("Konfiguration prüfen")
    report = client.configtest()
    lowered = report.lower()
    if any(m in lowered for m in ("[alert]", "[emerg]", "fatal errors")):
        raise ApiError("HAProxy lehnt die neue Konfiguration ab: "
                       + (report.strip().splitlines() or ["?"])[0][:200])
    say("HAProxy neu laden")
    reply = client.reconfigure()
    if str(reply.get("status", "ok")).lower() not in ("ok", "done"):
        raise ApiError(f"HAProxy-Neustart meldet: {json.dumps(reply)[:200]}")


def create_host(client, *, label, domain, target, listener_uuid,
                domain_entry=None, adguard=None, dns_target="", say=print):
    """Einen Host anlegen. ``say(text, level)`` meldet jeden Schritt.

    Gibt ``{"host", "warnings"}`` zurück; bei einem Fehler ist vorher alles
    wieder entfernt und es wird eine PforteError geworfen.
    """
    label = check_label(label)
    host = build_fqdn(label, domain)
    address, port, ssl_on = parse_target(target)
    names = Names(host)
    warnings = []

    frontend = client.get("frontend", listener_uuid)
    frontend_name = frontend.get("name", "")
    mode = selected_value(frontend.get("mode"))
    if mode not in ("http", *SNI_MODES):
        raise PforteError(f"Der Listener „{frontend_name}“ hat einen "
                          f"unbekannten Modus ({mode or '?'})")
    sni = mode in SNI_MODES
    backend_mode = "tcp" if sni else "http"

    if domain_entry is not None and not covered(domain_entry, host):
        warnings.append(f"Das Zertifikat „{domain_entry.get('certificate')}“ "
                        f"deckt {host} nicht ab — im Browser erscheint eine "
                        "Zertifikatswarnung.")

    for kind, name in (("server", names.server), ("backend", names.backend),
                       ("acl", names.acl), ("action", names.action)):
        if client.find(kind, name):
            raise PforteError(f"{host} gibt es schon.")

    note = f"{MANAGED} {host}"
    created = []
    try:
        say("Server anlegen")
        server = client.add("server", {
            "enabled": "1", "name": names.server, "description": note,
            "address": address, "port": str(port), "mode": "active",
            "type": "static", "ssl": "1" if ssl_on else "0", "sslVerify": "0"})
        created.append(("server", server))

        say("Pool anlegen")
        body = {"enabled": "1", "name": names.backend, "description": note,
                "mode": backend_mode, "linkedServers": server,
                "healthCheckEnabled": "0", "healthCheck": ""}
        if backend_mode == "http":
            body["forwardFor"] = "1"
        backend = client.add("backend", body)
        created.append(("backend", backend))
        _check_stored(client, "backend", backend, {"mode": backend_mode})

        say("Regel anlegen")
        expression = "ssl_sni" if sni else "hdr"
        acl_body = {"name": names.acl, "description": note,
                    "expression": expression, expression: host}
        acl = client.add("acl", acl_body)
        created.append(("acl", acl))
        _check_stored(client, "acl", acl,
                      {"expression": expression, expression: host})

        action = client.add("action", {
            "enabled": "1", "name": names.action, "description": note,
            "testType": "if", "operator": "and", "linkedAcls": acl,
            "type": "use_backend", "use_backend": backend})
        created.append(("action", action))

        say(f"In „{frontend_name}“ einhängen")
        linked = selected_values(frontend.get("linkedActions"))
        link_rules(client, listener_uuid, linked + [action])
        created.append(("link", (listener_uuid, linked)))

        if adguard is not None and dns_target:
            say("DNS-Eintrag setzen")
            existing = adguard.find_rewrite(host)
            if existing is None:
                adguard.add_rewrite(host, dns_target)
                created.append(("dns", (host, dns_target)))
            elif str(existing.get("answer", "")) != dns_target:
                warnings.append(f"AdGuard leitet {host} bereits auf "
                                f"{existing.get('answer')} — nicht verändert.")
        elif adguard is None:
            warnings.append("Kein AdGuard eingerichtet — den DNS-Eintrag "
                            "musst du selbst anlegen.")

        apply(client, say)
    except Exception:
        say("Etwas ging schief — alles wird zurückgenommen", "warn")
        rollback(client, created, say, adguard)
        raise
    return {"host": host, "warnings": warnings}


# --------------------------------------------------------------------------
# Entfernen
# --------------------------------------------------------------------------


def remove_host(client, action_uuid, adguard=None, say=print):
    """Rule, Condition, Pool und Server eines Hosts löschen, DNS-Eintrag auch."""
    action = client.get("action", action_uuid)
    if not str(action.get("description", "")).startswith(MANAGED):
        raise PforteError("Diese Regel wurde nicht von hier angelegt — "
                          "bitte in OPNsense selbst entfernen.")
    acls = selected_values(action.get("linkedAcls"))
    backend_uuid = selected_value(action.get("use_backend"))
    servers = []
    host = ""
    for acl_uuid in acls:
        acl = client.get("acl", acl_uuid)
        expression = selected_value(acl.get("expression"))
        if expression in ("hdr", "ssl_sni"):
            host = acl.get(expression, "") or host
    if backend_uuid:
        backend = client.get("backend", backend_uuid)
        servers = selected_values(backend.get("linkedServers"))

    say("Aus dem Listener lösen")
    for frontend in client.search("frontend"):
        current = selected_values(client.get("frontend", frontend["uuid"])
                                  .get("linkedActions"))
        if action_uuid in current:
            link_rules(client, frontend["uuid"],
                       [u for u in current if u != action_uuid])
    say("Regel entfernen")
    client.delete("action", action_uuid)

    def mine(kind, uuid):
        try:
            return str(client.get(kind, uuid).get("description", "")
                       ).startswith(MANAGED)
        except ApiError:
            return False

    for uuid in acls:
        if mine("acl", uuid):
            client.delete("acl", uuid)
    if backend_uuid and mine("backend", backend_uuid):
        client.delete("backend", backend_uuid)
        for uuid in servers:
            if mine("server", uuid):
                client.delete("server", uuid)

    if adguard is not None and host:
        existing = adguard.find_rewrite(host)
        if existing is not None:
            say("DNS-Eintrag entfernen")
            adguard.delete_rewrite(host, str(existing.get("answer", "")))
    apply(client, say)
    return {"host": host}
