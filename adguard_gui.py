#!/usr/bin/env python3
"""The AdGuard tab of the window.

Like the Portainer tab, everything here hangs off the main window: the
colours, the background thread and the log at the bottom belong to it, so this
file only describes what this tab shows and what its buttons set off.

Why a tab of its own. The host list on the first tab says what AdGuard knows
about a name that HAProxy already serves -- and nothing at all about the rest.
A DNS server holds more than that: the NAS, the printer, the machine that
answers on a port of its own, names that never went past a reverse proxy. Up
to now none of them was visible here, and writing one meant opening AdGuard's
own interface. This tab shows the whole list and writes into it directly.

The widgets it borrows (the scroller, the tooltip, the link) live in
haproxy_gui, which imports this module only when it builds the tab -- long
after it has finished loading itself, so the two can point at each other
without an import running in circles.
"""

import itertools
import re

import tkinter as tk
from tkinter import messagebox, ttk

import haproxy_gui as ui
import opnsense_haproxy as core

# What AdGuard accepts as the left hand side of a rewrite: a host name, with
# an optional ``*.`` in front for everything below it. Checked here rather
# than left to the server, whose answer to a typo is a 400 with no detail.
NAME_OK = re.compile(r"^(\*\.)?[a-z0-9_-]+(\.[a-z0-9_-]+)*$")


def sort_key(domain):
    """Sort by name from the back: relatives end up next to each other.

    ``example.de`` and ``app.example.de`` belong together in a list one reads
    with the eye, and by their first letter they would not be. The wildcard
    stands with the domain it covers, which is where one looks for it.
    """
    name = str(domain).lower()
    return list(reversed(name.lstrip("*.").split("."))), name


