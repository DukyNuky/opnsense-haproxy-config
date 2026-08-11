#!/usr/bin/env python3
"""Provision a complete HAProxy host entry on OPNsense with a single command.

One `add` call creates the real server, the backend pool, the host condition,
the rule, links the rule into the public service (frontend) and reloads
HAProxy -- the five steps that otherwise have to be clicked through by hand.

Only the Python standard library is required.
"""

import argparse
import base64
import getpass
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "2.7.1"

DEFAULT_CONFIG = os.path.expanduser("~/.config/opnsense-haproxy/config.json")

# API endpoint suffixes per object kind; the plugin names them inconsistently
# (plural for search, singular everywhere else), so keep the mapping explicit.
SEARCH_ENDPOINT = {
    "server": "searchServers",
    "backend": "searchBackends",
    "frontend": "searchFrontends",
    "acl": "searchAcls",
    "action": "searchActions",
    "healthcheck": "searchHealthchecks",
}
ENDPOINT_NAME = {
    "server": "Server",
    "backend": "Backend",
    "frontend": "Frontend",
    "acl": "Acl",
    "action": "Action",
    "healthcheck": "Healthcheck",
}

# Frontends in "http" mode inspect the Host header; "ssl"/"tcp" frontends only
# ever see the TLS handshake, so they have to match on SNI instead.
SNI_MODES = ("ssl", "tcp")

YES = ("y", "yes", "j", "ja", "true", "1")


class ApiError(RuntimeError):
    pass


class UsageError(RuntimeError):
    pass


def base_url(raw, what="address", default_scheme="https", keep_path=False):
    """Make sense of an address the way people actually type or paste it.

    Adds the scheme when it is missing (urllib refuses anything else) and
    drops the fragment and query a copied browser URL carries along, e.g.
    ``https://adguard.example/#dns_rewrites``.
    """
    text = (raw or "").strip()
    if not text:
        raise UsageError(f"no {what} given")
    text = text.split("#", 1)[0].split("?", 1)[0].strip()
    if "://" not in text:
        text = f"{default_scheme}://{text}"
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise UsageError(f"'{raw}' is not a usable {what}")
    path = parsed.path.rstrip("/") if keep_path else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------


class Client:
    def __init__(self, url, key, secret, verify=True, timeout=30):
        self.base = base_url(url, "OPNsense address", keep_path=True)
        self.timeout = timeout
        self._auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
        self._ctx = None
        if not verify:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    def call(self, path, payload=None, method=None):
        """Call an OPNsense API endpoint; ``path`` starts at the module name."""
        url = f"{self.base}/api/{path}"
        headers = {
            "Authorization": f"Basic {self._auth}",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if method is None:
            method = "POST" if data is not None else "GET"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace").strip()[:400]
            if exc.code == 401:
                raise ApiError("401 Unauthorized -- check API key/secret") from None
            raise ApiError(f"{exc.code} {exc.reason} on {path}: {detail}") from None
        except urllib.error.URLError as exc:
            raise ApiError(f"cannot reach {self.base}: {exc.reason}") from None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(f"non-JSON reply from {path}: {body[:200]}") from None

    # -- generic model helpers ---------------------------------------------

    def search(self, kind):
        reply = self.call(
            f"haproxy/settings/{SEARCH_ENDPOINT[kind]}",
            {"current": 1, "rowCount": -1, "searchPhrase": ""},
        )
        return reply.get("rows", [])

    def find(self, kind, name):
        for row in self.search(kind):
            if row.get("name") == name:
                return row
        return None

    def get(self, kind, uuid):
        reply = self.call(f"haproxy/settings/get{ENDPOINT_NAME[kind]}/{uuid}")
        return reply[kind]

    def blank(self, kind):
        """The empty add form of a model, with every choice it offers in it.

        Asked without a uuid, OPNsense answers with the model's defaults --
        and, more to the point, with the option fields filled in: which
        certificates exist, which modes there are. It is where the plugin's
        own web interface gets the contents of its dropdowns, and there is no
        second place to ask.
        """
        reply = self.call(f"haproxy/settings/get{ENDPOINT_NAME[kind]}")
        return reply.get(kind) or {}

    def add(self, kind, body):
        reply = self.call(f"haproxy/settings/add{ENDPOINT_NAME[kind]}", {kind: body})
        if reply.get("result") != "saved":
            raise ApiError(f"creating {kind} failed: {_validation_text(reply)}")
        return reply["uuid"]

    def update(self, kind, uuid, body):
        reply = self.call(f"haproxy/settings/set{ENDPOINT_NAME[kind]}/{uuid}", {kind: body})
        if reply.get("result") not in ("saved", "ok"):
            raise ApiError(f"updating {kind} failed: {_validation_text(reply)}")

    def delete(self, kind, uuid):
        reply = self.call(f"haproxy/settings/del{ENDPOINT_NAME[kind]}/{uuid}", {})
        if reply.get("result") not in ("deleted", "ok"):
            raise ApiError(f"deleting {kind} failed: {_validation_text(reply)}")

    # -- service -----------------------------------------------------------

    def configtest(self):
        return self.call("haproxy/service/configtest", method="POST").get("result", "")

    def reconfigure(self):
        return self.call("haproxy/service/reconfigure", method="POST")

    def status(self):
        return self.call("haproxy/service/status")


def _validation_text(reply):
    problems = reply.get("validations")
    if problems:
        return "; ".join(f"{k}: {v}" for k, v in problems.items())
    return json.dumps(reply)


# --------------------------------------------------------------------------
# Base domains, taken from the ACME client's certificates
# --------------------------------------------------------------------------


def certificate_names(row):
    """Every FQDN one ACME certificate covers: its name plus the alt names."""
    names = [str(row.get("name", "")).strip()]
    alt = row.get("altNames", "")
    if isinstance(alt, dict):  # search may report list fields as option maps
        alt = ",".join(alt.keys())
    names += [part.strip() for part in re.split(r"[,\s]+", str(alt or ""))]
    return [name.lower() for name in names if name]


def base_domains(client):
    """Offerable base domains, derived from the ACME client certificates.

    A wildcard certificate for ``*.example.com`` makes ``example.com`` usable
    for any host below it; a plain certificate only covers the exact names it
    lists, which are offered as-is.
    """
    try:
        reply = client.call("acmeclient/certificates/search",
                            {"current": 1, "rowCount": -1, "searchPhrase": ""})
    except ApiError as exc:
        raise ApiError(f"cannot read ACME certificates ({exc}) -- is the "
                       "os-acme-client plugin installed?") from None

    found = {}
    for row in reply.get("rows", []):
        if str(row.get("enabled", "1")) != "1":
            continue
        names = certificate_names(row)
        for name in names:
            domain = name[2:] if name.startswith("*.") else name
            if not domain or domain in found:
                continue
            found[domain] = {
                "domain": domain,
                "wildcard": name.startswith("*."),
                "certificate": row.get("name", ""),
                "covers": names,
            }
    return [found[key] for key in sorted(found)]


def covered_by(domain_entry, fqdn):
    """Would the certificate behind this base domain actually cover the host?"""
    fqdn = fqdn.lower()
    for name in domain_entry["covers"]:
        if name == fqdn:
            return True
        if name.startswith("*.") and fqdn.endswith(name[1:]):
            # a wildcard matches exactly one extra label
            return fqdn.count(".") == name.count(".")
    return False


def with_base(target, base):
    """Let an empty target (or ``@``) mean the base domain itself."""
    text = (target or "").strip()
    head = text.split("/", 1)[0]
    if base and head in ("", "@"):
        return base + text[len(head):]
    return text


def build_fqdn(host, base):
    """Combine the host part with a chosen base domain."""
    host = (host or "").strip().strip(".").lower()
    base = (base or "").strip().strip(".").lower()
    if not base:
        return host
    if not host or host == "@":
        return base
    if host == base or host.endswith(f".{base}"):
        return host
    return f"{host}.{base}"


# --------------------------------------------------------------------------
# AdGuard Home
# --------------------------------------------------------------------------


class AdGuard:
    """The handful of AdGuard Home calls needed to keep a DNS rewrite in sync."""

    def __init__(self, url, username="", password="", verify=True, timeout=15):
        root = base_url(url, "AdGuard address", keep_path=True)
        # people paste the UI URL, which may or may not already end in /control
        self.base = root if root.endswith("/control") else root + "/control"
        self.timeout = timeout
        self._auth = None
        if username or password:
            self._auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._ctx = None
        if not verify:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    def call(self, path, payload=None):
        url = f"{self.base}/{path}"
        headers = {"Accept": "application/json"}
        if self._auth:
            headers["Authorization"] = f"Basic {self._auth}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace").strip()[:300]
            if exc.code in (401, 403):
                raise ApiError("AdGuard rejected the login -- check user/password") \
                    from None
            raise ApiError(f"AdGuard {exc.code} on {path}: {detail}") from None
        except urllib.error.URLError as exc:
            raise ApiError(f"cannot reach AdGuard at {self.base}: {exc.reason}") \
                from None
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def rewrites(self):
        reply = self.call("rewrite/list")
        return reply if isinstance(reply, list) else []

    def find_rewrite(self, domain):
        return next((entry for entry in self.rewrites()
                     if str(entry.get("domain", "")).lower() == domain.lower()), None)

    def add_rewrite(self, domain, answer):
        self.call("rewrite/add", {"domain": domain, "answer": answer})

    def delete_rewrite(self, domain, answer):
        self.call("rewrite/delete", {"domain": domain, "answer": answer})

    def rewrite_map(self):
        """Every rewrite as ``{domain: answer}``, for looking many names up."""
        return as_rewrite_map(self.rewrites())


def as_rewrite_map(entries):
    """``{domain: answer}`` for a list that has already been read.

    The listing tab reads the rewrites whole -- domain *and* answer, one row
    per entry -- and the host list next door wants the same reading as a
    lookup table. Two calls to AdGuard for one question would be one too many.
    """
    return {str(entry.get("domain", "")).lower(): str(entry.get("answer", ""))
            for entry in entries}


def set_rewrite(adguard, host, target):
    """Make the rewrite for ``host`` answer with ``target``.

    AdGuard has no update call, so a rewrite pointing somewhere else has to be
    deleted and written again. Returns what happened, for the log.
    """
    existing = adguard.find_rewrite(host)
    if existing is not None:
        previous = str(existing.get("answer", ""))
        if previous == target:
            return "unchanged"
        adguard.delete_rewrite(host, previous)
        adguard.add_rewrite(host, target)
        return "changed"
    adguard.add_rewrite(host, target)
    return "added"


def clear_rewrite(adguard, host):
    """Remove the rewrite for ``host``, if there is one."""
    existing = adguard.find_rewrite(host)
    if existing is None:
        return "missing"
    adguard.delete_rewrite(host, str(existing.get("answer", "")))
    return "removed"


def adguard_from_config(config, overrides=None):
    """Build an AdGuard client from the config file, or None when unconfigured.

    Returns ``(client, settings)``; ``settings["error"]`` is set instead of
    raising when the address is unusable, so a UI can say so and carry on.
    The connection's ``haproxy_ip`` is what the rewrites answer with unless the
    AdGuard section names a target of its own.
    """
    settings = dict(config.get("adguard") or {})
    settings.update({k: v for k, v in (overrides or {}).items() if v})
    if not settings.get("target"):
        settings["target"] = str(config.get("haproxy_ip") or "").strip()
    if not settings.get("url"):
        return None, settings
    try:
        client = AdGuard(settings["url"], settings.get("username", ""),
                         settings.get("password", ""),
                         verify=settings.get("verify_ssl", True))
    except UsageError as exc:
        settings["error"] = str(exc)
        return None, settings
    return client, settings


