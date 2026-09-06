"""The whole arrangement in one picture, worked out from what was last read.

A host name that answers in a browser is the end of a chain, and every link
of it lives in a different place: a certificate on the firewall, a name in
AdGuard, a public service and a rule and a pool in HAProxy, a machine and a
port behind that, and something in Docker actually listening there. Nothing
tells anyone which link is the broken one -- each system only knows its own
part, and each says everything is fine.

This module puts the chain together and marks the gap. It asks nobody: it is
handed what the tabs already read and does arithmetic. That is the reason it
can be checked without a display and without a firewall.
"""

from dataclasses import dataclass, field

import opnsense_haproxy as core

from . import wiring
from .sources import FAILED

# How a station is doing.
OK = "ok"            # there, and it fits
WARN = "warn"        # there, but worth a look
MISSING = "missing"  # not there, and it should be
UNKNOWN = "unknown"  # nobody could tell us -- the system was not read
SKIPPED = "skipped"  # does not apply here, which is not a gap

# Worst first: the state of a chain is the worst of its stations, and a
# station nobody could read is not as bad as one that is definitely missing.
RANK = {MISSING: 4, WARN: 3, UNKNOWN: 2, OK: 1, SKIPPED: 0}


def worst(states):
    return max(states, key=lambda state: RANK.get(state, 0), default=SKIPPED)


@dataclass
class Station:
    """One link of the chain, and the way in when it is not right."""

    key: str
    title: str
    state: str
    detail: str = ""
    #: what to do about it, in words a person can act on
    hint: str = ""
    #: which tab to open when there is nothing better to offer
    tab: str = ""
    #: what the window can do about it right here. A station that names one
    #: gets a button that does the thing rather than one that moves someone
    #: to another tab to look for it -- the overview already knows which name
    #: is missing, and sending them off to type it again would be the program
    #: forgetting what it just worked out.
    fix: str = ""
    fix_label: str = ""
    #: whatever the window needs to act right here rather than send someone
    #: away -- the servers of this chain, for instance, so the note about
    #: what sits behind them can be set without leaving the tab
    data: dict = field(default_factory=dict)


@dataclass
class Chain:
    """One reachable thing, and everything it hangs on."""

    name: str
    where: str = ""          # which firewall it was found on
    path: str = ""
    kind: str = "host"       # host | listener
    stations: list = field(default_factory=list)

    @property
    def state(self):
        return worst([s.state for s in self.stations])

    @property
    def gaps(self):
        return [s for s in self.stations if s.state in (MISSING, WARN)]

    def station(self, key):
        return next((s for s in self.stations if s.key == key), None)


@dataclass
class Card:
    """One box of the map above the chains."""

    kind: str
    title: str
    state: str = OK
    lines: list = field(default_factory=list)


@dataclass
class Overview:
    cards: list = field(default_factory=list)
    chains: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def trouble(self):
        return [chain for chain in self.chains if chain.state in (MISSING, WARN)]


# --------------------------------------------------------------------------
# what was read, gathered into one shape
# --------------------------------------------------------------------------


def collect(shelf):
    """Everything the tabs have read, without asking anybody anything."""
    return {kind: list(shelf.of_kind(kind)) for kind in wiring.KINDS}


def dns_answers(sources):
    """``{name: [(which server, answer)]}`` across every AdGuard that answered."""
    found = {}
    for source in sources:
        for entry in (source.data or []):
            if not isinstance(entry, dict):
                continue
            domain = str(entry.get("domain", "")).strip().lower()
            if domain:
                found.setdefault(domain, []).append(
                    (source.name, str(entry.get("answer", "")).strip()))
    return found


def docker_ports(sources):
    """``{(address, port): [(which host, container, stack, state)]}``.

    Keyed by both, because the question a chain asks is "is anything actually
    listening on 192.168.1.40:8096" and the answer has to come from a machine
    with that address. The address of a Docker host is whatever was written in
    its settings; without one, the port is listed under an empty address and
    matches on the port alone.
    """
    found = {}
    for source in sources:
        inventory = source.data
        if inventory is None:
            continue
        address = str((source.settings or {}).get("host_ip", "")).strip()
        for stack in inventory.stacks:
            for port in stack.ports:
                found.setdefault((address, port.host), []).append(
                    (source.name, port.container, stack.name, stack.state))
        for container in inventory.loose:
            for port in container.ports:
                found.setdefault((address, port.host), []).append(
                    (source.name, container.name, "", container.state))
    return found


# --------------------------------------------------------------------------
# the chain
# --------------------------------------------------------------------------