class AdGuardTab(ttk.Frame):
    """Every DNS rewrite AdGuard holds -- and the way to write another one."""

    def __init__(self, parent, app):
        super().__init__(parent, style="TFrame")
        self.app = app
        self.client = None
        self.settings = {}
        self.problem = ""
        # what the rewrites of this place are supposed to answer, i.e. the
        # HAProxy address: an entry pointing there is marked as such, and a
        # new one is offered it
        self.target = ""
        self.name = ""
        self.connected = False
        self.entries = []
        self.error = ""
        # a new rewrite that is waiting for the list to be read first
        self.pending_new = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_list()

    # -- layout ------------------------------------------------------------

    def _build_list(self):
        outer = ttk.Frame(self, style="Card.TFrame", padding=(16, 16, 8, 12))
        outer.grid(row=0, column=0, sticky="nsew", padx=18, pady=(0, 9))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        head = ttk.Frame(outer, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="DNS-Umschreibungen", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")

        picks = ttk.Frame(head, style="Card.TFrame")
        picks.grid(row=0, column=2, sticky="e")
        self.var_filter = tk.StringVar()
        self.filter_box = ttk.Entry(picks, textvariable=self.var_filter,
                                    style="Card.TEntry", width=18)
        self.filter_box.grid(row=0, column=0, sticky="e", padx=(0, 6))
        ui.Tooltip(self.filter_box, "Nach Name oder Ziel suchen")
        self.new_button = ttk.Button(picks, text="＋ Neue Umschreibung",
                                     style="Accent.TButton", command=self.new)
        self.new_button.grid(row=0, column=1, sticky="e")

        self.hint = ttk.Label(outer, style="Hint.TLabel", text="")
        self.hint.grid(row=1, column=0, sticky="w", pady=(3, 12))

        self.listing = ui.ScrollFrame(outer, self.app.colors)
        self.listing.grid(row=2, column=0, sticky="nsew")
        # not before the listing exists -- the search redraws it on every key
        self.var_filter.trace_add("write", lambda *_a: self.render())

    def apply_theme(self):
        self.listing.apply_theme(self.app.colors)
        self.render()

    # -- connection --------------------------------------------------------

    def use_profile(self, profile):
        """Take up the AdGuard of the connection that was just chosen.

        The client is built here rather than borrowed from the window: over
        there it is dropped when no HAProxy address is known, because without
        one there is nothing to write into a host's rewrite. Reading and
        editing the list needs no such address.
        """
        self.client, self.settings = core.adguard_from_config(profile)
        self.problem = self.settings.get("error", "")
        self.target = self.settings.get("target", "")
        self.name = (profile.get("adguard") or {}).get("name", "")
        self.connected = False
        self.entries = []
        self.error = ""
        self.render()

    @property
    def configured(self):
        return self.client is not None

    def status_text(self):
        """What the pill in the header says while this tab is in front."""
        if not self.configured:
            return self.problem or "kein AdGuard eingerichtet", False
        if self.error:
            return "AdGuard antwortet nicht", False
        if not self.connected:
            return "nicht verbunden", False
        count = len(self.entries)
        return f"{count} Umschreibung{'' if count == 1 else 'en'}", True

    def reload(self):
        """Read AdGuard's rewrite list, whole."""
        if not self.client:
            self.app.open_settings()
            return
        client = self.client

        def work(report):
            report("lese die DNS-Umschreibungen aus AdGuard …")
            return client.rewrites()

        self.app.run_async(work, self._loaded, on_error=self._failed,
                           activity="verbinde mit AdGuard …")

    def _failed(self, error):
        self.connected = False
        self.error = str(error)
        self.pending_new = False  # whatever it was waiting for cannot happen
        self.app.paint_connection()
        self.render()

    def _loaded(self, entries):
        self.app.set_busy(False)
        self.take(entries)
        # the host list on the first tab reads the same rewrites; it may as
        # well have this one instead of asking again
        self.app.dns_reloaded(entries)
        if self.pending_new:
            self.pending_new = False
            self.new()

    def take(self, entries, error=""):
        """Take up a listing that was just read, wherever it came from."""
        self.connected = not error
        self.error = error
        self.entries = [{"domain": str(entry.get("domain", "")),
                         "answer": str(entry.get("answer", ""))}
                        for entry in entries]
        self.entries.sort(key=lambda entry: sort_key(entry["domain"]))
        self.app.paint_connection()
        self.render()

    def busy_buttons(self):
        return (self.new_button,)

    # -- the listing -------------------------------------------------------

    def render(self):
        self.listing.clear()
        body = self.listing.body
        body.columnconfigure(0, weight=1)
        self._paint_hint()

        if not self.configured:
            self._placeholder(
                "Kein AdGuard eingerichtet",
                self.problem or "Lege unter ⚙ ein AdGuard Home an — dann "
                                "stehen hier alle DNS-Umschreibungen, und neue "
                                "entstehen von hier aus.",
                "Einstellungen öffnen", self.app.open_settings)
            return
        if not self.connected:
            self._placeholder(
                "AdGuard antwortet nicht" if self.error else "Nicht verbunden",
                self.error or "„Verbinden“ oben rechts liest die "
                              "DNS-Umschreibungen aus AdGuard.",
                "Nochmal versuchen" if self.error else "Verbinden", self.reload)
            return
        if not self.entries:
            self._placeholder("Keine Umschreibung",
                              f"{self.name or 'AdGuard'} schreibt zurzeit "
                              "keinen Namen um.",
                              "Neue Umschreibung", self.new)
            return

        shown = self._shown()
        if not shown:
            self._placeholder("Nichts gefunden",
                              f"Keine Umschreibung enthält "
                              f"„{self.var_filter.get().strip()}“.")
            return

        row = itertools.count()
        for entry in shown:
            card = self._row(body, entry)
            card.grid(row=next(row), column=0, sticky="ew", pady=(0, 6),
                      padx=(0, 6))

    def _shown(self):
        """The entries the search field lets through -- name or target."""
        wanted = self.var_filter.get().strip().lower()
        if not wanted:
            return self.entries
        return [entry for entry in self.entries
                if wanted in entry["domain"].lower()
                or wanted in entry["answer"].lower()]

    def _paint_hint(self):
        """The line under the heading: whose list this is, and how it reads."""
        if not self.configured or not self.connected:
            self.hint.configure(
                text="Was AdGuard auf einen Namen antwortet, statt ihn nach "
                     "draußen weiterzureichen.")
            return
        parts = [f"{len(self.entries)} Einträge in "
                 f"{self.name or 'AdGuard'}"]
        if self.target:
            here = sum(1 for entry in self.entries
                       if entry["answer"] == self.target)
            parts.append(f"{here} davon auf HAProxy ({self.target})")
        shown = len(self._shown())
        if shown != len(self.entries):
            parts.append(f"{shown} passen zur Suche")
        self.hint.configure(text="  ·  ".join(parts))

    def _placeholder(self, title, text, button="", command=None):
        holder = ttk.Frame(self.listing.body, style="Card.TFrame", padding=30)
        holder.grid(row=0, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=title, style="H2.TLabel", anchor="center").grid(
            row=0, column=0)
        ttk.Label(holder, text=text, style="Hint.TLabel", anchor="center",
                  wraplength=420, justify="center").grid(row=1, column=0,
                                                         pady=(6, 0))
        if button:
            ttk.Button(holder, text=button, style="Accent.TButton",
                       command=command).grid(row=2, column=0, pady=(16, 0))

    def _row(self, parent, entry):
        colors = self.app.colors
        card = tk.Frame(parent, bg=colors["surface2"], padx=12, pady=9)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text=entry["domain"], style="Host.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(card, text=f"→  {entry['answer']}", style="Target.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 0))

        marks = ttk.Frame(card, style="Sub.TFrame")
        marks.grid(row=0, column=1, rowspan=2, padx=(10, 8))
        column = 0
        if entry["domain"].startswith("*."):
            badge = ttk.Label(marks, text="alle darunter",
                              style="BadgeMuted.TLabel")
            badge.grid(row=0, column=column, padx=2)
            ui.Tooltip(badge, "Gilt für jeden Namen unter dieser Domain, "
                              "sofern kein eigener Eintrag ihn übergeht")
            column += 1
        if self.target and entry["answer"] == self.target:
            badge = ttk.Label(marks, text="HAProxy", style="BadgeOk.TLabel")
            badge.grid(row=0, column=column, padx=2)
            ui.Tooltip(badge, f"Zeigt auf {self.target} — den Weg über HAProxy")

        buttons = ttk.Frame(card, style="Sub.TFrame")
        buttons.grid(row=0, column=2, rowspan=2)
        ttk.Button(buttons, text="Ändern", style="Del.TButton",
                   command=lambda e=entry: self.edit(e)).grid(row=0, column=0,
                                                              padx=(0, 6))
        ttk.Button(buttons, text="Löschen", style="Del.TButton",
                   command=lambda e=entry: self.delete(e)).grid(row=0, column=1)
        return card

    # -- writing -----------------------------------------------------------

    def new(self):
        """Write a name AdGuard should answer itself."""
        if not self.client:
            self.app.open_settings()
            return
        if self.app.busy:
            return
        if not self.connected:
            # Without the list there is no way to tell whether the name is
            # already taken, and a second, unnoticed answer is exactly the
            # kind of DNS entry nobody finds again. So it is read first and
            # the form opens on top of it.
            self.pending_new = True
            self.reload()
            return
        dialog = RewriteDialog(self.app, self.app.colors, target=self.target)
        self.app.wait_window(dialog)
        if dialog.result:
            self._write(dialog.result)

    def edit(self, entry):
        if self.app.busy or not self.client:
            return
        dialog = RewriteDialog(self.app, self.app.colors, target=self.target,
                               entry=entry)
        self.app.wait_window(dialog)
        if dialog.result:
            self._write(dialog.result, previous=entry)

    def delete(self, entry):
        if self.app.busy or not self.client:
            return
        if not messagebox.askyesno(
                ui.APP_TITLE,
                f"Die Umschreibung {entry['domain']} → {entry['answer']} in "
                f"{self.name or 'AdGuard'} löschen?\n\nDer Name wird danach "
                "wieder ganz normal aufgelöst.", icon="warning",
                parent=self.app):
            return
        self._run([entry], None,
                  [f"- {entry['domain']} → {entry['answer']}"])

    def _write(self, values, previous=None):
        """Put one rewrite in place, and say what that costs the old ones.

        AdGuard has no update call and no unique name: the same domain may
        stand there twice, with an IPv4 and an IPv6 answer. So an old entry is
        deleted by both its halves, and a second answer for a name is only
        removed after it has been asked about -- keeping both is a legitimate
        thing to want.
        """
        domain, answer = values["domain"], values["answer"]
        doomed = [previous] if previous else []
        clashes = [entry for entry in self.entries
                   if entry["domain"].lower() == domain.lower()
                   and entry is not previous]
        if any(entry["answer"] == answer for entry in clashes):
            messagebox.showinfo(ui.APP_TITLE,
                                f"{domain} → {answer} steht schon in "
                                f"{self.name or 'AdGuard'}.",
                                parent=self.app)
            return
        if clashes:
            answers = ", ".join(entry["answer"] for entry in clashes)
            replace = messagebox.askyesno(
                ui.APP_TITLE,
                f"{domain} zeigt schon auf {answers}.\n\n"
                f"Soll {answer} das ersetzen?\n"
                "Nein: beide bleiben stehen — AdGuard antwortet dann mit "
                "beiden Adressen.", icon="warning",
                default=messagebox.NO, parent=self.app)
            if replace:
                doomed += clashes

        lines = [f"- {entry['domain']} → {entry['answer']}" for entry in doomed]
        lines.append(f"+ {domain} → {answer}")
        self._run(doomed, {"domain": domain, "answer": answer}, lines)

    def _run(self, doomed, added, lines):
        """Delete what has to go, write what is new, then read the list again."""
        client = self.client

        def work(report):
            for entry in doomed:
                report(f"lösche {entry['domain']} → {entry['answer']} …")
                client.delete_rewrite(entry["domain"], entry["answer"])
            if added:
                report(f"trage {added['domain']} → {added['answer']} ein …")
                client.add_rewrite(added["domain"], added["answer"])
            report("lese die Liste neu …")
            return client.rewrites()

        self.app.run_async(work, lambda entries: self._written(entries, lines),
                           activity="AdGuard …")

    def _written(self, entries, lines):
        self.app.set_busy(False)
        self.take(entries)
        self.app.dns_reloaded(entries)
        self.app.write_log("AdGuard", [{"text": line, "level": "info"}
                                       for line in lines], True)