def link_actions(client, frontend_uuid, action_uuids):
    """Rewrite only a frontend's rule list, leaving every other field alone.

    setFrontend applies exactly the fields it is given (BaseField::setNodes
    skips keys that are absent), so there is no need to read the frontend and
    write it back whole -- and no way to do that safely either: several field
    types report something on GET that they do not accept on POST, which the
    API answers with a 500.
    """
    client.update("frontend", frontend_uuid,
                  {"linkedActions": ",".join(action_uuids)})


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------


def slug(text, allow_dots=True):
    """Reduce a string to what the plugin's name masks accept."""
    keep = r"0-9a-zA-Z._\-" if allow_dots else r"0-9a-zA-Z_\-"
    cleaned = re.sub(rf"[^{keep}]", "_", text)
    return re.sub(r"_+", "_", cleaned).strip("_")


class Names:
    """The object names derived from one host (plus optional path).

    Server and backend names may contain dots, condition and rule names may
    not -- the plugin's validation masks differ, so two variants are kept.
    """

    def __init__(self, host, path, prefix=""):
        base = f"{host}{path}"
        self.prefix = prefix or ""
        self.dotted = slug(base, allow_dots=True)
        self.plain = slug(base, allow_dots=False)

    @property
    def server(self):
        return f"{self.prefix}srv_{self.dotted}"

    @property
    def backend(self):
        return f"{self.prefix}be_{self.dotted}"

    @property
    def acl_host(self):
        return f"{self.prefix}acl_{self.plain}"

    @property
    def acl_path(self):
        return f"{self.prefix}acl_{self.plain}_path"

    @property
    def action(self):
        return f"{self.prefix}rule_{self.plain}"


def parse_target(raw):
    """Accept ``host``, ``https://host`` or ``https://host/path`` alike."""
    text = raw.strip()
    text = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", text)
    host, _, path = text.partition("/")
    host = host.split("@")[-1].split(":")[0].lower()
    if not host or not re.fullmatch(r"[0-9a-zA-Z._\-]+", host):
        raise UsageError(f"'{raw}' does not contain a usable hostname")
    path = ("/" + path.strip("/")) if path.strip("/") else ""
    return host, path


# --------------------------------------------------------------------------
# Provisioning
# --------------------------------------------------------------------------


def pick_frontend(client, wanted):
    rows = client.search("frontend")
    if not rows:
        raise UsageError("this OPNsense has no public service (frontend) yet")
    if wanted:
        for row in rows:
            if row.get("name") == wanted:
                return client.get("frontend", row["uuid"]), row["uuid"], row["name"]
        known = ", ".join(sorted(r.get("name", "?") for r in rows))
        raise UsageError(f"no public service named '{wanted}' (have: {known})")
    if len(rows) > 1:
        # Several listeners, and usually only one of them is the HTTPS entrance
        # everything arrives at -- the others send browsers to it or serve
        # something internal. Asking is only worth it when that is not clear.
        https = [row for row in rows
                 if serves_https({"bind": ", ".join(selected_values(
                     client.get("frontend", row["uuid"]).get("bind")))})]
        if len(https) != 1:
            known = ", ".join(sorted(r.get("name", "?") for r in rows))
            raise UsageError(
                f"several public services exist -- pick one with --frontend "
                f"(have: {known})")
        rows = https
    return client.get("frontend", rows[0]["uuid"]), rows[0]["uuid"], rows[0]["name"]


def selected_value(field):
    """Read the selected key out of an option/relation field of a get* reply."""
    if isinstance(field, dict):
        for key, value in field.items():
            if str(value.get("selected", 0)) == "1":
                return key
        return ""
    return field or ""


def selected_values(field):
    if isinstance(field, dict):
        return [k for k, v in field.items() if str(v.get("selected", 0)) == "1"]
    return [v for v in str(field or "").split(",") if v]


def option_list(field):
    """Every choice an option or relation field offers, as id and label."""
    if not isinstance(field, dict):
        return []
    choices = []
    for key, value in field.items():
        label = value.get("value", key) if isinstance(value, dict) else str(value)
        choices.append({"id": key, "name": str(label)})
    return choices


def provision(client, opts, out=print, adguard=None):
    base = (getattr(opts, "base_domain", "") or "").strip().strip(".")
    host, path = parse_target(with_base(opts.target, base))
    if base:
        host = build_fqdn(host, base)
    names = Names(host, path, opts.prefix)

    frontend, frontend_uuid, frontend_name = pick_frontend(client, opts.frontend)
    frontend_mode = selected_value(frontend.get("mode")) or "http"
    sni_mode = frontend_mode in SNI_MODES

    if path and sni_mode:
        raise UsageError(
            f"public service '{frontend_name}' runs in {frontend_mode} mode and cannot "
            "match on a path -- drop the path from the URL"
        )

    backend_mode = opts.backend_mode or ("tcp" if sni_mode else "http")
    port = opts.port if opts.port else (443 if opts.ssl else 80)

    healthcheck_uuid = ""
    if opts.healthcheck:
        row = client.find("healthcheck", opts.healthcheck)
        if row is None:
            raise UsageError(f"no health monitor named '{opts.healthcheck}'")
        healthcheck_uuid = row["uuid"]

    dns_target = (getattr(opts, "dns_target", "") or "").strip()
    want_dns = bool(adguard and dns_target)

    label = f"{host}{path}"
    out(f"public service : {frontend_name} (mode {frontend_mode})")
    out(f"match          : {'SNI' if sni_mode else 'Host header'} == {host}"
        + (f" and path starts with {path}" if path else ""))
    out(f"real server    : {opts.ip}:{port} ({'ssl' if opts.ssl else 'plain'}"
        + (", verify cert" if opts.ssl and opts.ssl_verify else "")
        + f", mode {backend_mode})")
    if base:
        out(f"base domain    : {base}")
    if want_dns:
        out(f"dns rewrite    : {host} -> {dns_target}")
    else:
        # Said rather than skipped in silence. A host created without its DNS
        # entry resolves nowhere, and the only thing worse than that is a log
        # that does not mention DNS at all -- there is nothing to search for.
        out("dns rewrite    : none -- " + ("no AdGuard for this connection"
                                           if not adguard else
                                           "no target address for AdGuard"))
    out("objects        : "
        + ", ".join([names.server, names.backend, names.acl_host]
                    + ([names.acl_path] if path else [])
                    + [names.action]))

    if base:
        entry = next((d for d in base_domains(client)
                      if d["domain"] == base.lower()), None)
        if entry is None:
            out(f"warning        : no ACME certificate lists {base}",
                file=sys.stderr)
        elif not covered_by(entry, host):
            out(f"warning        : certificate '{entry['certificate']}' does not "
                f"cover {host} -- HTTPS will show a name mismatch",
                file=sys.stderr)

    clashes = [
        f"{what} '{name}'"
        for kind, what, name in (
            ("server", "real server", names.server),
            ("backend", "backend pool", names.backend),
            ("acl", "condition", names.acl_host),
            ("action", "rule", names.action),
        )
        if client.find(kind, name)
    ]
    if clashes:
        raise UsageError(
            "already provisioned (" + ", ".join(clashes) + ") -- "
            f"use `remove {host}{path}` first if you want to recreate it"
        )

    if opts.dry_run:
        out("\ndry run -- nothing was changed")
        return 0

    created = []  # (kind, uuid) in creation order, for rollback
    try:
        server_uuid = client.add("server", {
            "enabled": "1",
            "name": names.server,
            "description": f"managed: {label}",
            "address": opts.ip,
            "port": str(port),
            "mode": "active",
            "type": "static",
            "ssl": "1" if opts.ssl else "0",
            "sslVerify": "1" if (opts.ssl and opts.ssl_verify) else "0",
        })
        created.append(("server", server_uuid))
        out(f"+ real server   {names.server}")

        backend_body = {
            "enabled": "1",
            "name": names.backend,
            "description": f"managed: {label}",
            "mode": backend_mode,
            "linkedServers": server_uuid,
            "healthCheckEnabled": "1" if healthcheck_uuid else "0",
            "healthCheck": healthcheck_uuid,
        }
        if backend_mode == "http":
            backend_body["forwardFor"] = "1" if opts.forward_for else "0"
        backend_uuid = client.add("backend", backend_body)
        created.append(("backend", backend_uuid))
        out(f"+ backend pool  {names.backend}")

        acl_uuids = []
        if sni_mode:
            host_acl = {"name": names.acl_host, "expression": "ssl_sni", "ssl_sni": host}
        else:
            host_acl = {"name": names.acl_host, "expression": "hdr", "hdr": host}
        host_acl["description"] = f"managed: {label}"
        acl_uuid = client.add("acl", host_acl)
        created.append(("acl", acl_uuid))
        acl_uuids.append(acl_uuid)
        out(f"+ condition     {names.acl_host}")

        if path:
            path_uuid = client.add("acl", {
                "name": names.acl_path,
                "description": f"managed: {label}",
                "expression": "path_beg",
                "path_beg": path,
            })
            created.append(("acl", path_uuid))
            acl_uuids.append(path_uuid)
            out(f"+ condition     {names.acl_path}")

        action_uuid = client.add("action", {
            "enabled": "1",
            "name": names.action,
            "description": f"managed: {label}",
            "testType": "if",
            "operator": "and",
            "linkedAcls": ",".join(acl_uuids),
            "type": "use_backend",
            "use_backend": backend_uuid,
        })
        created.append(("action", action_uuid))
        out(f"+ rule          {names.action}")

        linked = selected_values(frontend.get("linkedActions"))
        link_actions(client, frontend_uuid, linked + [action_uuid])
        created.append(("link", (frontend_uuid, linked)))
        out(f"+ linked rule into public service '{frontend_name}'")

        if want_dns:
            existing = adguard.find_rewrite(host)
            if existing is None:
                adguard.add_rewrite(host, dns_target)
                created.append(("dns", (host, dns_target)))
                out(f"+ dns rewrite   {host} -> {dns_target}")
            elif str(existing.get("answer", "")) == dns_target:
                out(f"= dns rewrite   {host} -> {dns_target} (already there)")
            else:
                out(f"! dns rewrite   {host} already points at "
                    f"{existing.get('answer')} -- left untouched", file=sys.stderr)
    except Exception:
        out("\nsomething went wrong -- rolling back", file=sys.stderr)
        rollback(client, created, out, adguard)
        raise

    return apply_changes(client, opts, out)


# --------------------------------------------------------------------------
# Listeners: a public service of one's own
# --------------------------------------------------------------------------

# What a listener may be. "tcp" is the one this is for: HAProxy answers on a
# port, does the TLS there and hands the connection on as it is. "ssl" looks
# at the SNI and passes the handshake through untouched, "http" is the usual
# web entrance -- both are offered because the plugin has them, and a listener
# built here can be any of the three.
LISTEN_MODES = ("tcp", "http", "ssl")


class ListenerNames:
    """The object names of a listener and the pool behind it."""

    def __init__(self, name, prefix=""):
        self.prefix = prefix or ""
        self.dotted = slug(name, allow_dots=True)
        self.plain = slug(name, allow_dots=False)

    @property
    def frontend(self):
        # the listener carries the name it was given: it is what the host list
        # and OPNsense's own overview show as the public service
        return f"{self.prefix}{self.plain}"

    @property
    def server(self):
        return f"{self.prefix}srv_{self.dotted}"

    @property
    def backend(self):
        return f"{self.prefix}be_{self.dotted}"


