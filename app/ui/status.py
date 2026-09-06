"""The Status tab: the whole arrangement, and where it breaks.

A name that answers in a browser is the end of a chain, and every link of it
lives somewhere else -- a certificate on the firewall, a name in AdGuard, a
public service and a rule and a pool in HAProxy, a machine and a port behind
that, and something in Docker actually listening there. No single system can
say which link is missing; each one only knows its own part and reports that
everything is fine.

The map at the top says how the three sides are doing. Under it, one line per
reachable thing, and opening one shows its chain with the gap marked and a way
in at every station.

Nothing here asks a machine anything. What is drawn was read before and is
labelled with its age; refreshing is a button, on purpose.
"""

import tkinter as tk
from tkinter import ttk

import haproxy_gui as gui
from app import overview as ov
from app import sources as shelf_module
from app import wiring

# How a station is shown: a mark, a badge style, and what the mark means.
MARK = {
    ov.OK: ("✓", "BadgeOk.TLabel", "in Ordnung"),
    ov.WARN: ("⚠", "BadgeAmber.TLabel", "ansehen"),
    ov.MISSING: ("✗", "BadgeWarn.TLabel", "fehlt"),
    ov.UNKNOWN: ("?", "BadgeMuted.TLabel", "nicht bekannt"),
    ov.SKIPPED: ("–", "BadgeMuted.TLabel", "nicht nötig"),
}

CARD_TAB = {wiring.DNS: "adguard", wiring.OPNSENSE: "haproxy",
            wiring.DOCKER: "portainer"}
CARD_HINT = {
    wiring.DNS: "Welcher Name im Heimnetz wohin zeigt.",
    wiring.OPNSENSE: "Wo HAProxy zuhört und welche Regel greift.",
    wiring.DOCKER: "Was hinter den Adressen tatsächlich läuft.",
}


def count_text(summary):
    """"2 erreichbar · 1 ohne Antwort", or what is true instead."""
    if not summary["total"]:
        return "noch nichts eingerichtet"
    parts = []
    for key, word in (("loading", "wird gelesen"), ("ok", "erreichbar"),
                      ("failed", "ohne Antwort"),
                      ("idle", "noch nicht gelesen")):
        if summary[key]:
            parts.append(f"{summary[key]} {word}")
    return " · ".join(parts)