def certificate_station(host, readings):
    """Is there a certificate that would cover this name?"""
    if readings["domains_error"]:
        return Station("certificate", "Zertifikat", UNKNOWN,
                       detail="Die Zertifikatsliste war nicht zu lesen",
                       hint=readings["domains_error"], tab="haproxy")
    domains = readings["domains"]
    if not domains:
        return Station("certificate", "Zertifikat", UNKNOWN,
                       detail="Kein ACME-Zertifikat gefunden",
                       hint="Ohne den ACME-Client auf der OPNsense kann hier "
                            "niemand sagen, wofür ein Zertifikat gilt.",
                       tab="haproxy")
    for entry in domains:
        if core.covered_by(entry, host):
            return Station("certificate", "Zertifikat", OK,
                           detail=f"{entry['certificate']} gilt für {host}",
                           tab="haproxy")
    names = ", ".join(sorted(entry["domain"] for entry in domains)[:4])
    return Station("certificate", "Zertifikat", WARN,
                   detail=f"Kein Zertifikat deckt {host}",
                   hint=f"Vorhanden ist eines für {names}. Der Browser wird "
                        "warnen, bis der Name mit abgedeckt ist.",
                   tab="haproxy")


def dns_station(host, answers, expected, configured):
    """Does the name lead to HAProxy inside the house?"""
    if not configured:
        return Station("dns", "DNS-Name", SKIPPED,
                       detail="Kein AdGuard eingerichtet",
                       hint="Ohne DNS im Heimnetz muss der Name von außen "
                            "aufgelöst werden — das kann richtig sein.",
                       tab="adguard")
    entries = answers.get(host.lower())
    if not entries:
        return Station("dns", "DNS-Name", MISSING,
                       detail=f"Keine Umschreibung für {host}",
                       hint="Ohne sie landet der Name nicht bei HAProxy, und "
                            "die Seite ist im Heimnetz nicht zu erreichen.",
                       tab="adguard", fix="dns",
                       fix_label="Eintrag anlegen",
                       data={"host": host, "answer": expected})
    where = ", ".join(sorted({name for name, _answer in entries}))
    targets = sorted({answer for _name, answer in entries if answer})
    detail = f"{host} → {', '.join(targets) or '?'}  ({where})"
    if expected and targets and any(t != expected for t in targets):
        return Station("dns", "DNS-Name", WARN, detail=detail,
                       hint=f"HAProxy steht auf {expected}. Ein Name, der "
                            "woandershin zeigt, geht am Proxy vorbei.",
                       tab="adguard", fix="dns", fix_label="Eintrag ändern",
                       data={"host": host, "answer": expected})
    if len(entries) > 1 and len(targets) > 1:
        return Station("dns", "DNS-Name", WARN, detail=detail,
                       hint="Zwei DNS-Server antworten verschieden. Welche "
                            "Antwort gilt, hängt daran, wer zuerst gefragt "
                            "wird.", tab="adguard")
    return Station("dns", "DNS-Name", OK, detail=detail, tab="adguard")


TITLE_BEHIND = "Dahinter"


def _noted(servers):
    """What was noted about these servers, as one answer if they agree."""
    kinds = {str(s.get("behind") or "") for s in servers}
    kinds.discard("")
    if len(kinds) == 1:
        return kinds.pop()
    return ""


