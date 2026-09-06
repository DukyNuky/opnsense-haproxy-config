"""Noting what sits behind an address, when it is not a container.

A VM behind a name looks exactly like a container that is not there: an
address with nothing of ours listening on it. Only somebody who knows can tell
the two apart -- and once they have, the answer is written onto the server
entry on the OPNsense itself, not into a file here. That way the next
installation of this program, on this machine or another, reads it back
instead of asking again.
"""

import threading
import tkinter as tk
from tkinter import ttk

import haproxy_gui as gui
import opnsense_haproxy as core
from app import wiring

# The order they are offered in: the common case first, then the reasons a
# container would not be found, then the way to take the note off again.
CHOICES = (
    ("docker", "Ein Docker-Container",
     "Er sollte in einem der eingerichteten Docker-Hosts auftauchen."),
    ("vm", "Eine eigene VM",
     "Eine virtuelle Maschine mit eigener Adresse — kein Container, also ist "
     "auch keiner zu finden."),
    ("geraet", "Ein eigenes Gerät",
     "NAS, Drucker, Kamera, Fritzbox: etwas, das für sich steht."),
    ("extern", "Etwas woanders",
     "Ein Dienst außerhalb, den dieses Programm nicht sehen kann."),
    ("", "Nicht vermerken",
     "Der Überblick sagt dann wieder, dass er es nicht weiß."),
)


class BehindDialog(tk.Toplevel):
    """Asks what runs behind these addresses and writes it onto the server."""

    def __init__(self, app, chain, servers, firewall):
        super().__init__(app)
        self.app = app
        self.servers = [s for s in servers if s.get("uuid")]
        self.firewall = firewall
        self.written = False
        self.title("Was läuft dahinter?")
        self.transient(app)
        self.configure(bg=app.colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        row = 0

        ttk.Label(body, text=chain.name, style="H2.TLabel").grid(
            row=row, column=0, sticky="w"); row += 1
        where = ", ".join(f"{s.get('address', '?')}:{s.get('port', '?')}"
                          for s in self.servers) or "keine Adresse"
        ttk.Label(body, style="Hint.TLabel", wraplength=440, justify="left",
                  text=f"HAProxy reicht diesen Namen an {where} weiter. Was "
                       "dort steht, kann das Programm nicht selbst "
                       "herausfinden, wenn es kein Container ist.").grid(
            row=row, column=0, sticky="w", pady=(3, 14)); row += 1

        current = {str(s.get("behind") or "") for s in self.servers}
        self.var = tk.StringVar(value=current.pop() if len(current) == 1 else "")
        for key, title, hint in CHOICES:
            ttk.Radiobutton(body, text=title, value=key, variable=self.var,
                            style="Card.TRadiobutton").grid(
                row=row, column=0, sticky="w", pady=(6, 0)); row += 1
            ttk.Label(body, text=hint, style="Hint.TLabel", wraplength=420,
                      justify="left").grid(row=row, column=0, sticky="w",
                                           padx=(24, 0)); row += 1

        ttk.Label(body, style="Hint.TLabel", wraplength=440, justify="left",
                  text="Der Vermerk wird in die Beschreibung des Servers auf "
                       f"„{firewall.name}“ geschrieben. Er bleibt dort — auch "
                       "wenn dieses Programm neu installiert wird oder auf "
                       "einem anderen Rechner läuft.").grid(
            row=row, column=0, sticky="w", pady=(16, 0)); row += 1

        self.note = ttk.Label(body, style="Hint.TLabel", wraplength=440,
                              justify="left", text="")
        self.note.grid(row=row, column=0, sticky="w", pady=(8, 0)); row += 1
        self.note.grid_remove()

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.cancel = ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                                 command=self.destroy)
        self.cancel.grid(row=0, column=0, padx=(0, 8))
        self.action = ttk.Button(buttons, text="Vermerken",
                                 style="Accent.TButton", command=self._write)
        self.action.grid(row=0, column=1)

        self.bind("<Escape>", lambda _e: self.destroy())
        gui.fit_window(self, floor=480)
        self.resizable(False, False)
        gui.place_over(self, self.app)
        self.grab_set()

    def _say(self, text):
        self.note.configure(text=text)
        self.note.grid()
        gui.fit_window(self, floor=480, shrink=False)

    def _write(self):
        if not self.servers:
            self._say("Zu diesem Eintrag gehört kein Server, an dem der "
                      "Vermerk hängen könnte.")
            return
        kind = self.var.get()
        self.action.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self._say("wird auf die OPNsense geschrieben …")
        servers = list(self.servers)
        settings = dict(self.firewall.settings)

        def task():
            try:
                client = wiring.opnsense_client(settings)
                for server in servers:
                    core.set_behind(client, server["uuid"], kind,
                                    server.get("description", ""))
            except Exception as exc:  # noqa: BLE001 - shown in the dialog
                self.app.results.put(
                    ("done", lambda _p, error=exc: self._failed(error),
                     None, None, None))
                return
            self.app.results.put(("done", self._done, None, kind, None))

        threading.Thread(target=task, daemon=True).start()

    def _failed(self, error):
        self.action.configure(state="normal")
        self.cancel.configure(state="normal")
        self._say(f"Nicht geschrieben: {error}")

    def _done(self, kind):
        self.written = True
        self.destroy()
        # read the firewall again, so the overview shows the note rather than
        # what it worked out before it existed
        # quietly: the line in the log below already says it happened, and a
        # cover flashing over the window right after a dialog closed reads as
        # something having gone wrong
        self.app.refresh_sources([wiring.OPNSENSE], quiet=True)
        word = core.BEHIND_KINDS.get(kind, "")
        self.app._write_log(
            "Vermerkt",
            [{"text": f"{len(self.servers)} Server: "
                      + (f"{word}" if word else "Vermerk entfernt")}], False)


def ask(app, chain, station):
    """Open the note dialog for the servers of one chain."""
    firewall = app.shelf.get(wiring.OPNSENSE, chain.where)
    if firewall is None:
        gui.messagebox.showinfo(
            gui.APP_TITLE,
            f"Die OPNsense „{chain.where}“ steht nicht mehr in den "
            "Einstellungen.", parent=app)
        return
    dialog = BehindDialog(app, chain, station.data.get("servers") or [],
                          firewall)
    app.wait_window(dialog)
    return dialog.written