def certificate_host(label, name="", domains=()):
    """The public name a certificate suggests for a listener called ``name``.

    A certificate is the one place that already knows which name the outside
    world may use: it is the whole point of having one. A wildcard leaves the
    first label open, so the listener's own name goes there; a certificate for
    exactly one name *is* the answer and the listener's name has no say.

    ``domains`` is what the ACME client reports, where a wildcard is known as
    such rather than guessed from the way the certificate is labelled.
    """
    found = re.search(r"\*?[a-z0-9_\-]+(?:\.[a-z0-9_\-]+)+", str(label).lower())
    if not found:
        return ""
    host = found.group(0)
    base = host[2:] if host.startswith("*.") else host
    wildcard = host.startswith("*.")
    for entry in domains or ():
        if entry.get("domain") == base:
            wildcard = wildcard or entry.get("wildcard", False)
            break
    if not wildcard:
        return host  # it covers this one name; there is nothing to add to it
    label = slug(name, allow_dots=False).strip("-_").lower()
    return f"{label}.{base}" if label else base


def listen_bind(address, port):
    """One bind entry, with an IPv6 address in the brackets it needs."""
    address = str(address or "").strip() or "0.0.0.0"
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    return f"{address}:{port}"


def listener_choices(client):
    """What a new listener can be offered, read from the plugin itself.

    Certificates are referred to by a refid that means nothing on its own, so
    the list has to come from the firewall. The empty add form carries it;
    should a plugin version answer that one differently, an existing frontend
    holds the same field and does just as well.
    """
    try:
        record = client.blank("frontend")
    except ApiError:
        record = {}
    if not record.get("ssl_certificates"):
        rows = client.search("frontend")
        if rows:
            record = client.get("frontend", rows[0]["uuid"])
    return {"certificates": option_list(record.get("ssl_certificates")),
            "modes": [choice for choice in option_list(record.get("mode"))
                      if choice["id"] in LISTEN_MODES]}


def verify_frontend(client, uuid, wanted):
    """Read a freshly written listener back and insist it says what we sent.

    The plugin applies the fields it is given and quietly ignores the rest, so
    a name it does not know costs no error -- it costs a listener on the wrong
    port, or in the wrong mode, found weeks later. Reading it back turns that
    into something to say now, while there is still a rollback to do.
    """
    written = client.get("frontend", uuid)
    problems = []
    if selected_value(written.get("mode")) != wanted["mode"]:
        problems.append(f"mode is {selected_value(written.get('mode')) or '?'}, "
                        f"not {wanted['mode']}")
    bound = ", ".join(selected_values(written.get("bind")))
    if wanted["bind"] not in bound:
        problems.append(f"listens on {bound or 'nothing'}, not {wanted['bind']}")
    if selected_value(written.get("defaultBackend")) != wanted["backend"]:
        problems.append("the backend pool did not stick")
    if wanted["certificate"] and wanted["certificate"] not in selected_values(
            written.get("ssl_certificates")):
        problems.append("the certificate did not stick")
    if problems:
        raise ApiError("the listener was not stored as asked: "
                       + "; ".join(problems))


def provision_listener(client, opts, out=print, adguard=None):
    """A public service of its own, with the pool and the server behind it.

    What ``provision`` hangs into an existing entrance, this builds from the
    ground up: HAProxy answers on a port of its own, ends the TLS there with a
    certificate that the outside world trusts, and speaks to the service
    inside the way that service wants to be spoken to -- plainly, or with a
    self-signed certificate nobody has to trust but HAProxy.

    That is what a TURN server, an IMAP server or a database has instead of a
    web entrance: no Host header to match on, no path, just a port.
    """
    name = (getattr(opts, "name", "") or "").strip()
    if not name:
        raise UsageError("a listener needs a name")
    names = ListenerNames(name, getattr(opts, "prefix", ""))
    if not names.frontend:
        raise UsageError(f"'{name}' leaves nothing usable as a name")

    port = _port_number(getattr(opts, "port", None), "the public port")
    backend_port = _port_number(getattr(opts, "backend_port", None)
                                or port, "the port inside")
    mode = (getattr(opts, "mode", "") or "tcp").lower()
    if mode not in LISTEN_MODES:
        raise UsageError(f"'{mode}' is not a mode ({', '.join(LISTEN_MODES)})")
    if not (getattr(opts, "ip", "") or "").strip():
        raise UsageError("the listener needs the address of the server behind it")
    ip = opts.ip.strip()
    certificate = (getattr(opts, "certificate", "") or "").strip()
    cert_label = (getattr(opts, "certificate_name", "") or certificate)
    bind = listen_bind(getattr(opts, "address", ""), port)

    host = (getattr(opts, "host", "") or "").strip().lower().rstrip(".")
    dns_target = (getattr(opts, "dns_target", "") or "").strip()
    want_dns = bool(adguard and dns_target and host)

    out(f"public service : {names.frontend} on {bind} (mode {mode})")
    out("tls            : " + (f"ends here, certificate {cert_label}"
                               if certificate else
                               "none -- passed on as it arrives"))
    out(f"real server    : {ip}:{backend_port} "
        + ("ssl" if getattr(opts, "ssl", False) else "plain")
        + (", verify cert" if getattr(opts, "ssl", False)
           and getattr(opts, "ssl_verify", False) else ""))
    if want_dns:
        out(f"dns rewrite    : {host} -> {dns_target}")
    elif host:
        out("dns rewrite    : none -- " + ("no AdGuard for this connection"
                                           if not adguard else
                                           "no target address for AdGuard"))
    out(f"objects        : {names.server}, {names.backend}, {names.frontend}")

    if mode != "tcp" and certificate:
        out(f"note           : {mode} mode with a certificate ends the TLS "
            "here as well", file=sys.stderr)
    if not certificate:
        out("note           : without a certificate this listener only "
            "forwards; the service behind it needs its own TLS",
            file=sys.stderr)

    clashes = [f"{what} '{obj}'"
               for kind, what, obj in (("server", "real server", names.server),
                                       ("backend", "backend pool", names.backend),
                                       ("frontend", "public service",
                                        names.frontend))
               if client.find(kind, obj)]
    if clashes:
        raise UsageError("already there (" + ", ".join(clashes)
                         + ") -- pick another name or remove it in OPNsense")
    taken = [row.get("name", "?") for row in client.search("frontend")
             if str(port) in bind_ports(", ".join(selected_values(
                 client.get("frontend", row["uuid"]).get("bind"))))]
    if taken:
        raise UsageError(f"port {port} is already taken by public service "
                         f"'{taken[0]}'")

    if getattr(opts, "dry_run", False):
        out("\ndry run -- nothing was changed")
        return 0

    created = []
    try:
        server_uuid = client.add("server", {
            "enabled": "1",
            "name": names.server,
            "description": f"managed: {name}",
            "address": ip,
            "port": str(backend_port),
            "mode": "active",
            "type": "static",
            "ssl": "1" if getattr(opts, "ssl", False) else "0",
            "sslVerify": "1" if (getattr(opts, "ssl", False)
                                 and getattr(opts, "ssl_verify", False)) else "0",
        })
        created.append(("server", server_uuid))
        out(f"+ real server   {names.server}")

        backend_uuid = client.add("backend", {
            "enabled": "1",
            "name": names.backend,
            "description": f"managed: {name}",
            # A pool behind a listener speaks the listener's language. In http
            # mode that is http, in the other two it is a stream of bytes.
            "mode": "http" if mode == "http" else "tcp",
            "linkedServers": server_uuid,
            "healthCheckEnabled": "0",
        })
        created.append(("backend", backend_uuid))
        out(f"+ backend pool  {names.backend}")

        frontend_uuid = client.add("frontend", {
            "enabled": "1",
            "name": names.frontend,
            # The DNS name goes into the description because there is nowhere
            # else to put it: OPNsense knows nothing about AdGuard, and when
            # this listener is taken away again the rewrite has to go with it.
            "description": f"managed: {name}"
                           + (f" dns={host}" if want_dns else ""),
            "bind": bind,
            "mode": mode,
            "defaultBackend": backend_uuid,
            "ssl_enabled": "1" if certificate else "0",
            "ssl_certificates": certificate,
        })
        created.append(("frontend", frontend_uuid))
        out(f"+ public service {names.frontend}")
        verify_frontend(client, frontend_uuid,
                        {"mode": mode, "bind": bind, "backend": backend_uuid,
                         "certificate": certificate})

        if want_dns:
            existing = adguard.find_rewrite(host)
            if existing is None:
                adguard.add_rewrite(host, dns_target)
                created.append(("dns", (host, dns_target)))
                out(f"+ dns rewrite   {host} -> {dns_target}")
            elif str(existing.get("answer", "")) == dns_target:
                out(f"= dns rewrite   {host} -> {dns_target} (already there)")
            else:
                out(f"! dns rewrite   {host} already points at "
                    f"{existing.get('answer')} -- left untouched", file=sys.stderr)
    except Exception:
        out("\nsomething went wrong -- rolling back", file=sys.stderr)
        rollback(client, created, out, adguard)
        raise

    return apply_changes(client, opts, out)


def listener_dns(description):
    """The DNS name a listener was created with, out of its description."""
    found = re.search(r"dns=(\S+)", str(description or ""))
    return found.group(1).lower() if found else ""


def _users_of_backend(client, backend_uuid, without_frontend=""):
    """Who else sends traffic to this pool -- by name, for a sentence."""
    users = []
    for row in client.search("frontend"):
        if row["uuid"] == without_frontend:
            continue
        frontend = client.get("frontend", row["uuid"])
        if selected_value(frontend.get("defaultBackend")) == backend_uuid:
            users.append(f"public service '{row.get('name')}'")
    for row in client.search("action"):
        action = client.get("action", row["uuid"])
        if selected_value(action.get("use_backend")) == backend_uuid:
            users.append(f"rule '{row.get('name')}'")
    return users


def _users_of_server(client, server_uuid, without_backend=""):
    """Which other pools this server is in."""
    users = []
    for row in client.search("backend"):
        if row["uuid"] == without_backend:
            continue
        backend = client.get("backend", row["uuid"])
        if server_uuid in selected_values(backend.get("linkedServers")):
            users.append(f"backend pool '{row.get('name')}'")
    return users


