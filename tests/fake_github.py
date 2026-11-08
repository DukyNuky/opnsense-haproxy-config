"""Ein Ersatz für die GitHub-Schnittstelle, die ein Updater braucht."""

import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = "DukyNuky/opnsense-haproxy-config"


def make_zip(files, root="DukyNuky-opnsense-haproxy-config-abc1234"):
    """Ein Quellarchiv wie GitHub es baut: ein Wurzelordner um alles."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(f"{root}/{name}", data)
    return buffer.getvalue()


class Fake:
    def __init__(self):
        self.releases = []        # neueste zuerst: {"tag", "zip": bytes, "notes"}
        self.tags_only = False    # keine Releases, nur Tags
        self.branch = None        # {"sha", "zip", "shim"} für den Beta-Zweig
        self.rate_limited = False
        self.hits = []
        self.server = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0]
                fake.hits.append(path)
                if fake.rate_limited:
                    return self.send(403, {"message": "rate limit"})
                base = f"/repos/{REPO}"
                if path == f"{base}/releases/latest":
                    if fake.tags_only or not fake.releases:
                        return self.send(404, {})
                    r = fake.releases[0]
                    return self.send(200, {"tag_name": r["tag"], "body": r.get("notes", ""),
                                           "zipball_url": f"{fake.url}/zip/{r['tag']}",
                                           "html_url": f"{fake.url}/release/{r['tag']}"})
                if path == f"{base}/tags":
                    return self.send(200, [{"name": r["tag"], "zipball_url": f"{fake.url}/zip/{r['tag']}"}
                                           for r in fake.releases])
                if path == f"{base}/branches/beta" and fake.branch:
                    return self.send(200, {"commit": {"sha": fake.branch["sha"], "commit": {
                        "committer": {"date": "2026-11-08T10:00:00Z"}, "message": "Beta-Stand"}}})
                if path.startswith(f"{base}/zipball/") and fake.branch:
                    return self.send(200, fake.branch["zip"], "application/zip")
                if path.startswith(f"/{REPO}/") and path.endswith("/opnsense_haproxy.py") and fake.branch:
                    return self.send(200, fake.branch["shim"], "text/plain")
                if path.startswith("/zip/"):
                    tag = path[len("/zip/"):]
                    for r in fake.releases:
                        if r["tag"] == tag:
                            return self.send(200, r["zip"], "application/zip")
                self.send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=lambda: self.server.serve_forever(0.05), daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
