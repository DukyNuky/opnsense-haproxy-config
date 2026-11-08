"""Eine Attrappe für OPNsense-HAProxy, AdGuard Home und Portainer.

Alles in einem kleinen HTTP-Server im Speicher: genug, um die echten Clients
und die Oberfläche ohne ein echtes Netz zu prüfen. Zugangsdaten der Attrappe:
OPNsense key/secret = ``k``/``s``, AdGuard ``admin``/``pw``, Portainer-Token
``tok``. Aufruf zum Ausprobieren: ``python3 tests/mock_services.py 8999``.
"""

import base64
import json
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SELECT_FIELDS = {
    "frontend": ("mode", "bind", "linkedActions", "defaultBackend"),
    "action": ("type", "linkedAcls", "use_backend"),
    "acl": ("expression",),
    "backend": ("mode", "linkedServers"),
    "server": (),
}
LIST_FIELDS = {"bind", "linkedActions", "linkedAcls", "linkedServers"}
KINDS = {"Server": "server", "Backend": "backend", "Frontend": "frontend",
         "Acl": "acl", "Action": "action"}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.objects = {k: {} for k in SELECT_FIELDS}
        self.rewrites = []
        self.reconfigured = 0
        self.config_ok = True
        self.fail_on = None            # ("add", "action") lässt genau das scheitern
        self.acme = True
        self.calls = []

    def add(self, kind, **fields):
        key = str(uuid.uuid4())
        self.objects[kind][key] = dict(fields)
        return key

    def seed(self):
        https = self.add("frontend", name="https_frontend", mode="http",
                         bind="0.0.0.0:443,[::]:443", linkedActions=[], enabled="1")
        self.add("frontend", name="http_redirect", mode="http", bind="0.0.0.0:80",
                 linkedActions=[], enabled="1")
        self.add("frontend", name="mqtt_tcp", mode="tcp", bind="0.0.0.0:8883",
                 linkedActions=[], enabled="1")
        for host, target in (("wiki.home.example.com", "192.168.0.20:8080"),
                             ("cloud.home.example.com", "192.168.0.21:443")):
            server = self.add("server", name=f"srv_{host}", description=f"managed: {host}",
                              address=target.split(":")[0], port=target.split(":")[1],
                              ssl="1" if target.endswith("443") else "0")
            backend = self.add("backend", name=f"be_{host}", description=f"managed: {host}",
                               mode="http", linkedServers=[server])
            acl = self.add("acl", name=f"acl_{host.replace('.', '_')}", description=f"managed: {host}",
                           expression="hdr", hdr=host)
            action = self.add("action", name=f"rule_{host.replace('.', '_')}", description=f"managed: {host}",
                              type="use_backend", linkedAcls=[acl], use_backend=backend)
            self.objects["frontend"][https]["linkedActions"].append(action)
        return self


