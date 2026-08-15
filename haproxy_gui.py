#!/usr/bin/env python3
"""Desktop interface for opnsense_haproxy.

A plain tkinter window -- no browser, no server, no third party packages.
All API work happens in a background thread and is handed back to the UI
through a queue, so the window never freezes while OPNsense is thinking.
"""

import argparse
import itertools
import json
import os
import queue
import sys
import threading
import time
import webbrowser

try:
    import tkinter as tk
    from tkinter import filedialog
    from tkinter import font as tkfont
    from tkinter import messagebox, ttk
except ImportError:  # tkinter ships separately on most Linux distributions
    raise SystemExit(
        "error: Python's tkinter module is missing.\n"
        "  Debian/Ubuntu : sudo apt install python3-tk\n"
        "  Fedora        : sudo dnf install python3-tkinter\n"
        "  Arch          : sudo pacman -S tk\n"
        "  openSUSE      : sudo zypper install python3-tk"
    ) from None

import opnsense_haproxy as core

try:
    import catalog
except ImportError:
    catalog = None  # see NoCatalog below -- the window still has to open

class NoCatalog:
    """Stands in for catalog.py when an old update did not bring it along.

    An update run by a version that predates a file copies everything except
    that file, and a program that imports it outright then does not start at
    all -- which is the worst way to find out. So the import above is allowed
    to fail and this takes over: the window opens, the Portainer tab says what
    is missing, and one more update from in there fetches it.

    ``favourites_of`` hands back what stands in the file untouched rather than
    an empty list. They are only ever edited from the Portainer half, which is
    not there either in this state -- but they are written back on every save,
    and a saved empty list would quietly delete them.
    """

    @staticmethod
    def favourites_of(config):
        listed = config.get("favorites") if isinstance(config, dict) else None
        return list(listed) if isinstance(listed, list) else []

    @staticmethod
    def put_favourite(favourites, _entry, _previous=""):
        return list(favourites)

    @staticmethod
    def drop_favourite(favourites, _name):
        return list(favourites)

    @staticmethod
    def token_page(_url):
        return "", ""


if catalog is None:
    catalog = NoCatalog

APP_TITLE = "HAProxy · OPNsense"
AUTHOR_URL = "https://github.com/DukyNuky/opnsense-haproxy-config"
NO_BASE = "— keine —"
NO_DNS = "— kein DNS-Eintrag —"
NO_CERT = "— kein Zertifikat —"
# What a listener can be, in the words of what it does rather than the
# plugin's own. Only these three; the ids are the plugin's.
LISTENER_MODES = {
    "tcp": "TCP — TLS endet hier",
    "ssl": "SSL — durchgereicht, nur nach SNI sortiert",
    "http": "HTTP — der übliche Web-Eingang",
}
LISTENER_MODE_HINTS = {
    "tcp": "HAProxy nimmt die Verbindung an, beendet dort die "
           "TLS-Verschlüsselung und reicht den Inhalt weiter. Das ist der "
           "Fall für TURN, IMAP, SMTP oder eine Datenbank.",
    "ssl": "Die Verschlüsselung bleibt bis zum Dienst bestehen; HAProxy "
           "liest nur den Namen aus dem Handshake. Der Dienst braucht dann "
           "sein eigenes Zertifikat.",
    "http": "Wie der Eingang, an dem die Hosts aus dem ersten Formular "
            "hängen — mit Host-Header, Pfaden und X-Forwarded-For.",
}
NO_HEALTHCHECK = "— keiner —"
EDIT_PROFILE = "⚙ Einstellungen …"
TOKEN_LOGIN = "Zugriffstoken"
USER_LOGIN = "Benutzer und Passwort"
# what the picker in the header is for -- it changes with the tab in front
SWITCHER_TIP = {"opnsense": "Welche OPNsense gemeint ist",
                "portainer": "Auf welchem Portainer gearbeitet wird",
                "adguard": "Welches AdGuard gezeigt wird"}

THEMES = {
    "light": {
        "bg": "#f2f4f7", "surface": "#ffffff", "surface2": "#f7f8fa",
        "border": "#dfe3ea", "border_strong": "#c8cedb",
        "text": "#14161b", "muted": "#5f6878",
        "accent": "#3563e9", "accent_text": "#ffffff", "accent_soft": "#e8eeff",
        "ok": "#0f8a4d", "ok_soft": "#e6f6ec",
        "danger": "#cf2b3a", "danger_soft": "#fdecee",
        "warn": "#a8710f",
    },
    "dark": {
        "bg": "#0f1218", "surface": "#161a23", "surface2": "#1c212c",
        "border": "#272d3a", "border_strong": "#3a4254",
        "text": "#e7eaf1", "muted": "#8d96a9",
        "accent": "#5b87ff", "accent_text": "#0b0e15", "accent_soft": "#1b2440",
        "ok": "#48d17f", "ok_soft": "#152a1e",
        "danger": "#ff6b74", "danger_soft": "#2c1a1e",
        "warn": "#e3b341",
    },
}

SETTINGS_FILE = os.path.expanduser("~/.config/opnsense-haproxy/gui.json")


def load_prefs():
    try:
        with open(SETTINGS_FILE) as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_prefs(prefs):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as handle:
            json.dump(prefs, handle, indent=2)
    except OSError:
        pass  # a missing preference file is not worth bothering the user with


# --------------------------------------------------------------------------
# widgets
# --------------------------------------------------------------------------


class LiveLog(core.LogRecorder):
    """Keeps the full log and shows each line as it happens."""

    def __init__(self, report):
        super().__init__()
        self.report = report

    def __call__(self, *parts, file=None):
        super().__call__(*parts, file=file)
        text = " ".join(str(part) for part in parts).strip()
        if text:
            self.report(text)