def deprovision_listener(client, opts, out=print, adguard=None):
    """Take a public service away again, with the pool and servers behind it.

    Only what nothing else is using: a pool that a rule still points at, or a
    server that stands in a second pool, is left where it is and said so. A
    listener with rules hanging in it is not touched at all -- those rules
    would keep working and answer nowhere, which is worse than refusing.
    """
    name = (getattr(opts, "name", "") or "").strip()
    row = client.find("frontend", name)
    if row is None:
        out(f"no public service named '{name}'")
        return 0
    frontend = client.get("frontend", row["uuid"])
    bind = ", ".join(selected_values(frontend.get("bind")))

    linked = selected_values(frontend.get("linkedActions"))
    if linked:
        rules = []
        for uuid in linked[:3]:
            try:
                rules.append(client.get("action", uuid).get("name", uuid))
            except ApiError:
                rules.append(uuid)
        more = f" and {len(linked) - 3} more" if len(linked) > 3 else ""
        raise UsageError(
            f"'{name}' still carries {len(linked)} rule(s): "
            + ", ".join(rules) + more
            + " -- remove those hosts first, or unlink them in OPNsense")

    doomed = [("frontend", name, row["uuid"])]
    keep = []
    backend_uuid = selected_value(frontend.get("defaultBackend"))
    if backend_uuid:
        try:
            backend = client.get("backend", backend_uuid)
        except ApiError:
            backend = None
        if backend is not None:
            users = _users_of_backend(client, backend_uuid, row["uuid"])
            if users:
                keep.append(f"backend pool '{backend.get('name')}' "
                            f"(still used by {users[0]})")
            else:
                doomed.append(("backend", backend.get("name", ""), backend_uuid))
                for server_uuid in selected_values(backend.get("linkedServers")):
                    try:
                        server = client.get("server", server_uuid)
                    except ApiError:
                        continue
                    others = _users_of_server(client, server_uuid, backend_uuid)
                    if others:
                        keep.append(f"real server '{server.get('name')}' "
                                    f"(still in {others[0]})")
                    else:
                        doomed.append(("server", server.get("name", ""),
                                       server_uuid))

    host = (getattr(opts, "host", "") or "").strip().lower() \
        or listener_dns(frontend.get("description"))
    rewrite = adguard.find_rewrite(host) if (adguard and host) else None

    label = {"frontend": "public service", "backend": "backend pool",
             "server": "real server"}
    out(f"public service : {name} on {bind or '?'}")
    for kind, obj, _ in doomed:
        out(f"will delete {label[kind]:14s} {obj}")
    if rewrite is not None:
        out(f"will delete {'dns rewrite':14s} {host} -> {rewrite.get('answer')}")
    elif host:
        out(f"dns rewrite    : {host} -- " + ("not in AdGuard" if adguard
                                              else "no AdGuard for this "
                                                   "connection"))
    for line in keep:
        out(f"keeping        : {line}")
    if getattr(opts, "dry_run", False):
        out("\ndry run -- nothing was changed")
        return 0
    if not getattr(opts, "yes", False) and not confirm("delete these objects?"):
        out("aborted")
        return 1

    # the listener goes first: nothing may point at a pool that is about to
    # be deleted, or the plugin refuses the delete and leaves half of it
    for kind, obj, uuid in doomed:
        client.delete(kind, uuid)
        out(f"- deleted {label[kind]} {obj}")
    if rewrite is not None:
        adguard.delete_rewrite(host, str(rewrite.get("answer", "")))
        out(f"- deleted dns rewrite {host}")

    return apply_changes(client, opts, out)


def _port_number(value, what="the port"):
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise UsageError(f"{what} has to be a number") from None
    if not 1 <= port <= 65535:
        raise UsageError(f"{port} is not a port ({what})")
    return port


def rollback(client, created, out, adguard=None):
    for kind, ref in reversed(created):
        try:
            if kind == "dns":
                if adguard:
                    adguard.delete_rewrite(*ref)
                    out(f"- removed dns rewrite {ref[0]}", file=sys.stderr)
            elif kind == "link":
                frontend_uuid, previous = ref
                link_actions(client, frontend_uuid, previous)
                out("- unlinked rule from public service", file=sys.stderr)
            else:
                client.delete(kind, ref)
                out(f"- removed {kind} {ref}", file=sys.stderr)
        except ApiError as exc:
            out(f"! could not undo {kind} {ref}: {exc}", file=sys.stderr)


def apply_changes(client, opts, out):
    if opts.no_apply:
        out("\nsaved but not applied -- run `apply` when you are ready")
        return 0
    out("\nchecking configuration ...")
    report = client.configtest()
    lowered = report.lower()
    # haproxy -c prints ALERT/EMERG lines and "Fatal errors" when it refuses a
    # config, and "Configuration file is valid" when it accepts one.
    if any(marker in lowered for marker in ("[alert]", "[emerg]", "fatal errors")):
        out(report.strip() or "(no output)", file=sys.stderr)
        out("config test failed -- not reloading HAProxy", file=sys.stderr)
        return 1
    valid = "configuration file is valid" in lowered
    if not valid:
        # Nothing came back at all on some plugin versions. That is not a
        # refusal -- a refusal is loud -- but it is no confirmation either, and
        # saying "configuration is valid" here would be inventing one.
        out("warning: the configuration test said nothing" if not report.strip()
            else f"warning: unexpected config test output: {report.strip()[:200]}",
            file=sys.stderr)
    for line in report.splitlines():
        if "[warning]" in line.lower():
            out(f"  {line.strip()}")
    out("configuration is valid, reloading HAProxy ..." if valid
        else "reloading HAProxy ...")
    reply = client.reconfigure()
    if reply.get("status", "ok").lower() not in ("ok", "done"):
        out(f"reload reported: {json.dumps(reply)}", file=sys.stderr)
        return 1
    out("done")
    return 0


def deprovision(client, opts, out=print, adguard=None):
    base = (getattr(opts, "base_domain", "") or "").strip().strip(".")
    host, path = parse_target(with_base(opts.target, base))
    if base:
        host = build_fqdn(host, base)
    names = Names(host, path, opts.prefix)

    targets = [
        ("action", names.action),
        ("acl", names.acl_host),
        ("acl", names.acl_path),
        ("backend", names.backend),
        ("server", names.server),
    ]
    found = []
    for kind, name in targets:
        row = client.find(kind, name)
        if row:
            found.append((kind, name, row["uuid"]))

    rewrite = adguard.find_rewrite(host) if adguard else None

    if not found and rewrite is None:
        out(f"nothing found for {host}{path}")
        return 0

    label = {"action": "rule", "acl": "condition", "backend": "backend pool",
             "server": "real server"}
    for kind, name, _ in found:
        out(f"will delete {label[kind]:14s} {name}")
    if rewrite is not None:
        out(f"will delete {'dns rewrite':14s} {host} -> {rewrite.get('answer')}")
    if opts.dry_run:
        out("\ndry run -- nothing was changed")
        return 0
    if not opts.yes and not confirm("delete these objects?"):
        out("aborted")
        return 1

    action_uuids = {uuid for kind, _, uuid in found if kind == "action"}
    if action_uuids:
        for row in client.search("frontend"):
            frontend = client.get("frontend", row["uuid"])
            linked = selected_values(frontend.get("linkedActions"))
            remaining = [u for u in linked if u not in action_uuids]
            if len(remaining) != len(linked):
                link_actions(client, row["uuid"], remaining)
                out(f"- unlinked rule from public service '{row.get('name')}'")

    for kind, name, uuid in found:
        client.delete(kind, uuid)
        out(f"- deleted {label[kind]} {name}")

    if rewrite is not None:
        adguard.delete_rewrite(host, str(rewrite.get("answer", "")))
        out(f"- deleted dns rewrite {host}")

    return apply_changes(client, opts, out)


class LogRecorder:
    """Captures the lines provision/deprovision would have printed.

    Each entry is ``{"text": ..., "level": "info"|"error"}`` so a UI can colour
    them the way the terminal does.
    """

    def __init__(self):
        self.lines = []

    def __call__(self, *parts, file=None):
        text = " ".join(str(part) for part in parts)
        level = "error" if file is sys.stderr else "info"
        for line in text.split("\n"):
            self.lines.append({"text": line, "level": level})


def run_step(operation, client, opts, adguard=None, log=None):
    """Run provision/deprovision and return its log even when it fails.

    The rollback messages are the interesting part of a failure, so they have
    to survive into the result instead of being replaced by the exception.
    Pass ``log`` to watch the lines arrive while the work is still running.
    """
    log = log if log is not None else LogRecorder()
    try:
        code = operation(client, opts, out=log, adguard=adguard)
    except (UsageError, ApiError) as exc:
        return {"ok": False, "error": str(exc), "log": log.lines,
                "dry_run": getattr(opts, "dry_run", False)}
    return {"ok": code == 0, "error": None, "log": log.lines,
            "dry_run": getattr(opts, "dry_run", False)}


def derive_path(conditions):
    return next((str(c["value"]) for c in conditions
                 if c["expression"] == "path_beg"), "")


def derive_host(conditions):
    """The name a browser would ask for, however the rule happens to match it.

    ``hdr_beg`` is in here because rules clicked together by hand often use it,
    and one of those still points at a host worth opening -- but only when it
    holds a whole name, not just the ``wiki`` of a ``wiki.*`` prefix match.
    """
    for wanted in ("hdr", "ssl_sni", "hdr_beg"):
        for condition in conditions:
            value = str(condition["value"] or "")
            if condition["expression"] == wanted and "." in value:
                return value
    return None


def derive_target(conditions):
    """The host (plus path) a rule matches, so it can be removed again.

    Only an exact match counts: ``remove`` looks the objects up by the names
    they would have been given, and a prefix match was never one of ours.
    """
    host = next((c["value"] for c in conditions
                 if c["expression"] in ("hdr", "ssl_sni")), None)
    if not host:
        return None
    return f"{host}{derive_path(conditions)}"


# The port that makes a public service the one a browser talks to. Everything
# else a place has listening -- 80 for the redirect, some port for an internal
# service -- is not where a new host belongs.
HTTPS_PORT = "443"


def bind_ports(bind):
    """Every port a public service listens on, in the order they are bound.

    A frontend can hold several addresses -- "0.0.0.0:443, [::]:443" is the
    usual pair, and a place with an extra address adds to it. The IPv6 form is
    why the port is taken from behind the last colon.
    """
    ports = []
    for entry in str(bind or "").split(","):
        text = entry.strip()
        port = text.rsplit(":", 1)[-1] if ":" in text else ""
        if port.isdigit() and port not in ports:
            ports.append(port)
    return ports


def bind_port(bind):
    """The port a public service answers on, or "" when it cannot be read."""
    found = bind_ports(bind)
    return found[0] if found else ""


def serves_https(service):
    """Whether this is the public service a browser reaches over HTTPS.

    The one that matters when a host is created: a place with more than one
    listener usually has a second on port 80 whose whole job is to send
    browsers to this one, and a rule hung into that one is never what anybody
    meant.
    """
    return HTTPS_PORT in bind_ports((service or {}).get("bind"))


def public_url(service, host, path=""):
    """The address a browser would use to reach a rule's host.

    A public service on 80 is plain HTTP, everything else is HTTPS -- that is
    what these frontends are for. A port other than the two default ones has to
    be part of the address, or the link goes somewhere else entirely.
    """
    if not host:
        return ""
    port = bind_port(service.get("bind"))
    scheme = "http" if port == "80" else "https"
    suffix = "" if port in ("", "80", "443") else f":{port}"
    return f"{scheme}://{host}{suffix}{path or ''}"


def inventory(client):
    """Collect every public service with the rules, pools and servers behind it."""
    services = []
    for row in sorted(client.search("frontend"), key=lambda r: r.get("name", "")):
        frontend = client.get("frontend", row["uuid"])
        # A listener without rules is not an empty listener: it may send
        # everything that arrives to one pool, which is what a port for one
        # service looks like. Reading it is the difference between "nothing
        # here" and "everything here goes to 192.168.1.40".
        default_uuid = selected_value(frontend.get("defaultBackend"))
        services.append({
            "uuid": row["uuid"],
            "name": row.get("name", ""),
            "mode": selected_value(frontend.get("mode")) or "http",
            "tls": str(frontend.get("ssl_enabled", "0")) == "1",
            "default": _read_backend(client, default_uuid) if default_uuid
                       else None,
            "managed": str(frontend.get("description", "")).startswith("managed:"),
            "dns": listener_dns(frontend.get("description")),
            # bind arrives as an option map on newer plugin versions and as a
            # plain string on older ones; both end up as "addr:port, addr:port"
            "bind": ", ".join(selected_values(frontend.get("bind"))),
            "enabled": str(frontend.get("enabled", "1")) == "1",
            "rules": [_read_rule(client, uuid)
                      for uuid in selected_values(frontend.get("linkedActions"))],
        })
    return services