def render(kind, obj):
    out = {}
    for key, value in obj.items():
        if key in SELECT_FIELDS[kind]:
            chosen = value if isinstance(value, list) else [value]
            out[key] = {c: {"value": c, "selected": 1} for c in chosen if c}
        else:
            out[key] = value
    return out


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def basic(self, expected):
            got = self.headers.get("Authorization", "")
            return got == "Basic " + base64.b64encode(expected.encode()).decode()

        def handle_any(self, method):
            path = self.path.split("?")[0]
            payload = self.body() if method == "POST" else {}
            with state.lock:
                state.calls.append((method, path))
                if path.startswith("/api/haproxy/") or path.startswith("/api/acmeclient/"):
                    if not self.basic("k:s"):
                        return self.reply({"status": 401}, 401)
                    return self.opnsense(method, path[len("/api/"):], payload)
                if path.startswith("/control/"):
                    if not self.basic("admin:pw"):
                        return self.reply({}, 401)
                    return self.adguard(path[len("/control/"):], payload)
                if path.startswith("/api/endpoints"):
                    if self.headers.get("X-API-Key") != "tok":
                        return self.reply({}, 401)
                    return self.portainer(path[len("/api/"):])
            self.reply({"error": "unbekannt"}, 404)

        # ---- OPNsense
        def opnsense(self, method, path, payload):
            if path == "haproxy/service/status":
                return self.reply({"status": "running"})
            if path == "haproxy/service/configtest":
                return self.reply({"result": "Configuration file is valid" if state.config_ok
                                   else "[ALERT] kaputt\nFatal errors found"})
            if path == "haproxy/service/reconfigure":
                state.reconfigured += 1
                return self.reply({"status": "ok"})
            if path == "acmeclient/certificates/search":
                if not state.acme:
                    return self.reply({"error": "no"}, 404)
                return self.reply({"rows": [
                    {"name": "*.home.example.com", "altNames": "home.example.com", "enabled": "1"},
                    {"name": "*.lab.example.org", "altNames": "", "enabled": "1"},
                    {"name": "alt.example.net", "altNames": "", "enabled": "0"}]})
            m = re.match(r"haproxy/settings/search(\w+)s$", path)
            if m:
                kind = KINDS[m.group(1)]
                rows = [{"uuid": k, **{f: ",".join(v) if isinstance(v, list) else v
                                       for f, v in o.items()}}
                        for k, o in state.objects[kind].items()]
                return self.reply({"rows": rows})
            m = re.match(r"haproxy/settings/(get|add|set|del)(\w+?)(?:/([\w-]+))?$", path)
            if m:
                verb, name, key = m.groups()
                kind = KINDS.get(name)
                if kind is None:
                    return self.reply({"error": "kind"}, 404)
                if verb == "get":
                    obj = state.objects[kind].get(key)
                    if obj is None:
                        return self.reply({}, 404)
                    return self.reply({kind: render(kind, obj)})
                if state.fail_on == (verb, kind):
                    return self.reply({"result": "failed", "validations": {kind + ".name": "absichtlich"}})
                if verb == "del":
                    state.objects[kind].pop(key, None)
                    return self.reply({"result": "deleted"})
                fields = payload.get(kind, {})
                fields = {f: ([x for x in v.split(",") if x] if f in LIST_FIELDS else v)
                          for f, v in fields.items()}
                if verb == "add":
                    return self.reply({"result": "saved", "uuid": state.add(kind, **fields)})
                state.objects[kind][key].update(fields)
                return self.reply({"result": "saved"})
            self.reply({"error": "unbekannt"}, 404)

        # ---- AdGuard
        def adguard(self, path, payload):
            if path == "status":
                return self.reply({"version": "v0.107.test"})
            if path == "rewrite/list":
                return self.reply(state.rewrites)
            if path == "rewrite/add":
                state.rewrites.append(payload)
                return self.reply({})
            if path == "rewrite/delete":
                state.rewrites[:] = [r for r in state.rewrites if r != payload]
                return self.reply({})
            self.reply({}, 404)

        # ---- Portainer
        def portainer(self, path):
            if path == "endpoints":
                return self.reply([{"Id": 1, "Name": "local", "Status": 1,
                                    "URL": "unix:///var/run/docker.sock", "PublicURL": ""}])
            if path == "endpoints/1/docker/containers/json":
                return self.reply([
                    {"Names": ["/grafana"], "Labels": {"com.docker.compose.project": "monitoring"},
                     "Ports": [{"IP": "0.0.0.0", "PrivatePort": 3000, "PublicPort": 3001, "Type": "tcp"},
                               {"IP": "::", "PrivatePort": 3000, "PublicPort": 3001, "Type": "tcp"}]},
                    {"Names": ["/vaultwarden"], "Labels": {},
                     "Ports": [{"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8222, "Type": "tcp"}]},
                    {"Names": ["/portainer"], "Labels": {},
                     "Ports": [{"IP": "0.0.0.0", "PrivatePort": 9443, "PublicPort": 9443, "Type": "tcp"}]},
                    {"Names": ["/db"], "Labels": {}, "Ports": [{"PrivatePort": 5432, "Type": "tcp"}]}])
            self.reply({}, 404)

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

    return Handler


def start(port=0, state=None):
    state = state or State().seed()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=lambda: server.serve_forever(0.05), daemon=True).start()
    return server, state


if __name__ == "__main__":
    server, _ = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8999)
    print(f"Attrappe läuft auf http://127.0.0.1:{server.server_address[1]}")
    threading.Event().wait()
