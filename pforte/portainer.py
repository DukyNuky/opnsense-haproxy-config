"""Portainer, nur lesend: welche Container veröffentlichen welche Ports?

Die Antwort füllt im Formular die Vorschlagsliste für das Ziel. Angelegt oder
gelöscht wird hier nichts.
"""

from urllib.parse import urlparse

from .net import ApiError, base_url, request_json

ANY = ("0.0.0.0", "::", "")
TLS_HINTS = (443, 8443, 9443)


class Portainer:
    def __init__(self, url, api_key, verify=True, timeout=20):
        self.base = base_url(url, "Portainer-Adresse")
        self.api_key = (api_key or "").strip()
        self.verify = verify
        self.timeout = timeout

    def call(self, path):
        return request_json(f"{self.base}/api/{path}",
                            headers={"X-API-Key": self.api_key},
                            verify=self.verify, timeout=self.timeout,
                            who="Portainer")

    def check(self):
        try:
            places = self.call("endpoints")
        except ApiError as exc:
            if "abgelehnt" in str(exc):
                raise ApiError("Portainer hat den Zugriffstoken "
                               "abgelehnt.") from None
            raise
        return {"hosts": len(places)}

    def published(self):
        """Alle veröffentlichten Ports, je Docker-Host, als Zielvorschläge."""
        found = []
        panel_host = urlparse(self.base).hostname or ""
        for place in self.call("endpoints"):
            if int(place.get("Status") or 0) != 1:
                continue
            host = place.get("PublicURL") or ""
            if not host:
                url = str(place.get("URL", ""))
                host = urlparse(url).hostname or "" if "://" in url else ""
                if url.startswith("unix:") or url.startswith("npipe:"):
                    host = ""
            host = host or panel_host
            try:
                containers = self.call(
                    f"endpoints/{place['Id']}/docker/containers/json")
            except ApiError:
                continue
            for item in containers:
                name = (item.get("Names") or ["?"])[0].lstrip("/")
                stack = (item.get("Labels") or {}).get(
                    "com.docker.compose.project", "")
                seen = set()
                for port in item.get("Ports") or []:
                    public = port.get("PublicPort")
                    if not public or port.get("Type", "tcp") != "tcp":
                        continue
                    if port.get("IP", "") not in ANY or public in seen:
                        continue
                    seen.add(public)
                    tls = port.get("PrivatePort") in TLS_HINTS
                    found.append({
                        "name": name, "stack": stack, "host": host,
                        "port": public, "tls": tls, "place": place.get("Name", ""),
                        "target": f"{'https://' if tls else ''}{host}:{public}"})
        found.sort(key=lambda i: (i["stack"] or i["name"], i["port"]))
        return found