class RewriteDialog(tk.Toplevel):
    """One rewrite: the name, and what AdGuard answers when it is asked."""

    def __init__(self, parent, colors, target="", entry=None):
        super().__init__(parent)
        self.title("Umschreibung ändern" if entry else "Neue Umschreibung")
        self.result = None
        self.target = target
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text="DNS-Umschreibung", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="AdGuard antwortet auf diesen Namen selbst, statt ihn "
                       "nach draußen weiterzureichen. Alles, was diesen DNS "
                       "benutzt, landet damit bei der Adresse unten.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 14))

        self.var_domain = tk.StringVar(value=(entry or {}).get("domain", ""))
        self.var_answer = tk.StringVar(value=(entry or {}).get("answer", "")
                                       or target)

        ttk.Label(body, text="Name", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.domain_box = ttk.Entry(body, textvariable=self.var_domain,
                                    style="Card.TEntry", font=parent.font_mono)
        self.domain_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 3))
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="z.B. nas.example.de  ·  *.example.de gilt für alles "
                       "darunter, ein eigener Eintrag geht immer vor").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 12))

        ttk.Label(body, text="Ziel", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        self.answer_box = ttk.Entry(body, textvariable=self.var_answer,
                                    style="Card.TEntry", font=parent.font_mono)
        self.answer_box.grid(row=next(rows), column=0, sticky="ew", pady=(4, 3))
        note = "IP-Adresse oder ein anderer Name."
        if target:
            note += f"  ·  {target} ist HAProxy — dorthin zeigen die Hosts " \
                    "aus dem ersten Tab."
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text=note).grid(row=next(rows), column=0, sticky="w")

        self.note = ttk.Label(body, style="Hint.TLabel", wraplength=420,
                              justify="left", text="")
        self.note.grid(row=next(rows), column=0, sticky="w", pady=(12, 0))
        self.note.grid_remove()

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=0, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Speichern" if entry else "Anlegen",
                   style="Accent.TButton", command=self._go).grid(row=0,
                                                                  column=1)

        self.bind("<Return>", lambda _e: self._go())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self.geometry(f"{max(self.winfo_reqwidth(), 480)}x{self.winfo_reqheight()}")
        self.resizable(False, False)
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.domain_box.focus_set()
        self.grab_set()

    def _say(self, text):
        self.note.configure(text=text)
        self.note.grid()

    def _go(self):
        # a name is a name whatever it was typed as; DNS does not care about
        # case, and two entries that differ only in it are a trap
        domain = self.var_domain.get().strip().lower().rstrip(".")
        answer = self.var_answer.get().strip()
        if not domain:
            self._say("Bitte einen Namen angeben.")
            return
        if not NAME_OK.match(domain):
            self._say(f"„{domain}“ ist kein Name, den AdGuard umschreiben "
                      "kann. Erlaubt sind Buchstaben, Ziffern, Punkt und "
                      "Bindestrich — und ein *. am Anfang.")
            return
        if not answer or any(char.isspace() for char in answer):
            self._say("Bitte ein Ziel angeben: eine IP-Adresse oder einen "
                      "Namen, ohne Leerzeichen.")
            return
        if answer.rstrip(".").lower() == domain:
            self._say("Der Name kann nicht auf sich selbst zeigen.")
            return
        self.result = {"domain": domain, "answer": answer}
        self.destroy()