def _read_rule(client, action_uuid):
    rule = {"uuid": action_uuid, "name": "", "type": "", "conditions": [],
            "backend": None, "target": None, "host": None, "path": ""}
    try:
        action = client.get("action", action_uuid)
    except ApiError:
        rule["name"] = f"(unreadable rule {action_uuid})"
        return rule

    rule["name"] = action.get("name", "")
    rule["type"] = selected_value(action.get("type"))
    for acl_uuid in selected_values(action.get("linkedAcls")):
        try:
            acl = client.get("acl", acl_uuid)
        except ApiError:
            continue
        expression = selected_value(acl.get("expression"))
        rule["conditions"].append({"expression": expression,
                                   "value": acl.get(expression, "")})
    rule["host"] = derive_host(rule["conditions"])
    rule["path"] = derive_path(rule["conditions"])
    rule["target"] = derive_target(rule["conditions"])

    backend_uuid = selected_value(action.get("use_backend"))
    if backend_uuid:
        rule["backend"] = _read_backend(client, backend_uuid)
    return rule


def _read_backend(client, uuid):
    """One pool with the servers in it, or None when it cannot be read."""
    try:
        backend = client.get("backend", uuid)
    except ApiError:
        return None
    pool = {"name": backend.get("name", ""),
            "mode": selected_value(backend.get("mode")), "servers": []}
    for server_uuid in selected_values(backend.get("linkedServers")):
        try:
            server = client.get("server", server_uuid)
        except ApiError:
            continue
        pool["servers"].append({
            "name": server.get("name", ""),
            "address": server.get("address", ""),
            "port": server.get("port", ""),
            "ssl": str(server.get("ssl", "0")) == "1",
        })
    return pool


def show(client, opts, out=print):
    """Print each public service with the rules and pools behind it."""
    services = inventory(client)
    if not services:
        out("no public services configured")
        return 0
    for service in services:
        state = "" if service["enabled"] else "  [disabled]"
        out(f"\n{service['name']}  ({service['mode']}, "
            f"bind {service['bind'] or '?'}){state}")
        if not service["rules"]:
            out("    (no rules)")
        for rule in service["rules"]:
            if rule["backend"] is None:
                out(f"    {rule['name']}  ->  {rule['type'] or '?'}")
                continue
            conditions = " & ".join(f"{c['expression']}={c['value']}"
                                    for c in rule["conditions"])
            out(f"    {rule['name']}  [{conditions}]")
            out(f"        pool {rule['backend']['name']} "
                f"({rule['backend']['mode']})")
            for server in rule["backend"]["servers"]:
                scheme = "https" if server["ssl"] else "http"
                out(f"        -> {server['name']}  "
                    f"{scheme}://{server['address']}:{server['port']}")
    return 0


def show_domains(client, opts, out=print):
    """List the base domains the ACME certificates make available."""
    entries = base_domains(client)
    if not entries:
        out("no ACME certificates found")
        return 0
    for entry in entries:
        kind = "wildcard" if entry["wildcard"] else "exact"
        out(f"{entry['domain']:40s} {kind:9s} certificate '{entry['certificate']}'")
    return 0


# --------------------------------------------------------------------------
# Updating from GitHub
# --------------------------------------------------------------------------

REPO = "DukyNuky/opnsense-haproxy-config"
GITHUB_API = "https://api.github.com"

# Exactly these files are replaced by an update. Anything else in the download
# is ignored, so neither a stray file in the repository nor a manipulated
# archive can drop something new into the user's folder -- and config.json /
# gui.json are never in the list, so personal settings survive every update.
# What an update or an installation may carry over, by kind rather than by
# name. A list of names is written by the version that does the copying, so it
# can only ever know the files that existed back then: that is how an update
# run by 1.3 left portainer.py behind, and an update run by 2.2 left catalog.py
# behind -- each time breaking the very version that was being installed. A
# rule cannot forget a file that did not exist when it was written.
UPDATE_SUFFIXES = (".py", ".json", ".md", ".bat", ".png", ".ico")
# Never taken from anywhere: the first two belong to the user, the last two are
# for building a release and have no business in an installation.
UPDATE_NEVER = ("config.json", "gui.json", "make_release.py", "make_icon.py")
# Without these there is no program, so an incomplete download is refused
# before a single file is replaced.
ESSENTIAL_FILES = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
                   "portainer_gui.py", "catalog.py", "adguard_gui.py")


def updatable(name):
    """Whether a file of this name belongs to the program itself.

    Also the answer to the usual zip question: a name with a path in it, or a
    hidden dotfile, is not one of ours and is never used to build a path.
    """
    return (bool(name) and name == os.path.basename(name)
            and not name.startswith(".") and name not in UPDATE_NEVER
            and name.endswith(UPDATE_SUFFIXES))

# The whole project is well under a megabyte; anything beyond this is either a
# mistake or something we should not be unpacking.
MAX_DOWNLOAD = 20 * 1024 * 1024


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3, 0). Anything without digits sorts lowest."""
    numbers = [int(n) for n in re.findall(r"\d+", text or "")][:4]
    return tuple(numbers + [0] * (4 - len(numbers)))


def _github(path, timeout=15):
    request = urllib.request.Request(
        f"{GITHUB_API}/{path}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"opnsense-haproxy/{VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(path) from None
        if exc.code in (403, 429):
            raise ApiError("GitHub is rate limiting this connection -- "
                           "please try again in an hour") from None
        raise ApiError(f"GitHub answered {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"cannot reach GitHub: {exc.reason}") from None
    except json.JSONDecodeError:
        raise ApiError("GitHub sent a reply that is not JSON") from None


def latest_release(repo=REPO, timeout=15):
    """The newest published version: a Release if one exists, else the highest tag.

    Tags are a deliberate fallback. Publishing a Release is a manual step in
    the web interface that is easy to forget, while a pushed tag already
    carries both the version number and a downloadable archive.
    """
    try:
        data = _github(f"repos/{repo}/releases/latest", timeout)
        tag = data.get("tag_name") or data.get("name") or ""
        return {"version": tag.lstrip("vV"), "tag": tag,
                "notes": (data.get("body") or "").strip(),
                "zip": data.get("zipball_url") or "",
                "page": data.get("html_url") or f"https://github.com/{repo}/releases"}
    except FileNotFoundError:
        pass  # no Release published -- ask the tags instead

    tags = _github(f"repos/{repo}/tags", timeout)
    if not isinstance(tags, list) or not tags:
        raise ApiError(f"{repo} has no published version yet")
    newest = max(tags, key=lambda entry: parse_version(entry.get("name")))
    tag = newest.get("name", "")
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": "",
            "zip": newest.get("zipball_url") or "",
            "page": f"https://github.com/{repo}/releases/tag/{tag}"}


def check_for_update(current=None, repo=REPO, timeout=15):
    """Release information when GitHub is ahead of us, otherwise None."""
    current = current or VERSION
    release = latest_release(repo, timeout)
    release["current"] = current
    if parse_version(release["version"]) <= parse_version(current):
        return None
    return release


def install_dir():
    return os.path.dirname(os.path.abspath(__file__))


UPDATE_BLOCKED_TEXT = {
    "git": "this folder is a git working copy -- update it with `git pull` so "
           "local changes are not overwritten",
    "readonly": "the program files in this folder may not be changed",
}


def update_blocked(folder=None):
    """Why replacing the files here would be wrong, or '' when it is fine.

    The answer is a short code rather than a sentence, so that the window can
    phrase it in German while the command line stays English.
    """
    folder = folder or install_dir()
    if os.path.isdir(os.path.join(folder, ".git")):
        return "git"
    if not os.access(folder, os.W_OK):
        return "readonly"
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if updatable(name) and os.path.isfile(path) and not os.access(path, os.W_OK):
            return "readonly"
    return ""


def update_blocked_text(code):
    return UPDATE_BLOCKED_TEXT.get(code, "this folder cannot be updated")


def _download(url, timeout=60, report=None):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"opnsense-haproxy/{VERSION}"})
    chunks, size = [], 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            while True:
                chunk = reply.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ApiError("the download is far bigger than expected -- stopped")
                chunks.append(chunk)
                if report:
                    report(f"loading … {size // 1024} KB")
    except urllib.error.HTTPError as exc:
        raise ApiError(f"download failed: {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"download failed: {exc.reason}") from None
    return b"".join(chunks)


def unpack_release(blob):
    """The files we care about, taken out of a GitHub source archive.

    GitHub wraps the repository in one top level directory, so the first path
    element is dropped. What is left has to look like one of the program's own
    files -- see ``updatable`` -- which also settles the usual zip path
    traversal question: no name from the archive is ever used to build a path.
    """
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for entry in archive.infolist():
                parts = entry.filename.split("/")
                if entry.is_dir() or len(parts) != 2:
                    continue  # only the top level of the repository
                if updatable(parts[1]):
                    files[parts[1]] = archive.read(entry)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ApiError(f"the downloaded archive is unreadable: {exc}") from None
    return files


def verify_download(files):
    """Refuse anything incomplete or broken before a single file is replaced."""
    missing = [name for name in ESSENTIAL_FILES if name not in files]
    if missing:
        raise ApiError(f"the download is incomplete: {', '.join(missing)} missing")
    for name, data in files.items():
        if not name.endswith(".py"):
            continue
        try:
            compile(data.decode("utf-8"), name, "exec")  # syntax check, no run
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ApiError(f"{name} from the download is damaged: {exc}") from None


def install_update(release, folder=None, report=None, timeout=60):
    """Replace the program files with the downloaded release.

    The previous files are copied into a backup folder first, so an update
    that turns out badly can be undone by copying them back by hand.
    """
    folder = folder or install_dir()
    blocked = update_blocked(folder)
    if blocked:
        raise UsageError(update_blocked_text(blocked))
    if not release.get("zip"):
        raise ApiError("this version has no downloadable archive")
    say = report or (lambda _text: None)

    say("downloading …")
    files = unpack_release(_download(release["zip"], timeout, report))
    verify_download(files)

    backup = os.path.join(folder, f"backup-{release.get('current') or VERSION}")
    say("keeping a copy of the current version …")
    os.makedirs(backup, exist_ok=True)
    for name in files:
        current = os.path.join(folder, name)
        if os.path.exists(current):
            shutil.copy2(current, os.path.join(backup, name))

    say("writing the new version …")
    written = []
    for name, data in sorted(files.items()):
        target = os.path.join(folder, name)
        mode = os.stat(target).st_mode if os.path.exists(target) else None
        temporary = f"{target}.new"
        with open(temporary, "wb") as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(temporary, mode)  # keep the executable bit
        os.replace(temporary, target)  # atomic: no half written script survives
        written.append(name)
    return {"files": written, "backup": backup, "version": release["version"]}


# --------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------

RUNNABLE = ("opnsense_haproxy.py", "haproxy_gui.py")

# The names the commands get in the bin folder. Underscores and a .py suffix
# are fine for files but awkward to type.
LAUNCHERS = {"opnsense-haproxy": "opnsense_haproxy.py",
             "haproxy-gui": "haproxy_gui.py"}

DESKTOP_FILE = "opnsense-haproxy.desktop"
# tkinter is told to use this as its window class, so the task bar can tell
# which running window belongs to the starter
WM_CLASS = "opnsense-haproxy"

DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Version=1.0
Name=HAProxy · OPNsense
GenericName=Reverse Proxy
Comment=HAProxy-Einträge auf OPNsense anlegen
Exec={exec}
Icon={icon}
Terminal=false
Categories=Network;
Keywords=HAProxy;OPNsense;Proxy;Reverse Proxy;AdGuard;DNS;
StartupWMClass={wmclass}
"""


