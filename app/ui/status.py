"""The Status tab: what is set up, and whether it answered.

Everything shown here is read from the shelf, never from a machine. Pressing
refresh is the only thing in this tab that asks anybody anything -- which is
what showing cached data means once there are several systems and one of them
is a timeout waiting to happen.

This is the first stage. The flow diagram of a service and everything it
depends on grows in below; the list of systems is what it hangs on, and it
earns its place on its own until then: three DNS servers where one is
unreachable is worth seeing at a glance rather than finding out later.
"""

import tkinter as tk
from tkinter import ttk

import haproxy_gui as gui
from app import sources as shelf_module
from app import wiring

# The state of one system, as a badge and a word.
PILL = {
    shelf_module.IDLE: ("BadgeMuted.TLabel", "noch nicht gelesen"),
    shelf_module.LOADING: ("Badge.TLabel", "wird gelesen …"),
    shelf_module.OK: ("BadgeOk.TLabel", "erreichbar"),
    shelf_module.FAILED: ("BadgeWarn.TLabel", "keine Antwort"),
}

SECTIONS = (
    (wiring.OPNSENSE, "OPNsense", "Die Firewall mit HAProxy darauf."),
    (wiring.DNS, "DNS", "AdGuard Home, für die Namen im Heimnetz."),
    (wiring.DOCKER, "Docker", "Portainer oder Dockhand, je Eintrag."),
)


def count_text(summary):
    """"3 von 4 erreichbar", or what is true instead."""
    if not summary["total"]:
        return "noch nichts eingerichtet"
    parts = []
    if summary["loading"]:
        parts.append(f"{summary['loading']} wird gelesen")
    if summary["ok"]:
        parts.append(f"{summary['ok']} erreichbar")
    if summary["failed"]:
        parts.append(f"{summary['failed']} ohne Antwort")
    if summary["idle"]:
        parts.append(f"{summary['idle']} noch nicht gelesen")
    return " · ".join(parts)


class StatusTab(ttk.Frame):
    """What is configured, how it is doing, and how old that answer is."""

    # what the window asks of every tab
    connected = False
    configured = True

    def __init__(self, parent, app):
        super().__init__(parent, style="TFrame")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        # one row of widgets per source, kept so an answer coming in changes a
        # line rather than rebuilding the page under the reader's hands
        self.rows = {}
        self.shown = ()

        head = ttk.Frame(self, style="TFrame")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Überblick", style="H2Page.TLabel").grid(
            row=0, column=0, sticky="w")
        self.age = ttk.Label(head, text="", style="Muted.TLabel")
        self.age.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.refresh_button = ttk.Button(head, text="↻ Alles neu lesen",
                                         style="Tool.TButton",
                                         command=self.reload)
        self.refresh_button.grid(row=0, column=2, sticky="e")

        self.scroll = gui.ScrollFrame(self, app.colors)
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)
        app.source_listeners.append(self.source_changed)
        self.render()

    # -- the window's protocol ---------------------------------------------

    def apply_theme(self):
        self.scroll.apply_theme(self.app.colors)
        self.render(force=True)

    def reload(self):
        self.app.refresh_sources()

    def source_changed(self, source):
        """One system answered, or started being asked."""
        self.render()

    # -- drawing ------------------------------------------------------------

    def _fingerprint(self):
        """What the page is made of, so it is rebuilt only when that changes."""
        return tuple((s.kind, s.name) for s in self.app.shelf.all())

    def render(self, force=False):
        if force or self._fingerprint() != self.shown:
            self._build()
        self._paint()

    def _build(self):
        self.scroll.clear()
        self.rows = {}
        self.shown = self._fingerprint()
        body = self.scroll.body
        body.columnconfigure(0, weight=1)
        row = 0
        for kind, title, hint in SECTIONS:
            card = self._section(body, kind, title, hint)
            card.grid(row=row, column=0, sticky="ew", padx=18, pady=(18, 0))
            row += 1
        ttk.Frame(body, style="TFrame", height=18).grid(row=row, column=0)

    def _section(self, parent, kind, title, hint):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.columnconfigure(0, weight=1)
        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text=title, style="H2.TLabel").grid(row=0, column=0,
                                                            sticky="w")
        summary = ttk.Label(head, text="", style="Hint.TLabel")
        summary.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Button(head, text="↻", style="Del.TButton", width=3,
                   command=lambda k=kind: self.app.refresh_sources([k])).grid(
            row=0, column=2, sticky="e")
        ttk.Label(card, text=hint, style="Hint.TLabel", wraplength=520,
                  justify="left").grid(row=1, column=0, sticky="w", pady=(3, 10))
        self.rows[kind] = {"summary": summary, "entries": {}}

        entries = self.app.shelf.of_kind(kind)
        if not entries:
            ttk.Label(card, style="RowHint.TLabel",
                      text="Nichts eingerichtet.").grid(row=2, column=0,
                                                        sticky="w")
            ttk.Button(card, text="+ Einrichten", style="Del.TButton",
                       command=self.app.open_settings).grid(row=3, column=0,
                                                            sticky="w",
                                                            pady=(8, 0))
            return card
        for number, source in enumerate(entries, start=2):
            self._row(card, source).grid(row=number, column=0, sticky="ew",
                                         pady=(0, 6))
        return card

    def _row(self, parent, source):
        row = tk.Frame(parent, bg=self.app.colors["surface2"], padx=12, pady=9)
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text=source.name, style="Host.TLabel").grid(
            row=0, column=0, sticky="w")
        pill = ttk.Label(row, text="", style="BadgeMuted.TLabel")
        pill.grid(row=0, column=1, padx=(8, 0))
        detail = ttk.Label(row, text=source.label, style="Target.TLabel",
                           wraplength=520, justify="left")
        detail.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        note = ttk.Label(row, text="", style="RowHint.TLabel", wraplength=520,
                         justify="left")
        note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.rows[source.kind]["entries"][source.name] = {
            "pill": pill, "detail": detail, "note": note}
        return row

    def _paint(self):
        total = self.app.shelf.summary()
        oldest = self.app.shelf.oldest()
        self.age.configure(
            text=count_text(total) + (
                f"  ·  Stand {shelf_module.describe_age(oldest)}"
                if oldest is not None else ""))
        busy = bool(total["loading"])
        self.refresh_button.configure(
            state="disabled" if busy else "normal",
            text="↻ wird gelesen …" if busy else "↻ Alles neu lesen")
        for kind, widgets in self.rows.items():
            widgets["summary"].configure(
                text=count_text(self.app.shelf.summary([kind])))
            for name, parts in widgets["entries"].items():
                source = self.app.shelf.get(kind, name)
                if source is None:
                    continue
                style, word = PILL[source.status]
                parts["pill"].configure(text=word, style=style)
                parts["detail"].configure(text=source.label)
                parts["note"].configure(text=self._note(source))

    @staticmethod
    def _note(source):
        """The line under a system: what it said, or how old what it said is."""
        if source.status == shelf_module.FAILED:
            was = shelf_module.describe_age(source.age())
            older = ("" if not source.ready
                     else f"  ·  gezeigt wird der Stand von {was}")
            return f"{source.error}{older}"
        if source.status == shelf_module.LOADING and not source.ready:
            return ""
        if not source.ready:
            return ""
        return f"gelesen {shelf_module.describe_age(source.age())}"