def behind_station(servers, ports, configured):
    """Was läuft an der Adresse -- und wenn nichts, ist das ein Problem?

    The note on the server settles the last question, and it is the only thing
    that can. A VM behind a name looks exactly like a container that is not
    there: both are an address with nothing of ours listening on it. Only
    somebody who knows can say which, and once they have said it, it is
    written on the server itself so nobody has to say it twice.
    """
    place = {"servers": servers}
    noted = _noted(servers)
    if noted and not core.BEHIND_EXPECTS_CONTAINER.get(noted, True):
        return Station("container", TITLE_BEHIND, OK,
                       detail=f"{core.BEHIND_KINDS[noted]} — vermerkt, es wird "
                              "kein Container erwartet",
                       tab="haproxy", fix="behind",
                       fix_label="Vermerk ändern", data=place)
    if not servers:
        return Station("container", TITLE_BEHIND, UNKNOWN, detail="",
                       tab="portainer", data=place)
    if not configured and not noted:
        return Station("container", TITLE_BEHIND, SKIPPED,
                       detail="Kein Docker-Host eingerichtet",
                       hint="Was hinter der Adresse läuft, kann von hier aus "
                            "niemand sehen — das ist in Ordnung, wenn es kein "
                            "Container ist.", tab="portainer", data=place)
    hits, misses = [], []
    for server in servers:
        address = str(server.get("address", "")).strip()
        try:
            port = int(str(server.get("port", "")).strip() or 0)
        except ValueError:
            port = 0
        found = ports.get((address, port)) or ports.get(("", port))
        if found:
            hits.extend(found)
        else:
            misses.append(f"{address}:{port or '?'}")
    if hits and not misses:
        running = [h for h in hits if h[3] == "running"]
        names = ", ".join(sorted({h[1] or h[2] for h in hits}))
        if not running:
            return Station("container", TITLE_BEHIND, WARN,
                           detail=f"{names} — läuft gerade nicht",
                           hint="Der Eintrag im Proxy stimmt, aber dahinter "
                                "antwortet nichts.", tab="portainer",
                           data=place)
        return Station("container", TITLE_BEHIND, OK, detail=names,
                       tab="portainer", data=place)
    if hits:
        return Station("container", TITLE_BEHIND, WARN,
                       detail=f"nur teilweise gefunden; offen: "
                              f"{', '.join(misses)}",
                       tab="portainer", data=place)
    if noted:
        # noted as a container, and none was found -- that is a real gap
        return Station("container", TITLE_BEHIND, WARN,
                       detail=f"Als {core.BEHIND_KINDS[noted]} vermerkt, aber "
                              f"auf {', '.join(misses)} läuft keiner",
                       hint="Entweder der Container ist weg, oder der Vermerk "
                            "stimmt nicht mehr.", tab="portainer",
                       fix="behind", fix_label="Vermerk ändern", data=place)
    return Station("container", TITLE_BEHIND, UNKNOWN,
                   detail=f"Nichts auf {', '.join(misses)} gefunden",
                   hint="Auf keinem eingerichteten Docker-Host ist dieser Port "
                        "veröffentlicht. Wenn dort eine eigene VM oder ein "
                        "Gerät steht, lässt sich das hier vermerken — dann ist "
                        "die Kette vollständig und bleibt es auch nach einer "
                        "Neuinstallation, denn der Vermerk steht auf der "
                        "OPNsense.", tab="portainer", fix="behind",
                       fix_label="Vermerken, was dort läuft", data=place)


def _servers_of(backend):
    return list((backend or {}).get("servers") or [])


def _server_detail(servers):
    return ", ".join(
        f"{'https' if s.get('ssl') else 'http'}://{s.get('address', '?')}:"
        f"{s.get('port', '?')}" for s in servers) or "kein Server im Pool"


def host_chain(host, path, service, rule, readings, answers, ports,
               expected, dns_on, docker_on, where):
    """The full chain of one host name that a rule points at."""
    backend = rule.get("backend")
    servers = _servers_of(backend)
    stations = [
        certificate_station(host, readings),
        dns_station(host, answers, expected, dns_on),
        Station("frontend", "Öffentlicher Dienst",
                OK if service["enabled"] else WARN,
                detail=f"{service['name']} auf {service['bind'] or '?'} "
                       f"({service['mode']})",
                hint="" if service["enabled"] else
                     "Der öffentliche Dienst ist abgeschaltet — nichts "
                     "dahinter ist erreichbar.",
                tab="haproxy"),
        Station("rule", "Regel", OK,
                detail=f"{rule['name']} erkennt {host}{path}", tab="haproxy"),
    ]
    if backend is None:
        stations.append(Station("backend", "Pool", MISSING,
                                detail="Die Regel zeigt auf keinen Pool",
                                hint="Ohne Pool weiß HAProxy nicht, wohin die "
                                     "Anfrage soll.", tab="haproxy"))
        stations.append(Station("server", "Server", MISSING, detail="",
                                tab="haproxy"))
    else:
        stations.append(Station("backend", "Pool", OK,
                                detail=f"{backend['name']} ({backend['mode']})",
                                tab="haproxy"))
        stations.append(Station("server", "Server",
                                OK if servers else MISSING,
                                detail=_server_detail(servers),
                                hint="" if servers else
                                     "Im Pool steht keine Maschine, an die "
                                     "weitergereicht werden könnte.",
                                tab="haproxy"))
    stations.append(behind_station(servers, ports, docker_on))
    return Chain(name=host, where=where, path=path, kind="host",
                 stations=stations)