def running_as_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def default_install_dir():
    """Where the program belongs on this system, unless told otherwise."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "Programs", "opnsense-haproxy")
    if running_as_root():
        return "/opt/opnsense-haproxy"
    return os.path.expanduser("~/.local/share/opnsense-haproxy")


def default_bin_dir():
    """The folder the commands are linked into -- one that is usually on PATH."""
    if os.name == "nt":
        return ""  # Windows has no such place; the shortcut is the way in
    return "/usr/local/bin" if running_as_root() else os.path.expanduser("~/.local/bin")


def applications_dir():
    """Where a .desktop file has to sit to appear in the menu and task bar."""
    if running_as_root():
        return "/usr/share/applications"
    root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, "applications")


def desktop_dir():
    """The user's desktop folder, whatever it is called in their language."""
    config = os.path.join(os.environ.get("XDG_CONFIG_HOME")
                          or os.path.expanduser("~/.config"), "user-dirs.dirs")
    try:
        with open(config) as handle:
            found = re.search(r'^XDG_DESKTOP_DIR="(.*)"\s*$', handle.read(), re.M)
    except OSError:
        found = None
    if found:
        path = found.group(1).replace("$HOME", os.path.expanduser("~"))
        if os.path.isdir(path):
            return path
    for name in ("Desktop", "Schreibtisch"):
        path = os.path.expanduser(f"~/{name}")
        if os.path.isdir(path):
            return path
    return ""


def on_path(folder):
    """Is this folder one the shell would find a command in?"""
    if not folder:
        return False
    wanted = os.path.normcase(os.path.abspath(folder))
    return any(os.path.normcase(os.path.abspath(part)) == wanted
               for part in (os.environ.get("PATH") or "").split(os.pathsep) if part)


def same_folder(one, other):
    """Two paths that mean the same folder, symlinks and all."""
    if not one or not other:
        return False
    try:
        return os.path.samefile(one, other)
    except OSError:
        # one of them does not exist -- then the names have to agree
        return (os.path.normcase(os.path.abspath(one))
                == os.path.normcase(os.path.abspath(other)))


def starter_targets():
    """The folders the starters on this machine point at.

    Read rather than remembered: the installation writes nothing about itself
    anywhere, and a note next to the program would be one more file that an
    update has to keep in step. The starters are the record -- a symlink says
    where its script is, and the .desktop file says which one it runs.
    """
    found = []
    for command in LAUNCHERS:
        link = os.path.join(default_bin_dir() or "", command)
        if os.path.islink(link):
            found.append(os.path.dirname(os.path.realpath(link)))
    for folder in (applications_dir(), desktop_dir()):
        path = os.path.join(folder or "", DESKTOP_FILE)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        line = re.search(r"^Exec=(.*)$", text, re.M)
        if line:
            script = line.group(1).strip().strip('"')
            found.append(os.path.dirname(script))
    return [folder for folder in found if folder]


def installed_here(folder=None):
    """Is this copy the installed one -- the one the starters lead to?

    Asked by the window to decide whether offering to install is worth a
    button. Installing again from the folder that is already installed only
    ever writes the starters anew, which is not what the word promises.

    A git working copy is never it: installing from there is the normal way
    to get an installation, and ``install`` refuses to write into one.
    """
    folder = os.path.abspath(folder or install_dir())
    if os.path.isdir(os.path.join(folder, ".git")):
        return False
    if same_folder(folder, default_install_dir()):
        return True
    return any(same_folder(folder, target) for target in starter_targets())


def install_source(folder=None):
    """The folder to copy from, checked for completeness before anything runs."""
    folder = folder or install_dir()
    missing = [name for name in RUNNABLE
               if not os.path.exists(os.path.join(folder, name))]
    if missing:
        raise UsageError(f"{folder} is not a complete copy: {', '.join(missing)} missing")
    return folder


def copy_program(source, target, report=None):
    """Put the program files into the target folder, keeping them runnable."""
    say = report or (lambda _text: None)
    os.makedirs(target, exist_ok=True)
    # Everything the running program is made of, by the same rule an update
    # goes by: the icons come along because the desktop starter points at
    # icon.png, and a file added in some later version comes along by itself.
    copied = []
    for name in sorted(os.listdir(source)):
        origin = os.path.join(source, name)
        if not updatable(name) or not os.path.isfile(origin):
            continue
        shutil.copy2(origin, os.path.join(target, name))
        copied.append(name)
    for name in RUNNABLE:
        path = os.path.join(target, name)
        if os.path.exists(path):
            os.chmod(path, os.stat(path).st_mode | 0o111)
    say(f"copied {len(copied)} files into {target}")
    return copied


def link_commands(target, bin_dir, report=None):
    """Make the two scripts callable by name from anywhere.

    A symlink is enough: Python resolves it before deciding where to look for
    the modules next to the script, so ``gui`` still finds haproxy_gui.py.
    """
    say = report or (lambda _text: None)
    os.makedirs(bin_dir, exist_ok=True)
    linked = []
    for command, script in sorted(LAUNCHERS.items()):
        link = os.path.join(bin_dir, command)
        script_path = os.path.join(target, script)
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(script_path, link)
        linked.append(link)
    say(f"linked the commands in {bin_dir}")
    return linked


def write_desktop_entry(target, folder, report=None, refresh=False):
    """Write the .desktop file that puts the program in the menu."""
    say = report or (lambda _text: None)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, DESKTOP_FILE)
    launcher = os.path.join(target, "haproxy_gui.py")
    text = DESKTOP_ENTRY.format(
        exec=f'"{launcher}"' if " " in launcher else launcher,
        icon=os.path.join(target, "icon.png"), wmclass=WM_CLASS)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o755)  # some desktops only trust an executable starter
    say(f"wrote the starter {path}")
    if refresh:
        refresh_menu(folder)
    return path


def refresh_menu(folder):
    """Nudge the desktop into noticing the new entry, where that tool exists."""
    tool = shutil.which("update-desktop-database")
    if not tool:
        return
    try:
        subprocess.run([tool, folder], timeout=20, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass  # the entry is written; a stale cache sorts itself out


def windows_shortcut(target, folder, report=None):
    """A .lnk with the icon, built by the shell's own scripting object.

    Windows has no file format we could just write here, but every installation
    can create a shortcut through WScript.Shell.
    """
    say = report or (lambda _text: None)
    os.makedirs(folder, exist_ok=True)
    link = os.path.join(folder, "HAProxy · OPNsense.lnk")
    runtime = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(runtime):
        runtime = sys.executable
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({link});"
        "$s.TargetPath = {runtime};"
        "$s.Arguments = {arguments};"
        "$s.WorkingDirectory = {target};"
        "$s.IconLocation = {icon};"
        "$s.Description = 'HAProxy-Einträge auf OPNsense anlegen';"
        "$s.Save()"
    ).format(
        link=_powershell_string(link),
        runtime=_powershell_string(runtime),
        arguments=_powershell_string(f'"{os.path.join(target, "haproxy_gui.py")}"'),
        target=_powershell_string(target),
        icon=_powershell_string(os.path.join(target, "icon.ico")),
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=60, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UsageError(f"could not create the shortcut: {exc}") from None
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[:200]
        raise UsageError(f"could not create the shortcut: {detail}")
    say(f"created the shortcut {link}")
    return link


def _powershell_string(text):
    """A literal PowerShell string -- single quotes, doubled to escape."""
    return "'" + str(text).replace("'", "''") + "'"


def install(target=None, bin_dir=None, commands=True, menu=True, desktop=False,
            source=None, report=None):
    """Copy the program somewhere permanent and add the starters asked for.

    Returns what was written, so the caller can say so in its own words.
    """
    say = report or (lambda _text: None)
    source = install_source(source)
    target = os.path.abspath(os.path.expanduser(target or default_install_dir()))

    if os.path.isdir(os.path.join(target, ".git")):
        raise UsageError(f"{target} is a git working copy -- installing there "
                         "would overwrite the checkout")
    same = os.path.exists(target) and os.path.samefile(source, target)
    if same:
        say("the program is already there -- only the starters are written")
    else:
        copy_program(source, target, report)

    result = {"target": target, "same": same, "commands": [], "menu": "",
              "desktop": "", "bin": bin_dir or "", "path_hint": False}

    if os.name == "nt":
        if menu:
            start = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                 "Microsoft", "Windows", "Start Menu", "Programs")
            result["menu"] = windows_shortcut(target, start, report)
        if desktop:
            folder = desktop_dir() or os.path.expanduser("~/Desktop")
            result["desktop"] = windows_shortcut(target, folder, report)
        return result

    if commands:
        folder = os.path.abspath(os.path.expanduser(bin_dir or default_bin_dir()))
        result["commands"] = link_commands(target, folder, report)
        result["bin"] = folder
        result["path_hint"] = not on_path(folder)
    if menu:
        result["menu"] = write_desktop_entry(target, applications_dir(), report,
                                             refresh=True)
    if desktop:
        folder = desktop_dir()
        if not folder:
            say("no desktop folder found -- skipped")
        else:
            result["desktop"] = write_desktop_entry(target, folder, report)
    return result


# --------------------------------------------------------------------------
# Configuration / CLI
# --------------------------------------------------------------------------


def load_config(path):
    if path and not os.path.exists(path):
        raise UsageError(f"config file not found: {path}")
    path = path or DEFAULT_CONFIG
    if not os.path.exists(path):
        return {}
    with open(path) as handle:
        text = handle.read().strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path} is not valid JSON: {exc}") from None


PROFILE_KEYS = ("name", "url", "key", "secret", "verify_ssl", "frontend",
                "haproxy_ip", "adguard", "portainer", "defaults")

# The three kinds of system the file knows, each in a list of its own. An
# OPNsense entry names the AdGuard and the Portainer it works with by name, so
# one AdGuard can serve several firewalls without being written down twice.
SYSTEM_KINDS = ("opnsense", "adguard", "portainer", "git")
OPNSENSE_KEYS = ("name", "url", "key", "secret", "verify_ssl", "frontend",
                 "haproxy_ip", "defaults", "adguard", "portainer")
ADGUARD_KEYS = ("name", "url", "username", "password", "target", "verify_ssl")
PORTAINER_KEYS = ("name", "url", "api_key", "username", "password", "host_ip",
                  "verify_ssl")
# A Git account is not a machine this program talks to -- Portainer does the
# cloning. It is kept here all the same: it is one more set of credentials, it
# belongs in the same file at the same mode, and it is edited the same way.
GIT_KEYS = ("name", "url", "username", "token")
SYSTEM_KEYS = {"opnsense": OPNSENSE_KEYS, "adguard": ADGUARD_KEYS,
               "portainer": PORTAINER_KEYS, "git": GIT_KEYS}


def old_profiles(config):
    """The bundles a file written before 2.0 holds, one per connection.

    Up to 1.4 every connection carried its own AdGuard and Portainer inside it.
    A file from before profiles existed holds a single connection at the top
    level; it counts as one bundle so nothing has to be migrated by hand.
    """
    listed = config.get("profiles")
    if isinstance(listed, list) and listed:
        result = []
        for index, entry in enumerate(listed, start=1):
            profile = dict(entry)
            profile.setdefault("name", profile.get("url") or f"Profil {index}")
            result.append(profile)
        return result
    if any(config.get(key) for key in ("url", "key", "secret")):
        flat = {k: v for k, v in config.items() if k in PROFILE_KEYS}
        flat.setdefault("name", "Standard")
        return [flat]
    return []


def _free_name(entries, wanted, fallback):
    """A name no entry in this list uses yet."""
    base = str(wanted or fallback).strip() or fallback
    taken = {entry.get("name") for entry in entries}
    candidate, suffix = base, 1
    while candidate in taken:
        suffix += 1
        candidate = f"{base} {suffix}"
    return candidate


def _same_system(entries, section):
    """The name of an entry that already describes this very system.

    Two connections to the same AdGuard were two copies of it in the old
    layout. They become one entry, named after whichever connection got there
    first, so the migration does not multiply what was always one machine.
    """
    for entry in entries:
        if (str(entry.get("url", "")).rstrip("/").lower()
                == str(section.get("url", "")).rstrip("/").lower()
                and entry.get("username", "") == section.get("username", "")
                and entry.get("api_key", "") == section.get("api_key", "")):
            return entry.get("name", "")
    return ""


