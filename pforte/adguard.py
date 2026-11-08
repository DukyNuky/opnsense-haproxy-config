"""AdGuard Home: DNS-Umleitungen („Rewrites“), mehr braucht es nicht."""

import base64

from .net import ApiError, base_url, request_json


class AdGuard:
    def __init__(self, url, username="", password="", verify=True, timeout=15):
        root = base_url(url, "AdGuard-Adresse")
        self.base = root if root.endswith("/control") else root + "/control"
        self.verify = verify
        self.timeout = timeout
        self._auth = None
        if username or password:
            self._auth = base64.b64encode(f"{username}:{password}".encode()).decode()

    def call(self, path, payload=None):
        headers = {"Authorization": f"Basic {self._auth}"} if self._auth else {}
        return request_json(f"{self.base}/{path}", headers=headers,
                            payload=payload, verify=self.verify,
                            timeout=self.timeout, who="AdGuard")

    def check(self):
        try:
            status = self.call("status")
        except ApiError as exc:
            if "abgelehnt" in str(exc):
                raise ApiError("AdGuard hat Benutzer oder Passwort "
                               "abgelehnt.") from None
            raise
        return {"version": status.get("version", ""),
                "rewrites": len(self.rewrites())}

    def rewrites(self):
        reply = self.call("rewrite/list")
        return reply if isinstance(reply, list) else []

    def find_rewrite(self, domain):
        return next((e for e in self.rewrites()
                     if str(e.get("domain", "")).lower() == domain.lower()), None)

    def add_rewrite(self, domain, answer):
        self.call("rewrite/add", {"domain": domain, "answer": answer})

    def delete_rewrite(self, domain, answer):
        self.call("rewrite/delete", {"domain": domain, "answer": answer})
