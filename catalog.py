#!/usr/bin/env python3
"""What there is to deploy: known stacks, own favourites, own repositories.

Three sources with one shape. A **known stack** comes from catalog.json in this
program's own repository -- a curated list, so that somebody who has just set
up Portainer has something to try that is known to work. A **favourite** is the
same thing written down locally, in the settings file next to the systems. And
**own repositories** are read from a Git account with the token that account
carries, which is also the token a deploy of one of them needs.

Nothing here draws anything or talks to Portainer: it collects the entries and
hands them over as plain dictionaries, so the window only has to show them.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import opnsense_haproxy as core

# The curated list lives in this program's repository, so it can grow without
# anybody having to update the program itself.
CATALOG_URL = ("https://raw.githubusercontent.com/DukyNuky/"
               "opnsense-haproxy-config/main/catalog.json")

# Anything larger than this is not a list of stacks any more.
MAX_CATALOG = 512 * 1024

# One entry, whichever of the three lists it comes from.
ENTRY_KEYS = ("name", "description", "repository", "reference", "compose_file",
              "homepage")

GITHUB_HOSTS = ("github.com", "www.github.com")
GITHUB_API = "https://api.github.com"

# Where a token for one of these is handed out, and what it has to be allowed
# to do. Reading the repository is the whole job: Portainer clones it, nothing
# is ever written back.
TOKEN_PAGES = {
    "github.com": ("https://github.com/settings/personal-access-tokens/new",
                   "Fine-grained token: Repository access → Only select "
                   "repositories, Permissions → Contents: Read-only"),
    "gitlab.com": ("https://gitlab.com/-/user_settings/personal_access_tokens",
                   "Scope: read_api und read_repository"),
}


def host_of(url):
    """The machine an address names, lowercased and without a user in front."""
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    host = urllib.parse.urlsplit(text).netloc.rsplit("@", 1)[-1]
    return host.split(":", 1)[0].lower()


def is_github(url):
    return host_of(url) in GITHUB_HOSTS


def token_page(url):
    """Where to make a token for this host, and what it needs to be allowed.

    A self-hosted GitLab keeps the page at the same path as gitlab.com, so the
    address it was given is enough to find it.
    """
    host = host_of(url)
    if host in GITHUB_HOSTS:
        return TOKEN_PAGES["github.com"]
    if not host:
        return ("", "")
    page, rights = TOKEN_PAGES["gitlab.com"]
    if host != "gitlab.com":
        page = f"https://{host}/-/user_settings/personal_access_tokens"
    return page, rights


# --------------------------------------------------------------------------
# entries
# --------------------------------------------------------------------------


def clean_entry(raw):
    """One entry, reduced to what this program uses, or nothing.

    The catalog is a file from the internet and a favourite is typed by hand,
    so both arrive here before anything is shown: a row without a name or
    without a repository has nothing to offer and is dropped rather than drawn
    as an empty line.
    """
    if not isinstance(raw, dict):
        return None
    entry = {key: str(raw.get(key, "") or "").strip() for key in ENTRY_KEYS}
    if not entry["name"] or not entry["repository"]:
        return None
    if not entry["repository"].lower().startswith(("http://", "https://")):
        return None  # Portainer clones over HTTP(S); anything else is not ours
    return entry


def read_catalog(text):
    """The entries in a catalog file, however much of it makes sense.

    Either a bare list or an object with ``stacks`` in it, so the file can grow
    a version or a note at the top later without breaking older programs.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise core.ApiError("the catalog is not readable JSON") from None
    if isinstance(data, dict):
        data = data.get("stacks") or data.get("entries") or []
    if not isinstance(data, list):
        raise core.ApiError("the catalog holds no list of stacks")
    found = [clean_entry(raw) for raw in data]
    return [entry for entry in found if entry]