def split_profiles(profiles):
    """Old bundles into the three lists of 2.0.

    Each connection keeps its own OPNsense entry and points at the AdGuard and
    the Portainer it used by name.
    """
    result = {kind: [] for kind in SYSTEM_KINDS}
    for profile in profiles:
        entry = {k: v for k, v in profile.items()
                 if k in OPNSENSE_KEYS and k not in ("adguard", "portainer")}
        entry.setdefault("name", profile.get("url") or "OPNsense")
        entry["name"] = _free_name(result["opnsense"], entry["name"], "OPNsense")
        for kind in ("adguard", "portainer"):
            section = profile.get(kind)
            if not isinstance(section, dict) or not str(section.get("url", "")).strip():
                continue
            known = _same_system(result[kind], section)
            if known:
                entry[kind] = known
                continue
            named = {k: v for k, v in section.items() if k in SYSTEM_KEYS[kind]}
            # a section that already carries a name keeps it: this also runs
            # when a 2.0 file is taken apart and put back together again
            named["name"] = _free_name(result[kind],
                                       section.get("name") or profile.get("name"),
                                       kind.capitalize())
            result[kind].append(named)
            entry[kind] = named["name"]
        result["opnsense"].append(entry)
    return result


def systems_of(config):
    """The three lists, whatever layout the file on disk is in.

    A 2.0 file holds them directly. Anything older is migrated on the way in --
    reading is never a reason to rewrite the file, so this happens every time
    until something is saved.
    """
    if any(isinstance(config.get(kind), list) for kind in SYSTEM_KINDS):
        return {kind: [dict(entry) for entry in (config.get(kind) or [])
                       if isinstance(entry, dict)]
                for kind in SYSTEM_KINDS}
    return split_profiles(old_profiles(config))


def find_system(systems, kind, name):
    """One entry by name, or nothing when the name is unknown or empty."""
    if not name:
        return {}
    for entry in systems.get(kind, []):
        if entry.get("name") == name:
            return entry
    return {}


def active_name(config, kind, systems=None):
    """Which system of this kind to start with.

    Falls back to the first one configured, so a file that names something
    since deleted still opens on something usable.
    """
    systems = systems if systems is not None else systems_of(config)
    entries = systems.get(kind, [])
    active = config.get("active")
    wanted = ""
    if isinstance(active, dict):
        wanted = str(active.get(kind, ""))
    elif kind == "opnsense":
        wanted = str(active or "")  # a 1.x file names the active profile here
    for entry in entries:
        if entry.get("name") == wanted:
            return wanted
    return entries[0].get("name", "") if entries else ""


def merged_profile(systems, entry, adguard=None, portainer=None):
    """One OPNsense entry with its AdGuard and Portainer filled in.

    The rest of the program works on this shape -- the same one the file held
    up to 1.4 -- so only the settings screen and this module have to know that
    the three are kept apart on disk. Passing ``adguard`` or ``portainer``
    overrides what the entry names, which is what the pickers before a deploy
    hand in.

    Without an entry there is still something to build: somebody who set up
    only a Portainer has no firewall to hang it on, and the Docker half of the
    window has to work for them too.
    """
    entry = entry or {}
    profile = {k: v for k, v in entry.items() if k not in ("adguard", "portainer")}
    for kind, chosen in (("adguard", adguard), ("portainer", portainer)):
        name = entry.get(kind, "") if chosen is None else chosen
        section = find_system(systems, kind, name)
        if section:
            profile[kind] = dict(section)
    return profile


def profiles_of(config):
    """Every OPNsense connection, each with its AdGuard and Portainer filled in."""
    systems = systems_of(config)
    return [merged_profile(systems, entry) for entry in systems["opnsense"]]


def pick_profile(config, name=None):
    """The profile to work with: the requested one, the active one, or the first."""
    profiles = profiles_of(config)
    if not profiles:
        return {}
    if name:
        for profile in profiles:
            if profile.get("name") == name:
                return profile
        known = ", ".join(p.get("name", "?") for p in profiles)
        raise UsageError(f"no profile named '{name}' (have: {known})")
    wanted = active_name(config, "opnsense")
    for profile in profiles:
        if profile.get("name") == wanted:
            return profile
    return profiles[0]


def as_settings_file(systems, active=None, favorites=None):
    """The file layout: one list per kind of system, and what is active in each.

    ``favorites`` are the stacks somebody wrote down to deploy again -- no
    credentials, but they belong with the systems rather than with the window's
    own preferences, because they describe the setup and not the view.
    """
    chosen = dict(active or {})
    for kind in SYSTEM_KINDS:
        entries = systems.get(kind, [])
        if not any(entry.get("name") == chosen.get(kind) for entry in entries):
            chosen[kind] = entries[0].get("name", "") if entries else ""
    written = {kind: list(systems.get(kind, [])) for kind in SYSTEM_KINDS}
    written["active"] = chosen
    if favorites:
        written["favorites"] = list(favorites)
    return written


def as_profile_file(profiles, active=None):
    """The file layout for a set of old-style bundles, split on the way out."""
    return as_settings_file(split_profiles(profiles), {"opnsense": active or ""})


def build_client(args, profile):
    url = args.url or os.environ.get("OPNSENSE_URL") or profile.get("url")
    key = args.key or os.environ.get("OPNSENSE_KEY") or profile.get("key")
    secret = args.secret or os.environ.get("OPNSENSE_SECRET") or profile.get("secret")
    missing = [n for n, v in (("url", url), ("key", key), ("secret", secret)) if not v]
    if missing:
        raise UsageError(
            f"missing {', '.join(missing)} -- run `{os.path.basename(sys.argv[0])} init` "
            "or pass --url/--key/--secret"
        )
    verify = profile.get("verify_ssl", True)
    if getattr(args, "insecure", False):
        verify = False
    return Client(url, key, secret, verify=verify)


def confirm(question):
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in YES
    except EOFError:
        return False


def ask(question, default=None, secret=False, allow_empty=False):
    """Prompt for a value; fall back to the default when there is no terminal."""
    if not sys.stdin.isatty():
        if allow_empty:
            return default or ""
        if default in (None, ""):
            raise UsageError(f"no terminal to ask for: {question}")
        return default
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        raw = (getpass.getpass if secret else input)(f"{question}{suffix}: ").strip()
        if raw:
            return raw
        if allow_empty or default not in (None, ""):
            return default or ""


def cmd_init(args, _config):
    path = args.config or DEFAULT_CONFIG
    existing = []
    if os.path.exists(path):
        try:
            existing = profiles_of(load_config(path))
        except UsageError:
            existing = []
        if existing:
            known = ", ".join(p.get("name", "?") for p in existing)
            print(f"{path} already holds: {known}")
            if not confirm("add another profile?"):
                print("aborted")
                return 1
        elif not confirm(f"{path} exists -- overwrite?"):
            print("aborted")
            return 1

    default_name = "Standard" if not existing else f"Profil {len(existing) + 1}"
    config = {
        "name": ask("profile name", default_name),
        "url": ask("OPNsense base URL", "https://opnsense.local"),
        "key": ask("API key"),
        "secret": ask("API secret", secret=True),
        "verify_ssl": ask("verify TLS certificate? (yes/no)", "no").lower() in YES,
    }
    frontend = ask("default public service (leave empty to auto-detect)",
                   allow_empty=True)
    if frontend:
        config["frontend"] = frontend

    haproxy_ip = ask("IP HAProxy answers on (used for the DNS rewrites)",
                     allow_empty=True)
    if haproxy_ip:
        config["haproxy_ip"] = haproxy_ip

    adguard_url = ask("AdGuard Home URL (empty = no DNS rewrites)",
                      allow_empty=True)
    if adguard_url:
        adguard = {
            "url": adguard_url,
            "username": ask("AdGuard user", allow_empty=True),
            "password": ask("AdGuard password", secret=True, allow_empty=True),
            "verify_ssl": ask("verify AdGuard's TLS certificate? (yes/no)",
                              "no").lower() in YES,
        }
        target = ask("address the rewrites should point at",
                     haproxy_ip, allow_empty=bool(haproxy_ip))
        if target and target != haproxy_ip:
            adguard["target"] = target  # this AdGuard points somewhere else
        config["adguard"] = adguard
    profiles = [p for p in existing if p.get("name") != config["name"]]
    profiles.append(config)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(as_profile_file(profiles, config["name"]), handle, indent=2)
        handle.write("\n")
    os.chmod(path, 0o600)
    print(f"\nwrote {path} (mode 600) -- profile '{config['name']}'")

    client = Client(config["url"], config["key"], config["secret"],
                    verify=config["verify_ssl"])
    try:
        status = client.status()
        print(f"connection ok -- haproxy is {status.get('status', 'unknown')}")
    except ApiError as exc:
        print(f"warning: could not talk to the API yet: {exc}", file=sys.stderr)
    return 0


def cmd_add(args, config):
    profile = pick_profile(config, args.profile)
    client = build_client(args, profile)
    defaults = profile.get("defaults", {})
    if not args.target:
        args.target = ask("URL / hostname")
    if not args.ip:
        args.ip = ask("real server IP")
    if args.port is None and args.ssl is None:
        answer = ask("use SSL to the backend? (yes/no)",
                     "yes" if defaults.get("ssl") else "no")
        args.ssl = answer.lower() in YES
    if args.ssl is None:
        args.ssl = bool(defaults.get("ssl", False))
    if args.port is None:
        args.port = ask("real server port", str(443 if args.ssl else 80))
    args.port = int(args.port)
    if not 1 <= args.port <= 65535:
        raise UsageError("port must be between 1 and 65535")
    args.frontend = args.frontend or profile.get("frontend")
    args.healthcheck = args.healthcheck or defaults.get("healthcheck")
    args.prefix = args.prefix if args.prefix is not None else defaults.get("prefix", "")
    args.base_domain = args.base_domain or defaults.get("base_domain", "")
    adguard = _adguard_for(args, profile)
    return provision(client, args, out=_out, adguard=adguard)


def cmd_listener(args, config):
    profile = pick_profile(config, args.profile)
    client = build_client(args, profile)
    if not args.name:
        args.name = ask("name of the public service")
    if not args.port:
        args.port = ask("port it listens on")
    if not args.ip:
        args.ip = ask("IP of the server behind it")
    args.prefix = args.prefix if args.prefix is not None else \
        profile.get("defaults", {}).get("prefix", "")
    if args.certificate:
        chosen = next((c for c in listener_choices(client)["certificates"]
                       if args.certificate in (c["id"], c["name"])), None)
        if chosen is None:
            raise UsageError(f"no certificate '{args.certificate}' -- see the "
                             "`certificates` command")
        args.certificate, args.certificate_name = chosen["id"], chosen["name"]
    adguard = _adguard_for(args, profile) if args.host else None
    return provision_listener(client, args, out=_out, adguard=adguard)


def cmd_unlisten(args, config):
    profile = pick_profile(config, args.profile)
    client = build_client(args, profile)
    if not args.name:
        args.name = ask("name of the public service")
    return deprovision_listener(client, args, out=_out,
                                adguard=_adguard_for(args, profile))


def cmd_certificates(args, config):
    client = _client_for(args, config)
    choices = listener_choices(client)["certificates"]
    if not choices:
        print("no certificates -- add one under System > Trust, or use the "
              "ACME client")
        return 0
    for entry in choices:
        print(f"{entry['id']}  {entry['name']}")
    return 0


