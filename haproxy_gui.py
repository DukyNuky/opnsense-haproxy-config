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

try:
    import tkinter as tk
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

APP_TITLE = "HAProxy · OPNsense"
NO_BASE = "— keine —"
NEW_PROFILE = "＋ neue Verbindung …"
EDIT_PROFILE = "⚙ diese bearbeiten …"

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


# --------------------------------------------------------------------------
# connection dialog
# --------------------------------------------------------------------------


class ProfileDialog(tk.Toplevel):
    """Edits one OPNsense connection, with its optional AdGuard underneath."""

    def __init__(self, parent, colors, profile, config_path, taken_names=(),
                 can_delete=False):
        super().__init__(parent)
        self.title("Verbindung bearbeiten")
        self.delete_requested = False
        self.colors = colors
        self.config_path = config_path or core.DEFAULT_CONFIG
        self.result = None
        self.original_name = profile.get("name", "")
        self.taken_names = {n for n in taken_names if n != self.original_name}
        # keep settings this dialog does not show, e.g. frontend and defaults
        self.extra = {k: v for k, v in profile.items()
                      if k not in ("name", "url", "key", "secret", "verify_ssl",
                                   "adguard")}
        self.transient(parent)
        self.configure(bg=colors["bg"])

        # The form is taller than some screens, so it scrolls; the buttons sit
        # outside the scroller and stay reachable.
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.scroll = ScrollFrame(self, colors)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)
        scroll = self.scroll

        body = ttk.Frame(scroll.body, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        self.vars = {
            "name": tk.StringVar(value=profile.get("name", "")),
            "url": tk.StringVar(value=profile.get("url", "https://opnsense.local")),
            "key": tk.StringVar(value=profile.get("key", "")),
            "secret": tk.StringVar(value=profile.get("secret", "")),
        }
        self.verify = tk.BooleanVar(value=profile.get("verify_ssl", False))

        ttk.Label(body, text="OPNsense", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 8))
        for label, name, secret, hint in (
                ("Name der Verbindung", "name", False, "z.B. Zuhause oder Büro"),
                ("Adresse", "url", False, ""),
                ("API-Key", "key", False, ""),
                ("API-Secret", "secret", True, "")):
            ttk.Label(body, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(8, 3))
            ttk.Entry(body, textvariable=self.vars[name], width=40,
                      style="Card.TEntry", show="•" if secret else "").grid(
                row=next(rows), column=0, sticky="ew")
            if hint:
                ttk.Label(body, text=hint, style="Hint.TLabel").grid(
                    row=next(rows), column=0, sticky="w", pady=(2, 0))

        ttk.Checkbutton(body, text="TLS-Zertifikat der OPNsense prüfen",
                        variable=self.verify, style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w", pady=(10, 0))

        ttk.Separator(body, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=12)

        adg = profile.get("adguard") or {}
        self.adg_vars = {
            "url": tk.StringVar(value=adg.get("url", "")),
            "username": tk.StringVar(value=adg.get("username", "")),
            "password": tk.StringVar(value=adg.get("password", "")),
            "target": tk.StringVar(value=adg.get("target", "")),
        }
        self.adg_verify = tk.BooleanVar(value=adg.get("verify_ssl", False))
        self.use_adguard = tk.BooleanVar(value=bool(adg.get("url")))

        ttk.Label(body, text="AdGuard Home", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Checkbutton(body, text="Für diese Verbindung DNS-Einträge anlegen",
                        variable=self.use_adguard, style="Card.TCheckbutton",
                        command=self._toggle_adguard).grid(
            row=next(rows), column=0, sticky="w", pady=(6, 0))
        ttk.Label(body, style="Hint.TLabel", wraplength=330, justify="left",
                  text="Ohne Haken bleibt DNS unangetastet.").grid(
            row=next(rows), column=0, sticky="w", pady=(2, 6))

        self.adg_box = ttk.Frame(body, style="Card.TFrame")
        self.adg_box.grid(row=next(rows), column=0, sticky="ew")
        self.adg_box.columnconfigure(0, weight=1)
        adg_rows = itertools.count()
        for label, name, secret, hint in (
                ("Adresse", "url", False, "z.B. https://adguard.example.de"),
                ("Benutzer", "username", False, ""),
                ("Passwort", "password", True, ""),
                ("Ziel der Umschreibung", "target", False,
                 "IP von HAProxy, z.B. 192.168.1.1")):
            ttk.Label(self.adg_box, text=label, style="FieldLabel.TLabel").grid(
                row=next(adg_rows), column=0, sticky="w", pady=(6, 3))
            ttk.Entry(self.adg_box, textvariable=self.adg_vars[name], width=40,
                      style="Card.TEntry", show="•" if secret else "").grid(
                row=next(adg_rows), column=0, sticky="ew")
            if hint:
                ttk.Label(self.adg_box, text=hint, style="Hint.TLabel").grid(
                    row=next(adg_rows), column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(self.adg_box, text="TLS-Zertifikat von AdGuard prüfen",
                        variable=self.adg_verify,
                        style="Card.TCheckbutton").grid(
            row=next(adg_rows), column=0, sticky="w", pady=(8, 0))
        self._toggle_adguard()

        ttk.Label(body, style="Hint.TLabel", wraplength=330, justify="left",
                  text="Schlüssel: System → Zugriff → Benutzer → API-Schlüssel. "
                       f"Gespeichert in {self.config_path}").grid(
            row=next(rows), column=0, sticky="w", pady=(12, 0))

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
        ttk.Button(buttons, text="Speichern & verbinden", style="Accent.TButton",
                   command=self._save).grid(row=0, column=1)

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self._fit(parent)
        self.grab_set()

    def _fit(self, parent):
        """Never grow past the screen -- the scroller takes care of the rest.

        The size has to come from the scrolled content: a canvas reports its
        own default size, not what is inside it.
        """
        content = self.scroll.body.winfo_reqheight()
        width = max(self.scroll.body.winfo_reqwidth() + 18, 380)
        tallest = int(self.winfo_screenheight() * 0.85)
        height = min(content + self.footer.winfo_reqheight() + 4, tallest)
        self.geometry(f"{width}x{height}")
        self.minsize(width, min(420, height))
        self.resizable(False, True)
        self.update_idletasks()
        self._centre(parent)

    def _delete(self):
        if messagebox.askyesno(
                APP_TITLE,
                f"Verbindung '{self.original_name}' entfernen?\n\n"
                "Es wird nur dieser Eintrag gelöscht, an OPNsense ändert sich "
                "nichts.", icon="warning", parent=self):
            self.delete_requested = True
            self.destroy()

    def _toggle_adguard(self):
        if self.use_adguard.get():
            self.adg_box.grid()
        else:
            self.adg_box.grid_remove()

    def _centre(self, parent):
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _save(self):
        values = {name: var.get().strip() for name, var in self.vars.items()}
        missing = [label for label, name in
                   (("Name", "name"), ("Adresse", "url"), ("API-Key", "key"),
                    ("API-Secret", "secret")) if not values[name]]
        if missing:
            messagebox.showwarning("Unvollständig",
                                   "Bitte ausfüllen: " + ", ".join(missing),
                                   parent=self)
            return
        if values["name"] in self.taken_names:
            messagebox.showwarning("Name schon vergeben",
                                   f"Es gibt bereits eine Verbindung namens "
                                   f"'{values['name']}'.", parent=self)
            return
        config = {**values, "verify_ssl": self.verify.get()}
        if self.use_adguard.get():
            adguard = {name: var.get().strip()
                       for name, var in self.adg_vars.items()}
            if not adguard["url"] or not adguard["target"]:
                messagebox.showwarning(
                    "AdGuard unvollständig",
                    "Adresse und Ziel der Umschreibung werden gebraucht — "
                    "oder den Haken entfernen.", parent=self)
                return
            config["adguard"] = {**adguard, "verify_ssl": self.adg_verify.get()}
        config.update({k: v for k, v in self.extra.items() if k not in config})
        # the caller owns the file; it knows about the other profiles
        self.result = config
        self.destroy()


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


class App(tk.Tk):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.config_path = args.config
        self.settings = {}
        self.api = None
        self.profiles = []
        self.profile = {}
        self.adguard = None
        self.adguard_target = ""
        self.adguard_problem = ""
        self.services = []
        self.healthchecks = []
        self.domains = []
        self.busy = False
        self.results = queue.Queue()
        self.port_touched = False

        self.update_release = None
        self.update_checking = False

        self.prefs = load_prefs()
        self.theme_name = self.prefs.get("theme", "dark")
        self.colors = THEMES[self.theme_name]

        self.title(APP_TITLE)
        self.geometry(self.prefs.get("geometry", "1080x720"))
        self.minsize(880, 560)

        self._init_fonts()
        self._build()
        self._apply_theme()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(60, self._pump)
        self.after(100, self._connect)
        self.after(1500, self._update_on_start)

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
        style.configure("Hint.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small)
        style.configure("FieldLabel.TLabel", background=c["surface"],
                        foreground=c["muted"], font=self.font_small)
        style.configure("Host.TLabel", background=c["surface2"],
                        foreground=c["text"], font=self.font_mono_bold)
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

        style.configure("Card.TEntry", fieldbackground=c["surface2"],
                        foreground=c["text"], insertcolor=c["text"],
                        bordercolor=c["border"], lightcolor=c["border"],
                        darkcolor=c["border"], borderwidth=1, padding=7)
        style.map("Card.TEntry",
                  bordercolor=[("focus", c["accent"])],
                  lightcolor=[("focus", c["accent"])],
                  darkcolor=[("focus", c["accent"])])

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

        style.configure("Icon.TButton", background=c["bg"], foreground=c["muted"],
                        borderwidth=0, focuscolor=c["bg"], padding=(9, 6),
                        font=self.font_base)
        style.map("Icon.TButton", background=[("active", c["surface2"])],
                  foreground=[("active", c["text"])])

        # the same button, but noticeable once there is something to install
        style.configure("Update.TButton", background=c["accent_soft"],
                        foreground=c["accent"], borderwidth=0,
                        focuscolor=c["accent_soft"], padding=(9, 6),
                        font=self.font_small)
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

        style.configure("Bar.Horizontal.TProgressbar", background=c["accent"],
                        troughcolor=c["surface2"], bordercolor=c["surface2"],
                        lightcolor=c["accent"], darkcolor=c["accent"],
                        borderwidth=0, thickness=4)

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

        self.ssl_switch.apply_theme(c, c["surface2"])
        self.switch_box.configure(bg=c["surface2"],
                                  highlightbackground=c["border"])
        self.inventory.apply_theme(c)
        self.form_scroll.apply_theme(c)
        self.theme_button.configure(text="☀" if self.theme_name == "dark" else "🌙")
        self._paint_update_button()
        self._render_inventory()

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.colors = THEMES[self.theme_name]
        self._apply_theme()

    # -- layout ------------------------------------------------------------

    def _build(self):
        self.columnconfigure(0, weight=0, minsize=380)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_form()
        self._build_inventory()
        self._build_log()

    def _build_header(self):
        head = ttk.Frame(self, style="Head.TFrame", padding=(18, 14, 18, 10))
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.columnconfigure(1, weight=1)

        titles = ttk.Frame(head, style="Head.TFrame")
        titles.grid(row=0, column=0, sticky="w")
        ttk.Label(titles, text="HAProxy", style="H1.TLabel").grid(row=0, column=0,
                                                                 sticky="w")
        ttk.Label(titles, text="OPNsense Reverse Proxy",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w")

        actions = ttk.Frame(head, style="Head.TFrame")
        actions.grid(row=0, column=2, sticky="e")

        self.var_profile = tk.StringVar()
        self.profile_box = ttk.Combobox(actions, textvariable=self.var_profile,
                                        state="readonly", width=18,
                                        style="Card.TCombobox")
        self.profile_box.grid(row=0, column=0, padx=(0, 10))
        self.profile_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._switch_profile())

        self.status_pill = ttk.Label(actions, text="verbinde …",
                                     style="IdlePill.TLabel")
        self.status_pill.grid(row=0, column=1, padx=(0, 10))
        ttk.Button(actions, text="↻", style="Icon.TButton",
                   command=self.reload).grid(row=0, column=2)
        self.update_button = ttk.Button(actions, text="⇩", style="Icon.TButton",
                                        command=self._check_update)
        self.update_button.grid(row=0, column=3)
        self.theme_button = ttk.Button(actions, text="☀", style="Icon.TButton",
                                       command=self._toggle_theme)
        self.theme_button.grid(row=0, column=4)
        ttk.Button(actions, text="⚙", style="Icon.TButton",
                   command=self._open_settings).grid(row=0, column=5)

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

    def _build_form(self):
        # The form is taller than a small window, so it lives in its own
        # scroller -- otherwise the buttons at the bottom become unreachable.
        holder = ttk.Frame(self, style="Card.TFrame")
        holder.grid(row=1, column=0, sticky="nsew", padx=(18, 9), pady=(0, 9))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.form_scroll = ScrollFrame(holder, self.colors)
        self.form_scroll.grid(row=0, column=0, sticky="nsew")
        self.form_scroll.body.columnconfigure(0, weight=1)

        outer = ttk.Frame(self.form_scroll.body, style="Card.TFrame",
                          padding=(18, 16))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="Neuer Host", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
                  text="Legt Real Server, Backend Pool, Condition und Rule an "
                       "und hängt die Rule in den Public Service.").grid(
            row=1, column=0, sticky="w", pady=(3, 14))

        self.var_target = tk.StringVar()
        self.var_ip = tk.StringVar()
        self.var_port = tk.StringVar()
        self.var_base = tk.StringVar(value=NO_BASE)
        self.var_dns = tk.BooleanVar(value=True)
        self.var_frontend = tk.StringVar()
        self.var_healthcheck = tk.StringVar(value="— keiner —")
        self.var_backend_mode = tk.StringVar(value="automatisch")
        self.var_prefix = tk.StringVar()
        self.var_ssl_verify = tk.BooleanVar(value=False)
        self.var_forward_for = tk.BooleanVar(value=True)
        self.var_no_apply = tk.BooleanVar(value=False)

        # Hand out grid rows in order, so inserting a field can never make two
        # widgets share a row again.
        rows = itertools.count(2)

        ttk.Label(outer, text="Basis-Domain", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.base_box = ttk.Combobox(outer, textvariable=self.var_base,
                                     state="readonly", style="Card.TCombobox",
                                     values=[NO_BASE])
        self.base_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 12))
        self.base_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_fqdn())

        ttk.Label(outer, text="Hostname", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        entry = ttk.Entry(outer, textvariable=self.var_target, style="Card.TEntry",
                          font=self.font_mono)
        entry.grid(row=next(rows), column=0, sticky="ew", pady=(4, 2))
        entry.focus_set()
        self.fqdn_hint = ttk.Label(outer, style="Hint.TLabel",
                                   text="app.example.com oder https://example.com/api")
        self.fqdn_hint.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))
        self.var_target.trace_add("write", lambda *_: self._refresh_fqdn())

        pair = ttk.Frame(outer, style="Card.TFrame")
        pair.grid(row=next(rows), column=0, sticky="ew")
        pair.columnconfigure(0, weight=1)
        pair.columnconfigure(1, weight=0)

        ttk.Label(pair, text="Server-IP", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(pair, textvariable=self.var_ip, style="Card.TEntry",
                  font=self.font_mono).grid(row=1, column=0, sticky="ew",
                                            padx=(0, 10), pady=(4, 12))
        ttk.Label(pair, text="Port", style="FieldLabel.TLabel").grid(
            row=0, column=1, sticky="w")
        port_entry = ttk.Entry(pair, textvariable=self.var_port, width=8,
                               style="Card.TEntry", font=self.font_mono)
        port_entry.grid(row=1, column=1, sticky="w", pady=(4, 12))
        port_entry.bind("<KeyRelease>", self._port_typed)

        self.switch_box = tk.Frame(outer, bg=self.colors["surface2"],
                                   highlightthickness=1, bd=0)
        self.switch_box.grid(row=next(rows), column=0, sticky="ew", pady=(0, 12))
        self.switch_box.columnconfigure(1, weight=1)
        self.ssl_switch = Switch(self.switch_box, self.colors,
                                 command=self._ssl_changed)
        self.ssl_switch.grid(row=0, column=0, rowspan=2, padx=12, pady=10)
        ttk.Label(self.switch_box, text="SSL zum Backend",
                  style="Switch.TLabel").grid(row=0, column=1, sticky="w",
                                              pady=(10, 0))
        self.ssl_note = ttk.Label(self.switch_box, style="RowHint.TLabel",
                                  text="HAProxy spricht HTTP mit dem Server")
        self.ssl_note.grid(row=1, column=1, sticky="w", pady=(0, 10))

        self.dns_check = ttk.Checkbutton(
            outer, text="DNS-Eintrag in AdGuard anlegen", variable=self.var_dns,
            style="Card.TCheckbutton", command=self._refresh_fqdn)
        self.dns_check.grid(row=next(rows), column=0, sticky="w", pady=(0, 4))
        self.dns_hint = ttk.Label(outer, style="Hint.TLabel", text="")
        self.dns_hint.grid(row=next(rows), column=0, sticky="w", pady=(0, 12))

        ttk.Label(outer, text="Public Service", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.frontend_box = ttk.Combobox(outer, textvariable=self.var_frontend,
                                         state="readonly", style="Card.TCombobox")
        self.frontend_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 12))

        self.advanced_button = ttk.Button(outer, text="▸  Erweiterte Optionen",
                                          style="Ghost.TButton",
                                          command=self._toggle_advanced)
        self.advanced_button.grid(row=next(rows), column=0, sticky="ew")

        self.advanced = ttk.Frame(outer, style="Card.TFrame", padding=(0, 12, 0, 0))
        self.advanced.grid(row=next(rows), column=0, sticky="ew")
        self.advanced.grid_remove()
        self.advanced_open = False
        self._build_advanced(self.advanced)

        buttons = ttk.Frame(outer, style="Card.TFrame")
        buttons.grid(row=next(rows), column=0, sticky="ew", pady=(14, 0))
        buttons.columnconfigure(1, weight=1)
        self.preview_button = ttk.Button(buttons, text="Vorschau",
                                         style="Ghost.TButton",
                                         command=lambda: self._submit(True))
        self.preview_button.grid(row=0, column=0, padx=(0, 8))
        self.submit_button = ttk.Button(buttons, text="Anlegen",
                                        style="Accent.TButton",
                                        command=lambda: self._submit(False))
        self.submit_button.grid(row=0, column=1, sticky="ew")

        self.bind("<Return>", lambda _e: self._submit(False))

    def _build_advanced(self, parent):
        parent.columnconfigure(0, weight=1)
        ttk.Checkbutton(parent, text="Backend-Zertifikat prüfen",
                        variable=self.var_ssl_verify,
                        style="Card.TCheckbutton").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(parent, text="X-Forwarded-For setzen",
                        variable=self.var_forward_for,
                        style="Card.TCheckbutton").grid(row=1, column=0, sticky="w",
                                                        pady=(4, 0))
        ttk.Checkbutton(parent, text="Nur speichern, HAProxy nicht neu laden",
                        variable=self.var_no_apply,
                        style="Card.TCheckbutton").grid(row=2, column=0, sticky="w",
                                                        pady=(4, 10))

        ttk.Label(parent, text="Health Monitor", style="FieldLabel.TLabel").grid(
            row=3, column=0, sticky="w")
        self.healthcheck_box = ttk.Combobox(parent, textvariable=self.var_healthcheck,
                                            state="readonly", style="Card.TCombobox",
                                            values=["— keiner —"])
        self.healthcheck_box.grid(row=4, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(parent, text="Backend-Modus", style="FieldLabel.TLabel").grid(
            row=5, column=0, sticky="w")
        ttk.Combobox(parent, textvariable=self.var_backend_mode, state="readonly",
                     style="Card.TCombobox",
                     values=["automatisch", "http", "tcp"]).grid(
            row=6, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(parent, text="Namens-Präfix", style="FieldLabel.TLabel").grid(
            row=7, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.var_prefix, style="Card.TEntry").grid(
            row=8, column=0, sticky="ew", pady=(4, 0))

    def _build_inventory(self):
        outer = ttk.Frame(self, style="Card.TFrame", padding=(16, 16, 8, 12))
        outer.grid(row=1, column=1, sticky="nsew", padx=(9, 18), pady=(0, 9))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text="Bestehende Hosts", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel",
                  text="Was aktuell an welchem Public Service hängt.").grid(
            row=1, column=0, sticky="w", pady=(3, 12))

        self.inventory = ScrollFrame(outer, self.colors)
        self.inventory.grid(row=2, column=0, sticky="nsew")

    def _build_log(self):
        self.log_frame = tk.Frame(self, bg=self.colors["surface"])
        self.log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew",
                            padx=18, pady=(0, 18))
        self.log_frame.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=0, minsize=170)

        bar = ttk.Frame(self.log_frame, style="Card.TFrame", padding=(14, 8, 8, 4))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.log_title = ttk.Label(bar, text="Protokoll", style="H2.TLabel")
        self.log_title.grid(row=0, column=0, sticky="w")
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
            self._placeholder("Nicht verbunden",
                              "Über ⚙ die Zugangsdaten der OPNsense eintragen.")
            return
        if not self.services:
            self._placeholder("Kein Public Service",
                              "In OPNsense muss zuerst ein Public Service "
                              "angelegt werden.")
            return
        if not any(service["rules"] for service in self.services):
            self._placeholder("Noch nichts angelegt",
                              "Links eine URL eintragen, um den ersten Host "
                              "zu erstellen.")
            return

        row = 0
        for service in self.services:
            header = ttk.Frame(body, style="Card.TFrame")
            header.grid(row=row, column=0, sticky="ew", pady=(6 if row else 0, 6))
            ttk.Label(header, text=service["name"], style="Group.TLabel").grid(
                row=0, column=0, sticky="w")
            ttk.Label(header, text=service["mode"], style="Badge.TLabel").grid(
                row=0, column=1, padx=8)
            if service["bind"]:
                ttk.Label(header, text=service["bind"],
                          style="BadgeMuted.TLabel").grid(row=0, column=2)
            row += 1

            if not service["rules"]:
                ttk.Label(body, text="keine Rules", style="Hint.TLabel").grid(
                    row=row, column=0, sticky="w", padx=4, pady=(0, 8))
                row += 1
                continue

            for rule in service["rules"]:
                self._rule_row(body, rule).grid(row=row, column=0, sticky="ew",
                                                pady=(0, 6), padx=(0, 6))
                row += 1

    def _placeholder(self, title, text):
        holder = ttk.Frame(self.inventory.body, style="Card.TFrame", padding=30)
        holder.grid(row=0, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=title, style="H2.TLabel", anchor="center").grid(
            row=0, column=0)
        ttk.Label(holder, text=text, style="Hint.TLabel", anchor="center",
                  wraplength=380, justify="center").grid(row=1, column=0,
                                                         pady=(6, 0))

    def _rule_row(self, parent, rule):
        card = tk.Frame(parent, bg=self.colors["surface2"], padx=12, pady=9)
        card.columnconfigure(0, weight=1)

        host = rule["target"] or rule["name"] or "?"
        ttk.Label(card, text=host, style="Host.TLabel").grid(row=0, column=0,
                                                             sticky="w")

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

        if rule["target"]:
            ttk.Button(card, text="Entfernen", style="Del.TButton",
                       command=lambda r=rule: self._remove(r)).grid(
                row=0, column=2, rowspan=2)
        return card

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
        """Deliver finished background work back onto the UI thread."""
        try:
            while True:
                message = self.results.get_nowait()
                if message[0] == "progress":
                    self._set_activity(message[1])
                    continue
                _, callback, on_error, payload, error = message
                if error is None:
                    callback(payload)
                    continue
                self._set_busy(False)
                self._write_log("Fehler",
                                [{"text": str(error), "level": "error"}], False)
                if on_error:
                    on_error(error)
        except queue.Empty:
            pass
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
        for button in (self.submit_button, self.preview_button):
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

    # -- updates -----------------------------------------------------------

    def _paint_update_button(self):
        """The button carries the new version number once one is known."""
        if self.update_release:
            self.update_button.configure(
                text=f"⇩ {self.update_release['version']}", style="Update.TButton")
        else:
            self.update_button.configure(text="⇩", style="Icon.TButton")

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
        # the connection dialog is what fills it in.
        config = {}
        path = self.config_path or core.DEFAULT_CONFIG
        if os.path.exists(path):
            try:
                config = core.load_config(path)
            except core.UsageError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
        self.settings = config
        self.profiles = core.profiles_of(config)
        self._fill_profiles()
        self._use_profile(core.pick_profile(config, self.args.profile),
                          first_run=True)

    def _fill_profiles(self):
        """Always show the switcher -- it is the only way to add a connection."""
        names = [p.get("name", "?") for p in self.profiles]
        self.profile_box.configure(values=names + [NEW_PROFILE, EDIT_PROFILE],
                                   state="readonly")
        self.profile_box.grid()

    def _use_profile(self, profile, first_run=False):
        """Connect with the given profile, or ask for one when it is unusable."""
        self.profile = profile or {}
        self.var_profile.set(self.profile.get("name", ""))
        try:
            self.api = core.build_client(self.args, self.profile)
        except core.UsageError:
            self.api = None
            self.services, self.domains = [], []
            self._set_status(None, "keine Zugangsdaten")
            self._refresh_fqdn()
            self._render_inventory()
            if first_run:
                self._edit_profile(self.profile, is_new=not self.profiles)
            return
        self._build_adguard()
        self.reload()

    def _switch_profile(self):
        choice = self.var_profile.get()
        if choice == NEW_PROFILE:
            self._edit_profile({}, is_new=True)
            return
        if choice == EDIT_PROFILE:
            self._edit_profile(self.profile)
            return
        if choice == self.profile.get("name"):
            return
        match = next((p for p in self.profiles if p.get("name") == choice), None)
        if match:
            self._use_profile(match)

    def _build_adguard(self):
        self.adguard, settings = core.adguard_from_config(self.profile)
        self.adguard_target = settings.get("target", "")
        self.adguard_problem = settings.get("error", "")
        if self.adguard and not self.adguard_target:
            self.adguard = None  # without a target there is nothing to write
            self.adguard_problem = "AdGuard: kein Ziel eingetragen (⚙)"
        self._refresh_fqdn()

    def _open_settings(self):
        self._edit_profile(self.profile, is_new=not self.profile)

    def _edit_profile(self, profile, is_new=False):
        dialog = ProfileDialog(self, self.colors, profile, self.config_path,
                               taken_names=[p.get("name") for p in self.profiles],
                               can_delete=not is_new and len(self.profiles) > 1)
        self.wait_window(dialog)

        if dialog.delete_requested:
            gone = profile.get("name")
            self.profiles = [p for p in self.profiles if p.get("name") != gone]
            remaining = self.profiles[0] if self.profiles else {}
            if self._write_profiles(remaining.get("name", "")):
                self._fill_profiles()
                self._use_profile(remaining)
            return

        if dialog.result is None:
            self.var_profile.set(self.profile.get("name", ""))
            if is_new and not self.api:
                self._write_log("Nicht verbunden",
                                [{"text": "Ohne Zugangsdaten kann nichts "
                                          "geladen werden.", "level": "error"}],
                                False)
            return

        saved = dialog.result
        previous = "" if is_new else profile.get("name", "")
        keep = [p for p in self.profiles
                if p.get("name") not in (previous, saved["name"])]
        self.profiles = keep + [saved]
        self.config_path = dialog.config_path
        if not self._write_profiles(saved["name"]):
            return
        self._fill_profiles()
        self.args.insecure = False
        self._use_profile(saved)

    def _write_profiles(self, active):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.config_path)),
                        exist_ok=True)
            with open(self.config_path, "w") as handle:
                json.dump(core.as_profile_file(self.profiles, active), handle,
                          indent=2)
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
        client = self.api

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
            return {"status": status, "services": services,
                    "healthchecks": healthchecks, "domains": domains}

        self._run_async(work, self._state_loaded,
                        on_error=lambda exc: self._set_status(None),
                        activity="verbinde …")

    def _state_loaded(self, state):
        self._set_busy(False)
        self.services = state["services"]
        self.healthchecks = state["healthchecks"]
        self._set_status(state["status"])

        names = [service["name"] for service in self.services]
        self.frontend_box.configure(values=names,
                                    state="disabled" if len(names) <= 1
                                    else "readonly")
        preferred = self.profile.get("frontend", "")
        if self.var_frontend.get() not in names:
            self.var_frontend.set(preferred if preferred in names
                                  else (names[0] if names else ""))

        self.healthcheck_box.configure(values=["— keiner —"] + self.healthchecks)
        if self.var_healthcheck.get() not in ["— keiner —"] + self.healthchecks:
            self.var_healthcheck.set("— keiner —")

        self.domains = state["domains"]
        bases = [NO_BASE] + [entry["domain"] for entry in self.domains]
        self.base_box.configure(values=bases)
        preferred = self.profile.get("defaults", {}).get("base_domain", "")
        if self.var_base.get() not in bases:
            self.var_base.set(preferred if preferred in bases else NO_BASE)

        self._refresh_fqdn()
        self._render_inventory()

    def _set_status(self, status, error=None):
        if error or status is None:
            self.status_pill.configure(text=error or "nicht erreichbar",
                                       style="BadPill.TLabel")
            return
        running = "running" in str(status).lower()
        self.status_pill.configure(
            text="HAProxy läuft" if running else f"HAProxy: {status}",
            style="OkPill.TLabel" if running else "BadPill.TLabel")

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
            ssl=self.ssl_switch.get(),
            ssl_verify=self.var_ssl_verify.get(),
            frontend=self.var_frontend.get() or None,
            backend_mode=None if mode == "automatisch" else mode,
            healthcheck=None if healthcheck.startswith("—") else healthcheck,
            forward_for=self.var_forward_for.get(),
            prefix=self.var_prefix.get().strip(),
            dry_run=dry_run,
            no_apply=self.var_no_apply.get(),
            yes=True,
        )

    def _submit(self, dry_run):
        if self.busy or not self.api:
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
            activity="prüfe Vorhandenes …")

    def _active_adguard(self):
        """The AdGuard client, unless the checkbox says to leave DNS alone."""
        return self.adguard if self.var_dns.get() else None

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

    @staticmethod
    def _prefix_of(rule):
        """Rules created with a name prefix must be removed with the same one."""
        marker = rule["name"].find("rule_")
        return rule["name"][:marker] if marker > 0 else ""

    def _step_done(self, result, dry_run):
        self._set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
        if not lines:
            lines = [{"text": "keine Rückmeldung", "level": "error"}]
        title = ("Vorschau" if dry_run else "Fertig") if result["ok"] \
            else "Fehlgeschlagen"
        self._write_log(title, lines, result["ok"])
        if result["ok"] and not dry_run:
            self.var_target.set("")
            self.var_ip.set("")
            self.var_port.set("")
            self.port_touched = False
            self.reload()

    # -- small interactions ------------------------------------------------

    def _refresh_fqdn(self):
        """Show the name that will actually be created, and what DNS will do."""
        base = "" if self.var_base.get() == NO_BASE else self.var_base.get()
        raw = core.with_base(self.var_target.get(), base)
        host = raw.split("/", 1)[0].strip()
        full = core.build_fqdn(host, base) if host else ""
        if not full:
            self.fqdn_hint.configure(
                text="app.example.com oder https://example.com/api")
        else:
            entry = next((d for d in self.domains if d["domain"] == base), None)
            note = ""
            if entry and not core.covered_by(entry, full):
                note = "  ·  kein Zertifikat dafür"
            self.fqdn_hint.configure(text=f"→ {full}{note}")

        if not self.adguard:
            self.dns_check.configure(state="disabled")
            self.dns_hint.configure(
                text=self.adguard_problem or "AdGuard ist nicht eingerichtet (⚙)")
        else:
            self.dns_check.configure(state="normal")
            target = self.adguard_target or "?"
            self.dns_hint.configure(
                text=f"{full or 'name'} → {target}" if self.var_dns.get()
                else "AdGuard bleibt unverändert")

    def _ssl_changed(self):
        on = self.ssl_switch.get()
        self.ssl_note.configure(text="HAProxy spricht HTTPS mit dem Server" if on
                                else "HAProxy spricht HTTP mit dem Server")
        if not self.port_touched:
            self.var_port.set("")

    def _port_typed(self, _event):
        self.port_touched = bool(self.var_port.get().strip())

    def _toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced.grid()
            self.advanced_button.configure(text="▾  Erweiterte Optionen")
        else:
            self.advanced.grid_remove()
            self.advanced_button.configure(text="▸  Erweiterte Optionen")

    def _save_prefs(self):
        # keep everything else that is in there, e.g. the update bookkeeping
        self.prefs.update({"theme": self.theme_name, "geometry": self.geometry()})
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
