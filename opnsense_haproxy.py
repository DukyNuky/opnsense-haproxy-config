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

VERSION = "2.0.0"

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
        return {str(entry.get("domain", "")).lower(): str(entry.get("answer", ""))
                for entry in self.rewrites()}


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
        known = ", ".join(sorted(r.get("name", "?") for r in rows))
        raise UsageError(
            f"several public services exist -- pick one with --frontend (have: {known})"
        )
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
    if "configuration file is valid" not in lowered:
        out(f"warning: unexpected config test output: {report.strip()[:200]}",
            file=sys.stderr)
    for line in report.splitlines():
        if "[warning]" in line.lower():
            out(f"  {line.strip()}")
    out("configuration is valid, reloading HAProxy ...")
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


def bind_port(bind):
    """The port a public service listens on, from its bind address.

    ``bind`` may hold several addresses (``0.0.0.0:443, [::]:443``); they share
    a port in every sane setup, so the first one answers the question.
    """
    first = str(bind or "").split(",")[0].strip()
    port = first.rsplit(":", 1)[-1] if ":" in first else ""
    return port if port.isdigit() else ""


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
        services.append({
            "uuid": row["uuid"],
            "name": row.get("name", ""),
            "mode": selected_value(frontend.get("mode")) or "http",
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
    if not backend_uuid:
        return rule
    backend = client.get("backend", backend_uuid)
    rule["backend"] = {
        "name": backend.get("name", ""),
        "mode": selected_value(backend.get("mode")),
        "servers": [],
    }
    for server_uuid in selected_values(backend.get("linkedServers")):
        server = client.get("server", server_uuid)
        rule["backend"]["servers"].append({
            "name": server.get("name", ""),
            "address": server.get("address", ""),
            "port": server.get("port", ""),
            "ssl": str(server.get("ssl", "0")) == "1",
        })
    return rule


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
UPDATE_FILES = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
                "portainer_gui.py", "HAProxy-Starter.bat",
                "README.md", "CHANGELOG.md", "config.example.json",
                "icon.png", "icon.ico")
ESSENTIAL_FILES = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
                   "portainer_gui.py")

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
    for name in UPDATE_FILES:
        path = os.path.join(folder, name)
        if os.path.exists(path) and not os.access(path, os.W_OK):
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
    element is dropped. Entries are matched against UPDATE_FILES instead of
    being trusted, which also settles the usual zip path traversal question:
    no name from the archive is ever used to build a path.
    """
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for entry in archive.infolist():
                parts = entry.filename.split("/")
                if entry.is_dir() or len(parts) != 2:
                    continue  # only the top level of the repository
                if parts[1] in UPDATE_FILES:
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

# Everything an installation consists of. The icons are in here because the
# desktop starter points at icon.png -- an installation without them would show
# a blank tile in the task bar.
INSTALL_FILES = ("opnsense_haproxy.py", "haproxy_gui.py", "portainer.py",
                 "portainer_gui.py", "icon.png", "icon.ico",
                 "HAProxy-Starter.bat", "README.md", "CHANGELOG.md",
                 "config.example.json")
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
    copied = []
    for name in INSTALL_FILES:
        origin = os.path.join(source, name)
        if not os.path.exists(origin):
            continue  # icons and docs are welcome but not required
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
SYSTEM_KINDS = ("opnsense", "adguard", "portainer")
OPNSENSE_KEYS = ("name", "url", "key", "secret", "verify_ssl", "frontend",
                 "haproxy_ip", "defaults", "adguard", "portainer")
ADGUARD_KEYS = ("name", "url", "username", "password", "target", "verify_ssl")
PORTAINER_KEYS = ("name", "url", "api_key", "username", "password", "host_ip",
                  "verify_ssl")
SYSTEM_KEYS = {"opnsense": OPNSENSE_KEYS, "adguard": ADGUARD_KEYS,
               "portainer": PORTAINER_KEYS}


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
    """
    if not entry:
        return {}
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


def as_settings_file(systems, active=None):
    """The file layout of 2.0: three lists and what is active in each."""
    chosen = dict(active or {})
    for kind in SYSTEM_KINDS:
        entries = systems.get(kind, [])
        if not any(entry.get("name") == chosen.get(kind) for entry in entries):
            chosen[kind] = entries[0].get("name", "") if entries else ""
    written = {kind: list(systems.get(kind, [])) for kind in SYSTEM_KINDS}
    written["active"] = chosen
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