def listener_chain(service, readings, answers, ports, expected, dns_on,
                   docker_on, where):
    """A public service that is its own port, with no host name to match on."""
    host = service.get("dns") or ""
    backend = service.get("default")
    servers = _servers_of(backend)
    stations = []
    if host:
        stations.append(certificate_station(host, readings))
        stations.append(dns_station(host, answers, expected, dns_on))
    else:
        stations.append(Station("certificate", "Zertifikat", SKIPPED,
                                detail="Kein Name hinterlegt", tab="haproxy"))
        stations.append(Station("dns", "DNS-Name", SKIPPED,
                                detail="Dieser Dienst wird über die Adresse "
                                       "erreicht, nicht über einen Namen",
                                tab="adguard"))
    stations.append(Station("frontend", "Öffentlicher Dienst",
                            OK if service["enabled"] else WARN,
                            detail=f"{service['name']} auf "
                                   f"{service['bind'] or '?'} "
                                   f"({service['mode']})",
                            hint="" if service["enabled"] else
                                 "Abgeschaltet — der Port nimmt nichts an.",
                            tab="haproxy"))
    stations.append(Station("rule", "Regel", SKIPPED,
                            detail="Alles auf diesem Port geht an denselben "
                                   "Pool", tab="haproxy"))
    stations.append(Station("backend", "Pool",
                            OK if backend else MISSING,
                            detail=backend["name"] if backend else
                                   "Kein Pool hinterlegt",
                            hint="" if backend else
                                 "Der Port nimmt an, weiß aber nicht, wohin "
                                 "damit.", tab="haproxy"))
    stations.append(Station("server", "Server", OK if servers else MISSING,
                            detail=_server_detail(servers), tab="haproxy"))
    stations.append(behind_station(servers, ports, docker_on))
    return Chain(name=host or service["name"], where=where, kind="listener",
                 stations=stations)


# --------------------------------------------------------------------------
# putting it together
# --------------------------------------------------------------------------


def _firewall_address(source):
    return str((source.settings or {}).get("haproxy_ip", "")).strip()


def chains_for(source, answers, ports, dns_on, docker_on):
    """Every chain one firewall's reading gives rise to."""
    reading = source.data or {}
    readings = {"domains": reading.get("domains") or [],
                "domains_error": reading.get("domains_error") or ""}
    expected = _firewall_address(source)
    found = []
    for service in reading.get("services") or []:
        rules = [r for r in service.get("rules") or [] if r.get("host")]
        for rule in rules:
            found.append(host_chain(rule["host"], rule.get("path") or "",
                                    service, rule, readings, answers, ports,
                                    expected, dns_on, docker_on, source.name))
        # A public service with no host rules is a port of its own -- a
        # listener. One with rules that match on nothing we understand is not,
        # and is left out rather than described wrongly.
        if not rules and (service.get("default") or service.get("dns")):
            found.append(listener_chain(service, readings, answers, ports,
                                        expected, dns_on, docker_on,
                                        source.name))
    return found


def _card(kind, title, sources, lines_for):
    """One box of the map, with the state of the systems behind it."""
    unread = [s for s in sources if not s.ready]
    broken = [s for s in sources if s.status == FAILED]
    if not sources:
        return Card(kind, title, MISSING, ["nichts eingerichtet"])
    state = OK
    if broken:
        state = WARN
    elif unread:
        state = UNKNOWN
    lines = lines_for([s for s in sources if s.ready])
    for source in broken:
        lines.append(f"{source.name}: keine Antwort")
    for source in unread:
        if source not in broken:
            lines.append(f"{source.name}: noch nicht gelesen")
    return Card(kind, title, state, lines)


def build(shelf):
    """The map and the chains, out of what is already on the shelf."""
    gathered = collect(shelf)
    firewalls = gathered[wiring.OPNSENSE]
    dns_sources = gathered[wiring.DNS]
    docker_sources = gathered[wiring.DOCKER]

    answers = dns_answers(dns_sources)
    ports = docker_ports(docker_sources)
    dns_on = bool(dns_sources)
    docker_on = bool(docker_sources)

    chains = []
    for source in firewalls:
        if source.ready:
            chains.extend(chains_for(source, answers, ports, dns_on, docker_on))
    chains.sort(key=lambda chain: (chain.name.lower(), chain.path))

    def dns_lines(ready):
        total = sum(len(source.data or []) for source in ready)
        return [f"{total} Umschreibung{'en' if total != 1 else ''} "
                f"auf {len(ready)} Server{'n' if len(ready) != 1 else ''}"] \
            if ready else []

    def proxy_lines(ready):
        services = sum(len((s.data or {}).get("services") or []) for s in ready)
        rules = sum(len(service.get("rules") or [])
                    for s in ready for service in (s.data or {}).get("services") or [])
        return [f"{services} öffentliche Dienste, {rules} Regeln"] if ready else []

    def docker_lines(ready):
        stacks = sum(len(s.data.stacks) for s in ready if s.data)
        running = sum(1 for s in ready if s.data
                      for stack in s.data.stacks
                      for container in stack.containers if container.running)
        return [f"{stacks} Stacks, {running} Container laufen"] if ready else []

    cards = [_card(wiring.DNS, "DNS", dns_sources, dns_lines),
             _card(wiring.OPNSENSE, "HAProxy", firewalls, proxy_lines),
             _card(wiring.DOCKER, "Docker", docker_sources, docker_lines)]

    notes = []
    for chain in chains:
        for station in chain.gaps:
            notes.append(f"{chain.name}: {station.title} — {station.detail}")
    return Overview(cards=cards, chains=chains, notes=notes)