class Tooltip:
    """Explains an icon button after a short hover -- tkinter has no such thing.

    The colours are read when the tip appears rather than kept, so switching
    between the light and dark theme needs no bookkeeping here.
    """

    DELAY = 550

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self.job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, _event=None):
        self._cancel()
        self.job = self.widget.after(self.DELAY, self._show)

    def _cancel(self):
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None

    def _hide(self, _event=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _show(self):
        self.job = None
        if self.tip is not None or not self.widget.winfo_exists():
            return
        app = self.widget.winfo_toplevel()
        colors = getattr(app, "colors", THEMES["dark"])
        self.tip = tk.Toplevel(self.widget, bg=colors["border_strong"])
        self.tip.wm_overrideredirect(True)  # no title bar, no shadow, no focus
        tk.Label(self.tip, text=self.text, bg=colors["surface2"],
                 fg=colors["text"], padx=8, pady=4,
                 font=getattr(app, "font_small", None)).pack(padx=1, pady=1)
        self.tip.update_idletasks()
        x = (self.widget.winfo_rootx() + self.widget.winfo_width() // 2
             - self.tip.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.wm_geometry(f"+{max(x, 0)}+{y}")


def link_label(parent, colors, text, url, style="Link.TLabel", tip=""):
    """A name that opens a page in the browser when it is clicked.

    Only the colour reacts to the mouse. Anything that changes the font
    changes the size the label asks for, and the row underneath it moves.

    ``url`` may be a function instead of a string: a link that is built from a
    field somebody is still filling in -- the address of their own Portainer,
    say -- has to ask where it goes at the moment it is clicked, not while the
    window is being drawn.
    """
    def go(_event=None):
        target = url() if callable(url) else url
        if target:
            webbrowser.open(target)

    def hover(_event=None):
        # the window itself knows the theme in force, which is what makes the
        # colour follow a switch between light and dark while it is open
        live = getattr(link.winfo_toplevel(), "colors", colors)
        link.configure(foreground=live["text"])

    link = ttk.Label(parent, text=text, style=style, cursor="hand2")
    link.bind("<Button-1>", go)
    link.bind("<Enter>", hover)
    link.bind("<Leave>", lambda _e: link.configure(foreground=""))
    Tooltip(link, tip or ("Öffnet die Seite im Browser" if callable(url)
                          else f"{url}  öffnen"))
    return link


class Switch(tk.Canvas):
    """A sliding on/off toggle -- tkinter has no such widget of its own."""

    WIDTH, HEIGHT = 42, 24

    def __init__(self, parent, colors, command=None, **kwargs):
        super().__init__(parent, width=self.WIDTH, height=self.HEIGHT,
                         highlightthickness=0, bd=0, **kwargs)
        self.colors = colors
        self.command = command
        self._on = False
        self.bind("<Button-1>", self._clicked)
        self.configure(cursor="hand2")
        self.redraw()

    def _clicked(self, _event):
        self.set(not self._on)
        if self.command:
            self.command()

    def get(self):
        return self._on

    def set(self, value):
        self._on = bool(value)
        self.redraw()

    def apply_theme(self, colors, background):
        self.colors = colors
        self.configure(bg=background)
        self.redraw()

    def redraw(self):
        self.delete("all")
        radius = self.HEIGHT / 2
        track = self.colors["accent"] if self._on else self.colors["border_strong"]
        self._rounded(0, 0, self.WIDTH, self.HEIGHT, radius, track)
        knob = 3
        size = self.HEIGHT - 2 * knob
        left = self.WIDTH - size - knob if self._on else knob
        self.create_oval(left, knob, left + size, knob + size,
                         fill="#ffffff", outline="")

    def _rounded(self, x1, y1, x2, y2, radius, color):
        self.create_oval(x1, y1, x1 + 2 * radius, y2, fill=color, outline="")
        self.create_oval(x2 - 2 * radius, y1, x2, y2, fill=color, outline="")
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2,
                              fill=color, outline="")


class ScrollFrame(ttk.Frame):
    """A vertically scrollable container built from a canvas."""

    def __init__(self, parent, colors, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                bg=colors["surface"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Card.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        for widget in (self.canvas, self.body):
            widget.bind("<Enter>", lambda _e: self._bind_wheel(True))
            widget.bind("<Leave>", lambda _e: self._bind_wheel(False))

    def _on_body(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, on):
        widget = self.winfo_toplevel()
        if on:
            widget.bind_all("<MouseWheel>", self._wheel)
            widget.bind_all("<Button-4>", self._wheel)
            widget.bind_all("<Button-5>", self._wheel)
        else:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.unbind_all(sequence)

    def _wheel(self, event):
        if not self.canvas.winfo_exists():
            return
        step = -1 if getattr(event, "num", 0) == 4 or event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def apply_theme(self, colors):
        self.canvas.configure(bg=colors["surface"])


class MissingTab(ttk.Frame):
    """Stands in for a tab whose files did not come along.

    An update run by a version that predates a half of the program copies only
    the files it knows, which leaves this program without them. Rather than
    refusing to start, the tab says so and points at the download.
    """

    connected = False
    configured = False

    def __init__(self, parent, app, part="Portainer"):
        super().__init__(parent, style="TFrame")
        self.app = app
        self.part = part
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        card = ttk.Frame(self, style="Card.TFrame", padding=30)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=f"Der {part}-Teil fehlt", style="H2.TLabel",
                  anchor="center").grid(row=0, column=0, sticky="ew")
        ttk.Label(card, style="Hint.TLabel", anchor="center", justify="center",
                  wraplength=460,
                  text=f"Beim Aktualisieren {self._missing()} nicht "
                       "mitgekommen. Ein Update von hier aus holt das nach — "
                       "danach das Programm einmal neu starten, und der Tab "
                       "ist da.").grid(row=1, column=0, sticky="ew",
                                       pady=(6, 12))
        # a button of its own, so _set_busy has the same handle it has on the
        # real tab
        self.deploy_button = ttk.Button(card, text="Update holen",
                                        style="Accent.TButton",
                                        command=self.app._check_update)
        self.deploy_button.grid(row=2, column=0)
        # der Weg von Hand bleibt daneben stehen: in einer Arbeitskopie oder in
        # einem schreibgeschützten Ordner lehnt das Update ab
        self.app._link(card, "oder das Paket von Hand herunterladen",
                       AUTHOR_URL + "/releases/latest").grid(
            row=3, column=0, pady=(12, 0))

    @staticmethod
    def _missing():
        """Which files are actually not there, in words, or a fallback.

        Naming them is worth the look on disk: the answer is different for an
        update that stopped before portainer.py than for one that stopped
        before catalog.py, and only one of the two is worth searching for.
        """
        folder = core.install_dir()
        gone = [name for name in core.ESSENTIAL_FILES
                if not os.path.exists(os.path.join(folder, name))]
        if not gone:
            return "ist eine Datei dieses Programms"
        if len(gone) == 1:
            return f"ist {gone[0]}"
        return "sind " + ", ".join(gone[:-1]) + f" und {gone[-1]}"

    def busy_buttons(self):
        return (self.deploy_button,)

    def status_text(self):
        return f"{self.part}-Teil fehlt", False

    def use_profile(self, _profile):
        pass

    def take(self, _entries, _error=""):
        pass

    def render(self):
        pass

    def apply_theme(self):
        pass

    def reload(self):
        self.app.write_log(
            self.part, [{"text": f"Die Dateien für den {self.part}-Teil fehlen "
                                 "in diesem Ordner.", "level": "error"}], False)


# --------------------------------------------------------------------------
# connection dialog
# --------------------------------------------------------------------------


SYSTEM_TITLES = {"opnsense": "OPNsense", "adguard": "AdGuard Home",
                 "portainer": "Portainer", "git": "Git-Konto"}
SYSTEM_ONE = {"opnsense": "OPNsense", "adguard": "AdGuard",
              "portainer": "Portainer", "git": "Git-Konto"}
SYSTEM_HINTS = {
    "opnsense": "Die Firewall mit HAProxy darauf. Hier entstehen Real Server, "
                "Backend, Condition und Rule.",
    "adguard": "Der DNS-Server, der die Namen auf HAProxy zeigen lässt. "
               "Mehrere OPNsense dürfen sich einen teilen.",
    "portainer": "Der Docker-Host, dessen Stacks und Ports im zweiten Tab "
                 "stehen.",
    "git": "GitHub oder GitLab. Mit dem Token listet das Programm die eigenen "
           "Repositories auf, und ein privates Repository deployt damit, ohne "
           "dass jedes Mal etwas eingetippt werden muss.",
}
# What each editor asks for, in the order it asks. Everything else about a
# system -- the frontend it last used, the defaults of its form -- is kept
# untouched next to these, so editing an address never loses it.
SYSTEM_FIELDS = {
    "opnsense": (("Name", "name", False, "z.B. Zuhause oder Büro"),
                 ("Adresse", "url", False, "https://opnsense.example.de"),
                 ("API-Key", "key", False, ""),
                 ("API-Secret", "secret", True, ""),
                 ("IP von HAProxy", "haproxy_ip", False,
                  "Darauf zeigen die DNS-Einträge, z.B. 192.168.1.1")),
    "adguard": (("Name", "name", False, "z.B. Zuhause"),
                ("Adresse", "url", False, "https://adguard.example.de"),
                ("Benutzer", "username", False, ""),
                ("Passwort", "password", True, ""),
                ("Ziel der Umschreibung", "target", False,
                 "leer = die HAProxy-IP der OPNsense")),
    "portainer": (("Name", "name", False, "z.B. Docker Zuhause"),
                  ("Adresse", "url", False,
                   "https://portainer.example.de:9443")),
    "git": (("Name", "name", False, "z.B. GitHub privat"),
            ("Adresse", "url", False,
             "Bei einem eigenen Server nur dessen Adresse, ohne Benutzer und "
             "Repository — z.B. https://git.example.de"),
            ("Benutzer", "username", False, "dein Anmeldename dort"),
            ("Token", "token", True, "")),
}
# The two big ones write their own address, so nobody has to know that only
# the machine belongs in that field: a profile page pasted in there points at
# the right host but at the wrong thing, and a GitLab of one's own would then
# be looked up under a path that holds no API.
GIT_HOSTS = (("GitHub", "https://github.com"),
             ("GitLab", "https://gitlab.com"),
             ("Eigener Server", ""))
# Where the fields that ask for a key or a token are handed one out. The two
# paths are appended to the address in the form above them, so the link leads
# to the machine being set up and not to a manual about somebody else's.
OPNSENSE_USERS_PATH = "/system_usermanager.php"
OPNSENSE_API_DOCS = "https://docs.opnsense.org/development/how-tos/api.html"
PORTAINER_TOKENS_PATH = "/#!/account/tokens"
# A Git account has no such switch: this program never connects to it with a
# certificate of its own to check -- Portainer does the cloning, and the repo
# listing goes to the official API over ordinary TLS.
VERIFY_LABEL = {"opnsense": "TLS-Zertifikat der OPNsense prüfen",
                "adguard": "TLS-Zertifikat von AdGuard prüfen",
                "portainer": "TLS-Zertifikat von Portainer prüfen"}
NO_LINK = "— keiner —"


def page_on(url, path):
    """One page on the machine whose address stands in the form, or nothing.

    The address is being typed while the link already sits under it, so half of
    one is the normal case: a link that stays quiet is better than a browser
    opening on nonsense.
    """
    address = str(url or "").strip().rstrip("/")
    if not address:
        return ""
    if "://" not in address:
        address = "https://" + address
    return address + path


class SystemDialog(tk.Toplevel):
    """Edits exactly one system: a firewall, an AdGuard or a Portainer.

    One kind at a time, so the form stays short enough to read in one go. The
    three used to sit in a single dialog underneath each other, which is what
    made the old settings hard to take in.
    """

    def __init__(self, parent, colors, kind, entry, taken_names=(),
                 systems=None, can_delete=False):
        super().__init__(parent)
        self.kind = kind
        self.colors = colors
        self.systems = systems or {}
        self.result = None
        self.delete_requested = False
        self.original_name = entry.get("name", "")
        self.taken_names = {n for n in taken_names if n != self.original_name}
        shown = {name for _l, name, _s, _h in SYSTEM_FIELDS[kind]}
        shown.update(("verify_ssl", "api_key", "username", "password",
                      "host_ip", "adguard", "portainer"))
        self.extra = {k: v for k, v in entry.items() if k not in shown}
        self.title(f"{SYSTEM_TITLES[kind]} bearbeiten" if self.original_name
                   else f"{SYSTEM_TITLES[kind]} hinzufügen")
        self.transient(parent)
        self.configure(bg=colors["bg"])

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.scroll = ScrollFrame(self, colors)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)

        body = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=22)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text=SYSTEM_TITLES[kind], style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, text=SYSTEM_HINTS[kind], style="Hint.TLabel",
                  wraplength=420, justify="left").grid(row=next(rows), column=0,
                                                       sticky="w", pady=(3, 12))

        self.vars = {}
        self.fields = {}
        for label, name, secret, hint in SYSTEM_FIELDS[kind]:
            self.vars[name] = tk.StringVar(value=str(entry.get(name, "")))
            if kind == "git" and name == "url":
                self._build_git_host(body, rows, entry)
            ttk.Label(body, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(8, 3))
            self.fields[name] = ttk.Entry(
                body, textvariable=self.vars[name], width=46,
                style="Card.TEntry", show="•" if secret else "")
            self.fields[name].grid(row=next(rows), column=0, sticky="ew")
            if hint:
                ttk.Label(body, text=hint, style="Hint.TLabel").grid(
                    row=next(rows), column=0, sticky="w", pady=(2, 0))
            self._field_help(body, rows, name)
        if kind == "git":
            self._git_host_chosen()

        if kind == "portainer":
            self._build_portainer(body, rows, entry)
        if kind == "opnsense":
            self._build_links(body, rows, entry)

        self.verify = tk.BooleanVar(value=bool(entry.get("verify_ssl", False)))
        if kind in VERIFY_LABEL:
            ttk.Checkbutton(body, text=VERIFY_LABEL[kind], variable=self.verify,
                            style="Card.TCheckbutton").grid(
                row=next(rows), column=0, sticky="w", pady=(14, 0))
        self.footer = footer = ttk.Frame(self, style="Card.TFrame",
                                         padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        if can_delete:
            ttk.Button(footer, text="Löschen", style="Del.TButton",
                       command=self._delete).grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Speichern", style="Accent.TButton",
                   command=self._save).grid(row=0, column=1)

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _fit_dialog(self, parent, self.scroll, self.footer, floor=460)
        self.grab_set()

    def _field_help(self, body, rows, field):
        """Under the field that asks for a key: how to get one, and where.

        At the field rather than at the end of the form -- somebody who has no
        API key yet needs the way there at the moment they run out of things to
        type, not three fields further down.
        """
        if self.kind == "git" and field == "username":
            # what the two fields above add up to: the page whose repositories
            # this account is going to list, spelled out while it is typed
            self.git_account = ttk.Label(body, style="Hint.TLabel",
                                         wraplength=420, justify="left", text="")
            self.git_account.grid(row=next(rows), column=0, sticky="w",
                                  pady=(2, 0))
            self.vars["username"].trace_add(
                "write", lambda *_a: self._git_account_hint())
            return
        if self.kind == "git" and field == "token":
            self._git_help(body, rows)
            return
        if self.kind != "opnsense" or field != "secret":
            return
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="Key und Secret entstehen zusammen: in OPNsense unter "
                       "System → Zugriff → Benutzer, dort rechts in der Zeile "
                       "des Benutzers auf das Briefmarken-Symbol. OPNsense "
                       "lädt daraufhin eine apikey.txt mit beiden Zeilen "
                       "herunter — das Secret zeigt es kein zweites Mal. Der "
                       "Benutzer braucht das Recht „Services: HAProxy“.").grid(
            row=next(rows), column=0, sticky="w", pady=(6, 0))
        links = ttk.Frame(body, style="Card.TFrame")
        links.grid(row=next(rows), column=0, sticky="w", pady=(4, 0))
        link_label(links, self.colors, "Benutzer in OPNsense öffnen",
                   lambda: page_on(self.vars["url"].get(), OPNSENSE_USERS_PATH),
                   style="CardLink.TLabel",
                   tip="Öffnet die Adresse von oben mit "
                       f"{OPNSENSE_USERS_PATH}").grid(row=0, column=0)
        link_label(links, self.colors, "Anleitung", OPNSENSE_API_DOCS,
                   style="CardLink.TLabel").grid(row=0, column=1, padx=(14, 0))

    def _git_help(self, body, rows):
        """Which rights the token needs, and the page that hands one out.

        The page follows the address in the form: gitlab.com and a GitLab of
        one's own keep it at the same path, so the link lands on the right
        machine without anybody having to say which kind it is.
        """
        self.git_hint = ttk.Label(body, style="Hint.TLabel", wraplength=420,
                                  justify="left", text="")
        self.git_hint.grid(row=next(rows), column=0, sticky="w", pady=(6, 0))
        links = ttk.Frame(body, style="Card.TFrame")
        links.grid(row=next(rows), column=0, sticky="w", pady=(4, 0))
        link_label(links, self.colors, "Token anlegen",
                   lambda: catalog.token_page(self.vars["url"].get())[0],
                   style="CardLink.TLabel",
                   tip="Öffnet die Seite für neue Token auf dem Host von oben "
                       "— bei GitHub mit den nötigen Scopes schon "
                       "angehakt").grid(row=0, column=0)
        self.git_narrow = link_label(links, self.colors,
                                     "oder Fine-grained Token",
                                     catalog.GITHUB_FINE_GRAINED,
                                     style="CardLink.TLabel",
                                     tip="Engere Rechte: Contents Read-only. "
                                         "Reicht für alles außer privaten "
                                         "Images aus ghcr.io")
        self.git_narrow.grid(row=0, column=1, padx=(14, 0))
        self.vars["url"].trace_add("write", lambda *_a: self._git_url_changed())
        self._git_rights()

    def _build_git_host(self, body, rows, entry):
        """Which Git host the account is on -- picked instead of typed.

        Only the machine belongs in the address underneath, and for GitHub and
        for GitLab it is the same machine for everybody. Typing it invites the
        two mistakes that look like a working account until something is
        deployed: a profile page pasted in, and a bare name that reads like an
        address but is one only by luck. So the two write their own address,
        and typing stays for the server somebody runs themselves.
        """
        known = {catalog.host_of(url): label for label, url in GIT_HOSTS if url}
        host = catalog.host_of(entry.get("url", ""))
        self.git_host = tk.StringVar(
            value=known.get(host) or (GIT_HOSTS[-1][0] if host
                                      else GIT_HOSTS[0][0]))
        ttk.Label(body, text="Anbieter", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(8, 3))
        choices = ttk.Frame(body, style="Card.TFrame")
        choices.grid(row=next(rows), column=0, sticky="w", pady=(0, 2))
        for column, (label, _url) in enumerate(GIT_HOSTS):
            ttk.Radiobutton(choices, text=label, value=label,
                            variable=self.git_host,
                            style="Card.TRadiobutton").grid(row=0, column=column,
                                                            padx=(0, 16))
        self.git_host.trace_add("write", lambda *_a: self._git_host_chosen())

    def _git_host_chosen(self):
        """Write the chosen host into the address, or hand the field over.

        The address stays visible either way rather than disappearing with the
        choice: it is what a deploy matches a repository against later, so it
        is worth seeing, and an own server needs it writable.
        """
        chosen = dict(GIT_HOSTS).get(self.git_host.get(), "")
        if chosen:
            self.vars["url"].set(chosen)
        self.fields["url"].configure(state="readonly" if chosen else "normal")
        self._git_account_hint()

    def _git_url_changed(self):
        self._git_rights()
        self._git_account_hint()

    def _git_account_hint(self):
        """Address and user name, put together the way they are meant."""
        address = catalog.base_url(self.vars["url"].get())
        user = self.vars["username"].get().strip()
        if address and user:
            text = (f"Ergibt {address}/{user} — von dort holt das Programm die "
                    "Liste der Repositories.")
        else:
            text = "Nur der Anmeldename, nicht die Adresse des Profils."
        self.git_account.configure(text=text)

    def _git_rights(self):
        """What the token has to be allowed, said for the host in the form.

        On GitHub that means the classic kind, and it is worth a sentence why:
        the tighter token is the better one everywhere except at the registry,
        and the registry is where the mistake only shows up -- two steps and
        one form later, in a message about a right rather than about a kind.
        """
        address = self.vars["url"].get()
        rights = catalog.token_page(address)[1]
        text = (f"Lesen genügt. {rights}." if rights else
                "Lesen genügt — der Token wird nur zum Auflisten der "
                "Repositories und zum Klonen durch Portainer benutzt.")
        if catalog.is_github(address):
            text += (" Klassisch und nicht fine-grained, weil ghcr.io "
                     "Fine-grained Tokens nicht annimmt: ein privates Image "
                     "scheitert damit später mit „denied“. Wer keine privaten "
                     "Images zieht, ist mit einem Fine-grained Token "
                     "(Contents: Read-only) enger dran.")
        self.git_hint.configure(
            text=text
            + " Der Token steht in der Konfigurationsdatei dieses Programms, "
              "sie liegt mit Rechten 600 im eigenen Benutzerordner.")
        self.git_narrow.grid() if catalog.is_github(address) \
            else self.git_narrow.grid_remove()

    def _build_portainer(self, body, rows, entry):
        """Token or user and password -- only one of the two is ever kept."""
        self.pt_method = tk.StringVar(
            value=USER_LOGIN if entry.get("username") else TOKEN_LOGIN)
        for name in ("api_key", "username", "password", "host_ip"):
            self.vars[name] = tk.StringVar(value=str(entry.get(name, "")))

        ttk.Label(body, text="Anmeldung", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(12, 3))
        ttk.Combobox(body, textvariable=self.pt_method, state="readonly",
                     values=[TOKEN_LOGIN, USER_LOGIN],
                     style="Card.TCombobox").grid(row=next(rows), column=0,
                                                  sticky="ew")

        self.pt_token_box = ttk.Frame(body, style="Card.TFrame")
        self.pt_token_box.grid(row=next(rows), column=0, sticky="ew")
        self.pt_token_box.columnconfigure(0, weight=1)
        ttk.Label(self.pt_token_box, text="Zugriffstoken",
                  style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w",
                                                  pady=(8, 3))
        ttk.Entry(self.pt_token_box, textvariable=self.vars["api_key"],
                  style="Card.TEntry", show="•").grid(row=1, column=0,
                                                      sticky="ew")
        ttk.Label(self.pt_token_box, style="Hint.TLabel", wraplength=420,
                  justify="left",
                  text="In Portainer oben rechts auf den Benutzer, dann "
                       "My account → Access tokens → Add access token. Das "
                       "Token steht nur einmal da, also gleich hierher "
                       "kopieren.").grid(row=2, column=0, sticky="w",
                                         pady=(2, 0))
        link_label(self.pt_token_box, self.colors,
                   "Access tokens in Portainer öffnen",
                   lambda: page_on(self.vars["url"].get(),
                                   PORTAINER_TOKENS_PATH),
                   style="CardLink.TLabel",
                   tip="Öffnet die Adresse von oben mit "
                       f"{PORTAINER_TOKENS_PATH}").grid(row=3, column=0,
                                                        sticky="w",
                                                        pady=(4, 0))

        self.pt_user_box = ttk.Frame(body, style="Card.TFrame")
        self.pt_user_box.grid(row=next(rows), column=0, sticky="ew")
        self.pt_user_box.columnconfigure(0, weight=1)
        user_rows = itertools.count()
        for label, name, secret in (("Benutzer", "username", False),
                                    ("Passwort", "password", True)):
            ttk.Label(self.pt_user_box, text=label,
                      style="FieldLabel.TLabel").grid(row=next(user_rows),
                                                      column=0, sticky="w",
                                                      pady=(8, 3))
            ttk.Entry(self.pt_user_box, textvariable=self.vars[name],
                      style="Card.TEntry",
                      show="•" if secret else "").grid(row=next(user_rows),
                                                       column=0, sticky="ew")

        ttk.Label(body, text="IP des Docker-Hosts",
                  style="FieldLabel.TLabel").grid(row=next(rows), column=0,
                                                  sticky="w", pady=(12, 3))
        ttk.Entry(body, textvariable=self.vars["host_ip"],
                  style="Card.TEntry").grid(row=next(rows), column=0,
                                            sticky="ew")
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="Dorthin schickt HAProxy die Anfragen für Container. "
                       "Leer = der Rechner aus der Adresse oben.").grid(
            row=next(rows), column=0, sticky="w", pady=(2, 0))
        self.pt_method.trace_add("write", lambda *_a: self._toggle_login())
        self._toggle_login()

    def _toggle_login(self):
        token = self.pt_method.get() == TOKEN_LOGIN
        self.pt_token_box.grid() if token else self.pt_token_box.grid_remove()
        self.pt_user_box.grid_remove() if token else self.pt_user_box.grid()

    def _build_links(self, body, rows, entry):
        """Which AdGuard and which Portainer this firewall works with.

        Only the starting point: both can be swapped for another one right
        before something is created, in the form and in the deploy dialog.
        """
        ttk.Separator(body, orient="horizontal").grid(row=next(rows), column=0,
                                                      sticky="ew", pady=16)
        ttk.Label(body, text="Arbeitet zusammen mit", style="Group.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="Die Vorauswahl für diese OPNsense. Beim Anlegen und "
                       "beim Deployen lässt sie sich jedes Mal ändern.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 8))
        self.links = {}
        for kind, label in (("adguard", "DNS über"),
                            ("portainer", "Docker über")):
            names = [e.get("name", "") for e in self.systems.get(kind, [])]
            current = entry.get(kind, "")
            self.links[kind] = tk.StringVar(
                value=current if current in names else NO_LINK)
            ttk.Label(body, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(8, 3))
            box = ttk.Combobox(body, textvariable=self.links[kind],
                               state="readonly", values=[NO_LINK] + names,
                               style="Card.TCombobox")
            box.grid(row=next(rows), column=0, sticky="ew")
            if not names:
                box.configure(state="disabled")
                ttk.Label(body, style="Hint.TLabel",
                          text=f"Noch kein {SYSTEM_ONE[kind]} eingerichtet.").grid(
                    row=next(rows), column=0, sticky="w", pady=(2, 0))

    def _delete(self):
        if messagebox.askyesno(
                APP_TITLE,
                f"„{self.original_name}“ aus den Einstellungen entfernen?\n\n"
                f"Es wird nur dieser Eintrag gelöscht, am {SYSTEM_ONE[self.kind]} "
                "selbst ändert sich nichts.", icon="warning", parent=self):
            self.delete_requested = True
            self.destroy()

    def _save(self):
        values = {name: var.get().strip() for name, var in self.vars.items()}
        required = [("Name", "name"), ("Adresse", "url")]
        if self.kind == "opnsense":
            required += [("API-Key", "key"), ("API-Secret", "secret")]
        if self.kind == "git":
            required += [("Benutzer", "username"), ("Token", "token")]
            # ``github.com`` is what people call the place; the program needs
            # an address, and putting the scheme there is nobody's job
            values["url"] = catalog.base_url(values["url"])
        missing = [label for label, name in required if not values.get(name)]
        if missing:
            messagebox.showwarning("Unvollständig",
                                   "Bitte ausfüllen: " + ", ".join(missing),
                                   parent=self)
            return
        if values["name"] in self.taken_names:
            messagebox.showwarning(
                "Name schon vergeben",
                f"Es gibt bereits einen Eintrag namens „{values['name']}“.",
                parent=self)
            return
        if self.kind == "portainer":
            # only one way in is kept, so a leftover from the other one cannot
            # decide the login later
            if self.pt_method.get() == TOKEN_LOGIN:
                values["username"] = values["password"] = ""
                if not values["api_key"]:
                    messagebox.showwarning(
                        "Unvollständig",
                        "Bitte das Zugriffstoken eintragen — oder auf Benutzer "
                        "und Passwort umstellen.", parent=self)
                    return
            else:
                values["api_key"] = ""
                if not (values["username"] and values["password"]):
                    messagebox.showwarning(
                        "Unvollständig",
                        "Bitte Benutzer und Passwort eintragen — oder auf "
                        "Zugriffstoken umstellen.", parent=self)
                    return
        entry = {k: v for k, v in values.items() if k in core.SYSTEM_KEYS[self.kind]}
        entry["verify_ssl"] = self.verify.get()
        if self.kind == "opnsense":
            for kind, var in self.links.items():
                chosen = var.get()
                if chosen and chosen != NO_LINK:
                    entry[kind] = chosen
            if not entry.get("haproxy_ip"):
                entry.pop("haproxy_ip", None)
        entry.update({k: v for k, v in self.extra.items() if k not in entry})
        self.result = entry
        self.destroy()


class SettingsDialog(tk.Toplevel):
    """Everything that is configured, in three lists under each other.

    Each change is written to the file straight away: with three lists and a
    dialog per entry, a single Save button at the end would have to remember
    far too much on the way there.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.colors = app.colors
        self.title("Einstellungen")
        self.transient(parent)
        self.configure(bg=self.colors["bg"])
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.scroll = ScrollFrame(self, self.colors)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)

        self.footer = footer = ttk.Frame(self, style="Card.TFrame",
                                         padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, style="Hint.TLabel", wraplength=520, justify="left",
                  text=f"Gespeichert in {app.config_path}").grid(row=0, column=0,
                                                                 sticky="w")
        ttk.Button(footer, text="Fertig", style="Accent.TButton",
                   command=self.destroy).grid(row=0, column=1, sticky="e")

        self._render()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _fit_dialog(self, parent, self.scroll, self.footer, floor=560)
        self.grab_set()

    def _render(self):
        self.scroll.clear()
        body = self.scroll.body
        body.columnconfigure(0, weight=1)
        rows = itertools.count()
        for kind in core.SYSTEM_KINDS:
            self._section(body, kind).grid(row=next(rows), column=0, sticky="ew",
                                           padx=18, pady=(18, 0))
        ttk.Frame(body, style="TFrame", height=18).grid(row=next(rows), column=0)

    def _section(self, parent, kind):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.columnconfigure(0, weight=1)
        rows = itertools.count()

        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=next(rows), column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text=SYSTEM_TITLES[kind], style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Button(head, text="+ Hinzufügen", style="Del.TButton",
                   command=lambda k=kind: self._edit(k, {})).grid(row=0, column=1,
                                                                  sticky="e")
        ttk.Label(card, text=SYSTEM_HINTS[kind], style="Hint.TLabel",
                  wraplength=520, justify="left").grid(row=next(rows), column=0,
                                                       sticky="w", pady=(3, 10))

        entries = self.app.systems.get(kind, [])
        if not entries:
            ttk.Label(card, style="RowHint.TLabel",
                      text=f"Noch kein {SYSTEM_ONE[kind]} eingerichtet.").grid(
                row=next(rows), column=0, sticky="w")
            return card
        for entry in entries:
            self._row(card, kind, entry).grid(row=next(rows), column=0,
                                              sticky="ew", pady=(0, 6))
        return card

    def _row(self, parent, kind, entry):
        row = tk.Frame(parent, bg=self.colors["surface2"], padx=12, pady=9)
        row.columnconfigure(0, weight=1)
        name = entry.get("name", "?")
        ttk.Label(row, text=name, style="Host.TLabel").grid(row=0, column=0,
                                                            sticky="w")
        # A Git account is not switched between: which one is used follows from
        # the address of the repository, so "active" would mean nothing here.
        if kind != "git" and name == self.app.active.get(kind):
            ttk.Label(row, text="aktiv", style="BadgeOk.TLabel").grid(
                row=0, column=1, padx=(8, 0))
        ttk.Label(row, text=entry.get("url", ""), style="Target.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        if kind == "opnsense":
            linked = "  ·  ".join(
                f"{label}: {entry.get(other) or '—'}"
                for other, label in (("adguard", "DNS"), ("portainer", "Docker")))
            ttk.Label(row, text=linked, style="RowHint.TLabel").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        if kind == "git":
            ttk.Label(row, text=f"als {entry.get('username') or '—'}",
                      style="RowHint.TLabel").grid(row=2, column=0, columnspan=2,
                                                   sticky="w", pady=(2, 0))
        ttk.Button(row, text="Bearbeiten", style="Del.TButton",
                   command=lambda: self._edit(kind, entry)).grid(row=0, column=2,
                                                                 rowspan=3,
                                                                 padx=(10, 0))
        return row

    def _edit(self, kind, entry):
        dialog = SystemDialog(self, self.colors, kind, entry,
                              taken_names=[e.get("name") for e
                                           in self.app.systems.get(kind, [])],
                              systems=self.app.systems,
                              can_delete=bool(entry))
        self.wait_window(dialog)
        if dialog.delete_requested:
            self.app.forget_system(kind, entry.get("name", ""))
            self._render()
            return
        if dialog.result is None:
            return
        self.app.remember_system(kind, entry.get("name", ""), dialog.result)
        self._render()


def _fit_dialog(window, parent, scroll, footer, floor=460):
    """Size a scrolled dialog to its content, but never past the screen.

    The size has to come from the scrolled content: a canvas reports its own
    default size, not what is inside it.
    """
    content = scroll.body.winfo_reqheight()
    width = max(scroll.body.winfo_reqwidth() + 18, floor)
    tallest = int(window.winfo_screenheight() * 0.85)
    height = min(content + footer.winfo_reqheight() + 4, tallest)
    window.geometry(f"{width}x{height}")
    window.minsize(width, min(420, height))
    window.resizable(False, True)
    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 3
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------


BLOCKED_TEXT = {
    "git": "Dieser Ordner ist eine git-Arbeitskopie. Bitte mit „git pull“ "
           "aktualisieren, damit eigene Änderungen nicht überschrieben werden.",
    "readonly": "Die Programmdateien in diesem Ordner dürfen nicht geändert "
                "werden. Starte das Programm mit den nötigen Rechten oder lege "
                "es in einen eigenen Ordner.",
}


class UpdateDialog(tk.Toplevel):
    """Shows what GitHub has to offer and installs it when asked to."""

    def __init__(self, parent, colors, release):
        super().__init__(parent)
        self.title("Update")
        self.app = parent
        self.release = release
        self.installed = None
        self.folder = core.install_dir()
        self.blocked = core.update_blocked(self.folder)
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text=f"Version {release['version']} ist verfügbar",
                  style="H2.TLabel").grid(row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel",
                  text=f"installiert: {core.VERSION}   ·   {release['page']}").grid(
            row=next(rows), column=0, sticky="w", pady=(2, 12))

        if release.get("notes"):
            notes = tk.Text(body, height=9, width=58, wrap="word", relief="flat",
                            bg=colors["surface2"], fg=colors["text"],
                            padx=10, pady=8, font=self.app.font_base)
            notes.insert("1.0", release["notes"])
            notes.configure(state="disabled")
            notes.grid(row=next(rows), column=0, sticky="ew")
        else:
            ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                      text="Zu dieser Version gibt es keine Beschreibung. "
                           "Was sich geändert hat, steht auf der Seite oben.").grid(
                row=next(rows), column=0, sticky="w")

        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text=f"Ersetzt werden nur die Programmdateien in {self.folder}. "
                       "Die bisherige Fassung wird vorher in einen Unterordner "
                       "kopiert, deine Zugangsdaten bleiben unangetastet.").grid(
            row=next(rows), column=0, sticky="w", pady=(12, 0))

        self.note = ttk.Label(body, style="Hint.TLabel", wraplength=420,
                              justify="left", text="")
        self.note.grid(row=next(rows), column=0, sticky="w", pady=(8, 0))
        self.note.grid_remove()

        self.progress = ttk.Progressbar(body, mode="indeterminate",
                                        style="Bar.Horizontal.TProgressbar")
        self.progress.grid(row=next(rows), column=0, sticky="ew", pady=(12, 0))
        self.progress.grid_remove()

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.later = ttk.Button(buttons, text="Später", style="Ghost.TButton",
                                command=self.destroy)
        self.later.grid(row=0, column=0, padx=(0, 8))
        self.action = ttk.Button(buttons, text="Jetzt installieren",
                                 style="Accent.TButton", command=self._install)
        self.action.grid(row=0, column=1)

        if self.blocked:
            self._say(BLOCKED_TEXT.get(self.blocked,
                                       "Hier kann nicht aktualisiert werden."))
            self.action.configure(state="disabled")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), 460)
        self.geometry(f"{width}x{self.winfo_reqheight()}")
        self.resizable(False, False)
        self.grab_set()

    def _say(self, text):
        self.note.configure(text=text)
        self.note.grid()

    def _install(self):
        self.action.configure(state="disabled")
        self.later.configure(state="disabled")
        self.progress.grid()
        self.progress.start(12)
        self._say("Update wird geladen …")

        # Progress arrives from the worker through the window's own queue, so
        # every widget change still happens on the UI thread.
        def report(text):
            self.app.results.put(("done", lambda _p: self._say(text), None,
                                  None, None))

        def task():
            try:
                result = core.install_update(self.release, self.folder, report)
                self.app.results.put(("done", self._done, None, result, None))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                # bound as a default: Python clears `exc` when the except block
                # ends, long before the UI thread runs this
                self.app.results.put(("done", lambda _p, error=exc: self._failed(error),
                                      None, None, None))

        threading.Thread(target=task, daemon=True).start()

    def _failed(self, error):
        self.progress.stop()
        self.progress.grid_remove()
        self.later.configure(state="normal", text="Schließen")
        self.action.configure(state="normal", text="Nochmal versuchen")
        self._say(f"Fehlgeschlagen: {error}\nEs wurde nichts verändert.")

    def _done(self, result):
        self.installed = result
        self.progress.stop()
        self.progress.grid_remove()
        self.app.update_release = None
        self.app.prefs["update_found"] = ""
        self.app._paint_update_button()
        self._say(f"Version {result['version']} ist installiert. "
                  "Sie wird nach einem Neustart des Programms verwendet.\n"
                  f"Die vorherige Fassung liegt in "
                  f"{os.path.basename(result['backup'])}.")
        self.later.configure(state="normal", text="Später neu starten")
        self.action.configure(state="normal", text="Jetzt neu starten",
                              command=self._restart)

    def _restart(self):
        self.destroy()
        self.app.restart()


class InstallDialog(tk.Toplevel):
    """Puts the program somewhere permanent and adds the starters for it."""

    def __init__(self, parent, colors):
        super().__init__(parent)
        self.title("Installieren")
        self.app = parent
        self.windows = os.name == "nt"
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text="Programm installieren", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=440, justify="left",
                  text="Kopiert das Programm in einen festen Ordner und legt "
                       "einen Starter an. Zugangsdaten bleiben, wo sie sind — "
                       "sie liegen ohnehin im eigenen Ordner unter ~/.config.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 14))

        self.var_target = tk.StringVar(value=core.default_install_dir())
        ttk.Label(body, text="Zielordner", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        picker = ttk.Frame(body, style="Card.TFrame")
        picker.grid(row=next(rows), column=0, sticky="ew", pady=(4, 12))
        picker.columnconfigure(0, weight=1)
        ttk.Entry(picker, textvariable=self.var_target, style="Card.TEntry",
                  font=self.app.font_mono).grid(row=0, column=0, sticky="ew")
        ttk.Button(picker, text="Wählen …", style="Ghost.TButton",
                   command=self._browse).grid(row=0, column=1, padx=(8, 0))

        self.var_menu = tk.BooleanVar(value=True)
        self.var_desktop = tk.BooleanVar(value=False)
        self.var_commands = tk.BooleanVar(value=not self.windows)

        ttk.Checkbutton(body, variable=self.var_menu, style="Card.TCheckbutton",
                        text="Ins Startmenü eintragen"
                             if self.windows else
                             "Ins Anwendungsmenü eintragen").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=440, justify="left",
                  text="Von dort lässt sich das Programm an die Taskleiste "
                       "anheften.").grid(row=next(rows), column=0, sticky="w",
                                         pady=(2, 8))

        ttk.Checkbutton(body, text="Verknüpfung auf dem Schreibtisch",
                        variable=self.var_desktop,
                        style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 8))

        if not self.windows:
            bin_dir = core.default_bin_dir()
            ttk.Checkbutton(
                body, text="Befehle fürs Terminal verlinken",
                variable=self.var_commands, style="Card.TCheckbutton").grid(
                row=next(rows), column=0, sticky="w")
            ttk.Label(body, style="Hint.TLabel", wraplength=440, justify="left",
                      text=f"haproxy-gui und opnsense-haproxy in {bin_dir}"
                           + ("" if core.on_path(bin_dir)
                              else "  ·  dieser Ordner ist nicht in deinem PATH")
                      ).grid(row=next(rows), column=0, sticky="w", pady=(2, 0))

        self.note = ttk.Label(body, style="Hint.TLabel", wraplength=440,
                              justify="left", text="")
        self.note.grid(row=next(rows), column=0, sticky="w", pady=(12, 0))
        self.note.grid_remove()

        self.progress = ttk.Progressbar(body, mode="indeterminate",
                                        style="Bar.Horizontal.TProgressbar")
        self.progress.grid(row=next(rows), column=0, sticky="ew", pady=(12, 0))
        self.progress.grid_remove()

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.close_button = ttk.Button(buttons, text="Abbrechen",
                                       style="Ghost.TButton", command=self.destroy)
        self.close_button.grid(row=0, column=0, padx=(0, 8))
        self.action = ttk.Button(buttons, text="Installieren",
                                 style="Accent.TButton", command=self._install)
        self.action.grid(row=0, column=1)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self.geometry(f"{max(self.winfo_reqwidth(), 500)}x{self.winfo_reqheight()}")
        self.resizable(False, False)
        self.grab_set()

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Zielordner",
                                         mustexist=False,
                                         initialdir=os.path.dirname(
                                             self.var_target.get()) or "/")
        if chosen:
            self.var_target.set(chosen)

    def _say(self, text):
        self.note.configure(text=text)
        self.note.grid()

    def _install(self):
        target = self.var_target.get().strip()
        if not target:
            self._say("Bitte einen Zielordner angeben.")
            return
        self.action.configure(state="disabled")
        self.close_button.configure(state="disabled")
        self.progress.grid()
        self.progress.start(12)
        self._say("wird installiert …")

        options = {"target": target, "menu": self.var_menu.get(),
                   "desktop": self.var_desktop.get(),
                   "commands": self.var_commands.get()}

        # progress travels through the window's queue, so every widget change
        # still happens on the UI thread
        def report(text):
            self.app.results.put(("done", lambda _p: self._say(text), None,
                                  None, None))

        def task():
            try:
                self.app.results.put(("done", self._done, None,
                                      core.install(report=report, **options),
                                      None))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                # bound as a default: Python clears `exc` when the except block
                # ends, long before the UI thread runs this
                self.app.results.put(("done",
                                      lambda _p, error=exc: self._failed(error),
                                      None, None, None))

        threading.Thread(target=task, daemon=True).start()

    def _failed(self, error):
        self.progress.stop()
        self.progress.grid_remove()
        self.close_button.configure(state="normal", text="Schließen")
        self.action.configure(state="normal", text="Nochmal versuchen")
        self._say(f"Fehlgeschlagen: {error}")

    def _done(self, result):
        self.progress.stop()
        self.progress.grid_remove()
        lines = ["Fertig." if not result["same"]
                 else "Das Programm lag schon dort — die Starter sind neu.",
                 f"Ordner: {result['target']}"]
        if result["menu"]:
            lines.append("Im Menü eingetragen — von dort an die Taskleiste "
                         "anheften.")
        if result["desktop"]:
            lines.append("Verknüpfung auf dem Schreibtisch angelegt.")
        if result["commands"]:
            lines.append("Befehle: " + ", ".join(
                sorted(os.path.basename(path) for path in result["commands"])))
        if result["path_hint"]:
            lines.append(f"Hinweis: {result['bin']} liegt nicht in deinem PATH. "
                         "Die Befehle gibt es dann nur mit vollem Pfad.")
        self._say("\n".join(lines))
        self.close_button.configure(state="normal", text="Schließen")
        self.action.grid_remove()


class FormDialog(tk.Toplevel):
    """What the two forms of the HAProxy tab have in common.

    Both stand in front of the window whose log they write into, so neither
    may be modal: a preview is meant to be read while the form is still
    standing. What they edit lives on the window (see ``_init_form_vars``), so
    closing one in the middle of typing loses nothing that was picked.
    """

    title_text = ""
    subtitle = ""
    floor = 780

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.colors = colors = app.colors
        self.title(self.title_text)
        self.transient(app)
        self.configure(bg=colors["bg"])
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.scroll = ScrollFrame(self, colors)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)

        body = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=22)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="half")
        body.columnconfigure(1, weight=1, uniform="half")

        ttk.Label(body, text=self.title_text, style="H2.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=700, justify="left",
                  text=self.subtitle).grid(row=1, column=0, columnspan=2,
                                           sticky="w", pady=(3, 16))

        left = ttk.Frame(body, style="Card.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        right = ttk.Frame(body, style="Card.TFrame")
        right.grid(row=2, column=1, sticky="nsew", padx=(12, 0))
        right.columnconfigure(0, weight=1)
        self.build(left, right)

        self.footer = footer = ttk.Frame(self, style="Card.TFrame",
                                         padding=(22, 12, 22, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.note = ttk.Label(footer, style="Hint.TLabel", text="",
                              wraplength=460, justify="left")
        self.note.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=1, padx=(0, 8))
        self.preview_button = ttk.Button(footer, text="Vorschau",
                                         style="Ghost.TButton",
                                         command=lambda: self.go(True))
        self.preview_button.grid(row=0, column=2, padx=(0, 8))
        self.submit_button = ttk.Button(footer, text=self.action_text,
                                        style="Accent.TButton",
                                        command=lambda: self.go(False))
        self.submit_button.grid(row=0, column=3)

        self.apply_theme(colors)
        self.refresh()
        self.bind("<Return>", lambda _e: self.go(False))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _fit_dialog(self, app, self.scroll, self.footer, floor=self.floor)

    # -- what the window asks of a form ------------------------------------

    def busy_buttons(self):
        return self.preview_button, self.submit_button

    def say(self, text, ok=True):
        """The one line the form itself shows: the log is behind it."""
        self.note.configure(text=text,
                            style="Hint.TLabel" if ok else "Bad.TLabel")

    def apply_theme(self, colors):
        self.colors = colors
        self.configure(bg=colors["bg"])
        self.scroll.apply_theme(colors)
        # the sliding switch paints itself, so it has to be told
        if getattr(self, "ssl_switch", None) is not None:
            self.ssl_switch.apply_theme(colors, colors["surface2"])
            self.switch_box.configure(bg=colors["surface2"],
                                      highlightbackground=colors["border"])

    def _field(self, parent, rows, label, variable, hint="", mono=True):
        """Label, entry and the sentence under it -- the shape every field has.

        ``rows`` is the counter the column hands out its rows from, so a field
        added in the middle cannot make two widgets share a row again.
        """
        ttk.Label(parent, text=label, style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        extra = {"font": self.app.font_mono} if mono else {}
        entry = ttk.Entry(parent, textvariable=variable, style="Card.TEntry",
                          **extra)
        entry.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        note = ttk.Label(parent, style="Hint.TLabel", text=hint, wraplength=340,
                         justify="left")
        note.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))
        return entry, note

    def _switch(self, parent, rows, variable, label, command):
        """The sliding switch with its two lines, on its own surface."""
        box = tk.Frame(parent, bg=self.colors["surface2"], highlightthickness=1,
                       bd=0)
        box.grid(row=next(rows), column=0, sticky="ew", pady=(0, 12))
        box.columnconfigure(1, weight=1)
        switch = Switch(box, self.colors, command=command)
        switch.set(bool(variable.get()))
        switch.grid(row=0, column=0, rowspan=2, padx=12, pady=10)
        ttk.Label(box, text=label, style="Switch.TLabel").grid(
            row=0, column=1, sticky="w", pady=(10, 0))
        note = ttk.Label(box, style="RowHint.TLabel", text="")
        note.grid(row=1, column=1, sticky="w", pady=(0, 10))
        return box, switch, note


class HostDialog(FormDialog):
    """A name that HAProxy answers for, and the server behind it."""

    title_text = "Neuer Host"
    action_text = "Anlegen"
    subtitle = ("Legt Real Server, Backend Pool, Condition und Rule an und "
                "hängt die Rule in den Public Service. Der Name wird dort am "
                "Host-Header (oder an der SNI) erkannt.")

    def build(self, left, right):
        app = self.app
        rows = itertools.count()

        ttk.Label(left, text="Basis-Domain", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.base_box = ttk.Combobox(left, textvariable=app.var_base,
                                     state="readonly", style="Card.TCombobox",
                                     values=[NO_BASE])
        self.base_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 12))
        self.base_box.bind("<<ComboboxSelected>>",
                           lambda _e: self.refresh_hints())

        entry, self.fqdn_hint = self._field(
            left, rows, "Hostname", app.var_target,
            "app.example.com oder https://example.com/api")
        entry.focus_set()
        self._fqdn_trace = app.var_target.trace_add(
            "write", lambda *_a: self.refresh_hints())

        pair = ttk.Frame(left, style="Card.TFrame")
        pair.grid(row=next(rows), column=0, sticky="ew")
        pair.columnconfigure(0, weight=1)
        ttk.Label(pair, text="Server-IP", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(pair, textvariable=app.var_ip, style="Card.TEntry",
                  font=app.font_mono).grid(row=1, column=0, sticky="ew",
                                           padx=(0, 10), pady=(4, 12))
        ttk.Label(pair, text="Port", style="FieldLabel.TLabel").grid(
            row=0, column=1, sticky="w")
        port = ttk.Entry(pair, textvariable=app.var_port, width=8,
                         style="Card.TEntry", font=app.font_mono)
        port.grid(row=1, column=1, sticky="w", pady=(4, 12))
        port.bind("<KeyRelease>", app._port_typed)

        self.switch_box, self.ssl_switch, self.ssl_note = self._switch(
            left, rows, app.var_ssl, "SSL zum Backend", self._ssl_changed)
        self._ssl_changed()

        rows = itertools.count()
        ttk.Label(right, text="DNS-Eintrag in", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.dns_box = ttk.Combobox(right, textvariable=app.var_dns_target,
                                    state="readonly", style="Card.TCombobox",
                                    values=[NO_DNS])
        self.dns_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        self.dns_box.bind("<<ComboboxSelected>>",
                          lambda _e: app._dns_target_changed())
        self.dns_hint = ttk.Label(right, style="Hint.TLabel", text="",
                                  wraplength=340, justify="left")
        self.dns_hint.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))

        ttk.Label(right, text="Public Service", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.frontend_box = ttk.Combobox(right, textvariable=app.var_frontend,
                                         state="readonly",
                                         style="Card.TCombobox")
        self.frontend_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        self.frontend_box.bind("<<ComboboxSelected>>",
                               lambda _e: self.frontend_hint())
        self.hidden_frontends = 0
        self.frontend_note = ttk.Label(right, style="Hint.TLabel", text="",
                                       wraplength=340, justify="left")
        self.frontend_note.grid(row=next(rows), column=0, sticky="w",
                                pady=(0, 12))

        ttk.Separator(right, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=(4, 12))
        ttk.Label(right, text="Erweiterte Optionen",
                  style="Group.TLabel").grid(row=next(rows), column=0, sticky="w",
                                             pady=(0, 8))
        for text, variable in (
                ("Backend-Zertifikat prüfen", app.var_ssl_verify),
                ("X-Forwarded-For setzen", app.var_forward_for),
                ("Nur speichern, HAProxy nicht neu laden", app.var_no_apply),
                ("Auch Public Services ohne Port 443 zeigen",
                 app.var_all_frontends)):
            ttk.Checkbutton(right, text=text, variable=variable,
                            style="Card.TCheckbutton").grid(
                row=next(rows), column=0, sticky="w", pady=(0, 4))

        ttk.Label(right, text="Health Monitor", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(8, 0))
        self.healthcheck_box = ttk.Combobox(
            right, textvariable=app.var_healthcheck, state="readonly",
            style="Card.TCombobox", values=[NO_HEALTHCHECK])
        self.healthcheck_box.grid(row=next(rows), column=0, sticky="ew",
                                  pady=(4, 10))

        ttk.Label(right, text="Backend-Modus", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Combobox(right, textvariable=app.var_backend_mode, state="readonly",
                     style="Card.TCombobox",
                     values=["automatisch", "http", "tcp"]).grid(
            row=next(rows), column=0, sticky="ew", pady=(4, 10))

        ttk.Label(right, text="Namens-Präfix", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Entry(right, textvariable=app.var_prefix,
                  style="Card.TEntry").grid(row=next(rows), column=0,
                                            sticky="ew", pady=(4, 0))

    def destroy(self):
        if getattr(self, "_fqdn_trace", None):
            self.app.var_target.trace_remove("write", self._fqdn_trace)
            self._fqdn_trace = None
        if self.app.host_dialog is self:
            self.app.host_dialog = None
        super().destroy()

    def go(self, dry_run):
        self.app._submit(dry_run)

    # -- keeping up with the firewall --------------------------------------

    def refresh(self):
        """Take up what the last reading of the firewall brought."""
        app = self.app
        self.base_box.configure(
            values=[NO_BASE] + [entry["domain"] for entry in app.domains])
        self.healthcheck_box.configure(
            values=[NO_HEALTHCHECK] + app.healthchecks)
        self.fill_dns_choices()
        self.fill_frontends()
        self.refresh_hints()

    def fill_dns_choices(self):
        names = [e.get("name", "?") for e in self.app.systems.get("adguard", [])]
        self.dns_box.configure(values=[NO_DNS] + names,
                               state="readonly" if names else "disabled")

    def fill_frontends(self):
        """The public services to choose from, the one on 443 in front.

        A place with more than one listener usually has a second on port 80
        whose whole job is to send browsers to the first. A rule hung into that
        one answers nothing, and the list used to begin with whichever came
        first by name -- so that is what got picked.

        The others are left out rather than merely sorted down, because the
        choice is between things that look alike from here. What is hidden is
        said under the field, and the switch in the advanced options brings
        them back for a place whose HTTPS lives on 8443.
        """
        app = self.app
        every = list(app.services)
        shown = every if app.var_all_frontends.get() else [
            service for service in every if core.serves_https(service)]
        if not shown:
            shown = every  # nothing on 443 at all: better all of them than none
        chosen = app.var_frontend.get()
        if chosen and chosen not in [service["name"] for service in shown]:
            # a service somebody picked on purpose does not vanish underneath
            keep = next((s for s in every if s["name"] == chosen), None)
            if keep:
                shown = shown + [keep]
        # 443 first, then what is switched on, then by name -- so the first
        # entry is the one to start with even when everything is shown
        shown.sort(key=lambda service: (0 if core.serves_https(service) else 1,
                                        0 if service.get("enabled", True) else 1,
                                        service.get("name", "").lower()))
        names = [service["name"] for service in shown]
        self.frontend_box.configure(values=names,
                                    state="disabled" if len(names) <= 1
                                    else "readonly")
        if chosen not in names:
            preferred = app.profile.get("frontend", "")
            app.var_frontend.set(preferred if preferred in names
                                 else (names[0] if names else ""))
        self.hidden_frontends = len(every) - len(shown)
        self.frontend_hint()

    def frontend_hint(self):
        """What the chosen service listens on, and what is not in the list."""
        chosen = next((service for service in self.app.services
                       if service["name"] == self.app.var_frontend.get()), None)
        parts = []
        if chosen:
            parts.append(f"hört auf {chosen.get('bind') or '?'}")
            if not core.serves_https(chosen):
                parts.append("nicht Port 443 — sicher, dass Anfragen hier "
                             "ankommen?")
            elif not chosen.get("enabled", True):
                parts.append("ist abgeschaltet")
        elif not self.app.connected:
            parts.append("erst nach dem Verbinden bekannt")
        if self.hidden_frontends:
            parts.append(f"{self.hidden_frontends} ohne 443 ausgeblendet "
                         "(Erweiterte Optionen)" if self.hidden_frontends > 1
                         else "einer ohne 443 ausgeblendet (Erweiterte Optionen)")
        self.frontend_note.configure(text=" · ".join(parts))

    def refresh_hints(self):
        """Show the name that will actually be created, and what DNS will do."""
        app = self.app
        base = "" if app.var_base.get() == NO_BASE else app.var_base.get()
        raw = core.with_base(app.var_target.get(), base)
        host = raw.split("/", 1)[0].strip()
        full = core.build_fqdn(host, base) if host else ""
        if not full:
            self.fqdn_hint.configure(
                text="app.example.com oder https://example.com/api")
        else:
            entry = next((d for d in app.domains if d["domain"] == base), None)
            note = "" if entry is None or core.covered_by(entry, full) \
                else "  ·  kein Zertifikat dafür"
            self.fqdn_hint.configure(text=f"→ {full}{note}")

        if app.var_dns_target.get() == NO_DNS:
            self.dns_hint.configure(text="DNS bleibt unangetastet"
                                    if app.systems.get("adguard")
                                    else "Noch kein AdGuard eingerichtet (⚙)")
        elif not app.adguard:
            self.dns_hint.configure(
                text=app.adguard_problem or "AdGuard antwortet hier nicht (⚙)")
        else:
            self.dns_hint.configure(
                text=f"{full or 'name'} → {app.adguard_target or '?'}")

    def _ssl_changed(self):
        on = self.ssl_switch.get()
        self.app.var_ssl.set(on)
        self.ssl_note.configure(text="HAProxy spricht HTTPS mit dem Server" if on
                                else "HAProxy spricht HTTP mit dem Server")
        if not self.app.port_touched:
            self.app.var_port.set("")


class ListenerDialog(FormDialog):
    """A public service of its own: TLS outside, whatever fits inside.

    The other form hangs a name into an entrance that already exists, which is
    what a web service needs. A TURN server, an IMAP server or a database has
    no name in the request to match on -- it has a port. This builds that: the
    listener, the pool and the server behind it in one go.
    """

    title_text = "Neuer TCP-Listener"
    action_text = "Listener anlegen"
    subtitle = ("Ein eigener Public Service auf einem eigenen Port. HAProxy "
                "beendet dort die TLS-Verbindung mit einem öffentlichen "
                "Zertifikat und spricht nach innen so, wie der Dienst es "
                "will — auch ganz ohne Verschlüsselung.")

    def build(self, left, right):
        app = self.app
        rows = itertools.count()
        # a name that is already in there was written by somebody, and the
        # suggestion has no business overwriting it
        self.host_touched = bool(app.var_listen_host.get().strip())

        ttk.Label(left, text="Außen — was ankommt",
                  style="Group.TLabel").grid(row=next(rows), column=0,
                                             sticky="w", pady=(0, 10))
        self._field(left, rows, "Name", app.var_listen_name,
                    "So heißt der Public Service in OPNsense, z.B. turn-tls",
                    mono=False)
        self._field(left, rows, "Port", app.var_listen_port,
                    "Der Port, auf dem HAProxy nach außen hört, z.B. 5349")
        self._field(left, rows, "Adresse", app.var_listen_address,
                    "0.0.0.0 = alle IPv4-Adressen der Firewall")

        ttk.Label(left, text="Modus", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.mode_box = ttk.Combobox(left, state="readonly",
                                     style="Card.TCombobox",
                                     values=list(LISTENER_MODES.values()))
        self.mode_box.set(LISTENER_MODES[app.var_listen_mode.get()])
        self.mode_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        self.mode_box.bind("<<ComboboxSelected>>", lambda _e: self._mode_changed())
        self.mode_hint = ttk.Label(left, style="Hint.TLabel", text="",
                                   wraplength=340, justify="left")
        self.mode_hint.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))

        ttk.Label(left, text="Zertifikat", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.cert_box = ttk.Combobox(left, textvariable=app.var_listen_cert,
                                     state="readonly", style="Card.TCombobox",
                                     values=[NO_CERT])
        self.cert_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        self.cert_box.bind("<<ComboboxSelected>>", lambda _e: self._cert_changed())
        self.cert_hint = ttk.Label(left, style="Hint.TLabel", text="",
                                   wraplength=340, justify="left")
        self.cert_hint.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))

        rows = itertools.count()
        ttk.Label(right, text="Innen — wohin es geht",
                  style="Group.TLabel").grid(row=next(rows), column=0,
                                             sticky="w", pady=(0, 10))
        pair = ttk.Frame(right, style="Card.TFrame")
        pair.grid(row=next(rows), column=0, sticky="ew")
        pair.columnconfigure(0, weight=1)
        ttk.Label(pair, text="Server-IP", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(pair, textvariable=app.var_listen_ip, style="Card.TEntry",
                  font=app.font_mono).grid(row=1, column=0, sticky="ew",
                                           padx=(0, 10), pady=(4, 2))
        ttk.Label(pair, text="Port", style="FieldLabel.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Entry(pair, textvariable=app.var_listen_backend_port, width=8,
                  style="Card.TEntry", font=app.font_mono).grid(
            row=1, column=1, sticky="w", pady=(4, 2))
        ttk.Label(right, style="Hint.TLabel", wraplength=340, justify="left",
                  text="Der Dienst dahinter. Ohne Port derselbe wie außen.").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 12))

        self.switch_box, self.ssl_switch, self.ssl_note = self._switch(
            right, rows, app.var_listen_ssl, "TLS zum Server",
            self._ssl_changed)
        self._ssl_changed()
        ttk.Checkbutton(right, text="Zertifikat des Servers prüfen",
                        variable=app.var_listen_ssl_verify,
                        style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 12))

        ttk.Separator(right, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=(4, 12))
        ttk.Label(right, text="Name nach außen", style="Group.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 8))
        host_entry, self.host_note = self._field(
            right, rows, "Öffentlicher Name", app.var_listen_host,
            "Für den DNS-Eintrag, z.B. turn.example.de.")
        # Typed once, it is theirs: the suggestion stops the moment somebody
        # writes their own name in here.
        host_entry.bind("<KeyRelease>", self._host_typed)
        self.dns_check = ttk.Checkbutton(
            right, text="Passenden DNS-Eintrag in AdGuard anlegen",
            variable=app.var_listen_dns, style="Card.TCheckbutton")
        self.dns_check.grid(row=next(rows), column=0, sticky="w")
        self.dns_hint = ttk.Label(right, style="Hint.TLabel", text="",
                                  wraplength=340, justify="left")
        self.dns_hint.grid(row=next(rows), column=0, sticky="w", pady=(2, 0))
        self._dns_trace = app.var_listen_host.trace_add(
            "write", lambda *_a: self._paint_dns())
        self._name_trace = app.var_listen_name.trace_add(
            "write", lambda *_a: self.suggest_host())

    def destroy(self):
        if getattr(self, "_dns_trace", None):
            self.app.var_listen_host.trace_remove("write", self._dns_trace)
            self._dns_trace = None
        if getattr(self, "_name_trace", None):
            self.app.var_listen_name.trace_remove("write", self._name_trace)
            self._name_trace = None
        if self.app.listener_dialog is self:
            self.app.listener_dialog = None
        super().destroy()

    def go(self, dry_run):
        self.app.var_listen_mode.set(self._mode_id())
        self.app.create_listener(dry_run)

    def refresh(self):
        """Take up the certificates and modes the firewall just reported."""
        choices = self.app.listener_choices
        names = [entry["name"] for entry in choices["certificates"]]
        self.cert_box.configure(values=[NO_CERT] + names,
                                state="readonly" if names else "disabled")
        if self.app.var_listen_cert.get() not in names:
            self.app.var_listen_cert.set(NO_CERT)
        offered = [choice["id"] for choice in choices["modes"]] \
            or list(LISTENER_MODES)
        # in the order this form thinks about them, not the plugin's: the one
        # this window is for stands first
        self.mode_box.configure(values=[label for key, label
                                        in LISTENER_MODES.items()
                                        if key in offered])
        self._mode_changed()
        self.suggest_host()
        self._paint_dns()

    def _host_typed(self, _event=None):
        self.host_touched = True
        self._paint_dns()

    def _cert_changed(self):
        self.suggest_host()
        self._mode_changed()

    def suggest_host(self):
        """Put name and certificate together into the name for the outside.

        The certificate already says which names may be used -- that is what
        it is for. A wildcard leaves the first label open, and the listener's
        own name is exactly what belongs there; a certificate for one single
        name is the answer by itself. So the field fills itself, until
        somebody types in it.
        """
        if getattr(self, "host_touched", False):
            return
        chosen = self.app.var_listen_cert.get()
        if chosen == NO_CERT:
            self.app.var_listen_host.set("")
            self._paint_dns()
            return
        self.app.var_listen_host.set(core.certificate_host(
            chosen, self.app.var_listen_name.get(), self.app.domains))
        self._paint_dns()

    def _mode_id(self):
        shown = self.mode_box.get()
        return next((key for key, label in LISTENER_MODES.items()
                     if label == shown), "tcp")

    def _mode_changed(self):
        mode = self._mode_id()
        cert = self.app.var_listen_cert.get() != NO_CERT
        self.mode_hint.configure(text=LISTENER_MODE_HINTS[mode])
        if not self.app.listener_choices["certificates"]:
            self.cert_hint.configure(
                text="Noch keine Zertifikate gelesen — dafür einmal verbinden."
                if not self.app.connected else
                "Diese OPNsense hat keine Zertifikate (System → Trust).")
        elif cert:
            self.cert_hint.configure(
                text="Damit antwortet HAProxy nach außen; die Verbindung "
                     "endet hier." if mode != "ssl" else
                     "Im SSL-Modus wird die Verbindung durchgereicht — das "
                     "Zertifikat wird dann nicht gebraucht.")
        else:
            self.cert_hint.configure(
                text="Ohne Zertifikat reicht der Listener nur weiter. Der "
                     "Dienst dahinter braucht dann sein eigenes TLS.")

    def _ssl_changed(self):
        on = self.ssl_switch.get()
        self.app.var_listen_ssl.set(on)
        self.ssl_note.configure(
            text="HAProxy spricht TLS mit dem Dienst" if on else
                 "HAProxy spricht unverschlüsselt mit dem Dienst")

    def _paint_dns(self):
        host = self.app.var_listen_host.get().strip()
        self.host_note.configure(
            text="Für den DNS-Eintrag, z.B. turn.example.de."
            if getattr(self, "host_touched", False) or not host else
            "Aus Name und Zertifikat zusammengesetzt — tippen überschreibt das.")
        if not host:
            self.dns_hint.configure(text="Ohne Namen wird kein DNS-Eintrag "
                                         "angelegt.")
            self.dns_check.configure(state="disabled")
            return
        self.dns_check.configure(state="normal")
        if not self.app.adguard:
            self.dns_hint.configure(
                text=self.app.adguard_problem
                     or "Kein AdGuard für diese OPNsense (⚙)")
            return
        self.dns_hint.configure(
            text=f"{host} → {self.app.adguard_target or '?'}")


class App(tk.Tk):
    def __init__(self, args):
        # the class name is what the task bar matches the desktop starter
        # against, so a pinned icon and the running window belong together
        super().__init__(className=core.WM_CLASS)
        self.args = args
        # Without --config this used to stay None, and every attempt to save
        # died on the way to the file -- in a callback, where nobody sees it.
        self.config_path = args.config or core.DEFAULT_CONFIG
        self.settings = {}
        self.api = None
        # the three lists from the file, and which of each is selected right
        # now; self.profile is the OPNsense in use with its two filled in
        self.systems = {kind: [] for kind in core.SYSTEM_KINDS}
        self.active = {kind: "" for kind in core.SYSTEM_KINDS}
        # stacks written down to deploy again -- they live in the same file as
        # the systems, because they describe the setup and not the view
        self.favorites = []
        self.profile = {}
        self.adguard = None
        self.adguard_target = ""
        self.adguard_problem = ""
        self.rewrites = {}
        self.rewrites_error = ""
        self.connected = False
        self.services = []
        self.healthchecks = []
        self.domains = []
        self.busy = False
        self.results = queue.Queue()
        self.port_touched = False
        # what the pill would say about the OPNsense side; the Portainer tab
        # has an answer of its own and the header shows one of the two
        self.haproxy_pill = ("nicht verbunden", "IdlePill.TLabel")

        # what a new listener could be given, read from the plugin when the
        # firewall is read; empty until then
        self.listener_choices = {"certificates": [], "modes": []}
        # the two forms of this tab, each in a window of its own
        self.host_dialog = None
        self.listener_dialog = None

        self.update_release = None
        self.update_checking = False

        self.prefs = load_prefs()
        self.theme_name = self.prefs.get("theme", "dark")
        self.colors = THEMES[self.theme_name]

        self.title(APP_TITLE)
        self.geometry(self.prefs.get("geometry", "1080x720"))
        self.minsize(880, 560)
        self._set_icon()

        self._init_fonts()
        self._init_form_vars()
        self._build()
        self._apply_theme()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(60, self._pump)
        self.after(100, self._connect)
        self.after(1500, self._update_on_start)

    def _set_icon(self):
        """Give the window and the task bar the program's own icon."""
        folder = core.install_dir()
        windows_icon = os.path.join(folder, "icon.ico")
        if os.name == "nt" and os.path.exists(windows_icon):
            try:
                self.iconbitmap(windows_icon)
                return
            except tk.TclError:
                pass  # fall through to the PNG, which Tk reads everywhere
        picture = os.path.join(folder, "icon.png")
        if not os.path.exists(picture):
            return
        try:
            # kept on the instance: Tk does not hold on to the image itself
            self._icon = tk.PhotoImage(file=picture)
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass  # an unusual Tk build without PNG support is no reason to stop

    # -- theming -----------------------------------------------------------

    def _init_fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        self.font_base = base
        self.font_h1 = tkfont.Font(family=base.cget("family"), size=13, weight="bold")
        self.font_h2 = tkfont.Font(family=base.cget("family"), size=11, weight="bold")
        self.font_small = tkfont.Font(family=base.cget("family"), size=9)
        self.font_mono = tkfont.nametofont("TkFixedFont").copy()
        self.font_mono.configure(size=10)
        self.font_mono_bold = self.font_mono.copy()
        self.font_mono_bold.configure(weight="bold")
        # Links are underlined for good: switching the font on hover changes
        # what the label reports as its size, and the whole row jumps.
        self.font_link = self.font_mono_bold.copy()
        self.font_link.configure(underline=True)
        # the same idea in the size a hint under a field is written in
        self.font_link_small = self.font_small.copy()
        self.font_link_small.configure(underline=True)
        self.font_icon = tkfont.Font(family=base.cget("family"), size=12)

    def _apply_theme(self):
        c = self.colors
        style = ttk.Style(self)
        style.theme_use("clam")

        self.configure(bg=c["bg"])
        self.option_add("*TCombobox*Listbox.background", c["surface2"])
        self.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", c["accent_text"])

        style.configure("TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["surface"])
        style.configure("Sub.TFrame", background=c["surface2"])
        style.configure("Head.TFrame", background=c["bg"])

        style.configure("TLabel", background=c["surface"], foreground=c["text"],
                        font=self.font_base)
        style.configure("Head.TLabel", background=c["bg"], foreground=c["text"])
        style.configure("H1.TLabel", background=c["bg"], foreground=c["text"],
                        font=self.font_h1)
        style.configure("H2.TLabel", background=c["surface"], foreground=c["text"],
                        font=self.font_h2)
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"],
                        font=self.font_small)
        style.configure("Version.TLabel", background=c["surface2"],
                        foreground=c["muted"], font=self.font_small,
                        padding=(7, 2))
        style.configure("Mark.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small)
        style.configure("Hint.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small)
        # the same line when it carries bad news -- a form says in itself what
        # went wrong, because the log it wrote into stands behind it
        style.configure("Bad.TLabel", background=c["surface"],
                        foreground=c["danger"], font=self.font_small)
        style.configure("FieldLabel.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small)
        style.configure("Host.TLabel", background=c["surface2"],
                        foreground=c["text"], font=self.font_mono_bold)
        style.configure("Link.TLabel", background=c["surface2"],
                        foreground=c["accent"], font=self.font_link)
        # a link in the running text under a field, on the card behind it
        style.configure("CardLink.TLabel", background=c["surface"],
                        foreground=c["accent"], font=self.font_link_small)
        style.configure("Target.TLabel", background=c["surface2"],
                        foreground=c["muted"], font=self.font_mono)
        style.configure("RowHint.TLabel", background=c["surface2"],
                        foreground=c["muted"], font=self.font_small)
        style.configure("Group.TLabel", background=c["surface"],
                        foreground=c["text"], font=self.font_h2)
        style.configure("Switch.TLabel", background=c["surface2"],
                        foreground=c["text"], font=self.font_base)

        for name, fg, bg in (("Ok", c["ok"], c["ok_soft"]),
                             ("Bad", c["danger"], c["danger_soft"]),
                             ("Idle", c["muted"], c["surface2"])):
            style.configure(f"{name}Pill.TLabel", background=bg, foreground=fg,
                            font=self.font_small, padding=(10, 4))
        style.configure("Badge.TLabel", background=c["accent_soft"],
                        foreground=c["accent"], font=self.font_small,
                        padding=(6, 1))
        style.configure("BadgeMuted.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small,
                        padding=(6, 1))
        style.configure("BadgeOk.TLabel", background=c["ok_soft"],
                        foreground=c["ok"], font=self.font_small,
                        padding=(6, 1))
        style.configure("BadgeWarn.TLabel", background=c["danger_soft"],
                        foreground=c["danger"], font=self.font_small,
                        padding=(6, 1))

        style.configure("Card.TEntry", fieldbackground=c["surface2"],
                        foreground=c["text"], insertcolor=c["text"],
                        bordercolor=c["border"], lightcolor=c["border"],
                        darkcolor=c["border"], borderwidth=1, padding=7)
        style.map("Card.TEntry",
                  bordercolor=[("focus", c["accent"])],
                  lightcolor=[("focus", c["accent"])],
                  darkcolor=[("focus", c["accent"])],
                  # a field that something else fills in stays readable, and
                  # says by its colour that typing in it leads nowhere
                  fieldbackground=[("readonly", c["surface2"])],
                  foreground=[("readonly", c["muted"])])

        style.configure("Card.TCombobox", fieldbackground=c["surface2"],
                        background=c["surface2"], foreground=c["text"],
                        arrowcolor=c["muted"], bordercolor=c["border"],
                        lightcolor=c["border"], darkcolor=c["border"],
                        borderwidth=1, padding=6)
        style.map("Card.TCombobox",
                  fieldbackground=[("readonly", c["surface2"])],
                  foreground=[("readonly", c["text"])],
                  bordercolor=[("focus", c["accent"])],
                  selectbackground=[("readonly", c["surface2"])],
                  selectforeground=[("readonly", c["text"])])
        # the same picker for things that are typed as much as chosen -- an
        # address reads better in the same face as the field above it
        style.configure("CardMono.TCombobox", fieldbackground=c["surface2"],
                        background=c["surface2"], foreground=c["text"],
                        arrowcolor=c["muted"], bordercolor=c["border"],
                        lightcolor=c["border"], darkcolor=c["border"],
                        borderwidth=1, padding=6, font=self.font_mono)

        style.configure("Accent.TButton", background=c["accent"],
                        foreground=c["accent_text"], borderwidth=0,
                        focuscolor=c["accent"], padding=(16, 9),
                        font=self.font_base)
        style.map("Accent.TButton",
                  background=[("active", c["accent"]), ("disabled", c["border"])],
                  foreground=[("disabled", c["muted"])])

        style.configure("Ghost.TButton", background=c["surface2"],
                        foreground=c["text"], borderwidth=1,
                        bordercolor=c["border"], lightcolor=c["surface2"],
                        darkcolor=c["surface2"], focuscolor=c["surface2"],
                        padding=(14, 9), font=self.font_base)
        style.map("Ghost.TButton",
                  background=[("active", c["border"]), ("disabled", c["surface"])],
                  foreground=[("disabled", c["muted"])])

        # The header buttons sit on the window background, where a borderless
        # button is barely there. A surface of their own and a border make them
        # read as something to press.
        style.configure("Tool.TButton", background=c["surface"],
                        foreground=c["text"], borderwidth=1,
                        bordercolor=c["border_strong"], lightcolor=c["surface"],
                        darkcolor=c["surface"], focuscolor=c["surface"],
                        padding=(12, 8), font=self.font_icon)
        style.map("Tool.TButton",
                  background=[("active", c["surface2"])],
                  bordercolor=[("active", c["accent"])],
                  foreground=[("disabled", c["muted"])])

        # the same button, but noticeable once there is something to install
        style.configure("Update.TButton", background=c["accent_soft"],
                        foreground=c["accent"], borderwidth=1,
                        bordercolor=c["accent"], lightcolor=c["accent_soft"],
                        darkcolor=c["accent_soft"], focuscolor=c["accent_soft"],
                        padding=(12, 8), font=self.font_icon)
        style.map("Update.TButton", background=[("active", c["accent"])],
                  foreground=[("active", c["accent_text"])])

        style.configure("Del.TButton", background=c["surface2"],
                        foreground=c["muted"], borderwidth=1,
                        bordercolor=c["border"], lightcolor=c["surface2"],
                        darkcolor=c["surface2"], focuscolor=c["surface2"],
                        padding=(9, 4), font=self.font_small)
        style.map("Del.TButton",
                  background=[("active", c["danger_soft"])],
                  foreground=[("active", c["danger"])])

        style.configure("Card.TCheckbutton", background=c["surface"],
                        foreground=c["text"], font=self.font_base,
                        indicatorcolor=c["surface2"], focuscolor=c["surface"])
        style.map("Card.TCheckbutton",
                  background=[("active", c["surface"])],
                  indicatorcolor=[("selected", c["accent"])])

        style.configure("Card.TRadiobutton", background=c["surface"],
                        foreground=c["text"], font=self.font_base,
                        indicatorcolor=c["surface2"], focuscolor=c["surface"])
        style.map("Card.TRadiobutton",
                  background=[("active", c["surface"])],
                  indicatorcolor=[("selected", c["accent"])])

        style.configure("Bar.Horizontal.TProgressbar", background=c["accent"],
                        troughcolor=c["surface2"], bordercolor=c["surface2"],
                        lightcolor=c["accent"], darkcolor=c["accent"],
                        borderwidth=0, thickness=4)

        # Big tabs: the two halves of the program are a place to be, not a
        # setting, so they get the size and the weight of a heading.
        for name, fg, bg, border in (("Tab", c["muted"], c["surface"], c["border"]),
                                     ("TabOn", c["accent"], c["accent_soft"],
                                      c["accent"])):
            style.configure(f"{name}.TButton", background=bg, foreground=fg,
                            font=self.font_h2, padding=(30, 13), borderwidth=1,
                            bordercolor=border, lightcolor=bg, darkcolor=bg,
                            focuscolor=bg)
            style.map(f"{name}.TButton", background=[("active", bg)],
                      foreground=[("active", fg)],
                      bordercolor=[("active", c["accent"])])

        style.configure("TSeparator", background=c["border"])
        style.configure("Vertical.TScrollbar", background=c["surface2"],
                        troughcolor=c["surface"], bordercolor=c["surface"],
                        arrowcolor=c["muted"], borderwidth=0)
        style.map("Vertical.TScrollbar",
                  background=[("active", c["border_strong"])])

        self.log.configure(bg=c["surface"], fg=c["text"],
                           insertbackground=c["text"],
                           selectbackground=c["accent_soft"])
        self.log.tag_configure("info", foreground=c["text"])
        self.log.tag_configure("muted", foreground=c["muted"])
        self.log.tag_configure("add", foreground=c["ok"])
        self.log.tag_configure("del", foreground=c["warn"])
        self.log.tag_configure("error", foreground=c["danger"])
        self.log_frame.configure(bg=c["surface"])

        self.inventory.apply_theme(c)
        self.theme_button.configure(text="☀" if self.theme_name == "dark" else "🌙")
        self._paint_update_button()
        self._render_inventory()
        self.portainer.apply_theme()
        self.dns.apply_theme()
        for dialog in (self.host_dialog, self.listener_dialog):
            if dialog is not None and dialog.winfo_exists():
                dialog.apply_theme(c)
        self._paint_tabs()
        self.paint_connection()

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.colors = THEMES[self.theme_name]
        self._apply_theme()

    # -- layout ------------------------------------------------------------

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()
        self._build_log()

    def _build_tabs(self):
        """The three parts of the program, one behind each tab.

        The strip is built by hand rather than from a ttk.Notebook: clam draws
        the tab that is not chosen taller than the one that is, which reads as
        a mistake, and no amount of styling talks it out of that.

        The other two are imported here rather than at the top of the file:
        they borrow the widgets defined above, and a window is only ever built
        after this module has finished loading, so they can point at each
        other without an import running in circles.
        """
        try:
            import portainer_gui
        except ImportError:
            # An update installed by an older version copies only the files
            # that version knew about, so this half can be missing on a fresh
            # 1.4.0. The window still opens; the tab says what to do about it.
            portainer_gui = None
        try:
            import adguard_gui
        except ImportError:
            adguard_gui = None  # same story, for anything before 2.5.0

        strip = ttk.Frame(self, style="Head.TFrame")
        strip.grid(row=1, column=0, sticky="nsew", padx=18)
        strip.columnconfigure(0, weight=1)
        strip.rowconfigure(1, weight=1)

        bar = ttk.Frame(strip, style="Head.TFrame")
        bar.grid(row=0, column=0, sticky="w")
        pages = ttk.Frame(strip, style="TFrame", padding=(0, 12, 0, 0))
        pages.grid(row=1, column=0, sticky="nsew")
        pages.columnconfigure(0, weight=1)
        pages.rowconfigure(0, weight=1)

        proxy = ttk.Frame(pages, style="TFrame")
        proxy.grid(row=0, column=0, sticky="nsew")
        proxy.columnconfigure(0, weight=1)
        proxy.rowconfigure(0, weight=1)
        self._build_hosts(proxy)

        self.portainer = (portainer_gui.PortainerTab(pages, self)
                          if portainer_gui else MissingTab(pages, self))
        self.portainer.grid(row=0, column=0, sticky="nsew")

        self.dns = (adguard_gui.AdGuardTab(pages, self) if adguard_gui
                    else MissingTab(pages, self, "AdGuard"))
        self.dns.grid(row=0, column=0, sticky="nsew")

        self.pages = {"haproxy": proxy, "portainer": self.portainer,
                      "adguard": self.dns}
        self.tab_buttons = {}
        for column, (name, label) in enumerate((("haproxy", "HAProxy"),
                                                ("portainer", "Portainer"),
                                                ("adguard", "AdGuard"))):
            button = ttk.Button(bar, text=label, style="Tab.TButton",
                                command=lambda n=name: self.show_tab(n))
            button.grid(row=0, column=column, padx=(0, 6))
            self.tab_buttons[name] = button
        self.current_tab = "haproxy"
        self.show_tab("haproxy")

    def show_tab(self, name):
        """Bring one half to the front and let the header follow it."""
        self.current_tab = name
        for other, page in self.pages.items():
            page.grid() if other == name else page.grid_remove()
        self._paint_tabs()
        self._fill_switcher()
        self.paint_connection()

    def _paint_tabs(self):
        for name, button in self.tab_buttons.items():
            button.configure(style="TabOn.TButton" if name == self.current_tab
                             else "Tab.TButton")

    def active_tab(self):
        """Which half is in front -- the header speaks for that one."""
        return getattr(self, "current_tab", "haproxy")

    def _build_header(self):
        head = ttk.Frame(self, style="Head.TFrame", padding=(18, 14, 18, 10))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)

        titles = ttk.Frame(head, style="Head.TFrame")
        titles.grid(row=0, column=0, sticky="w")
        ttk.Label(titles, text="HAProxy", style="H1.TLabel").grid(row=0, column=0,
                                                                 sticky="w")
        ttk.Label(titles, text=f"v{core.VERSION}", style="Version.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0))
        # the line under the name says which half of the program is in front
        self.subtitle = ttk.Label(titles, text="OPNsense Reverse Proxy",
                                  style="Muted.TLabel")
        self.subtitle.grid(row=1, column=0, columnspan=2, sticky="w")

        actions = ttk.Frame(head, style="Head.TFrame")
        actions.grid(row=0, column=2, sticky="e")

        self.var_profile = tk.StringVar()
        self.profile_box = ttk.Combobox(actions, textvariable=self.var_profile,
                                        state="readonly", width=16,
                                        style="Card.TCombobox")
        self.profile_box.grid(row=0, column=0, padx=(0, 8))
        self.profile_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._switch_active())
        self.profile_tip = Tooltip(self.profile_box, SWITCHER_TIP["opnsense"])

        self.status_pill = ttk.Label(actions, text="nicht verbunden",
                                     style="IdlePill.TLabel")
        self.status_pill.grid(row=0, column=1, padx=(0, 8))

        # Labels rather than symbols alone: "update" and "install" are two
        # arrows pointing down, and nobody should have to guess which is which.
        self.connect_button = ttk.Button(actions, text="Verbinden",
                                         style="Accent.TButton",
                                         command=self._connect_now)
        self.connect_button.grid(row=0, column=2, padx=(0, 6))
        self.update_button = ttk.Button(actions, text="⇩ Update",
                                        style="Tool.TButton",
                                        command=self._check_update)
        self.update_button.grid(row=0, column=3, padx=(0, 6))
        self.install_button = ttk.Button(actions, text="⤓ Installieren",
                                         style="Tool.TButton",
                                         command=self._open_install)
        self.install_button.grid(row=0, column=4, padx=(0, 6))
        self._paint_install_button()
        # Without a width of their own, ttk hands every button the same
        # eleven-character minimum -- which leaves the two symbols swimming in
        # a button four times their size.
        self.theme_button = ttk.Button(actions, text="☀", style="Tool.TButton",
                                       width=3, command=self._toggle_theme)
        self.theme_button.grid(row=0, column=5, padx=(0, 6))
        settings_button = ttk.Button(actions, text="⚙", style="Tool.TButton",
                                     width=3, command=self.open_settings)
        settings_button.grid(row=0, column=6)

        for button, explanation in (
                (self.connect_button, "Mit der OPNsense verbinden und alles "
                                      "neu einlesen"),
                (self.update_button, "Auf GitHub nach einer neueren Version "
                                     "sehen"),
                (self.install_button, "Programm an einen festen Platz legen und "
                                      "Starter anlegen"),
                (self.theme_button, "Hell / Dunkel"),
                (settings_button, "Einstellungen: OPNsense, AdGuard und "
                                  "Portainer")):
            Tooltip(button, explanation)

        # a slim progress strip so long API calls never look like a freeze
        self.progress = ttk.Progressbar(head, mode="indeterminate",
                                        style="Bar.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew",
                           pady=(10, 0))
        self.progress.grid_remove()
        self.activity = ttk.Label(head, text="", style="Muted.TLabel")
        self.activity.grid(row=2, column=0, columnspan=3, sticky="w",
                           pady=(4, 0))
        self.activity.grid_remove()

    def _init_form_vars(self):
        """What the two forms of this tab hold, kept by the window itself.

        The forms live in windows that come and go; what was typed into a
        picker should not. Keeping the variables here also means the removal
        of a host and a deploy from the Portainer tab can read the same
        switches -- "do not reload yet", "which AdGuard" -- without a form
        having to be open anywhere.
        """
        self.var_target = tk.StringVar()
        self.var_ip = tk.StringVar()
        self.var_port = tk.StringVar()
        self.var_base = tk.StringVar(value=NO_BASE)
        self.var_dns_target = tk.StringVar(value=NO_DNS)
        self.var_frontend = tk.StringVar()
        self.var_healthcheck = tk.StringVar(value=NO_HEALTHCHECK)
        self.var_backend_mode = tk.StringVar(value="automatisch")
        self.var_prefix = tk.StringVar()
        self.var_ssl = tk.BooleanVar(value=False)
        self.var_ssl_verify = tk.BooleanVar(value=False)
        self.var_forward_for = tk.BooleanVar(value=True)
        self.var_no_apply = tk.BooleanVar(value=False)
        # A place with an unusual listener -- 8443, or plain HTTP inside --
        # would otherwise have to tick this at every start.
        self.var_all_frontends = tk.BooleanVar(
            value=bool(self.prefs.get("all_frontends", False)))
        self.var_all_frontends.trace_add("write",
                                         lambda *_a: self._fill_frontends())

        # the second form of this tab: a listener of its own
        self.var_listen_name = tk.StringVar()
        self.var_listen_port = tk.StringVar()
        self.var_listen_address = tk.StringVar(value="0.0.0.0")
        self.var_listen_mode = tk.StringVar(value="tcp")
        self.var_listen_cert = tk.StringVar(value=NO_CERT)
        self.var_listen_ip = tk.StringVar()
        self.var_listen_backend_port = tk.StringVar()
        self.var_listen_ssl = tk.BooleanVar(value=False)
        self.var_listen_ssl_verify = tk.BooleanVar(value=False)
        self.var_listen_host = tk.StringVar()
        self.var_listen_dns = tk.BooleanVar(value=True)

    def _build_hosts(self, parent):
        """The listing of this tab, and the two ways to add to it.

        Built like the other two tabs: the whole width for what is there, and
        a button in the head for what is not yet. The form for a new host used
        to be a column pressed against the left edge, which left it about a
        third of the window for fields that are wider than that -- and left
        the listing squeezed for the rest of the time, which is most of it.
        """
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(16, 16, 8, 12))
        outer.grid(row=0, column=0, sticky="nsew", padx=18, pady=(0, 9))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        head = ttk.Frame(outer, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Bestehende Hosts", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")

        picks = ttk.Frame(head, style="Card.TFrame")
        picks.grid(row=0, column=2, sticky="e")
        self.listener_button = ttk.Button(picks, text="＋ TCP-Listener",
                                          style="Del.TButton",
                                          command=self.open_listener)
        self.listener_button.grid(row=0, column=0, sticky="e", padx=(0, 6))
        Tooltip(self.listener_button,
                "Ein eigener Public Service auf einem eigenen Port — für "
                "Dienste ohne Hostnamen, z.B. TURN, IMAP oder eine Datenbank")
        self.new_host_button = ttk.Button(picks, text="＋ Neuer Host",
                                          style="Accent.TButton",
                                          command=self.open_host)
        self.new_host_button.grid(row=0, column=1, sticky="e")

        ttk.Label(outer, style="Hint.TLabel",
                  text="Was aktuell an welchem Public Service hängt.").grid(
            row=1, column=0, sticky="w", pady=(3, 12))

        self.inventory = ScrollFrame(outer, self.colors)
        self.inventory.grid(row=2, column=0, sticky="nsew")

    def _build_log(self):
        self.log_frame = tk.Frame(self, bg=self.colors["surface"])
        self.log_frame.grid(row=2, column=0, sticky="nsew",
                            padx=18, pady=(0, 18))
        self.log_frame.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=0, minsize=170)

        bar = ttk.Frame(self.log_frame, style="Card.TFrame", padding=(14, 8, 8, 4))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.log_title = ttk.Label(bar, text="Protokoll", style="H2.TLabel")
        self.log_title.grid(row=0, column=0, sticky="w")
        self._link(bar, f"DukyNuky · v{core.VERSION}", AUTHOR_URL,
                   style="Mark.TLabel").grid(row=0, column=1, sticky="e",
                                             padx=(0, 12))
        ttk.Button(bar, text="leeren", style="Del.TButton",
                   command=self._clear_log).grid(row=0, column=2, sticky="e")

        self.log = tk.Text(self.log_frame, height=7, wrap="word", bd=0,
                           highlightthickness=0, padx=14, pady=8,
                           font=self.font_mono, state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew", padx=(0, 0), pady=(0, 8))
        scroll = ttk.Scrollbar(self.log_frame, orient="vertical",
                               command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.log_frame.rowconfigure(1, weight=1)

    # -- inventory rendering ----------------------------------------------

    def _render_inventory(self):
        self.inventory.clear()
        body = self.inventory.body
        body.columnconfigure(0, weight=1)

        if not self.api:
            self._placeholder("Keine Zugangsdaten",
                              "Über ⚙ die Zugangsdaten der OPNsense eintragen.",
                              button="Zugangsdaten eintragen",
                              command=self._connect_now)
            return
        if not self.connected:
            self._placeholder(
                "Nicht verbunden",
                f"Es wird nichts von allein geladen. „{self.profile.get('name', '')}“ "
                "wird gelesen, sobald du es sagst.",
                button="Verbinden", command=self._connect_now)
            return
        if not self.services:
            self._placeholder("Kein Public Service",
                              "Es gibt noch keinen Eingang, in den ein Host "
                              "hineinkönnte. ＋ TCP-Listener legt einen an — "
                              "oder du baust ihn in OPNsense selbst.",
                              button="＋ TCP-Listener",
                              command=self.open_listener)
            return
        if not any(service["rules"] or service.get("default")
                   for service in self.services):
            self._placeholder("Noch nichts angelegt",
                              "＋ Neuer Host trägt den ersten Namen in einen "
                              "der Public Services ein.",
                              button="＋ Neuer Host", command=self.open_host)
            return

        row = 0
        for service in self.services:
            header = ttk.Frame(body, style="Card.TFrame")
            header.grid(row=row, column=0, sticky="ew", pady=(6 if row else 0, 6))
            ttk.Label(header, text=service["name"], style="Group.TLabel").grid(
                row=0, column=0, sticky="w")
            ttk.Label(header, text=service["mode"], style="Badge.TLabel").grid(
                row=0, column=1, padx=8)
            column = 2
            if service["bind"]:
                ttk.Label(header, text=service["bind"],
                          style="BadgeMuted.TLabel").grid(row=0, column=column)
                column += 1
            if service.get("tls"):
                badge = ttk.Label(header, text="TLS", style="BadgeOk.TLabel")
                badge.grid(row=0, column=column, padx=(6, 0))
                Tooltip(badge, "Die TLS-Verbindung endet hier — HAProxy "
                               "antwortet mit einem eigenen Zertifikat")
                column += 1
            # Only where nothing hangs in it. A public service with rules is
            # the entrance those rules answer at: taking it away would leave
            # them working and pointing nowhere, so it is not offered.
            header.columnconfigure(column, weight=1)
            if not service["rules"]:
                remove = ttk.Button(
                    header, text="Entfernen", style="Del.TButton",
                    command=lambda s=service: self._remove_listener(s))
                remove.grid(row=0, column=column + 1, sticky="e", padx=(8, 6))
                Tooltip(remove, "Diesen Public Service samt Backend Pool und "
                                "Real Server löschen")
            row += 1

            if service.get("default"):
                # a listener that sends everything to one pool: the port is
                # the whole address, and there is no rule to look for
                self._default_row(body, service).grid(
                    row=row, column=0, sticky="ew", pady=(0, 6), padx=(0, 6))
                row += 1
            elif not service["rules"]:
                ttk.Label(body, text="keine Rules", style="Hint.TLabel").grid(
                    row=row, column=0, sticky="w", padx=4, pady=(0, 8))
                row += 1
                continue

            for rule in service["rules"]:
                self._rule_row(body, service, rule).grid(
                    row=row, column=0, sticky="ew", pady=(0, 6), padx=(0, 6))
                row += 1

    def _placeholder(self, title, text, button="", command=None):
        holder = ttk.Frame(self.inventory.body, style="Card.TFrame", padding=30)
        holder.grid(row=0, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=title, style="H2.TLabel", anchor="center").grid(
            row=0, column=0)
        ttk.Label(holder, text=text, style="Hint.TLabel", anchor="center",
                  wraplength=380, justify="center").grid(row=1, column=0,
                                                         pady=(6, 0))
        if button:
            ttk.Button(holder, text=button, style="Accent.TButton",
                       command=command).grid(row=2, column=0, pady=(16, 0))

    def _default_row(self, parent, service):
        """Where a listener sends everything that arrives on its port."""
        card = tk.Frame(parent, bg=self.colors["surface2"], padx=12, pady=9)
        card.columnconfigure(0, weight=1)
        port = core.bind_port(service["bind"])
        ttk.Label(card, text=f"alles auf Port {port}" if port
                  else "alles auf diesem Port", style="Host.TLabel").grid(
            row=0, column=0, sticky="w")

        servers = (service["default"] or {}).get("servers") or []
        if servers:
            first = servers[0]
            more = f"  (+{len(servers) - 1})" if len(servers) > 1 else ""
            target = (f"→  {'tls' if first['ssl'] else 'plain'}://"
                      f"{first['address']}:{first['port']}{more}")
        else:
            target = "→  Backend ohne Server"
        ttk.Label(card, text=target, style="Target.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0))

        marks = ttk.Frame(card, style="Sub.TFrame")
        marks.grid(row=0, column=1, rowspan=2, padx=(10, 8))
        badge = ttk.Label(marks, text="Listener", style="BadgeMuted.TLabel")
        badge.grid(row=0, column=0, padx=2)
        Tooltip(badge, "Kein Hostname im Spiel: dieser Public Service reicht "
                       "alles weiter, was auf seinem Port ankommt")
        return card

    def _rule_row(self, parent, service, rule):
        card = tk.Frame(parent, bg=self.colors["surface2"], padx=12, pady=9)
        card.columnconfigure(0, weight=1)

        label = (rule["host"] or "") + rule["path"] \
            or rule["target"] or rule["name"] or "?"
        url = core.public_url(service, rule["host"], rule["path"])
        if url:
            self._link(card, label, url).grid(row=0, column=0, sticky="w")
        else:
            ttk.Label(card, text=label, style="Host.TLabel").grid(
                row=0, column=0, sticky="w")

        server = (rule["backend"] or {}).get("servers") or []
        if server:
            first = server[0]
            scheme = "https" if first["ssl"] else "http"
            target = f"→  {scheme}://{first['address']}:{first['port']}"
        elif rule["type"] and rule["type"] != "use_backend":
            target = f"→  {rule['type']}"
        else:
            target = "→  kein Backend"
        ttk.Label(card, text=target, style="Target.TLabel").grid(row=1, column=0,
                                                                 sticky="w",
                                                                 pady=(2, 0))

        dns = self._dns_state(rule)
        marks = ttk.Frame(card, style="Sub.TFrame")
        marks.grid(row=0, column=1, rowspan=2, padx=(10, 8))
        column = 0
        if any(c["expression"] == "ssl_sni" for c in rule["conditions"]):
            ttk.Label(marks, text="SNI", style="BadgeMuted.TLabel").grid(
                row=0, column=column, padx=2)
            column += 1
        if server and server[0]["ssl"]:
            ttk.Label(marks, text="SSL", style="Badge.TLabel").grid(
                row=0, column=column, padx=2)
            column += 1
        if dns:
            badge = ttk.Label(marks, text=dns["badge"], style=dns["style"])
            badge.grid(row=0, column=column, padx=2)
            Tooltip(badge, dns["explains"])

        buttons = ttk.Frame(card, style="Sub.TFrame")
        buttons.grid(row=0, column=2, rowspan=2)
        if dns and dns["button"]:
            ttk.Button(buttons, text=dns["button"], style="Del.TButton",
                       command=lambda r=rule, a=dns["action"]:
                       self._dns_apply(r, a)).grid(row=0, column=0, padx=(0, 6))
        if rule["target"]:
            ttk.Button(buttons, text="Entfernen", style="Del.TButton",
                       command=lambda r=rule: self._remove(r)).grid(row=0,
                                                                    column=1)
        return card

    def _link(self, parent, text, url, style="Link.TLabel"):
        return link_label(parent, self.colors, text, url, style)

    def _dns_state(self, rule):
        """What AdGuard has to say about this host, and what to offer about it."""
        host = rule["host"]
        if not self.adguard or not host:
            return None
        if self.rewrites_error:
            return {"badge": "DNS ?", "style": "BadgeMuted.TLabel", "button": "",
                    "action": "", "explains": self.rewrites_error}
        answer = self.rewrites.get(host.lower())
        if answer == self.adguard_target:
            return {"badge": "DNS ✓", "style": "BadgeOk.TLabel",
                    "button": "DNS löschen", "action": "clear",
                    "explains": f"{host} → {answer} in AdGuard"}
        if answer:
            return {"badge": f"DNS → {answer}", "style": "BadgeWarn.TLabel",
                    "button": "auf HAProxy zeigen", "action": "set",
                    "explains": f"{host} zeigt auf {answer}, nicht auf "
                                f"{self.adguard_target}"}
        return {"badge": "kein DNS", "style": "BadgeMuted.TLabel",
                "button": "DNS eintragen", "action": "set",
                "explains": f"AdGuard kennt {host} nicht"}

    def _dns_apply(self, rule, action):
        """Write or delete this host's DNS rewrite, then show the new state."""
        if self.busy or not self.adguard:
            return
        host, adguard = rule["host"], self.adguard
        target = self.adguard_target
        if action == "clear" and not messagebox.askyesno(
                APP_TITLE, f"DNS-Eintrag für {host} in AdGuard löschen?\n\n"
                           "An HAProxy ändert sich nichts.", icon="warning"):
            return

        def work(report):
            if action == "clear":
                report(f"lösche DNS-Eintrag {host} …")
                outcome = core.clear_rewrite(adguard, host)
            else:
                report(f"trage {host} → {target} in AdGuard ein …")
                outcome = core.set_rewrite(adguard, host, target)
            return {"outcome": outcome, "host": host, "target": target,
                    "entries": adguard.rewrites()}

        self._run_async(work, self._dns_done, activity="AdGuard …")

    def _dns_done(self, result):
        self._set_busy(False)
        self.rewrites = core.as_rewrite_map(result["entries"])
        self.rewrites_error = ""
        self.dns.take(result["entries"])  # the DNS tab shows the same list
        host, target = result["host"], result["target"]
        said = {
            "added": (f"+ DNS-Eintrag {host} → {target}", "info"),
            "changed": (f"+ DNS-Eintrag {host} zeigt jetzt auf {target}", "info"),
            "unchanged": (f"= DNS-Eintrag {host} → {target} war schon da", "info"),
            "removed": (f"- DNS-Eintrag {host} gelöscht", "info"),
            "missing": (f"= für {host} gab es keinen DNS-Eintrag", "info"),
        }[result["outcome"]]
        self._write_log("AdGuard", [{"text": said[0], "level": said[1]}], True)
        self._render_inventory()

    # -- logging -----------------------------------------------------------

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log_title.configure(text="Protokoll")

    def _write_log(self, title, lines, ok=None):
        self.log_title.configure(text=title)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for line in lines:
            self.log.insert("end", line["text"] + "\n", self._tag(line))
        self.log.configure(state="disabled")
        self.log.see("end")
        if ok is False:
            self.bell()

    @staticmethod
    def _tag(line):
        text = line["text"]
        if line["level"] == "error":
            return "error"
        if text.startswith("+"):
            return "add"
        if text.startswith("-") or text.startswith("will delete"):
            return "del"
        if text.startswith(("public service", "match", "real server", "objects",
                            "checking")):
            return "muted"
        return "info"

    # -- background work ---------------------------------------------------

    def _pump(self):
        """Deliver finished background work back onto the UI thread.

        Nothing in here may escape. This runs every 60 ms and schedules its own
        next turn at the end: an exception on the way out would take that with
        it, and the window would go on looking alive while never again learning
        that anything had finished -- busy for good, every button disabled.
        A broken callback is worth one line in the log, not that.
        """
        try:
            while True:
                message = self.results.get_nowait()
                if message[0] == "progress":
                    self._set_activity(message[1])
                    continue
                _, callback, on_error, payload, error = message
                try:
                    if error is None:
                        callback(payload)
                        continue
                    self._set_busy(False)
                    self._write_log(
                        "Fehler", [{"text": str(error), "level": "error"}], False)
                    if on_error:
                        on_error(error)
                except Exception as exc:  # noqa: BLE001 - shown, never swallowed
                    self._set_busy(False)
                    self._write_log("Fehler im Programm",
                                    [{"text": f"{type(exc).__name__}: {exc}",
                                      "level": "error"}], False)
        except queue.Empty:
            pass
        finally:
            self._pump_job = self.after(60, self._pump)

    def _run_async(self, work, callback, on_error=None, activity=""):
        """Run `work(report)` off the UI thread; `report(text)` shows progress."""
        if self.busy:
            return
        self._set_busy(True, activity)

        def report(text):
            self.results.put(("progress", text))

        def task():
            try:
                self.results.put(("done", callback, on_error, work(report), None))
            except Exception as exc:  # noqa: BLE001 - reported in the UI
                self.results.put(("done", callback, on_error, None, exc))

        threading.Thread(target=task, daemon=True).start()

    def _set_busy(self, busy, activity=""):
        self.busy = busy
        state = "disabled" if busy else "normal"
        buttons = [self.connect_button, self.new_host_button,
                   self.listener_button, *self.portainer.busy_buttons(),
                   *self.dns.busy_buttons()]
        for dialog in (self.host_dialog, self.listener_dialog):
            if dialog is not None and dialog.winfo_exists():
                buttons += list(dialog.busy_buttons())
        for button in buttons:
            button.configure(state=state)
        self.configure(cursor="watch" if busy else "")
        if busy:
            self.progress.grid()
            self.progress.start(12)
            self._set_activity(activity or "einen Moment …")
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self._set_activity("")

    def _set_activity(self, text):
        self.activity.configure(text=text)
        self.activity.grid() if text else self.activity.grid_remove()

    def _run_quiet(self, work, callback):
        """Background work that must not disturb anything: no progress bar and
        no error box. The update check runs this way -- it is never the reason
        someone opened the window, so a failing one stays silent."""
        def task():
            try:
                payload = work()
            except Exception:  # noqa: BLE001 - GitHub being unreachable is normal
                return
            self.results.put(("done", callback, None, payload, None))

        threading.Thread(target=task, daemon=True).start()

    # -- what the Portainer tab borrows ------------------------------------
    #
    # The window owns the thread, the progress strip and the log. The tab asks
    # for them through these four rather than reaching into the underscores.

    def run_async(self, work, callback, on_error=None, activity=""):
        self._run_async(work, callback, on_error=on_error, activity=activity)

    def set_busy(self, busy, activity=""):
        self._set_busy(busy, activity)

    def write_log(self, title, lines, ok=None):
        self._write_log(title, lines, ok)

    def removal_plan(self, rules):
        """What it takes to remove these hosts from the firewall again.

        The Portainer tab deletes a stack and the way in to it in one go, in
        one background job with one log. What that job needs from this half --
        the client, the AdGuard in use and the options per host -- is put
        together here, where those things live.
        """
        return {
            "client": self.api,
            "adguard": self._active_adguard(),
            "steps": [argparse.Namespace(
                target=rule["target"], base_domain="",
                prefix=self._prefix_of(rule), dry_run=False,
                no_apply=self.var_no_apply.get(), yes=True)
                for rule in (rules if self.api else [])],
        }

    def remember_endpoint(self, endpoint_id):
        """Keep the chosen Docker environment with the preferences.

        It belongs to the connection but not in the config file: it is a view,
        not a credential, and writing the config would rewrite the profiles.
        """
        chosen = dict(self.prefs.get("portainer_endpoint") or {})
        name = self.active.get("portainer", "")
        if chosen.get(name) == endpoint_id:
            return  # already written down; every reading says it again
        chosen[name] = endpoint_id
        self.prefs["portainer_endpoint"] = chosen
        save_prefs(self.prefs)

    def provision_host(self, values):
        """Create a HAProxy host for a container port from the Portainer tab."""
        if self.busy or not self.api:
            return
        opts = argparse.Namespace(
            base_domain=values["base_domain"],
            dns_target=self.adguard_target,
            target=values["target"],
            ip=values["ip"],
            port=values["port"],
            ssl=values["ssl"],
            ssl_verify=False,
            frontend=values["frontend"],
            backend_mode=None,
            healthcheck=values["healthcheck"],
            forward_for=True,
            prefix="",
            dry_run=False,
            no_apply=self.var_no_apply.get(),
            yes=True,
        )
        adguard = self.adguard if values.get("dns") else None
        client = self.api
        self._run_async(
            lambda report: core.run_step(core.provision, client, opts, adguard,
                                         log=LiveLog(report)),
            lambda result: self._step_done(result, False, clear=False),
            activity=f"lege {values['target']} an …")

    # -- updates -----------------------------------------------------------

    def _paint_update_button(self):
        """The button carries the new version number once one is known."""
        if self.update_release:
            self.update_button.configure(
                text=f"⇩ {self.update_release['version']}", style="Update.TButton")
        else:
            self.update_button.configure(text="⇩ Update", style="Tool.TButton")

    def _update_on_start(self):
        """Ask GitHub at most once a day, and remember the answer in between."""
        if not self.prefs.get("update_check", True):
            return
        known = self.prefs.get("update_found", "")
        if known and core.parse_version(known) > core.parse_version(core.VERSION):
            self.update_release = {"version": known}  # enough to show the badge
            self._paint_update_button()

        last = self.prefs.get("update_checked", 0)
        if isinstance(last, (int, float)) and time.time() - last < 24 * 3600:
            return
        self.prefs["update_checked"] = int(time.time())
        self._run_quiet(lambda: core.check_for_update(), self._update_found)

    def _update_found(self, release):
        self.update_release = release
        self.prefs["update_found"] = release["version"] if release else ""
        self._paint_update_button()

    def _check_update(self):
        """The button: always asks GitHub, and always says what it found."""
        if self.update_checking:
            return
        self.update_checking = True
        self._set_activity("suche nach Updates …")

        def done(release):
            self.update_checking = False
            self.prefs["update_checked"] = int(time.time())
            self._set_activity("")
            self._update_found(release)
            if release is None:
                messagebox.showinfo(
                    APP_TITLE,
                    f"Version {core.VERSION} ist aktuell.\n\n"
                    "Es gibt nichts Neueres auf GitHub.", parent=self)
                return
            UpdateDialog(self, self.colors, release)

        def failed(error):
            self.update_checking = False
            self._set_activity("")
            messagebox.showwarning(
                APP_TITLE, f"Die Update-Prüfung ist fehlgeschlagen:\n\n{error}",
                parent=self)

        def task():
            try:
                self.results.put(("done", done, None,
                                  core.check_for_update(), None))
            except Exception as exc:  # noqa: BLE001 - shown in the box above
                # bound as a default: `exc` is gone once the except block ends
                self.results.put(("done", lambda _p, error=exc: failed(error),
                                  None, None, None))

        threading.Thread(target=task, daemon=True).start()

    def restart(self):
        """Start the freshly installed version in place of this one."""
        self._save_prefs()
        if self._pump_job is not None:
            self.after_cancel(self._pump_job)
            self._pump_job = None
        self.destroy()
        try:
            script = os.path.abspath(sys.argv[0])
            os.execl(sys.executable, sys.executable, script, *sys.argv[1:])
        except OSError as exc:
            print(f"please start the program again ({exc})", file=sys.stderr)

    # -- actions -----------------------------------------------------------

    def _connect(self):
        # A missing config file is the normal first start here, not an error --
        # the settings are what fill it in.
        config = {}
        path = self.config_path
        if os.path.exists(path):
            try:
                config = core.load_config(path)
            except core.UsageError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
        self.settings = config
        self.systems = core.systems_of(config)
        self.favorites = catalog.favourites_of(config)
        self.active = {kind: core.active_name(config, kind, self.systems)
                       for kind in core.SYSTEM_KINDS}
        if self.args.profile:
            named = core.find_system(self.systems, "opnsense", self.args.profile)
            if not named:
                known = ", ".join(e.get("name", "?")
                                  for e in self.systems["opnsense"])
                messagebox.showerror(
                    APP_TITLE, f"Keine OPNsense namens „{self.args.profile}“ "
                               f"(vorhanden: {known or 'keine'}).")
            else:
                self.active["opnsense"] = self.args.profile
        self._follow_links()
        self._fill_switcher()
        self._use_active(first_run=True, connect=False)

    def _follow_links(self):
        """Let the chosen OPNsense decide which AdGuard and Portainer to use.

        Only where it names one: a firewall without a link keeps whatever is
        selected, so switching back and forth does not silently drop DNS.
        """
        entry = core.find_system(self.systems, "opnsense", self.active["opnsense"])
        for kind in ("adguard", "portainer"):
            named = entry.get(kind, "")
            if named and core.find_system(self.systems, kind, named):
                self.active[kind] = named

    def _fill_switcher(self):
        """The picker in the header belongs to whichever half is in front.

        On the HAProxy tab it chooses the firewall, on the Portainer tab the
        Docker host, on the AdGuard tab the DNS server -- so it always names
        the thing that is being looked at. It used to switch the firewall on
        both, which on the second tab changed something that was nowhere on
        the screen. The way to the settings is at the end of every list.
        """
        kind = self.active_tab()
        if kind not in ("portainer", "adguard"):
            kind = "opnsense"
        names = [e.get("name", "?") for e in self.systems.get(kind, [])]
        self.profile_box.configure(values=names + [EDIT_PROFILE],
                                   state="readonly")
        self.var_profile.set(self.active.get(kind, ""))
        self.profile_tip.text = SWITCHER_TIP[kind]
        self.profile_box.grid()

    def _fill_frontends(self):
        """Let an open form take up a fresh reading of the public services."""
        if self.host_dialog is not None and self.host_dialog.winfo_exists():
            self.host_dialog.fill_frontends()

    def _fill_dns_choices(self):
        """Which AdGuard the next host gets -- the one this OPNsense uses.

        The choice itself lives here rather than in the form: it is written
        down on the firewall, the header picker on the AdGuard tab changes it
        too, and a host removed while no form is open has to know it as well.
        """
        names = [e.get("name", "?") for e in self.systems.get("adguard", [])]
        chosen = self.active.get("adguard", "")
        self.var_dns_target.set(chosen if chosen in names else NO_DNS)
        if self.host_dialog is not None and self.host_dialog.winfo_exists():
            self.host_dialog.fill_dns_choices()

    def _dns_target_changed(self):
        """A different AdGuard for what is about to be created.

        The choice is remembered on the OPNsense entry, so the next start comes
        up with the pair that was last used together. Where there is no
        firewall to remember it -- somebody who set up only an AdGuard -- the
        selection itself is written down, which is kept in the same file.
        """
        chosen = self.var_dns_target.get()
        self.active["adguard"] = "" if chosen == NO_DNS else chosen
        entry = core.find_system(self.systems, "opnsense", self.active["opnsense"])
        if entry:
            if self.active["adguard"]:
                entry["adguard"] = self.active["adguard"]
            else:
                entry.pop("adguard", None)
        self._write_settings()
        self.profile = core.merged_profile(self.systems, entry,
                                           adguard=self.active["adguard"],
                                           portainer=self.active["portainer"])
        self._build_adguard()
        self._render_inventory()

    def _use_active(self, first_run=False, connect=True):
        """Take up whatever is selected right now, or ask when nothing works.

        ``connect`` is false on start-up: opening the window should not reach
        out to anything by itself. The connect button does that.
        """
        entry = core.find_system(self.systems, "opnsense", self.active["opnsense"])
        self.profile = core.merged_profile(self.systems, entry,
                                           adguard=self.active.get("adguard"),
                                           portainer=self.active.get("portainer"))
        self.connected = False
        self.services, self.domains = [], []
        self._fill_switcher()
        self._fill_dns_choices()
        # all three parts belong to the same window, so the other two follow
        # what was just chosen -- without reaching out yet
        self.portainer.use_profile(self.profile)
        # before the firewall's own client, which may not exist at all: a
        # place with AdGuard but no OPNsense still has a DNS list to show
        self._build_adguard()
        try:
            self.api = core.build_client(self.args, self.profile)
        except core.UsageError:
            self.api = None
            self._set_status(None, "keine Zugangsdaten")
            self.paint_connection()
            self._render_inventory()
            if first_run:
                self.open_settings()
            return
        if not connect:
            self._set_status(None, "nicht verbunden", idle=True)
            self.paint_connection()
            self._render_inventory()
            return
        self.reload()

    def _connect_now(self):
        """The connect button: it works on whichever tab is in front."""
        if self.active_tab() == "portainer":
            self.portainer.reload()
            return
        if self.active_tab() == "adguard":
            self.dns.reload()
            return
        if not self.api:
            self.open_settings()
            return
        self.reload()

    def paint_connection(self):
        """Let the pill and the connect button speak for the tab in front."""
        if self.active_tab() == "portainer":
            text, ok = self.portainer.status_text()
            style = "OkPill.TLabel" if ok else "IdlePill.TLabel"
            connected = self.portainer.connected
            self.subtitle.configure(text="Docker-Stacks über Portainer")
        elif self.active_tab() == "adguard":
            text, ok = self.dns.status_text()
            style = "OkPill.TLabel" if ok else "IdlePill.TLabel"
            connected = self.dns.connected
            self.subtitle.configure(text="DNS-Umschreibungen in AdGuard Home")
        else:
            text, style = self.haproxy_pill
            connected = self.connected
            self.subtitle.configure(text="OPNsense Reverse Proxy")
        self.status_pill.configure(text=text, style=style)
        self.connect_button.configure(
            text="Neu laden" if connected else "Verbinden",
            style="Tool.TButton" if connected else "Accent.TButton")

    def _switch_active(self):
        """The picker was used: change what the tab in front stands for."""
        choice = self.var_profile.get()
        if choice == EDIT_PROFILE:
            self._fill_switcher()  # put the name back before the dialog opens
            self.open_settings()
            return
        if self.active_tab() == "portainer":
            self.switch_portainer(choice)
            return
        if self.active_tab() == "adguard":
            self.switch_adguard(choice)
            return
        self._switch_profile(choice)

    def _switch_profile(self, choice):
        if choice == self.profile.get("name"):
            return
        if core.find_system(self.systems, "opnsense", choice):
            self.active["opnsense"] = choice
            self._follow_links()
            self._write_settings()
            self._use_active()

    def switch_portainer(self, name):
        """Point the second tab at another Portainer and remember the pairing.

        Like the AdGuard picker in the form, the choice sticks to the OPNsense
        that is in use: a place has one firewall and one Docker host, and the
        next start should come up with the pair that was last used together.
        """
        if (not name or name == self.active.get("portainer")
                or not core.find_system(self.systems, "portainer", name)):
            self._fill_switcher()  # the picker may be showing something else
            return
        self.active["portainer"] = name
        entry = core.find_system(self.systems, "opnsense", self.active["opnsense"])
        if entry:
            entry["portainer"] = name
        self._write_settings()
        self.profile = core.merged_profile(
            self.systems, entry, adguard=self.active.get("adguard"),
            portainer=name)
        self.portainer.use_profile(self.profile)
        self._fill_switcher()
        # a Portainer that was read a moment ago comes back with what it said
        # then; only one nobody has looked at yet is asked now
        if not self.portainer.connected:
            self.portainer.reload()

    def switch_adguard(self, name):
        """Show another AdGuard, and let the form's picker follow along.

        Both pickers choose the same thing, so the header goes through the
        form: one place decides what the choice costs -- the note on the
        firewall, the client, and the DNS marks in the host list.
        """
        if (not name or name == self.active.get("adguard")
                or not core.find_system(self.systems, "adguard", name)):
            self._fill_switcher()  # the picker may be showing something else
            return
        self.var_dns_target.set(name)
        self._dns_target_changed()
        self._fill_switcher()
        self.dns.reload()

    def connect_and_deploy(self, opnsense, portainer, preset):
        """Take up the chosen pair, then carry on to the deploy form.

        Three things that cannot happen at once, so each one hands over to the
        next: the firewall first -- taking one up rebuilds the profile and
        resets the Portainer half, which would undo a connection made before
        it. Then Portainer, which is what a deploy actually needs. The form and
        the reading of the repository come last, from ``_loaded`` over there,
        once there is an environment to send the stack to.

        Unless the pair asked for is the pair in hand, which is the usual
        answer: then nothing is taken up at all. Being asked where a stack
        should go must not cost a round of logins to the two machines that are
        already logged into.
        """
        in_hand = self._pair_in_hand(opnsense, portainer)
        if portainer and core.find_system(self.systems, "portainer", portainer):
            self.active["portainer"] = portainer
        if opnsense and core.find_system(self.systems, "opnsense", opnsense):
            self.active["opnsense"] = opnsense
        entry = core.find_system(self.systems, "opnsense", self.active["opnsense"])
        if entry and self.active.get("portainer"):
            entry["portainer"] = self.active["portainer"]  # the pair, remembered
        self._write_settings()

        self.portainer.pending_deploy = preset
        if in_hand:
            self.portainer.start_pending_deploy()
            return
        self._use_active(connect=bool(opnsense))
        self._fill_switcher()
        if self.busy:
            return  # the firewall is being read; the hand-over follows it
        # Nothing was started when there is no firewall to reach, or none was
        # chosen -- then the Portainer half goes now rather than waiting for a
        # hand-over that will never come.
        self._hand_over_to_portainer()

    def _pair_in_hand(self, opnsense, portainer):
        """Whether what was just chosen is what is connected right now.

        The firewall only counts where one was chosen: „ohne OPNsense“ is an
        answer about this deploy, not a reason to drop a connection.
        """
        if not self.portainer.connected:
            return False
        if portainer and portainer != self.active.get("portainer"):
            return False
        if not opnsense:
            return True
        return self.connected and opnsense == self.active.get("opnsense")

    def _hand_over_to_portainer(self):
        """After the firewall: connect Portainer, if a deploy is waiting."""
        if self.portainer.pending_deploy is None:
            return
        if self.portainer.connected:
            # the reading of this one is still in hand -- straight to the form
            self.portainer.start_pending_deploy()
            return
        self.portainer.reload()

    def _build_adguard(self):
        self.adguard, settings = core.adguard_from_config(self.profile)
        self.adguard_target = settings.get("target", "")
        self.adguard_problem = settings.get("error", "")
        self.rewrites, self.rewrites_error = {}, ""
        if self.adguard and not self.adguard_target:
            self.adguard = None  # without a target there is nothing to write
            self.adguard_problem = "AdGuard: keine HAProxy-IP eingetragen (⚙)"
        self._refresh_fqdn()
        # The third tab keeps a client of its own: reading and editing the
        # rewrite list works without a HAProxy address, which is the one thing
        # this half insists on.
        self.dns.use_profile(self.profile)

    def dns_reloaded(self, entries, error=""):
        """A fresh reading of AdGuard's rewrites, from wherever it came.

        The host list marks every name with what AdGuard says about it, so a
        rewrite written on the third tab shows up on the first one right away
        -- without a second round trip for the same answer.
        """
        self.rewrites = core.as_rewrite_map(entries)
        self.rewrites_error = error
        self._render_inventory()

    def open_settings(self, parent=None):
        """The one place where systems are added, changed and removed.

        ``parent`` is the window that asked for it. The dialog is modal, and a
        modal window belonging to the main window opens *behind* a dialog that
        is currently in front -- where it holds every click and looks like the
        program has hung.
        """
        dialog = SettingsDialog(parent if parent is not None else self, self)
        self.wait_window(dialog)
        self._fill_switcher()
        self.args.insecure = False
        # an address or a token may be a different one now, so what was read
        # from the old ones says nothing any more
        self.portainer.forget_cache()
        self._use_active()

    def _paint_install_button(self):
        """Offer to install only while there is something left to install.

        Started from the folder the starters lead to, the answer is already
        given: installing again would do nothing but write those same starters
        once more, under a word that promises more than that. A copy run from
        wherever it was unpacked keeps the button.
        """
        if core.installed_here():
            self.install_button.grid_remove()
        else:
            self.install_button.grid()

    def _open_install(self):
        dialog = InstallDialog(self, self.colors)
        self.wait_window(dialog)
        # installing into the folder this copy runs from makes it the
        # installed one, so the button goes without waiting for a restart
        self._paint_install_button()

    def remember_system(self, kind, previous, entry):
        """Add or replace one system, and keep the links pointing at it.

        Renaming is the reason the old name is passed in: every OPNsense that
        named the old one has to follow, or the rename would quietly unlink
        DNS or Docker.
        """
        entries = self.systems.setdefault(kind, [])
        for index, known in enumerate(entries):
            if known.get("name") == previous:
                entries[index] = entry
                break
        else:
            entries.append(entry)
        if previous and previous != entry["name"] and kind != "opnsense":
            for firewall in self.systems.get("opnsense", []):
                if firewall.get(kind) == previous:
                    firewall[kind] = entry["name"]
        if self.active.get(kind) in ("", previous) or len(entries) == 1:
            self.active[kind] = entry["name"]
        self._write_settings()

    def forget_system(self, kind, name):
        """Remove one system and cut every link that pointed at it."""
        self.systems[kind] = [e for e in self.systems.get(kind, [])
                              if e.get("name") != name]
        if kind != "opnsense":
            for firewall in self.systems.get("opnsense", []):
                if firewall.get(kind) == name:
                    firewall.pop(kind, None)
        if self.active.get(kind) == name:
            remaining = self.systems[kind]
            self.active[kind] = remaining[0].get("name", "") if remaining else ""
        self._write_settings()

    def remember_favourite(self, entry, previous=""):
        """Keep one stack under the favourites, or replace the one renamed."""
        self.favorites = catalog.put_favourite(self.favorites, entry, previous)
        self._write_settings()

    def forget_favourite(self, name):
        self.favorites = catalog.drop_favourite(self.favorites, name)
        self._write_settings()

    def _write_settings(self):
        """Put the three lists back on disk, mode 600 -- they hold keys."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.config_path)),
                        exist_ok=True)
            with open(self.config_path, "w") as handle:
                json.dump(core.as_settings_file(self.systems, self.active,
                                                self.favorites),
                          handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.chmod(self.config_path, 0o600)
        except OSError as exc:
            messagebox.showerror("Nicht gespeichert", str(exc))
            return False
        self.settings = core.load_config(self.config_path)
        return True

    def reload(self):
        if not self.api:
            return
        client, adguard = self.api, self.adguard

        def work(report):
            report(f"verbinde mit {self.profile.get('name', 'OPNsense')} …")
            status = client.status().get("status", "unknown")
            report("lese Public Services und Rules …")
            services = core.inventory(client)
            report("lese Health Monitore …")
            healthchecks = sorted(row.get("name", "")
                                  for row in client.search("healthcheck"))
            report("lese Zertifikate des ACME-Clients …")
            try:
                domains = core.base_domains(client)
            except core.ApiError:
                domains = []  # the ACME plugin is optional
            report("lese, was ein Listener bekommen kann …")
            try:
                listener_choices = core.listener_choices(client)
            except core.ApiError:
                # only the second form needs them; the rest of the tab is
                # worth more than an empty certificate list costs
                listener_choices = {"certificates": [], "modes": []}
            entries, rewrites_error = None, ""
            if adguard:
                report("lese DNS-Einträge aus AdGuard …")
                try:
                    entries = adguard.rewrites()
                except core.ApiError as exc:
                    # AdGuard being away must not cost us the whole inventory
                    rewrites_error = str(exc)
            return {"status": status, "services": services,
                    "healthchecks": healthchecks, "domains": domains,
                    "listener_choices": listener_choices,
                    "entries": entries, "rewrites_error": rewrites_error}

        self._run_async(work, self._state_loaded,
                        on_error=self._connect_failed,
                        activity="verbinde …")

    def _connect_failed(self, _error):
        self.connected = False
        self._set_status(None)
        self.paint_connection()
        self._render_inventory()
        # a firewall that cannot be reached is no reason to drop a deploy: the
        # stack goes to Portainer, the way over HAProxy can wait
        self._hand_over_to_portainer()

    def _state_loaded(self, state):
        self._set_busy(False)
        self.connected = True
        self.services = state["services"]
        self.healthchecks = state["healthchecks"]
        self.rewrites = core.as_rewrite_map(state["entries"] or [])
        self.rewrites_error = state["rewrites_error"]
        if state["entries"] is not None:
            # read on the way past, so the third tab is filled in without a
            # connect of its own
            self.dns.take(state["entries"])
        self.listener_choices = state["listener_choices"]
        self._set_status(state["status"])
        self.paint_connection()

        self.domains = state["domains"]
        bases = [NO_BASE] + [entry["domain"] for entry in self.domains]
        if self.var_base.get() not in bases:
            preferred = self.profile.get("defaults", {}).get("base_domain", "")
            self.var_base.set(preferred if preferred in bases else NO_BASE)
        if self.var_healthcheck.get() not in [NO_HEALTHCHECK] + self.healthchecks:
            self.var_healthcheck.set(NO_HEALTHCHECK)

        # a form that is open was filled from what we knew a moment ago
        for dialog in (self.host_dialog, self.listener_dialog):
            if dialog is not None and dialog.winfo_exists():
                dialog.refresh()

        self._render_inventory()
        # the ports over there are marked with what HAProxy already does with
        # them, so a fresh reading of the rules changes that list too
        self.portainer.render()
        self._hand_over_to_portainer()

    def _set_status(self, status, error=None, idle=False):
        # kept rather than shown right away: the pill belongs to whichever tab
        # is in front, and this is only the HAProxy side's half of it
        if error or status is None:
            self.haproxy_pill = (error or "nicht erreichbar",
                                 "IdlePill.TLabel" if idle else "BadPill.TLabel")
        else:
            running = "running" in str(status).lower()
            self.haproxy_pill = (
                "HAProxy läuft" if running else f"HAProxy: {status}",
                "OkPill.TLabel" if running else "BadPill.TLabel")
        self.paint_connection()

    def _form_options(self, dry_run):
        healthcheck = self.var_healthcheck.get()
        mode = self.var_backend_mode.get()
        base = self.var_base.get()
        return argparse.Namespace(
            base_domain="" if base == NO_BASE else base,
            dns_target=self.adguard_target,
            target=self.var_target.get().strip(),
            ip=self.var_ip.get().strip(),
            port=int(self.var_port.get()) if self.var_port.get().strip() else None,
            ssl=self.var_ssl.get(),
            ssl_verify=self.var_ssl_verify.get(),
            frontend=self.var_frontend.get() or None,
            backend_mode=None if mode == "automatisch" else mode,
            healthcheck=None if healthcheck.startswith("\u2014") else healthcheck,
            forward_for=self.var_forward_for.get(),
            prefix=self.var_prefix.get().strip(),
            dry_run=dry_run,
            no_apply=self.var_no_apply.get(),
            yes=True,
        )

    def open_host(self):
        """The form for a new host, in a window of its own.

        Like the deploy form on the Portainer tab, and for the same reason: as
        a column beside the listing it had a third of the window for fields
        that want more, and the listing had the rest of the time to be narrow
        in. Not modal -- the log at the bottom belongs to this, and a preview
        is meant to be read while the form is still standing.
        """
        if self.host_dialog is not None and self.host_dialog.winfo_exists():
            self.host_dialog.lift()
            self.host_dialog.focus_set()
            return
        self.host_dialog = HostDialog(self)

    def open_listener(self):
        """The form for a public service of its own."""
        if self.listener_dialog is not None and self.listener_dialog.winfo_exists():
            self.listener_dialog.lift()
            self.listener_dialog.focus_set()
            return
        self.listener_dialog = ListenerDialog(self)

    def _ready_to_write(self):
        """Nothing is created from a firewall nobody has read yet."""
        if not self.api:
            messagebox.showinfo(APP_TITLE,
                                "Für die OPNsense fehlen die Zugangsdaten (\u2699).")
            return False
        if not self.connected:
            messagebox.showinfo(APP_TITLE,
                                "Bitte zuerst verbinden \u2014 ohne die Public "
                                "Services von der OPNsense wei\u00df das Programm "
                                "nicht, wo die Rule hin soll.")
            return False
        return True

    def _submit(self, dry_run):
        if self.busy or not self._ready_to_write():
            return
        opts = self._form_options(dry_run)
        if not opts.target:
            messagebox.showwarning(APP_TITLE, "Bitte eine URL eintragen.")
            return
        if not opts.ip:
            messagebox.showwarning(APP_TITLE, "Bitte die IP des Servers eintragen.")
            return
        client, adguard = self.api, self._active_adguard()
        self._run_async(
            lambda report: core.run_step(core.provision, client, opts, adguard,
                                         log=LiveLog(report)),
            lambda result: self._step_done(result, dry_run),
            activity="pr\u00fcfe Vorhandenes \u2026")

    def create_listener(self, dry_run):
        """Build the public service the second form describes."""
        if self.busy or not self._ready_to_write():
            return
        cert = next((entry for entry in self.listener_choices["certificates"]
                     if entry["name"] == self.var_listen_cert.get()), None)
        host = self.var_listen_host.get().strip().lower().rstrip(".")
        opts = argparse.Namespace(
            name=self.var_listen_name.get().strip(),
            port=self.var_listen_port.get().strip(),
            backend_port=self.var_listen_backend_port.get().strip(),
            address=self.var_listen_address.get().strip(),
            mode=self.var_listen_mode.get(),
            certificate=cert["id"] if cert else "",
            certificate_name=cert["name"] if cert else "",
            ip=self.var_listen_ip.get().strip(),
            ssl=self.var_listen_ssl.get(),
            ssl_verify=self.var_listen_ssl_verify.get(),
            host=host,
            dns_target=self.adguard_target,
            prefix=self.var_prefix.get().strip(),
            dry_run=dry_run,
            no_apply=self.var_no_apply.get(),
            yes=True,
        )
        adguard = self._active_adguard() if (self.var_listen_dns.get()
                                             and host) else None
        client = self.api
        self._run_async(
            lambda report: core.run_step(core.provision_listener, client, opts,
                                         adguard, log=LiveLog(report)),
            lambda result: self._step_done(result, dry_run, form="listener"),
            activity="pr\u00fcfe Vorhandenes \u2026")

    def _active_adguard(self):
        """The chosen AdGuard, unless the picker says to leave DNS alone."""
        return self.adguard if self.var_dns_target.get() != NO_DNS else None

    def _remove(self, rule):
        if self.busy or not self.api:
            return
        target = rule["target"]
        adguard = self._active_adguard()
        extra = "\nEin passender AdGuard-Eintrag wird ebenfalls entfernt." \
            if adguard else ""
        if not messagebox.askyesno(
                APP_TITLE,
                f"{target} entfernen?\n\n"
                "Real Server, Backend Pool, Condition und Rule werden gelöscht."
                + extra,
                icon="warning"):
            return
        opts = argparse.Namespace(target=target, base_domain="",
                                  prefix=self._prefix_of(rule),
                                  dry_run=False, no_apply=self.var_no_apply.get(),
                                  yes=True)
        client = self.api
        self._run_async(
            lambda report: core.run_step(core.deprovision, client, opts, adguard,
                                         log=LiveLog(report)),
            lambda result: self._step_done(result, False),
            activity=f"entferne {target} …")

    def _remove_listener(self, service):
        """Take a whole public service away, with what stands behind it."""
        if self.busy or not self._ready_to_write():
            return
        pool = service.get("default") or {}
        parts = [f"Public Service {service['name']}"
                 + (f" ({service['bind']})" if service["bind"] else "")]
        if pool.get("name"):
            parts.append(f"Backend Pool {pool['name']}")
        parts += [f"Real Server {server['name']}"
                  for server in pool.get("servers") or []]
        adguard = self._active_adguard() if service.get("dns") else None
        text = (", ".join(parts[:-1]) + " und " + parts[-1]) if len(parts) > 1 \
            else parts[0]
        question = (f"{service['name']} entfernen?\n\n{text} werden gelöscht — "
                    "soweit sie nicht noch anderswo benutzt werden.")
        if adguard:
            question += f"\n\nDer DNS-Eintrag {service['dns']} geht mit."
        if not service.get("managed"):
            question += ("\n\nDieser Public Service wurde nicht von diesem "
                         "Programm angelegt.")
        if not messagebox.askyesno(APP_TITLE, question, icon="warning",
                                   default=messagebox.NO):
            return
        opts = argparse.Namespace(name=service["name"], host="", dry_run=False,
                                  no_apply=self.var_no_apply.get(), yes=True)
        client = self.api
        self._run_async(
            lambda report: core.run_step(core.deprovision_listener, client,
                                         opts, adguard, log=LiveLog(report)),
            lambda result: self._step_done(result, False, clear=False),
            activity=f"entferne {service['name']} …")

    @staticmethod
    def _prefix_of(rule):
        """Rules created with a name prefix must be removed with the same one."""
        marker = rule["name"].find("rule_")
        return rule["name"][:marker] if marker > 0 else ""

    def _step_done(self, result, dry_run, clear=True, form="host"):
        self._set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
        if not lines:
            lines = [{"text": "keine R\u00fcckmeldung", "level": "error"}]
        title = ("Vorschau" if dry_run else "Fertig") if result["ok"] \
            else "Fehlgeschlagen"
        self._write_log(title, lines, result["ok"])

        # The form stands in front of the log, so what it set off has to reach
        # it as well: a preview and a failure keep the window and say so in it,
        # a finished one closes.
        dialog = self.listener_dialog if form == "listener" else self.host_dialog
        if dialog is not None and dialog.winfo_exists():
            if result["ok"] and not dry_run:
                dialog.destroy()
            else:
                dialog.say(lines[-1]["text"], ok=result["ok"])
        if result["ok"] and not dry_run:
            # a host created from the Portainer tab must not empty a form
            # somebody may have been filling in over here
            if clear:
                for var in (self.var_target, self.var_ip, self.var_port):
                    var.set("")
                self.port_touched = False
            self.reload()

    # -- small interactions ------------------------------------------------

    def _refresh_fqdn(self):
        """The open form shows the name it would create; without one, nothing."""
        if self.host_dialog is not None and self.host_dialog.winfo_exists():
            self.host_dialog.refresh_hints()

    def _port_typed(self, _event):
        self.port_touched = bool(self.var_port.get().strip())

    def _save_prefs(self):
        # keep everything else that is in there, e.g. the update bookkeeping
        self.prefs.update({"theme": self.theme_name, "geometry": self.geometry(),
                           "all_frontends": bool(self.var_all_frontends.get())})
        save_prefs(self.prefs)

    def _on_close(self):
        self._save_prefs()
        if self._pump_job is not None:
            self.after_cancel(self._pump_job)
            self._pump_job = None
        self.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Desktop GUI for opnsense-haproxy")
    parser.add_argument("--config", help=f"config file (default: {core.DEFAULT_CONFIG})")
    parser.add_argument("-P", "--profile", help="which connection to start with")
    parser.add_argument("--url")
    parser.add_argument("--key")
    parser.add_argument("--secret")
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args(argv)
    try:
        App(args).mainloop()
    except tk.TclError as exc:
        print(f"error: no graphical display available ({exc})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
