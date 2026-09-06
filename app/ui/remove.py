"""Removing one entry from every system it stands in, from the status page.

Two steps, and the first one is the point: the firewall is asked what it
would delete before anything is deleted. That list is what somebody confirms
-- not a sentence this program made up about what it thinks is there. A pool
that another rule still uses stays, and the list says so, because the answer
comes from the firewall rather than from a guess here.

DNS is taken from every AdGuard that answers for the name. The removal built
into the command line knows one AdGuard, which is right for a command line
with one connection; the status page reads all of them, and a name that is
gone on one server and standing on another is worse than one that is simply
still there -- nobody can see which server they got.
"""

import threading
import tkinter as tk
from tkinter import ttk

import haproxy_gui as gui
import opnsense_haproxy as core
from app import removal, wiring


class RemoveDialog(tk.Toplevel):
    """Shows what would go, then takes it away when told to."""

    def __init__(self, app, chain, firewall):
        super().__init__(app)
        self.app = app
        self.chain = chain
        self.firewall = firewall
        self.removed = False
        self.title("Eintrag entfernen")
        self.transient(app)
        self.configure(bg=app.colors["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        row = 0

        ttk.Label(body, text=f"{chain.name}{chain.path}",
                  style="H2.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Label(body, style="Hint.TLabel", wraplength=520, justify="left",
                  text=f"Gelesen von {chain.where}. Was dazugehört, wird "
                       "zuerst bei der OPNsense erfragt — gelöscht wird erst "
                       "danach und erst auf Knopfdruck.").grid(
            row=row, column=0, sticky="w", pady=(3, 12))
        row += 1

        self.list = tk.Text(body, height=9, width=62, wrap="word",
                            relief="flat", bg=app.colors["surface2"],
                            fg=app.colors["text"], padx=10, pady=8,
                            font=app.font_base)
        self.list.grid(row=row, column=0, sticky="ew")
        self.list.configure(state="disabled")
        row += 1

        self.bar = ttk.Progressbar(body, mode="indeterminate",
                                   style="Bar.Horizontal.TProgressbar")
        self.bar.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        row += 1

        for title, why in removal.KEPT:
            ttk.Label(body, text=f"{title} — {why}", style="Hint.TLabel",
                      wraplength=520, justify="left").grid(
                row=row, column=0, sticky="w", pady=(8, 0))
            row += 1

        self.note = ttk.Label(body, style="Hint.TLabel", wraplength=520,
                              justify="left", text="")
        self.note.grid(row=row, column=0, sticky="w", pady=(10, 0))
        self.note.grid_remove()

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.cancel = ttk.Button(buttons, text="Abbrechen",
                                 style="Ghost.TButton", command=self.destroy)
        self.cancel.grid(row=0, column=0, padx=(0, 8))
        self.action = ttk.Button(buttons, text="Endgültig entfernen",
                                 style="Danger.TButton", command=self._remove,
                                 state="disabled")
        self.action.grid(row=0, column=1)

        self.bind("<Escape>", lambda _e: self.destroy())
        gui.fit_window(self, floor=560)
        self.resizable(False, False)
        gui.place_over(self, app)
        self.grab_set()
        self._ask_what_would_go()

    # -- the list -----------------------------------------------------------

    def _show(self, lines):
        self.list.configure(state="normal")
        self.list.delete("1.0", "end")
        self.list.insert("1.0", "\n".join(lines))
        self.list.configure(state="disabled")

    def _say(self, text):
        self.note.configure(text=text)
        self.note.grid()
        gui.fit_window(self, floor=560, shrink=False)

    def _working(self, on, text=""):
        if on:
            self.bar.grid()
            self.bar.start(12)
            self.action.configure(state="disabled")
        else:
            self.bar.stop()
            self.bar.grid_remove()
        self.cancel.configure(state="disabled" if on else "normal")
        if text:
            self._say(text)

    # -- step one: what would go -------------------------------------------

    def _ask_what_would_go(self):
        self._show(["wird geprüft …"])
        self._working(True, "Die OPNsense wird gefragt, was dazugehört …")
        chain = self.chain
        settings = dict(self.firewall.settings)
        dns_sources = list(self.app.shelf.of_kind(wiring.DNS))

        def task():
            try:
                client = wiring.opnsense_client(settings)
                result = core.run_step(
                    removal.operation_for(chain), client,
                    removal.options_for(chain, dry_run=True))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                self._later(lambda _p, error=exc: self._failed(error))
                return
            plan = removal.plan_lines(result["log"])
            plan += removal.dns_plan(dns_sources, chain.data.get("host", ""))
            unread = removal.unread_dns(dns_sources)
            self._later(lambda _p, p=plan, u=unread, r=result:
                        self._planned(p, u, r))

        threading.Thread(target=task, daemon=True).start()

    def _planned(self, plan, unread, result):
        self._working(False)
        if not result["ok"]:
            self._show(plan or ["—"])
            self._say(f"Nicht zu ermitteln: {result.get('error') or 'unklar'}")
            return
        self._show(plan or ["Es ist nichts (mehr) da, was entfernt werden "
                            "könnte."])
        self.action.configure(state="normal" if plan else "disabled")
        if unread:
            self._say("Nicht gelesen und daher nicht zu prüfen: "
                      + ", ".join(unread)
                      + ". Steht der Name dort auch, bleibt er dort stehen.")
        else:
            self.note.grid_remove()

    # -- step two: take it away --------------------------------------------

    def _remove(self):
        self._working(True, "wird entfernt …")
        chain = self.chain
        settings = dict(self.firewall.settings)
        dns_sources = list(self.app.shelf.of_kind(wiring.DNS))

        def task():
            try:
                client = wiring.opnsense_client(settings)
                result = core.run_step(
                    removal.operation_for(chain), client,
                    removal.options_for(chain, dry_run=False))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                self._later(lambda _p, error=exc: self._failed(error))
                return
            lines = [removal.german(entry.get("text", ""))
                     for entry in result["log"]]
            if not result["ok"]:
                # DNS is left alone on purpose: with the rule still standing,
                # taking the name away would break what is currently working
                self._later(lambda _p, l=lines, r=result: self._stopped(l, r))
                return
            done, failed = removal.remove_dns(
                dns_sources, chain.data.get("host", ""), report=lines.append)
            self._later(lambda _p, l=lines, d=done, f=failed:
                        self._finished(l, d, f))

        threading.Thread(target=task, daemon=True).start()

    def _stopped(self, lines, result):
        self._working(False)
        self._show(lines or ["—"])
        self.cancel.configure(text="Schließen")
        self.action.configure(state="normal")
        self._say("Auf der OPNsense hat es nicht geklappt — der DNS-Eintrag "
                  "wurde deshalb nicht angefasst: "
                  + (result.get("error") or "unklar"))

    def _finished(self, lines, done, failed):
        self.removed = True
        self._working(False)
        self._show(lines or ["—"])
        self.action.grid_remove()
        self.cancel.configure(text="Schließen", state="normal")
        if failed:
            self._say("Auf der OPNsense entfernt. Im DNS blieb etwas stehen: "
                      + "; ".join(f"{name}: {why}" for name, why in failed))
        else:
            where = f" und aus {len(done)} DNS-Server{'n' if len(done) != 1 else ''}" \
                if done else ""
            self._say(f"Entfernt — von {self.firewall.name}{where}.")
        # every line needs its level: the log colours by it and reads it
        # without asking whether it is there
        self.app._write_log(
            "Entfernt", [{"text": line, "level": "info"} for line in lines]
            + [{"text": f"{name}: {why}", "level": "error"}
               for name, why in failed], not failed)
        # This window is a receipt now, not a decision, so it lets go of the
        # grab: otherwise the progress window that comes up for the re-read
        # would be sitting there unable to take a single click, its "keep
        # reading in the background" button included.
        try:
            self.grab_release()
        except tk.TclError:
            pass  # already gone with the window
        # read again, so the overview stops showing what is gone
        self.app.refresh_sources([wiring.OPNSENSE, wiring.DNS])

    def _failed(self, error):
        self._working(False)
        self.cancel.configure(state="normal")
        self._say(f"Fehlgeschlagen: {error}")

    def _later(self, call):
        """Hand a result back to the window's own thread."""
        self.app.results.put(("done", call, None, None, None))


def ask(app, chain):
    """Open the removal for one chain of the status page."""
    firewall = removal.firewall_of(app.shelf, chain)
    if firewall is None:
        gui.messagebox.showinfo(
            gui.APP_TITLE,
            f"Die OPNsense „{chain.where}“ steht nicht mehr in den "
            "Einstellungen.", parent=app)
        return False
    dialog = RemoveDialog(app, chain, firewall)
    app.wait_window(dialog)
    return dialog.removed