def fetch_catalog(url=CATALOG_URL, timeout=15):
    """Read the curated list from the program's own repository."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": f"opnsense-haproxy/{core.VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read(MAX_CATALOG + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise core.ApiError("this version of the program has no catalog "
                                "published yet") from None
        raise core.ApiError(f"the catalog answered {exc.code} "
                            f"{exc.reason}") from None
    except urllib.error.URLError as exc:
        raise core.ApiError(f"cannot reach the catalog: {exc.reason}") from None
    if len(body) > MAX_CATALOG:
        raise core.ApiError("the catalog is far bigger than expected")
    return read_catalog(body.decode(errors="replace"))


def local_catalog():
    """The copy that came with the program, for when GitHub cannot be reached.

    It is as old as the installed version, which is exactly why it is only the
    fallback: the point of keeping the list in the repository is that it can
    grow between releases.
    """
    path = os.path.join(core.install_dir(), "catalog.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return read_catalog(handle.read())
    except (OSError, core.ApiError):
        return []


# --------------------------------------------------------------------------
# favourites -- the same entries, kept in the settings file
# --------------------------------------------------------------------------


def favourites_of(config):
    """What the settings file has under ``favorites``, cleaned up."""
    listed = config.get("favorites") if isinstance(config, dict) else None
    if not isinstance(listed, list):
        return []
    found = [clean_entry(raw) for raw in listed]
    return [entry for entry in found if entry]


def put_favourite(favourites, entry, previous=""):
    """Add one or replace the one that had this name, keeping the order."""
    entry = clean_entry(entry)
    if not entry:
        return list(favourites)
    wanted = previous or entry["name"]
    result = list(favourites)
    for index, known in enumerate(result):
        if known["name"] == wanted:
            result[index] = entry
            return result
    result.append(entry)
    return result


def drop_favourite(favourites, name):
    return [entry for entry in favourites if entry["name"] != name]


def is_favourite(favourites, entry):
    """Whether this very repository is already among the favourites.

    By repository rather than by name: the same stack under two names is one
    entry too many, and the name is the part somebody changes.
    """
    wanted = str(entry.get("repository", "")).rstrip("/").lower()
    return any(known["repository"].rstrip("/").lower() == wanted
               for known in favourites)


# --------------------------------------------------------------------------
# Git accounts
# --------------------------------------------------------------------------


def accounts_of(systems):
    return [entry for entry in (systems or {}).get("git", [])
            if isinstance(entry, dict)]


def account_for(systems, repository):
    """The account that belongs to the machine this repository is on.

    Matched by host: a token for github.com is the answer for every repository
    on github.com, which is what makes deploying an own repository from the
    list need no further bookkeeping.
    """
    host = host_of(repository)
    if not host:
        return {}
    for entry in accounts_of(systems):
        if host_of(entry.get("url", "")) == host:
            return entry
    return {}


def credentials_for(systems, repository):
    """User name and token for that repository, or two empty strings."""
    account = account_for(systems, repository)
    if not account or not account.get("token"):
        return "", ""
    return str(account.get("username", "")), str(account.get("token", ""))


def _json_get(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode(errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise core.ApiError(
                f"the account refused the token ({exc.code}) -- it may have "
                "expired, or it may not be allowed to read repositories"
            ) from None
        raise core.ApiError(f"the Git host answered {exc.code} "
                            f"{exc.reason}") from None
    except urllib.error.URLError as exc:
        raise core.ApiError(f"cannot reach the Git host: {exc.reason}") from None
    except json.JSONDecodeError:
        raise core.ApiError("the Git host sent a reply that is not JSON") from None


def _github_repos(account, timeout, pages=3):
    """The repositories this token can see, newest activity first."""
    headers = {"Accept": "application/vnd.github+json",
               "Authorization": f"Bearer {account.get('token', '')}",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": f"opnsense-haproxy/{core.VERSION}"}
    found = []
    for page in range(1, pages + 1):
        batch = _json_get(
            f"{GITHUB_API}/user/repos?per_page=100&sort=pushed&page={page}",
            headers, timeout)
        if not isinstance(batch, list) or not batch:
            break
        found.extend(batch)
        if len(batch) < 100:
            break
    return [{"name": str(raw.get("name", "")),
             "description": str(raw.get("description") or ""),
             "repository": str(raw.get("clone_url") or raw.get("html_url") or ""),
             "reference": "",
             "compose_file": "",
             "homepage": str(raw.get("html_url") or ""),
             "private": bool(raw.get("private"))}
            for raw in found if isinstance(raw, dict)]


def _gitlab_repos(account, timeout, pages=3):
    base = str(account.get("url", "")).strip().rstrip("/") or "https://gitlab.com"
    if "://" not in base:
        base = "https://" + base
    headers = {"Accept": "application/json",
               "PRIVATE-TOKEN": str(account.get("token", "")),
               "User-Agent": f"opnsense-haproxy/{core.VERSION}"}
    found = []
    for page in range(1, pages + 1):
        batch = _json_get(
            f"{base}/api/v4/projects?membership=true&per_page=100"
            f"&order_by=last_activity_at&page={page}", headers, timeout)
        if not isinstance(batch, list) or not batch:
            break
        found.extend(batch)
        if len(batch) < 100:
            break
    return [{"name": str(raw.get("path") or raw.get("name", "")),
             "description": str(raw.get("description") or ""),
             "repository": str(raw.get("http_url_to_repo") or ""),
             "reference": "",
             "compose_file": "",
             "homepage": str(raw.get("web_url") or ""),
             "private": str(raw.get("visibility", "")) != "public"}
            for raw in found if isinstance(raw, dict)]


def own_repos(account, timeout=20):
    """Every repository the account's token may see, ready to deploy from.

    GitHub and GitLab answer differently but mean the same thing, so both are
    reduced to the entry shape the list shows. Anything else -- a Gitea, a bare
    git server -- has no listing here; its repositories still deploy, they just
    have to be typed in.
    """
    if not account or not account.get("token"):
        raise core.UsageError("this account has no token")
    entries = (_github_repos(account, timeout) if is_github(account.get("url"))
               else _gitlab_repos(account, timeout))
    named = [entry for entry in entries if entry["name"] and entry["repository"]]
    named.sort(key=lambda entry: entry["name"].lower())
    return named