def cmd_remove(args, config):
    profile = pick_profile(config, args.profile)
    client = build_client(args, profile)
    defaults = profile.get("defaults", {})
    if not args.target:
        args.target = ask("URL / hostname")
    args.prefix = args.prefix if args.prefix is not None else \
        defaults.get("prefix", "")
    args.base_domain = args.base_domain or defaults.get("base_domain", "")
    return deprovision(client, args, out=_out,
                       adguard=_adguard_for(args, profile))


def _adguard_for(args, profile):
    """The AdGuard client to use, unless DNS handling is switched off."""
    if getattr(args, "no_dns", False):
        return None
    adguard, settings = adguard_from_config(
        profile, {"url": getattr(args, "adguard_url", None)})
    if adguard is None:
        if settings.get("error"):
            raise UsageError(settings["error"])
        return None
    args.dns_target = (getattr(args, "dns_target", None)
                       or settings.get("target", ""))
    if not args.dns_target:
        raise UsageError(
            "AdGuard is configured but no target address is set -- add "
            '"haproxy_ip" to the profile (or "target" to the adguard '
            "section) or pass --dns-target")
    return adguard


def cmd_list(args, config):
    return show(_client_for(args, config), args, out=_out)


def cmd_domains(args, config):
    return show_domains(_client_for(args, config), args, out=_out)


def cmd_profiles(args, config):
    """List the configured profiles, marking the active one."""
    profiles = profiles_of(config)
    if not profiles:
        _out("no profiles configured -- run `init`")
        return 0
    chosen = pick_profile(config, args.profile).get("name")
    for profile in profiles:
        mark = "*" if profile.get("name") == chosen else " "
        adguard = (profile.get("adguard") or {}).get("url", "")
        _out(f"{mark} {profile.get('name', '?'):24s} {profile.get('url', '?')}"
             + (f"   adguard: {adguard}" if adguard else ""))
    return 0


def _client_for(args, config):
    return build_client(args, pick_profile(config, args.profile))


def cmd_apply(args, config):
    return apply_changes(_client_for(args, config), args, out=_out)


def cmd_gui(args, config):
    try:
        import haproxy_gui
    except ImportError:
        raise UsageError("haproxy_gui.py must sit next to this script") from None
    return haproxy_gui.App(args).mainloop() or 0


def cmd_status(args, config):
    client = _client_for(args, config)
    status = client.status()
    print(f"haproxy: {status.get('status', 'unknown')}")
    return 0


def cmd_update(args, _config):
    print(f"installed : {VERSION}")
    release = check_for_update()
    if release is None:
        print("this is the newest version")
        return 0

    print(f"available : {release['version']}  ({release['page']})")
    if release["notes"]:
        print()
        for line in release["notes"].splitlines():
            print(f"  {line}")
    print()
    if args.check:
        return 0

    blocked = update_blocked()
    if blocked:
        raise UsageError(update_blocked_text(blocked))
    if not args.yes and not confirm(f"install {release['version']} now?"):
        return 0

    result = install_update(release, report=lambda text: print(f"  {text}"))
    print(f"updated to {result['version']}: {', '.join(result['files'])}")
    print(f"the previous version is in {result['backup']}")
    print("restart the program to use it")
    return 0


def cmd_install(args, _config):
    result = install(target=args.target, bin_dir=args.bin,
                     commands=not args.no_commands, menu=not args.no_menu,
                     desktop=args.desktop,
                     report=lambda text: print(f"  {text}"))
    if result["same"]:
        print(f"\nalready installed in {result['target']}")
    else:
        print(f"\ninstalled into {result['target']}")
    if result["commands"]:
        print("commands  : " + ", ".join(sorted(os.path.basename(c)
                                                for c in result["commands"])))
    if result["menu"]:
        print(f"starter   : {result['menu']}")
    if result["desktop"]:
        print(f"desktop   : {result['desktop']}")
    if result["path_hint"]:
        print(f"\nnote: {result['bin']} is not on your PATH -- add it to your "
              "shell profile, or call the commands with their full path")
    return 0


def _out(*parts, file=None):
    print(*parts, file=file or sys.stdout)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="opnsense-haproxy",
        description="Create a full HAProxy host entry on OPNsense in one step.",
    )
    parser.add_argument("--version", action="version",
                        version=f"opnsense-haproxy {VERSION}")
    parser.add_argument("--config", help=f"config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("-P", "--profile",
                        help="which configured OPNsense to talk to "
                             "(see the `profiles` command)")
    parser.add_argument("--url", help="OPNsense base URL, e.g. https://opnsense.local")
    parser.add_argument("--key", help="API key")
    parser.add_argument("--secret", help="API secret")
    parser.add_argument("--insecure", action="store_true",
                        help="do not verify the OPNsense TLS certificate")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="provision a new host")
    add.add_argument("target", nargs="?",
                     help="URL or hostname, e.g. app.example.com or https://x.tld/api")
    add.add_argument("-i", "--ip", help="IP or hostname of the real server")
    add.add_argument("-p", "--port", help="port of the real server (default 80/443)")
    add.add_argument("--ssl", dest="ssl", action="store_const", const=True,
                     help="use SSL towards the backend")
    add.add_argument("--no-ssl", dest="ssl", action="store_const", const=False,
                     help="plain HTTP towards the backend")
    add.add_argument("--ssl-verify", action="store_true",
                     help="verify the backend certificate (off by default, "
                          "internal hosts usually have self-signed certs)")
    add.add_argument("-b", "--base-domain", default="",
                     help="base domain the host lives under; the target may then "
                          "be just the host part (see the `domains` command)")
    add.add_argument("-f", "--frontend", help="public service to attach the rule to")
    add.add_argument("--dns-target",
                     help="address the AdGuard rewrite should answer with")
    add.add_argument("--no-dns", action="store_true",
                     help="do not touch AdGuard, even when it is configured")
    add.add_argument("--adguard-url", help="AdGuard Home base URL")
    add.add_argument("--backend-mode", choices=("http", "tcp"),
                     help="backend pool mode (default: derived from the frontend)")
    add.add_argument("--healthcheck", help="name of an existing health monitor")
    add.add_argument("--no-forward-for", dest="forward_for", action="store_false",
                     help="do not add X-Forwarded-For (HTTP backends only)")
    add.add_argument("--prefix", help="prefix for generated object names")
    add.add_argument("-n", "--dry-run", action="store_true",
                     help="show what would be created and stop")
    add.add_argument("--no-apply", action="store_true",
                     help="save but do not test/reload HAProxy")
    add.set_defaults(func=cmd_add, forward_for=True)

    remove = sub.add_parser("remove", help="delete a previously provisioned host")
    remove.add_argument("target", nargs="?", help="URL or hostname")
    remove.add_argument("-b", "--base-domain", default="",
                        help="base domain used when it was created")
    remove.add_argument("--prefix", help="prefix used when it was created")
    remove.add_argument("--no-dns", action="store_true",
                        help="leave the AdGuard rewrite in place")
    remove.add_argument("--adguard-url", help="AdGuard Home base URL")
    remove.add_argument("-n", "--dry-run", action="store_true")
    remove.add_argument("-y", "--yes", action="store_true", help="do not ask")
    remove.add_argument("--no-apply", action="store_true")
    remove.set_defaults(func=cmd_remove, dns_target=None)

    listener = sub.add_parser(
        "listener", help="create a public service of its own on a port")
    listener.add_argument("name", nargs="?",
                          help="what the public service is called, e.g. turn-tls")
    listener.add_argument("-p", "--port", help="the port it listens on")
    listener.add_argument("-i", "--ip", help="IP or hostname of the server behind it")
    listener.add_argument("--backend-port",
                          help="port of that server (default: the public one)")
    listener.add_argument("--address", default="",
                          help="address to listen on (default 0.0.0.0)")
    listener.add_argument("--mode", choices=LISTEN_MODES, default="tcp",
                          help="tcp ends the TLS here, ssl passes it through, "
                               "http is the usual web entrance (default: tcp)")
    listener.add_argument("--certificate",
                          help="refid of the certificate to answer with "
                               "(see the `certificates` command)")
    listener.add_argument("--ssl", action="store_true",
                          help="speak TLS to the server behind it as well")
    listener.add_argument("--ssl-verify", action="store_true",
                          help="verify that server's certificate")
    listener.add_argument("--host",
                          help="public name for the AdGuard rewrite, if wanted")
    listener.add_argument("--dns-target",
                          help="address the AdGuard rewrite should answer with")
    listener.add_argument("--no-dns", action="store_true",
                          help="do not touch AdGuard, even when it is configured")
    listener.add_argument("--adguard-url", help="AdGuard Home base URL")
    listener.add_argument("--prefix", help="prefix for generated object names")
    listener.add_argument("-n", "--dry-run", action="store_true",
                          help="show what would be created and stop")
    listener.add_argument("--no-apply", action="store_true",
                          help="save but do not test/reload HAProxy")
    listener.set_defaults(func=cmd_listener)

    unlisten = sub.add_parser(
        "unlisten", help="delete a public service and the pool behind it")
    unlisten.add_argument("name", nargs="?", help="the public service to remove")
    unlisten.add_argument("--host",
                          help="AdGuard rewrite to remove with it (default: "
                               "the one it was created with)")
    unlisten.add_argument("--no-dns", action="store_true",
                          help="leave the AdGuard rewrite in place")
    unlisten.add_argument("--adguard-url", help="AdGuard Home base URL")
    unlisten.add_argument("-n", "--dry-run", action="store_true")
    unlisten.add_argument("-y", "--yes", action="store_true", help="do not ask")
    unlisten.add_argument("--no-apply", action="store_true")
    unlisten.set_defaults(func=cmd_unlisten, dns_target=None)

    certs = sub.add_parser("certificates",
                           help="list the certificates a listener can use")
    certs.set_defaults(func=cmd_certificates)

    listing = sub.add_parser("list", help="show public services and what is behind them")
    listing.set_defaults(func=cmd_list)

    domains = sub.add_parser("domains",
                             help="list base domains from the ACME certificates")
    domains.set_defaults(func=cmd_domains)

    profiles = sub.add_parser("profiles", help="list the configured connections")
    profiles.set_defaults(func=cmd_profiles)

    apply_cmd = sub.add_parser("apply", help="test the config and reload HAProxy")
    apply_cmd.set_defaults(func=cmd_apply, no_apply=False)

    gui = sub.add_parser("gui", help="open the desktop window")
    gui.set_defaults(func=cmd_gui)

    status = sub.add_parser("status", help="show the HAProxy service state")
    status.set_defaults(func=cmd_status)

    init = sub.add_parser("init", help="write the config file interactively")
    init.set_defaults(func=cmd_init)

    installer = sub.add_parser(
        "install",
        help="copy the program somewhere permanent and add a desktop starter")
    installer.add_argument("target", nargs="?",
                           help=f"where to install (default: {default_install_dir()})")
    installer.add_argument("--bin", help="folder for the commands "
                                         f"(default: {default_bin_dir() or 'none'})")
    installer.add_argument("--no-commands", action="store_true",
                           help="do not link opnsense-haproxy / haproxy-gui")
    installer.add_argument("--no-menu", action="store_true",
                           help="do not add the program to the application menu")
    installer.add_argument("--desktop", action="store_true",
                           help="also put a starter on the desktop")
    installer.set_defaults(func=cmd_install)

    update = sub.add_parser("update", help="look for a newer version on GitHub")
    update.add_argument("--check", action="store_true",
                        help="only report what is available, install nothing")
    update.add_argument("-y", "--yes", action="store_true",
                        help="install without asking")
    update.set_defaults(func=cmd_update)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        # init writes the config; update and install do not need one
        needs_config = args.command not in ("init", "update", "install")
        config = load_config(args.config) if needs_config else {}
        return args.func(args, config)
    except (UsageError, ApiError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
