"""Kleine HTTP-Hilfen für alle drei Gegenstellen (nur Standardbibliothek)."""

import json
import re
import ssl
import urllib.error
import urllib.request


class PforteError(RuntimeError):
    """Etwas, das der Nutzer in einem Satz erfahren soll.

    ``code`` lässt die Oberfläche gezielt reagieren (z. B. „tls“ bietet an,
    das Zertifikat nicht zu prüfen).
    """

    def __init__(self, message, code="", status=0):
        super().__init__(message)
        self.code = code
        self.status = status      # HTTP-Status der Gegenstelle, sonst 0


class ApiError(PforteError):
    pass


def base_url(raw, what="Adresse", default_scheme="https"):
    """Aus allem, was jemand eintippt, eine brauchbare Basisadresse machen."""
    text = (raw or "").strip()
    if not text:
        raise PforteError(f"{what} fehlt")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", text):
        text = f"{default_scheme}://{text}"
    scheme, _, rest = text.partition("://")
    if scheme not in ("http", "https"):
        raise PforteError(f"{what}: nur http und https sind möglich")
    host = rest.split("/", 1)[0]
    if not host or " " in host:
        raise PforteError(f"{what} ist nicht lesbar: {raw!r}")
    path = rest[len(host):].rstrip("/")
    return f"{scheme}://{host}{path}"


def tls_context(verify):
    if verify:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def request_json(url, headers=None, payload=None, method=None, verify=True,
                 timeout=30, who="Gegenstelle"):
    """Eine Anfrage, deren Antwort JSON ist (oder leer)."""
    headers = dict(headers or {})
    headers.setdefault("Accept", "application/json")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if method is None:
        method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=tls_context(verify)) as resp:
            body = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()[:300]
        if exc.code in (401, 403):
            raise ApiError(f"{who} hat die Anmeldung abgelehnt "
                           f"({exc.code})", status=exc.code) from None
        raise ApiError(f"{who}: {exc.code} {exc.reason} {detail}".strip(),
                       status=exc.code) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY" in str(reason):
            raise ApiError(f"{who}: Das Zertifikat ist nicht vertraut "
                           "(selbst signiert?).", code="tls") from None
        raise ApiError(f"{who} ist nicht erreichbar ({reason})") from None
    except (TimeoutError, OSError) as exc:
        raise ApiError(f"{who} ist nicht erreichbar ({exc})") from None
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ApiError(f"{who} antwortet nicht mit JSON — stimmt die "
                       "Adresse?") from None


def reachable(url, verify=True, timeout=10, who="Gegenstelle"):
    """Antwortet unter der Adresse ein Webserver? Der Inhalt ist egal."""
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=tls_context(verify)) as resp:
            resp.read(1)
    except urllib.error.HTTPError:
        return True                       # eine Absage ist auch eine Antwort
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY" in str(reason):
            raise ApiError(f"{who}: Das Zertifikat ist nicht vertraut "
                           "(selbst signiert?).", code="tls") from None
        raise ApiError(f"{who} ist nicht erreichbar ({reason})") from None
    except (TimeoutError, OSError) as exc:
        raise ApiError(f"{who} ist nicht erreichbar ({exc})") from None
    return True