class StatusTab(ttk.Frame):
    """The map, the chains, and the way in at every station."""

    # what the window asks of every tab
    connected = False
    configured = True

    def __init__(self, parent, app):
        super().__init__(parent, style="TFrame")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        #: which chains the reader has opened
        self.open_chains = set()
        self._drawn = None
        #: a redraw waiting to happen, so a burst of answers costs one
        self._pending = None

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

        # No bar here. There is one in the program and it sits on the cover
        # that goes over the window; a second one in the corner of a tab said
        # the same thing twice and neither of them said the thing that
        # matters, which is that nothing can be used right now. What stays is
        # the line naming which systems are still out, for the reading that
        # happens by itself at the start and leaves the window usable.
        self.waiting = ttk.Label(head, text="", style="Muted.TLabel")
        self.waiting.grid(row=1, column=0, columnspan=3, sticky="w",
                          pady=(3, 0))
        self.waiting.grid_remove()

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

    def source_changed(self, _source=None):
        self.render()

    # -- when to redraw -----------------------------------------------------

    def _signature(self):
        """What the picture is made of, so it is redrawn only when that moves.

        Rebuilding on every notification would pull the page out from under
        whoever is reading it -- and a refresh of four systems sends eight.
        """
        return (tuple((s.kind, s.name, s.status, s.reads)
                      for s in self.app.shelf.all()),
                tuple(sorted(self.open_chains)))

    def render(self, force=False):
        """Redraw, but not once per answer.

        A refresh of five systems reports ten times -- once as each starts and
        once as it finishes. Rebuilding the page on every one of them pulls it
        out from under whoever is reading, and the reading is the point. So
        the head, which is cheap and is where the progress shows, follows
        every answer; the page itself waits until the answers stop coming.
        """
        self._paint_head()
        if force:
            self._redraw()
            return
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = self.after(250, self._redraw)

    def _redraw(self):
        self._pending = None
        if not self.winfo_exists():
            return
        signature = self._signature()
        if signature != self._drawn:
            self._drawn = signature
            self._build()

    def _paint_head(self):
        counted = self.app.shelf.summary()
        oldest = self.app.shelf.oldest()
        self.age.configure(
            text=count_text(counted) + (
                f"  ·  Stand {shelf_module.describe_age(oldest)}"
                if oldest is not None else ""))
        here = self.app.shelf.round
        busy = bool(here and here.active)
        self.refresh_button.configure(
            state="disabled" if busy else "normal",
            text=(f"↻ {here.done} von {here.total}" if busy
                  else "↻ Alles neu lesen"))
        if not busy:
            self.waiting.grid_remove()
            return
        outstanding = here.running
        self.waiting.configure(
            text="wird gelesen: " + ", ".join(outstanding[:3])
                 + (f" und {len(outstanding) - 3} weitere"
                    if len(outstanding) > 3 else ""))
        self.waiting.grid()

    # -- drawing ------------------------------------------------------------

    def _build(self):
        self.scroll.clear()
        body = self.scroll.body
        body.columnconfigure(0, weight=1)
        picture = ov.build(self.app.shelf)
        rows = 0
        self._map(body, picture).grid(row=rows, column=0, sticky="ew",
                                      padx=18, pady=(18, 0))
        rows += 1
        self._chains(body, picture).grid(row=rows, column=0, sticky="ew",
                                         padx=18, pady=(18, 0))
        rows += 1
        ttk.Frame(body, style="TFrame", height=18).grid(row=rows, column=0)

    # -- the map ------------------------------------------------------------

    def _map(self, parent, picture):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Die drei Seiten", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(card, style="Hint.TLabel", wraplength=640, justify="left",
                  text="Ein Name wird im DNS auf HAProxy gelenkt, HAProxy "
                       "reicht ihn an eine Adresse weiter, und dort läuft ein "
                       "Container. Fehlt eine der drei Seiten, kommt nichts "
                       "an — die Kette darunter sagt, welche.").grid(
            row=1, column=0, sticky="w", pady=(3, 12))

        strip = ttk.Frame(card, style="Card.TFrame")
        strip.grid(row=2, column=0, sticky="ew")
        for column in (0, 2, 4):
            strip.columnconfigure(column, weight=1, uniform="side")
        for index, box in enumerate(picture.cards):
            self._box(strip, box).grid(row=0, column=index * 2, sticky="nsew",
                                       padx=(0, 0))
            if index < len(picture.cards) - 1:
                ttk.Label(strip, text="→", style="Chain.TLabel").grid(
                    row=0, column=index * 2 + 1, padx=10)
        return card

    def _box(self, parent, box):
        frame = tk.Frame(parent, bg=self.app.colors["surface2"], padx=14,
                         pady=12)
        frame.columnconfigure(0, weight=1)
        head = ttk.Frame(frame, style="Sub.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text=box.title, style="Switch.TLabel").grid(
            row=0, column=0, sticky="w")
        mark, style, _word = MARK[box.state]
        ttk.Label(head, text=mark, style=style).grid(row=0, column=1, sticky="e")
        for number, line in enumerate(box.lines or ["—"], start=1):
            ttk.Label(frame, text=line, style="RowHint.TLabel", wraplength=200,
                      justify="left").grid(row=number, column=0, sticky="w",
                                           pady=(3, 0))
        ttk.Button(frame, text="öffnen", style="Del.TButton",
                   command=lambda k=box.kind: self.app.show_tab(CARD_TAB[k])).grid(
            row=len(box.lines or [1]) + 1, column=0, sticky="w", pady=(8, 0))
        gui.Tooltip(frame, CARD_HINT.get(box.kind, ""))
        return frame

    # -- the chains ---------------------------------------------------------

    def _chains(self, parent, picture):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.columnconfigure(0, weight=1)
        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Was erreichbar sein soll", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        trouble = len(picture.trouble)
        ttk.Label(head, style="Hint.TLabel",
                  text=(f"{trouble} von {len(picture.chains)} brauchen "
                        "Aufmerksamkeit" if trouble
                        else f"{len(picture.chains)} vollständig")).grid(
            row=0, column=1, sticky="w", padx=(10, 0))

        if not picture.chains:
            ttk.Label(card, style="RowHint.TLabel", wraplength=640,
                      justify="left",
                      text="Noch nichts zu zeigen. Sobald eine OPNsense "
                           "gelesen wurde, steht hier jeder Name, der über "
                           "HAProxy erreichbar sein soll — mit allem, woran "
                           "er hängt.").grid(row=1, column=0, sticky="w",
                                             pady=(8, 0))
            return card

        row = 1
        for chain in picture.chains:
            self._chain_row(card, chain).grid(row=row, column=0, sticky="ew",
                                              pady=(8, 0))
            row += 1
            if chain.name in self.open_chains:
                self._chain_body(card, chain).grid(row=row, column=0,
                                                   sticky="ew")
                row += 1
        return card

    def _chain_row(self, parent, chain):
        row = tk.Frame(parent, bg=self.app.colors["surface2"], padx=12, pady=9,
                       cursor="hand2")
        row.columnconfigure(1, weight=1)
        mark, style, _word = MARK[chain.state]
        ttk.Label(row, text=mark, style=style).grid(row=0, column=0,
                                                    rowspan=2, padx=(0, 10))
        ttk.Label(row, text=chain.name + chain.path, style="Host.TLabel").grid(
            row=0, column=1, sticky="w")
        # Everything that is not settled, gaps first. Saying "alles vorhanden"
        # beside a question mark was a line contradicting the mark next to it.
        loose = chain.gaps + chain.unclear
        summary = ("alles vorhanden" if not loose else
                   ", ".join(f"{s.title} {MARK[s.state][2]}" for s in loose))
        ttk.Label(row, text=summary, style="RowHint.TLabel", wraplength=560,
                  justify="left").grid(row=1, column=1, sticky="w", pady=(2, 0))
        open_now = chain.name in self.open_chains
        ttk.Button(row, text="▴" if open_now else "▾", style="Del.TButton",
                   width=3,
                   command=lambda n=chain.name: self._toggle(n)).grid(
            row=0, column=2, rowspan=2, padx=(10, 0))
        # the whole line answers to a click, not only the button at the end:
        # a row that visibly opens something is a row people click on
        self._clickable(row, chain.name)
        return row

    def _clickable(self, frame, name):
        """Let a click anywhere on the row open or close its chain."""
        def opened(_event):
            self._toggle(name)
            return "break"

        frame.bind("<Button-1>", opened)
        for child in frame.winfo_children():
            child.bind("<Button-1>", opened)
            try:
                child.configure(cursor="hand2")
            except tk.TclError:
                pass  # a ttk widget that will not take a cursor is no reason
                      # to leave the row unclickable

    def _toggle(self, name):
        self.open_chains.symmetric_difference_update({name})
        self.render()

    def _chain_body(self, parent, chain):
        holder = ttk.Frame(parent, style="Card.TFrame", padding=(30, 6, 0, 10))
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, style="Hint.TLabel", wraplength=600, justify="left",
                  text=f"Gelesen von {chain.where}. Von oben nach unten: jede "
                       "Station braucht die darüber.").grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        row = 1
        for number, station in enumerate(chain.stations):
            self._station(holder, station, chain).grid(row=row, column=0,
                                                        sticky="ew")
            row += 1
            if number < len(chain.stations) - 1:
                ttk.Label(holder, text="│", style="Chain.TLabel").grid(
                    row=row, column=0, sticky="w", padx=(18, 0))
                row += 1
        return holder

    def _station(self, parent, station, chain):
        frame = tk.Frame(parent, bg=self.app.colors["surface2"], padx=12,
                         pady=8)
        frame.columnconfigure(1, weight=1)
        mark, style, _word = MARK[station.state]
        ttk.Label(frame, text=mark, style=style).grid(row=0, column=0,
                                                      rowspan=3, padx=(0, 10))
        ttk.Label(frame, text=station.title, style="Switch.TLabel").grid(
            row=0, column=1, sticky="w")
        if station.detail:
            ttk.Label(frame, text=station.detail, style="Target.TLabel",
                      wraplength=520, justify="left").grid(
                row=1, column=1, sticky="w", pady=(2, 0))
        if station.hint:
            ttk.Label(frame, text=station.hint, style="RowHint.TLabel",
                      wraplength=520, justify="left").grid(
                row=2, column=1, sticky="w", pady=(2, 0))
        interesting = station.state in (ov.MISSING, ov.WARN, ov.UNKNOWN)
        if station.fix_label or (station.tab and interesting):
            ttk.Button(frame, text=station.fix_label or "im Tab öffnen",
                       style="Accent.TButton" if station.fix else "Del.TButton",
                       command=lambda c=chain, s=station: self._start(c, s)).grid(
                row=0, column=2, rowspan=3, padx=(10, 0))
        return frame

    def _start(self, chain, station):
        """Begin the repair right here, rather than pointing at a tab.

        The overview already worked out which name is missing and where it
        should point. Handing someone a tab and letting them find that out
        again would be the program forgetting what it just said.
        """
        if station.fix == "dns":
            tab = self.app.dns
            if not hasattr(tab, "add_named"):
                self.app.show_tab("adguard")
                return
            self.app.show_tab("adguard")
            tab.add_named(station.data.get("host", ""),
                          station.data.get("answer", ""))
            return
        if station.fix == "behind":
            from app.ui import behind
            behind.ask(self.app, chain, station)
            return
        if station.tab:
            self.app.show_tab(station.tab)
