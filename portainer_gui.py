#!/usr/bin/env python3
"""The Portainer tab of the window.

Everything here hangs off the main window: the colours, the background thread
and the log at the bottom belong to it, so this file only describes what the
second tab shows and what its buttons set off.

The widgets it borrows (the scroller, the sliding switch, the tooltip) live in
haproxy_gui. That module imports this one only when it builds the tab, which is
long after it has finished loading itself -- so the two can point at each other
without an import running in circles.
"""

import argparse
import itertools
import time

import tkinter as tk
from tkinter import messagebox, ttk

import catalog as cat
import haproxy_gui as ui
import opnsense_haproxy as core
import portainer as pcore

# How many published ports a card shows before the rest are folded away. One
# more than this still shows in full -- hiding a single row helps nobody.
PORTS_SHOWN = 4

AUTO_OFF = "aus"
AUTO_INTERVAL = "regelmäßig nachsehen"
AUTO_WEBHOOK = "auf Webhook warten"
AUTO_MODES = (AUTO_OFF, AUTO_INTERVAL, AUTO_WEBHOOK)

NO_HEALTHCHECK = "— keiner —"

# Where a token for a private repository is handed out. Only these two are
# offered: they are what the field above them expects an address from.
GITHUB_TOKEN_URL = cat.TOKEN_PAGES["github.com"][0]
GITLAB_TOKEN_URL = cat.TOKEN_PAGES["gitlab.com"][0]

# The three lists the catalog window shows, in the order it offers them.
KNOWN = "Bekannte Stacks"
FAVOURITES = "Meine Favoriten"
OWN = "Meine Repos"

# From which port upwards the window looks for a free one. Below 1024 a Linux
# host wants root, and 80 and 443 belong to whatever is already listening.
FIRST_FREE_PORT = 8000


class PortainerTab(ttk.Frame):
    """Stacks, containers and their published ports -- and the way to HAProxy."""

    def __init__(self, parent, app):
        super().__init__(parent, style="TFrame")
        self.app = app
        self.client = None
        self.settings = {}
        self.problem = ""
        self.connected = False
        self.state = None
        self.endpoint_id = None
        self.last_deploy = None
        self.link_after_deploy = True
        self.dialog = None
        self.catalog = None
        # what a deploy is waiting to do while the environment is being checked
        self.pending = None
        # stacks whose port list is unfolded; the listing is rebuilt often, so
        # the answer cannot live on the widgets themselves
        self.unfolded = set()

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
        ttk.Label(head, text="Stacks und Ports", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")

        # Which Portainer is being worked on is chosen in the header, next to
        # the connection state -- the same place the firewall is chosen on the
        # other tab. A second picker for it used to sit here and was easy to
        # take for the environment picker beside it.
        picks = ttk.Frame(head, style="Card.TFrame")
        picks.grid(row=0, column=2, sticky="e")
        self.var_endpoint = tk.StringVar()
        self.endpoint_box = ttk.Combobox(picks, textvariable=self.var_endpoint,
                                         state="readonly", width=18,
                                         style="Card.TCombobox")
        self.endpoint_box.grid(row=0, column=0, sticky="e", padx=(0, 6))
        self.endpoint_box.bind("<<ComboboxSelected>>",
                               lambda _e: self._endpoint_changed())
        self.endpoint_box.grid_remove()
        ui.Tooltip(self.endpoint_box, "Welche Docker-Umgebung dieses Portainers")
        self.catalog_button = ttk.Button(picks, text="★ Katalog",
                                         style="Del.TButton",
                                         command=self.open_catalog)
        self.catalog_button.grid(row=0, column=1, sticky="e", padx=(0, 6))
        ui.Tooltip(self.catalog_button,
                   "Bekannte Stacks, eigene Favoriten und die eigenen "
                   "Repositories — zum Deployen ohne Tipparbeit")
        self.new_button = ttk.Button(picks, text="＋ Neuer Stack",
                                     style="Accent.TButton",
                                     command=self.open_deploy)
        self.new_button.grid(row=0, column=2, sticky="e")

        ttk.Label(outer, style="Hint.TLabel",
                  text="Welche Ports nach außen offen sind — und damit die, "
                       "die HAProxy ansprechen kann.").grid(row=1, column=0,
                                                            sticky="w",
                                                            pady=(3, 12))

        self.listing = ui.ScrollFrame(outer, self.app.colors)
        self.listing.grid(row=2, column=0, sticky="nsew")

    def apply_theme(self):
        self.listing.apply_theme(self.app.colors)
        for window in (self.dialog, self.catalog):
            if window is not None and window.winfo_exists():
                window.apply_theme(self.app.colors)
        self.render()

    # -- connection --------------------------------------------------------

    def use_profile(self, profile):
        """Take up the Portainer part of the connection that was just chosen."""
        self.connected = False
        self.state = None
        self.client, self.settings = pcore.client_from_config(
            profile, insecure=getattr(self.app.args, "insecure", False))
        self.problem = self.settings.get("error", "")
        # remembered under the Portainer's own name: with two Docker hosts on
        # one firewall, the environment of the one is no answer for the other
        remembered = (self.app.prefs.get("portainer_endpoint") or {}).get(
            (profile.get("portainer") or {}).get("name", ""))
        self.endpoint_id = self.settings.get("endpoint_id") or remembered
        self.endpoint_box.grid_remove()
        self.render()

    @property
    def configured(self):
        return self.client is not None

    def status_text(self):
        """What the pill in the header says while this tab is in front."""
        if not self.configured:
            return self.problem or "kein Portainer eingerichtet", False
        if not self.connected:
            return "nicht verbunden", False
        state = self.state or {}
        stacks = len(state.get("stacks", []))
        containers = sum(len(stack["containers"])
                         for stack in state.get("stacks", []))
        containers += len(state.get("loose", []))
        return (f"{stacks} Stack{'' if stacks == 1 else 's'} · "
                f"{containers} Container"), True

    def reload(self):
        """Read everything Portainer knows about this environment."""
        if not self.client:
            self.app.open_settings()
            return
        client, wanted = self.client, self.endpoint_id

        def work(report):
            report("melde mich bei Portainer an …")
            version = client.version()
            report("lese Umgebungen, Stacks und Container …")
            try:
                state = pcore.inventory(client, wanted)
            except pcore.PortainerError as exc:
                # the environment we looked at last time can be gone; that is
                # no reason to leave the tab empty
                if wanted is None or "no environment" not in str(exc):
                    raise
                report("die zuletzt benutzte Umgebung gibt es nicht mehr …")
                state = pcore.inventory(client, None)
            state["version"] = version
            return state

        self.app.run_async(work, self._loaded, on_error=self._failed,
                           activity="verbinde mit Portainer …")

    def _failed(self, _error):
        self.connected = False
        self.app.paint_connection()
        self.render()

    def _loaded(self, state):
        self.app.set_busy(False)
        self.connected = True
        self.state = state
        self.endpoint_id = state["endpoint"]["id"]
        names = [f"{entry['name']}" for entry in state["endpoints"]]
        self.endpoint_box.configure(values=names)
        self.var_endpoint.set(state["endpoint"]["name"])
        self.endpoint_box.grid() if len(names) > 1 else self.endpoint_box.grid_remove()
        self.app.remember_endpoint(self.endpoint_id)
        self.app.paint_connection()
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.refresh_target()
        self.render()
        if self.last_deploy:
            self._offer_link(self.last_deploy)
            self.last_deploy = None

    def _endpoint_changed(self):
        self.choose_endpoint(self.var_endpoint.get())

    def choose_endpoint(self, name):
        """Work on another Docker environment of this Portainer."""
        for entry in (self.state or {}).get("endpoints", []):
            if entry["name"] == name and entry["id"] != self.endpoint_id:
                self.endpoint_id = entry["id"]
                self.reload()
                return

    # -- the listing -------------------------------------------------------

    def render(self):
        self.listing.clear()
        body = self.listing.body
        body.columnconfigure(0, weight=1)

        if not self.configured:
            self._placeholder(
                "Kein Portainer eingerichtet",
                self.problem or "Lege unter ⚙ einen Portainer an, dann "
                                "erscheinen hier alle Stacks mit ihren "
                                "Ports.",
                "Einstellungen öffnen", self.app.open_settings)
            return
        if not self.connected:
            self._placeholder("Nicht verbunden",
                              "„Verbinden“ oben rechts liest Stacks, Container "
                              "und Ports aus Portainer.",
                              "Verbinden", self.reload)
            return

        state = self.state
        row = itertools.count()
        if not state["stacks"] and not state["loose"]:
            self._placeholder("Nichts zu sehen",
                              f"Auf {state['endpoint']['name']} läuft weder ein "
                              "Stack noch ein Container.")
            return

        for stack in state["stacks"]:
            card = self._stack_card(body, stack)
            card.grid(row=next(row), column=0, sticky="ew", pady=(0, 8))
        if state["loose"]:
            ttk.Label(body, text="Einzelne Container",
                      style="Group.TLabel").grid(row=next(row), column=0,
                                                 sticky="w", pady=(10, 6))
            ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                      text="Ohne Stack gestartet. Sie belegen dieselben Ports "
                           "auf dem Host.").grid(row=next(row), column=0,
                                                 sticky="w", pady=(0, 6))
            for container in state["loose"]:
                card = self._container_card(body, container)
                card.grid(row=next(row), column=0, sticky="ew", pady=(0, 6))

    def _placeholder(self, title, text, button="", command=None):
        holder = ttk.Frame(self.listing.body, style="Card.TFrame", padding=30)
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

    def _stack_card(self, parent, stack):
        colors = self.app.colors
        card = tk.Frame(parent, bg=colors["surface2"], padx=12, pady=10)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text=stack["name"], style="Host.TLabel").grid(
            row=0, column=0, sticky="w")

        marks = ttk.Frame(card, style="Sub.TFrame")
        marks.grid(row=0, column=1, padx=(10, 8))
        column = itertools.count()
        ttk.Label(marks, text=stack["kind"], style="BadgeMuted.TLabel").grid(
            row=0, column=next(column), padx=2)
        if stack["auto_update"]:
            auto = stack["auto_update"]
            badge = ttk.Label(marks, text="⟳ auto", style="Badge.TLabel")
            badge.grid(row=0, column=next(column), padx=2)
            ui.Tooltip(badge, f"alle {auto['interval']}" if auto["interval"]
                       else "wartet auf einen Webhook")
        total = len(stack["containers"])
        if total:
            healthy = stack["running"] == total
            state = ttk.Label(marks, text=f"{stack['running']}/{total}",
                              style="BadgeOk.TLabel" if healthy
                              else "BadgeWarn.TLabel")
            state.grid(row=0, column=next(column), padx=2)
            ui.Tooltip(state, f"{stack['running']} von {total} Containern laufen")

        buttons = ttk.Frame(card, style="Sub.TFrame")
        buttons.grid(row=0, column=2, rowspan=2)
        ttk.Button(buttons, text="Neu deployen", style="Del.TButton",
                   command=lambda s=stack: self._redeploy(s)).grid(row=0, column=0)
        remove = ttk.Button(buttons, text="Löschen", style="Del.TButton",
                            command=lambda s=stack: self._remove_stack(s))
        remove.grid(row=0, column=1, padx=(6, 0))
        ui.Tooltip(remove, "Stack samt Containern entfernen — und auf Wunsch "
                           "die HAProxy-Einträge, die auf seine Ports zeigen")

        source = "kein Repository hinterlegt"
        if stack["git"]:
            source = "→  " + stack["git"]["url"]
            if stack["git"]["reference"]:
                source += f"  ({stack['git']['reference']})"
        ttk.Label(card, text=source, style="Target.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ports = ttk.Frame(card, style="Sub.TFrame")
        ports.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ports.columnconfigure(0, weight=1)
        if not stack["ports"]:
            ttk.Label(ports, style="RowHint.TLabel",
                      text="kein Port nach außen veröffentlicht").grid(
                row=0, column=0, sticky="w")
        self._port_list(ports, stack["ports"], stack["name"], stack["name"])
        return card

    def _container_card(self, parent, container):
        colors = self.app.colors
        card = tk.Frame(parent, bg=colors["surface2"], padx=12, pady=8)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=container["name"], style="Host.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(card, text="→  " + container["image"],
                  style="Target.TLabel").grid(row=1, column=0, sticky="w")
        badge = ttk.Label(card, text=container["state"],
                          style="BadgeOk.TLabel" if container["state"] == "running"
                          else "BadgeMuted.TLabel")
        badge.grid(row=0, column=1, padx=(10, 0))
        ui.Tooltip(badge, container["status"] or container["state"])
        ports = ttk.Frame(card, style="Sub.TFrame")
        ports.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ports.columnconfigure(0, weight=1)
        listed = [{**port, "container": container["name"],
                   "service": container["name"]} for port in container["ports"]]
        self._port_list(ports, listed, "", "container:" + container["name"])
        return card

    def _port_list(self, parent, ports, stack_name, key):
        """The published ports, with the tail folded away when there are many.

        A stack that publishes a dozen ports would otherwise push everything
        below it off the screen, and the first few are the interesting ones.
        """
        shown = ports if (len(ports) <= PORTS_SHOWN + 1
                          or key in self.unfolded) else ports[:PORTS_SHOWN]
        for index, port in enumerate(shown):
            self._port_row(parent, port, stack_name).grid(
                row=index, column=0, sticky="ew", pady=(0, 2))
        hidden = len(ports) - len(shown)
        if not hidden and key not in self.unfolded:
            return
        if hidden:
            text = f"▾  {hidden} weitere Ports"
        else:
            text = "▴  weniger anzeigen"
        more = ttk.Button(parent, text=text, style="Ghost.TButton",
                          command=lambda: self._unfold(key))
        more.grid(row=len(shown), column=0, sticky="w", pady=(2, 0))

    def _unfold(self, key):
        self.unfolded.symmetric_difference_update({key})
        self.render()

    def _port_row(self, parent, port, stack_name):
        """One published port: where it listens, and what HAProxy makes of it."""
        row = ttk.Frame(parent, style="Sub.TFrame")
        row.columnconfigure(1, weight=1)

        text = (f"{port['host_port']}  →  {port['container_port']}"
                f"/{port['proto']}")
        ttk.Label(row, text=text, style="Target.TLabel").grid(row=0, column=0,
                                                              sticky="w")
        ttk.Label(row, text=f"  {port.get('service', '')}",
                  style="RowHint.TLabel").grid(row=0, column=1, sticky="w")

        if not port["everywhere"]:
            badge = ttk.Label(row, text="nur lokal", style="BadgeWarn.TLabel")
            badge.grid(row=0, column=2, padx=(6, 0))
            ui.Tooltip(badge,
                       "Nur auf " + ", ".join(port["addresses"]) + " gebunden. "
                       "Von einer anderen Maschine — also auch von HAProxy — "
                       "ist dieser Port nicht erreichbar.")

        existing = self._haproxy_rule(port)
        if existing:
            badge = ttk.Label(row, text="HAProxy ✓", style="BadgeOk.TLabel")
            badge.grid(row=0, column=3, padx=(6, 0))
            ui.Tooltip(badge, f"{existing} zeigt bereits auf diesen Port")
        else:
            button = ttk.Button(row, text="→ HAProxy", style="Del.TButton",
                                command=lambda p=port, s=stack_name:
                                self._link(p, s))
            button.grid(row=0, column=3, padx=(6, 0))
            ui.Tooltip(button, "Diesen Port über HAProxy von außen erreichbar "
                               "machen")
        return row

    def _haproxy_rule(self, port):
        """The HAProxy host already pointing at this port, if there is one."""
        target = self.host_ip()
        if not target:
            return ""
        for service in self.app.services:
            for rule in service.get("rules", []):
                for server in (rule.get("backend") or {}).get("servers") or []:
                    if (str(server.get("address", "")) == target
                            and str(server.get("port", "")) == str(port["host_port"])):
                        return rule.get("host") or rule.get("target") or "Eine Rule"
        return ""

    def host_ip(self):
        """The address HAProxy has to send traffic to for these containers."""
        return pcore.host_ip_of(self.app.profile)

    # -- actions -----------------------------------------------------------

    def busy_buttons(self):
        """What the window switches off while something is running."""
        buttons = [self.new_button, self.catalog_button]
        for window in (self.dialog, self.catalog):
            if window is not None and window.winfo_exists():
                buttons.extend(window.busy_buttons())
        return tuple(buttons)

    def open_catalog(self):
        """The collection to deploy from, in a window of its own."""
        if self.catalog is not None and self.catalog.winfo_exists():
            self.catalog.lift()
            self.catalog.focus_set()
            return
        self.catalog = CatalogDialog(self.app, self)

    def deploy_entry(self, entry):
        """Open the deploy form with one entry of the collection filled in.

        The credentials come from the Git account that matches the host of the
        repository, so an own repository needs no more than a click -- and they
        are filled into the visible fields rather than sent along quietly.
        """
        username, token = cat.credentials_for(self.app.systems,
                                              entry.get("repository", ""))
        preset = dict(entry)
        preset["username"], preset["password"] = username, token
        self.open_deploy(preset)

    def open_deploy(self, preset=None):
        """The form for a new stack, in a window of its own.

        It used to be a column squeezed against the left edge of the tab, where
        a compose path and a block of variables had about three hundred pixels
        between them. As a dialog it gets the room those fields need, and the
        listing gets the whole width back.
        """
        if self.dialog is not None and self.dialog.winfo_exists():
            if preset:
                self.dialog.fill_in(preset)
            self.dialog.lift()
            self.dialog.focus_set()
            return
        if not self.client:
            self.app.open_settings()
            return
        if not self.connected:
            messagebox.showinfo(
                ui.APP_TITLE,
                "Bitte zuerst verbinden — ohne die Umgebung aus Portainer "
                "weiß das Programm nicht, wohin der Stack soll.")
            return
        self.dialog = DeployDialog(self.app, self)
        if preset:
            self.dialog.fill_in(preset)

    def portainer_names(self):
        return [entry.get("name", "?")
                for entry in self.app.systems.get("portainer", [])]

    def endpoint_names(self):
        return [entry["name"] for entry in (self.state or {}).get("endpoints", [])]

    def free_ports(self):
        """Host ports on this environment that nothing answers on, for the form."""
        if not self.connected:
            return []
        return pcore.free_ports(self.state, FIRST_FREE_PORT)

    def taken_ports(self):
        """Host ports that are gone -- what the free list was measured against."""
        return pcore.taken_ports(self.state) if self.connected else []

    def _load_env(self, values):
        """Ask the repository what this stack expects, before deploying it."""
        if self.app.busy:
            return
        if not values["repository"]:
            messagebox.showwarning(ui.APP_TITLE,
                                   "Bitte die Adresse des Repositories eintragen.",
                                   parent=self.dialog)
            return
        opts = argparse.Namespace(
            repository=values["repository"],
            reference=values["reference"],
            compose_file=values["compose_file"],
            username=values["username"],
            password=values["password"],
            skip_tls_verify=values["skip_tls_verify"],
        )
        client = self.client
        self.app.run_async(
            lambda report: pcore.run_step(pcore.discover_env, client, opts,
                                          log=ui.LiveLog(report)),
            self._env_found, activity="lese das Repository …")

    def _env_found(self, result):
        self.app.set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
        if not result["ok"]:
            self.app.write_log("Nichts gelesen", lines, False)
            return
        if self.dialog is None or not self.dialog.winfo_exists():
            return  # the form was closed while the repository was being read

        found = result["result"]
        # what is already in the box wins: those values were typed on purpose
        try:
            taken = {entry["name"] for entry in
                     pcore.parse_env(self.dialog.env_value())}
        except core.UsageError:
            taken = set()
        block = self._env_block(found, taken)
        if not block:
            lines.append({"text": "= im Feld steht schon alles, was gebraucht "
                                  "wird", "level": "info"})
            self.app.write_log("Nichts zu ergänzen", lines, True)
            return
        added = self.dialog.add_env(block)
        lines.append({"text": f"+ {added} Zeilen ins Feld übernommen",
                      "level": "info"})
        self.app.write_log("Aus dem Repository", lines, True)

    @staticmethod
    def _env_block(found, taken):
        """The lines to append: from the file first, then what it did not cover.

        The comments say where each part comes from. They are just comments --
        the reader in portainer.py steps over them, so they can stay in the
        field and be there again the next time somebody looks.
        """
        parts = []
        fresh = [entry for entry in found["entries"]
                 if entry["name"] not in taken]
        if fresh:
            parts.append(f"# aus {found['source']}")
            parts.extend(f"{entry['name']}={entry['value']}" for entry in fresh)
        missing = [entry for entry in found["missing"]
                   if entry["name"] not in taken]
        if missing:
            if parts:
                parts.append("")
            filled = sum(1 for entry in missing if entry["value"])
            if not filled:
                note = "bitte ausfüllen"
            elif filled == len(missing):
                note = "Vorgaben aus der Datei eingetragen"
            else:
                note = "Vorgaben eingetragen, leere bitte ausfüllen"
            parts.append(f"# in {found['compose']} verwendet, {note}")
            parts.extend(f"{entry['name']}={entry['value']}"
                         for entry in missing)
        return "\n".join(parts) + "\n" if parts else ""

    def _deploy(self, values):
        """Create the stack the dialog describes, on the chosen environment."""
        if self.app.busy:
            return
        if not self.connected:
            messagebox.showinfo(
                ui.APP_TITLE,
                "Bitte zuerst verbinden — ohne die Umgebung aus Portainer "
                "weiß das Programm nicht, wohin der Stack soll.",
                parent=self.dialog)
            return
        name = values["name"]
        parent = self.dialog
        if not name:
            messagebox.showwarning(ui.APP_TITLE, "Bitte einen Namen vergeben.",
                                   parent=parent)
            return
        if not values["repository"]:
            messagebox.showwarning(ui.APP_TITLE,
                                   "Bitte die Adresse des Repositories eintragen.",
                                   parent=parent)
            return
        if pcore.stack_name_taken(self.state, name):
            messagebox.showwarning(
                ui.APP_TITLE,
                f"Es gibt auf {self.target_text()} schon einen Stack namens "
                f"„{name}“.\n\nZum Aktualisieren „Neu deployen“ in der Liste "
                f"benutzen.", parent=parent)
            return
        try:
            variables = pcore.parse_env(values["env_text"])
        except core.UsageError as exc:
            messagebox.showwarning("Umgebungsvariablen", str(exc), parent=parent)
            return

        auto = pcore.auto_update_settings(values["auto_mode"],
                                          values["interval"],
                                          values["force_pull"])
        opts = argparse.Namespace(
            endpoint_id=self.endpoint_id,
            name=name,
            repository=values["repository"],
            reference=values["reference"],
            compose_file=values["compose_file"],
            env_text=pcore.env_text(variables),
            username=values["username"],
            password=values["password"],
            auto_update=auto,
            skip_tls_verify=values["skip_tls_verify"],
        )
        self.link_after_deploy = values["link"]
        # Names and ports are the host's to hand out, and Portainer only finds
        # that out halfway through creating the stack. Asking first costs one
        # read of the repository and can still be answered here.
        self.pending = opts
        client = self.client
        state = self.state
        self.app.run_async(
            lambda report: pcore.run_step(pcore.check_deploy, client, opts,
                                          state, log=ui.LiveLog(report)),
            self._checked, activity=f"prüfe {name} …")

    def _checked(self, result):
        """What the environment already has, before anything is created."""
        self.app.set_busy(False)
        opts, self.pending = self.pending, None
        if opts is None:
            return
        if not result["ok"]:
            # the compose file could not be read -- whatever is wrong with the
            # repository, Portainer says it better while deploying
            self._start_deploy(opts)
            return
        clashes = result["result"]["clashes"]
        if not clashes:
            self._start_deploy(opts)
            return
        answer = self._ask_clashes(clashes, result["result"]["compose"])
        if answer is None:
            self.app.write_log(
                "Deploy abgebrochen",
                list(result["log"])
                + [{"text": "= nichts angelegt", "level": "info"}], False)
            return
        if answer:
            self._resolve(opts, clashes)
        self._start_deploy(opts)

    def _ask_clashes(self, clashes, compose):
        """Ask what to do about it: change the values, deploy anyway, or stop.

        Returns True for the way out that was offered, False for deploying as
        it stands, None for going back to the form.
        """
        fixable = [clash for clash in clashes
                   if clash["variable"] and clash["suggest"]]
        text = self._clash_text(clashes, compose, fixable)
        # the form may have been closed while the repository was being read
        parent = self.dialog if (self.dialog is not None
                                 and self.dialog.winfo_exists()) else self
        if not fixable:
            return False if messagebox.askyesno(
                "Schon vergeben", text, default=messagebox.NO,
                parent=parent) else None
        answer = messagebox.askyesnocancel("Schon vergeben", text,
                                           parent=parent)
        return answer if answer is None else bool(answer)

    def _clash_text(self, clashes, compose, fixable):
        """The whole story in one box: what is taken, by whom, and what helps."""
        kinds = {"name": "Container-Name", "port": "Host-Port"}
        lines = [f"Auf {self.target_text()} ist schon vergeben:", ""]
        for clash in clashes:
            owner = clash["stack"] or clash["container"] or "einem Container"
            lines.append(f"• {kinds[clash['kind']]} „{clash['value']}“ "
                         f"— belegt von {owner}")
        lines += ["",
                  "Container-Namen und Host-Ports gelten für den ganzen "
                  "Docker-Host, nicht für den einzelnen Stack. Docker würde "
                  "den Deploy darum abweisen."]
        if fixable:
            lines += ["", "Diese Werte kommen aus Variablen und lassen sich "
                          "hier ändern:"]
            lines += [f"    {clash['variable']}={clash['suggest']}"
                      for clash in fixable]
        stuck = [clash for clash in clashes if not clash["variable"]]
        if stuck:
            lines += ["", f"Fest in {compose} eingetragen — das geht nur im "
                          f"Repository selbst:"]
            lines += [f"    {kinds[clash['kind']]} {clash['value']}"
                      for clash in stuck]
        if fixable:
            lines += ["", "Ja: Variablen eintragen und deployen.",
                      "Nein: unverändert deployen.",
                      "Abbrechen: zurück zum Formular."]
        else:
            lines += ["", "Trotzdem deployen?"]
        return "\n".join(lines)

    def _resolve(self, opts, clashes):
        """Put the free values into the environment, in the form and the deploy."""
        values = {clash["variable"]: str(clash["suggest"]) for clash in clashes
                  if clash["variable"] and clash["suggest"]}
        if not values:
            return
        opts.env_text = pcore.put_env(
            opts.env_text, values,
            note="damit der Stack neben dem bestehenden laufen kann")
        # the form keeps the same text: a second try after a failed deploy
        # should start from what was actually sent
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.set_env(opts.env_text)

    def _start_deploy(self, opts):
        client = self.client
        self.app.run_async(
            lambda report: pcore.run_step(pcore.deploy, client, opts,
                                          log=ui.LiveLog(report)),
            self._deployed, activity=f"deploye {opts.name} …")

    def target_text(self):
        """Where a deploy would land, in words -- Portainer and environment."""
        where = (self.state or {}).get("endpoint", {}).get("name", "")
        portainer = self.app.active.get("portainer", "")
        if portainer and where:
            return f"{portainer} · {where}"
        return portainer or where or "diesem Portainer"

    def _deployed(self, result):
        self.app.set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
            hint = self._conflict_hint(result["error"])
            if hint:
                lines.append({"text": hint, "level": "info"})
        title = "Stack deployt" if result["ok"] else "Deploy fehlgeschlagen"
        if result["ok"]:
            # A webhook is only useful once its address is known, and Portainer
            # makes that address up while creating the stack.
            created = (result["result"].get("stack") or {}).get("AutoUpdate") or {}
            if created.get("Webhook"):
                lines.append({"text": "Webhook: " + pcore.webhook_url(
                    self.client, created["Webhook"]), "level": "info"})
        self.app.write_log(title, lines, result["ok"])
        if not result["ok"]:
            return
        name = result["result"]["name"]
        # Only after the containers are up does Docker know their ports, so
        # the offer to publish one has to wait for the next reading.
        self.last_deploy = name if self.link_after_deploy else None
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.destroy()
        self.dialog = None
        self.after(1200, self.reload)

    @staticmethod
    def _conflict_hint(message):
        """Docker's own words about a collision, said in the tab's language.

        The check before the deploy catches most of these. What still gets
        here came from a compose file that could not be read beforehand, or
        from a container that appeared in the meantime.
        """
        clash = pcore.conflict_in(message)
        if not clash:
            return ""
        if clash["kind"] == "name":
            return (f"= Der Container-Name „{clash['value']}“ ist auf diesem "
                    f"Docker-Host schon vergeben. Er gilt dort einmal, nicht "
                    f"einmal pro Stack: damit zwei Stacks aus demselben "
                    f"Repository laufen können, muss container_name im "
                    f"Compose-File aus einer Variablen kommen "
                    f"(container_name: ${{STACK_NAME:-{clash['value']}}}) oder "
                    f"ganz entfallen — dann benennt Docker die Container nach "
                    f"dem Stack.")
        return (f"= Host-Port {clash['value']} ist auf diesem Docker-Host schon "
                f"belegt. Kommt er im Compose-File aus einer Variablen, reicht "
                f"hier ein anderer Wert; sonst muss er im Repository geändert "
                f"werden.")

    def _offer_link(self, stack_name):
        """After a deploy: suggest the way in for the first published port."""
        stack = next((s for s in (self.state or {}).get("stacks", [])
                      if s["name"] == stack_name), None)
        if not stack:
            return
        outside = [port for port in stack["ports"] if port["everywhere"]]
        if not outside:
            self.app.write_log(
                "Stack deployt",
                [{"text": f"= {stack_name} veröffentlicht keinen Port nach "
                          f"außen — für HAProxy gibt es hier nichts zu tun.",
                  "level": "info"}], True)
            return
        self._link(outside[0], stack_name)

    def _redeploy(self, stack):
        if self.app.busy:
            return
        dialog = RedeployDialog(self.app, self.app.colors, stack)
        self.app.wait_window(dialog)
        if not dialog.result:
            return
        answer = dialog.result
        client = self.client
        self.app.run_async(
            lambda report: pcore.run_step(
                pcore.redeploy, client, stack,
                pull_image=answer["pull"], prune=answer["prune"],
                username=answer["username"], password=answer["password"],
                log=ui.LiveLog(report)),
            self._redeployed, activity=f"deploye {stack['name']} neu …")

    def _haproxy_hosts(self, stack):
        """The HAProxy hosts that send traffic to this stack's ports.

        They are the reason a stack cannot simply be deleted and forgotten: the
        rule on the firewall stays behind, pointing at a port nothing answers
        on any more, and the name keeps resolving to it.
        """
        target = self.host_ip()
        if not target or not self.app.connected:
            return []
        ports = {str(port["host_port"]) for port in stack["ports"]}
        found = []
        for service in self.app.services:
            for rule in service.get("rules", []):
                for server in (rule.get("backend") or {}).get("servers") or []:
                    if (str(server.get("address", "")) == target
                            and str(server.get("port", "")) in ports
                            and rule.get("target")):
                        found.append(rule)
                        break
        return found

    def _remove_stack(self, stack):
        """Delete one stack, and offer to take its way in down with it."""
        if self.app.busy:
            return
        if not self.connected:
            messagebox.showinfo(ui.APP_TITLE,
                                "Bitte zuerst verbinden — gelöscht wird nur, "
                                "was gerade auch zu sehen ist.")
            return
        hosts = self._haproxy_hosts(stack)
        dialog = RemoveDialog(self.app, self.app.colors, stack, hosts,
                              self._haproxy_note())
        self.app.wait_window(dialog)
        if not dialog.result:
            return

        client = self.client
        plan = self.app.removal_plan(hosts if dialog.result["haproxy"] else [])

        def work(report):
            log = ui.LiveLog(report)
            answer = pcore.run_step(pcore.remove_stack, client, stack, log=log)
            answer["haproxy"] = []
            if not answer["ok"]:
                return answer
            for opts in plan["steps"]:
                try:
                    core.deprovision(plan["client"], opts, out=log,
                                     adguard=plan["adguard"])
                    answer["haproxy"].append(opts.target)
                except (core.UsageError, core.ApiError) as exc:
                    # the stack is gone by now, so this is worth saying rather
                    # than raising: the rest of the clean-up still runs
                    log(f"! {opts.target}: {exc}")
                    answer["ok"] = False
            return answer

        self.app.run_async(work, self._removed,
                           activity=f"entferne {stack['name']} …")

    def _haproxy_note(self):
        """Why the HAProxy half of the removal may not be on offer."""
        if not self.app.api:
            return "Für die OPNsense fehlen die Zugangsdaten (⚙)."
        if not self.app.connected:
            return "Dafür muss der Tab „HAProxy“ verbunden sein."
        if not self.host_ip():
            return "Es ist nicht bekannt, unter welcher IP der Docker-Host zu "\
                   "erreichen ist (⚙ beim Portainer)."
        return ""

    def _removed(self, result):
        self.app.set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
        for target in result.get("haproxy", []):
            lines.append({"text": f"= {target} ist auch aus HAProxy heraus",
                          "level": "info"})
        self.app.write_log("Gelöscht" if result["ok"] else "Fehlgeschlagen",
                           lines, result["ok"])
        if result.get("haproxy"):
            self.app.reload()  # the host list on the other tab is one short now
        self.after(1200, self.reload)

    def _redeployed(self, result):
        self.app.set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
        self.app.write_log("Neu deployt" if result["ok"] else "Fehlgeschlagen",
                           lines, result["ok"])
        if result["ok"]:
            self.after(1200, self.reload)

    def _link(self, port, stack_name):
        """Hand one published port over to the HAProxy side of the program."""
        if not self.app.api:
            messagebox.showinfo(ui.APP_TITLE,
                                "Für den Weg über HAProxy fehlen die "
                                "Zugangsdaten der OPNsense (⚙).")
            return
        if not self.app.connected:
            messagebox.showinfo(
                ui.APP_TITLE,
                "Bitte zuerst im Tab „HAProxy“ verbinden — ohne die Public "
                "Services von der OPNsense weiß das Programm nicht, wo die "
                "Rule hin soll.")
            return
        target = self.host_ip()
        if not target:
            messagebox.showinfo(
                ui.APP_TITLE,
                "Es ist nicht bekannt, unter welcher IP der Docker-Host zu "
                "erreichen ist. Trage sie unter ⚙ beim Portainer ein.")
            return
        suggestion = port.get("service") or stack_name or ""
        dialog = LinkDialog(self.app, self.app.colors, suggestion, target, port)
        self.app.wait_window(dialog)
        if dialog.result:
            self.app.provision_host(dialog.result)


class DeployDialog(tk.Toplevel):
    """Everything a new stack needs, in two columns and with room to type.

    The tab does the talking to Portainer; this window only collects what to
    say. It stays open while the repository is read, so the variables it finds
    land in the field the user is looking at.
    """

    def __init__(self, app, tab):
        super().__init__(app)
        self.app = app
        self.tab = tab
        # kept on the window itself: the tooltips and the links read the theme
        # off whichever window they hang in
        self.colors = colors = app.colors
        self.title("Neuer Stack")
        self.transient(app)
        self.configure(bg=colors["bg"])
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.scroll = ui.ScrollFrame(self, colors)
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.body.columnconfigure(0, weight=1)

        body = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=22)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="half")
        body.columnconfigure(1, weight=1, uniform="half")

        self.var_name = tk.StringVar()
        self.var_repo = tk.StringVar()
        self.var_ref = tk.StringVar()
        self.var_compose = tk.StringVar(value=pcore.DEFAULT_COMPOSE_FILE)
        self.var_user = tk.StringVar()
        self.var_token = tk.StringVar()
        self.var_auto = tk.StringVar(value=AUTO_OFF)
        self.var_interval = tk.StringVar(value=pcore.DEFAULT_INTERVAL)
        self.var_force_pull = tk.BooleanVar(value=True)
        self.var_git_tls = tk.BooleanVar(value=True)
        self.var_link = tk.BooleanVar(value=True)
        self.var_free_port = tk.StringVar()
        self.var_portainer = tk.StringVar()
        self.var_endpoint = tk.StringVar()

        head = ttk.Frame(body, style="Card.TFrame")
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Neuer Stack", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=700, justify="left",
                  text="Holt eine docker-compose.yml aus einem GitHub- oder "
                       "GitLab-Repository und lässt Portainer sie "
                       "ausrollen.").grid(row=1, column=0, columnspan=2,
                                          sticky="w", pady=(3, 14))
        self._build_target(body)

        left = ttk.Frame(body, style="Card.TFrame")
        left.grid(row=3, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        right = ttk.Frame(body, style="Card.TFrame")
        right.grid(row=3, column=1, sticky="nsew", padx=(12, 0))
        right.columnconfigure(0, weight=1)
        self._build_left(left)
        self._build_right(right)

        self.footer = footer = ttk.Frame(self, style="Card.TFrame",
                                         padding=(22, 12, 22, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.note = ttk.Label(footer, style="Hint.TLabel", text="")
        self.note.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=1, padx=(0, 8))
        self.deploy_button = ttk.Button(footer, text="Stack deployen",
                                        style="Accent.TButton",
                                        command=self._go)
        self.deploy_button.grid(row=0, column=2)

        self.apply_theme(colors)
        self.refresh_target()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        ui._fit_dialog(self, app, self.scroll, self.footer, floor=820)

    # -- the three blocks --------------------------------------------------

    def _build_target(self, body):
        """Where this stack is going: which Portainer, which environment.

        Both are pickers rather than a sentence: with more than one Docker host
        around, the last thing anybody wants is to find out afterwards that the
        stack went to the other one.
        """
        card = tk.Frame(body, bg=self.app.colors["surface2"], padx=14, pady=10)
        card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        card.columnconfigure(3, weight=1)
        ttk.Label(card, text="Deployen auf", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        self.portainer_box = ttk.Combobox(card, textvariable=self.var_portainer,
                                          state="readonly", width=22,
                                          style="Card.TCombobox")
        self.portainer_box.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.portainer_box.bind(
            "<<ComboboxSelected>>",
            lambda _e: self.app.switch_portainer(self.var_portainer.get()))
        self.endpoint_box = ttk.Combobox(card, textvariable=self.var_endpoint,
                                         state="readonly", width=22,
                                         style="Card.TCombobox")
        self.endpoint_box.grid(row=0, column=2, sticky="w")
        self.endpoint_box.bind("<<ComboboxSelected>>",
                               lambda _e: self.tab.choose_endpoint(
                                   self.var_endpoint.get()))

    def _build_left(self, outer):
        rows = itertools.count()
        for label, var, hint in (
                ("Name des Stacks", self.var_name,
                 "Kleinbuchstaben, wie bei Portainer — z.B. nextcloud"),
                ("Repository", self.var_repo,
                 "https://github.com/… oder https://gitlab.com/…"),
                ("Branch oder Tag", self.var_ref,
                 "leer = der Standardbranch des Repositories"),
                ("Datei im Repository", self.var_compose, "")):
            ttk.Label(outer, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(8, 3))
            ttk.Entry(outer, textvariable=var, style="Card.TEntry").grid(
                row=next(rows), column=0, sticky="ew")
            if hint:
                ttk.Label(outer, text=hint, style="Hint.TLabel").grid(
                    row=next(rows), column=0, sticky="w", pady=(2, 0))

        head = ttk.Frame(outer, style="Card.TFrame")
        head.grid(row=next(rows), column=0, sticky="ew", pady=(14, 3))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Umgebungsvariablen",
                  style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.env_button = ttk.Button(head, text="aus dem Repository",
                                     style="Del.TButton",
                                     command=self._read_repository)
        self.env_button.grid(row=0, column=1, sticky="e")
        ui.Tooltip(self.env_button,
                   "Liest die Compose-Datei und eine .env daneben und trägt "
                   "ein, was der Stack braucht — dann sind nur noch die Werte "
                   "anzupassen")
        self.env_text = tk.Text(outer, height=14, wrap="none", bd=0,
                                highlightthickness=1, padx=8, pady=6,
                                font=self.app.font_mono)
        env_row = next(rows)
        self.env_text.grid(row=env_row, column=0, sticky="nsew")
        outer.rowconfigure(env_row, weight=1)  # the field that may grow
        ttk.Label(outer, style="Hint.TLabel", wraplength=360, justify="left",
                  text="Eine Zeile je Variable, KEY=wert — genau wie im "
                       "Textfeld von Portainer.").grid(row=next(rows), column=0,
                                                       sticky="w", pady=(2, 0))
        self._build_ports(outer, rows)

    def _build_ports(self, outer, rows):
        """Which host port this stack may take -- and which are gone.

        A published port belongs to the whole Docker host, not to the stack
        that asks for it, so the number that goes into a variable up there has
        to be one nothing else answers on. Guessing it is what makes a first
        stack fail, and the answer is already in the window: the environment
        was read a moment ago.
        """
        self.ports_card = tk.Frame(outer, bg=self.app.colors["surface2"],
                                   padx=12, pady=10)
        self.ports_card.grid(row=next(rows), column=0, sticky="ew", pady=(12, 0))
        self.ports_card.columnconfigure(2, weight=1)
        ttk.Label(self.ports_card, text="Freie Host-Ports",
                  style="Switch.TLabel").grid(row=0, column=0, columnspan=3,
                                              sticky="w")
        self.ports_hint = ttk.Label(self.ports_card, style="RowHint.TLabel",
                                    wraplength=330, justify="left", text="")
        self.ports_hint.grid(row=1, column=0, columnspan=3, sticky="w",
                             pady=(2, 8))
        self.port_box = ttk.Combobox(self.ports_card,
                                     textvariable=self.var_free_port,
                                     state="readonly", width=8,
                                     style="Card.TCombobox")
        self.port_box.grid(row=2, column=0, sticky="w")
        self.port_button = ttk.Button(self.ports_card, text="einsetzen",
                                      style="Del.TButton",
                                      command=self._insert_port)
        self.port_button.grid(row=2, column=1, sticky="w", padx=(8, 0))
        ui.Tooltip(self.port_button,
                   "Schreibt die Zahl an die Stelle, an der oben im Feld der "
                   "Cursor steht")

    def _insert_port(self):
        """Put the chosen number where the cursor stands in the variables.

        Only where somebody put it: without a click in the field the cursor is
        still at the very top, and a number dropped in front of the first line
        would be a riddle rather than a help. Then it goes at the end, where
        anything typed next would have gone anyway.
        """
        port = self.var_free_port.get()
        if not port:
            return
        try:
            typing = self.focus_get() is self.env_text
        except KeyError:  # Tk knows no widget under that name any more
            typing = False
        # "end" is behind the newline every Text keeps at the bottom, so the
        # number would land on a line of its own -- one character earlier is
        # the end of the last line somebody wrote
        self.env_text.insert("insert" if typing else "end-1c", port)
        self.env_text.focus_set()

    def _build_right(self, outer):
        rows = itertools.count()
        ttk.Label(outer, text="Privates Repository", style="Group.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(8, 0))
        ttk.Label(outer, style="Hint.TLabel", wraplength=360, justify="left",
                  text="Nur ausfüllen, wenn das Repository nicht öffentlich "
                       "ist. Als Benutzer der eigene Anmeldename, als Passwort "
                       "ein Token — GitHub und GitLab nehmen das eigentliche "
                       "Passwort dafür nicht mehr an. Die Angaben gehen an "
                       "Portainer und werden hier nicht "
                       "gespeichert.").grid(row=next(rows), column=0,
                                            sticky="w", pady=(3, 6))
        for label, var, secret in (("Benutzer", self.var_user, False),
                                   ("Passwort oder Token", self.var_token, True)):
            ttk.Label(outer, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(6, 3))
            ttk.Entry(outer, textvariable=var, style="Card.TEntry",
                      show="•" if secret else "").grid(row=next(rows), column=0,
                                                       sticky="ew")
        ttk.Label(outer, style="Hint.TLabel", wraplength=360, justify="left",
                  text="Lesen genügt. Bei einem GitHub Fine-grained token: "
                       "Repository access → Only select repositories → dieses "
                       "eine, dann Permissions → Repository permissions → "
                       "Contents auf Read-only. Bei GitLab: Scope "
                       "read_repository.").grid(row=next(rows), column=0,
                                                sticky="w", pady=(6, 0))
        links = ttk.Frame(outer, style="Card.TFrame")
        links.grid(row=next(rows), column=0, sticky="w", pady=(4, 0))
        ui.link_label(links, self.app.colors, "GitHub-Token anlegen",
                      GITHUB_TOKEN_URL,
                      style="CardLink.TLabel").grid(row=0, column=0)
        ui.link_label(links, self.app.colors, "GitLab-Token anlegen",
                      GITLAB_TOKEN_URL,
                      style="CardLink.TLabel").grid(row=0, column=1,
                                                    padx=(14, 0))
        ttk.Checkbutton(outer, text="TLS-Zertifikat des Git-Servers prüfen",
                        variable=self.var_git_tls,
                        style="Card.TCheckbutton").grid(row=next(rows), column=0,
                                                        sticky="w", pady=(8, 0))

        ttk.Separator(outer, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=16)

        ttk.Label(outer, text="Automatisch aktualisieren",
                  style="Group.TLabel").grid(row=next(rows), column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=360, justify="left",
                  text="Portainer sieht selbst im Repository nach und rollt "
                       "Änderungen aus.").grid(row=next(rows), column=0,
                                               sticky="w", pady=(3, 6))
        self.auto_box = ttk.Combobox(outer, textvariable=self.var_auto,
                                     values=list(AUTO_MODES), state="readonly",
                                     style="Card.TCombobox")
        self.auto_box.grid(row=next(rows), column=0, sticky="ew")
        self.auto_box.bind("<<ComboboxSelected>>", lambda _e: self._auto_changed())

        self.auto_extra = ttk.Frame(outer, style="Card.TFrame")
        self.auto_extra.grid(row=next(rows), column=0, sticky="ew")
        self.auto_extra.columnconfigure(0, weight=1)
        self.interval_label = ttk.Label(self.auto_extra, text="Abstand",
                                        style="FieldLabel.TLabel")
        self.interval_label.grid(row=0, column=0, sticky="w", pady=(8, 3))
        self.interval_entry = ttk.Entry(self.auto_extra,
                                        textvariable=self.var_interval,
                                        style="Card.TEntry")
        self.interval_entry.grid(row=1, column=0, sticky="ew")
        self.interval_hint = ttk.Label(self.auto_extra, style="Hint.TLabel",
                                       text="z.B. 5m, 30m oder 24h")
        self.interval_hint.grid(row=2, column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(self.auto_extra,
                        text="dabei die Images neu herunterladen",
                        variable=self.var_force_pull,
                        style="Card.TCheckbutton").grid(row=3, column=0,
                                                        sticky="w", pady=(8, 0))
        self._auto_changed()

        ttk.Separator(outer, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=16)

        ttk.Checkbutton(outer, text="danach den Weg über HAProxy anbieten",
                        variable=self.var_link,
                        style="Card.TCheckbutton").grid(row=next(rows), column=0,
                                                        sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=360, justify="left",
                  text="Sobald der Stack läuft, wird für den ersten "
                       "veröffentlichten Port ein HAProxy-Eintrag "
                       "vorgeschlagen.").grid(row=next(rows), column=0,
                                              sticky="w", pady=(2, 0))

    def _auto_changed(self):
        mode = self.var_auto.get()
        if mode == AUTO_OFF:
            self.auto_extra.grid_remove()
            return
        self.auto_extra.grid()
        showing = mode == AUTO_INTERVAL
        for widget in (self.interval_label, self.interval_entry,
                       self.interval_hint):
            widget.grid() if showing else widget.grid_remove()

    # -- what the tab asks for ---------------------------------------------

    def refresh_target(self):
        """Say again where this would go -- after a switch, or a reload."""
        names = self.tab.portainer_names()
        self.portainer_box.configure(values=names,
                                     state="readonly" if len(names) > 1
                                     else "disabled")
        self.var_portainer.set(self.app.active.get("portainer", ""))
        endpoints = self.tab.endpoint_names()
        self.endpoint_box.configure(values=endpoints,
                                    state="readonly" if len(endpoints) > 1
                                    else "disabled")
        self.var_endpoint.set((self.tab.state or {}).get("endpoint", {}).get(
            "name", ""))
        self.refresh_ports()

    def refresh_ports(self):
        """Say again what is free and what is gone on the chosen environment."""
        free = [str(port) for port in self.tab.free_ports()]
        self.port_box.configure(values=free,
                                state="readonly" if free else "disabled")
        self.port_button.configure(state="normal" if free else "disabled")
        if self.var_free_port.get() not in free:
            self.var_free_port.set(free[0] if free else "")
        self.ports_hint.configure(text=self._ports_text())

    def _ports_text(self):
        """What stands in the way, in numbers -- the first few of them."""
        if not self.tab.connected:
            return ("Erst nach dem Verbinden bekannt — dann steht hier, was "
                    f"{self.tab.target_text()} schon belegt.")
        taken = self.tab.taken_ports()
        if not taken:
            return (f"Auf {self.tab.target_text()} veröffentlicht gerade kein "
                    f"Container einen Port.")
        shown = ", ".join(str(port) for port in taken[:8])
        if len(taken) > 8:
            shown += f" … (+{len(taken) - 8})"
        return (f"Belegt auf {self.tab.target_text()}: {shown}. Die Liste "
                f"lässt diese aus.")

    def fill_in(self, preset):
        """Take up one entry of the collection: repository, path, credentials.

        The name is offered as the catalog spells it but lowercased, because
        that is what it becomes in Portainer anyway. Everything stays editable
        -- this is a starting point, not a decision.
        """
        for var, key in ((self.var_name, "name"),
                         (self.var_repo, "repository"),
                         (self.var_ref, "reference"),
                         (self.var_user, "username"),
                         (self.var_token, "password")):
            value = str(preset.get(key, "") or "")
            if value:
                var.set(value.lower() if key == "name" else value)
        self.var_compose.set(preset.get("compose_file")
                             or pcore.DEFAULT_COMPOSE_FILE)
        note = str(preset.get("description", "") or "")
        self.note.configure(text=note[:120] + ("…" if len(note) > 120 else ""))
        self.lift()
        self.focus_set()

    def busy_buttons(self):
        return self.deploy_button, self.env_button

    def env_value(self):
        return self.env_text.get("1.0", "end")

    def set_env(self, text):
        """Replace the block -- used when a value had to be changed in place."""
        self.env_text.delete("1.0", "end")
        self.env_text.insert("1.0", text)
        self.env_text.see("end")

    def add_env(self, block):
        """Append what the repository had to say, and say how much that was."""
        if self.env_text.get("1.0", "end").strip():
            self.env_text.insert("end", "\n")
        self.env_text.insert("end", block)
        self.env_text.see("end")  # what was just added is what one wants to see
        return sum(1 for line in block.splitlines()
                   if line and not line.startswith("#"))

    def apply_theme(self, colors):
        self.colors = colors
        self.configure(bg=colors["bg"])
        self.scroll.apply_theme(colors)
        self.ports_card.configure(bg=colors["surface2"])
        self.env_text.configure(bg=colors["surface2"], fg=colors["text"],
                                insertbackground=colors["text"],
                                selectbackground=colors["accent_soft"],
                                highlightbackground=colors["border"],
                                highlightcolor=colors["accent"])

    def values(self):
        mode = {AUTO_OFF: "off", AUTO_INTERVAL: "interval",
                AUTO_WEBHOOK: "webhook"}[self.var_auto.get()]
        return {
            "name": self.var_name.get().strip(),
            "repository": self.var_repo.get().strip(),
            "reference": self.var_ref.get().strip(),
            "compose_file": self.var_compose.get().strip(),
            "username": self.var_user.get().strip(),
            "password": self.var_token.get(),
            "skip_tls_verify": not self.var_git_tls.get(),
            "env_text": self.env_value(),
            "auto_mode": mode,
            "interval": self.var_interval.get(),
            "force_pull": self.var_force_pull.get(),
            "link": self.var_link.get(),
        }

    def _read_repository(self):
        self.tab._load_env(self.values())

    def _go(self):
        self.tab._deploy(self.values())


class RedeployDialog(tk.Toplevel):
    """What should happen on the way: fresh images, and what about leftovers."""

    def __init__(self, parent, colors, stack):
        super().__init__(parent)
        self.title("Neu deployen")
        self.result = None
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text=stack["name"], style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        source = stack["git"]["url"] if stack["git"] \
            else "aus der bei Portainer hinterlegten Compose-Datei"
        ttk.Label(body, text=source, style="Hint.TLabel", wraplength=380,
                  justify="left").grid(row=next(rows), column=0, sticky="w",
                                       pady=(3, 14))

        self.pull = tk.BooleanVar(value=True)
        self.prune = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Images neu herunterladen (Update)",
                        variable=self.pull, style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=380, justify="left",
                  text="Ohne Haken werden dieselben Images noch einmal "
                       "gestartet — die Container sind dann neu, die Software "
                       "darin nicht.").grid(row=next(rows), column=0, sticky="w",
                                            pady=(2, 10))
        ttk.Checkbutton(body, text="Container entfernen, die nicht mehr in der "
                                   "Compose-Datei stehen",
                        variable=self.prune, style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w")

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        if stack["git"] and stack["git"]["authenticated"]:
            ttk.Separator(body, orient="horizontal").grid(
                row=next(rows), column=0, sticky="ew", pady=14)
            ttk.Label(body, text="Privates Repository", style="Group.TLabel").grid(
                row=next(rows), column=0, sticky="w")
            ttk.Label(body, style="Hint.TLabel", wraplength=380, justify="left",
                      text="Leer lassen — Portainer benutzt dann die "
                           "Zugangsdaten, die es für diesen Stack schon "
                           "gespeichert hat.").grid(row=next(rows), column=0,
                                                    sticky="w", pady=(3, 6))
            for label, var, secret in (("Benutzer", self.username, False),
                                       ("Passwort oder Token", self.password,
                                        True)):
                ttk.Label(body, text=label, style="FieldLabel.TLabel").grid(
                    row=next(rows), column=0, sticky="w", pady=(6, 3))
                ttk.Entry(body, textvariable=var, style="Card.TEntry",
                          show="•" if secret else "").grid(row=next(rows),
                                                           column=0, sticky="ew")

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=0, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Neu deployen", style="Accent.TButton",
                   command=self._go).grid(row=0, column=1)

        self.bind("<Return>", lambda _e: self._go())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _centre(self, parent)
        self.grab_set()

    def _go(self):
        self.result = {"pull": self.pull.get(), "prune": self.prune.get(),
                       "username": self.username.get().strip(),
                       "password": self.password.get()}
        self.destroy()


class CatalogDialog(tk.Toplevel):
    """What there is to deploy, in three lists: known, kept, and one's own.

    The point of the window is the second click: pick a line, and the deploy
    form opens with the repository, the path and -- for an own repository --
    the account's user name and token already in it.
    """

    # the curated list is fetched at most once a day; it is a file of a few
    # kilobytes that changes when somebody adds a stack to it, not by the hour
    MAX_AGE = 24 * 3600

    def __init__(self, app, tab):
        super().__init__(app)
        self.app = app
        self.tab = tab
        self.colors = colors = app.colors
        self.known = []
        self.own = []
        self.own_from = ""  # which account the list in hand belongs to
        self.title("Katalog")
        self.transient(app)
        self.configure(bg=colors["bg"])
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        head = ttk.Frame(self, style="Card.TFrame", padding=(20, 16, 20, 0))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Stacks zum Deployen", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")

        picks = ttk.Frame(head, style="Card.TFrame")
        picks.grid(row=0, column=1, sticky="e")
        self.var_source = tk.StringVar(value=KNOWN)
        self.source_box = ttk.Combobox(picks, textvariable=self.var_source,
                                       state="readonly", width=18,
                                       values=[KNOWN, FAVOURITES, OWN],
                                       style="Card.TCombobox")
        self.source_box.grid(row=0, column=0, padx=(0, 6))
        self.source_box.bind("<<ComboboxSelected>>",
                             lambda _e: self._source_changed())
        self.var_account = tk.StringVar()
        self.account_box = ttk.Combobox(picks, textvariable=self.var_account,
                                        state="readonly", width=16,
                                        style="Card.TCombobox")
        self.account_box.grid(row=0, column=1, padx=(0, 6))
        self.account_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._load_own(force=True))
        self.account_box.grid_remove()
        self.reload_button = ttk.Button(picks, text="↻", width=3,
                                        style="Tool.TButton",
                                        command=self._refresh)
        self.reload_button.grid(row=0, column=2)
        ui.Tooltip(self.reload_button, "Die Liste neu holen")

        self.hint = ttk.Label(head, style="Hint.TLabel", wraplength=560,
                              justify="left", text="")
        self.hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 12))

        self.listing = ui.ScrollFrame(self, colors)
        self.listing.grid(row=1, column=0, sticky="nsew", padx=20)

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.add_button = ttk.Button(footer, text="＋ Eigener Favorit",
                                     style="Del.TButton",
                                     command=self._new_favourite)
        self.add_button.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Schließen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=2, sticky="e")

        self.geometry("720x620")
        self.minsize(560, 420)
        self.bind("<Escape>", lambda _e: self.destroy())
        _centre(self, app)
        self._fill_accounts()
        self._source_changed()

    # -- what is on offer --------------------------------------------------

    def busy_buttons(self):
        return self.add_button, self.reload_button

    def apply_theme(self, colors):
        self.colors = colors
        self.configure(bg=colors["bg"])
        self.listing.apply_theme(colors)
        self.render()

    def _fill_accounts(self):
        names = [entry.get("name", "?") for entry in cat.accounts_of(self.app.systems)]
        self.account_box.configure(values=names)
        if self.var_account.get() not in names:
            self.var_account.set(names[0] if names else "")
        return names

    def _account(self):
        for entry in cat.accounts_of(self.app.systems):
            if entry.get("name") == self.var_account.get():
                return entry
        return {}

    def _source_changed(self):
        source = self.var_source.get()
        if source == OWN and self._fill_accounts():
            self.account_box.grid()
        else:
            self.account_box.grid_remove()
        if source == KNOWN and not self.known:
            self._load_known()
            return
        if source == OWN:
            self._load_own()
            return
        self.render()

    def _refresh(self):
        source = self.var_source.get()
        if source == KNOWN:
            self._load_known(force=True)
        elif source == OWN:
            self._load_own(force=True)
        else:
            self.render()

    def _load_known(self, force=False):
        """The curated list -- from the cache unless it is old or refused."""
        cached = self.app.prefs.get("catalog") or {}
        fresh = (time.time() - float(cached.get("fetched") or 0)) < self.MAX_AGE
        if not force and fresh and cached.get("stacks"):
            self.known = [entry for entry in
                          (cat.clean_entry(raw) for raw in cached["stacks"])
                          if entry]
            self.render()
            return
        self.app.run_async(lambda _report: cat.fetch_catalog(),
                           self._known_loaded, on_error=self._failed,
                           activity="hole den Katalog …")

    def _known_loaded(self, entries):
        self.app.set_busy(False)
        self.known = entries
        self.app.prefs["catalog"] = {"fetched": int(time.time()),
                                     "stacks": entries}
        ui.save_prefs(self.app.prefs)
        if self.winfo_exists():
            self.render()

    def _load_own(self, force=False):
        account = self._account()
        if not account:
            self.own, self.own_from = [], ""
            self.render()
            return
        if not force and self.own_from == account.get("name"):
            self.render()
            return
        self.app.run_async(lambda _report: cat.own_repos(account),
                           self._own_loaded, on_error=self._failed,
                           activity=f"lese die Repositories von "
                                    f"{account.get('name', '')} …")

    def _own_loaded(self, entries):
        self.app.set_busy(False)
        self.own = entries
        self.own_from = self._account().get("name", "")
        if self.winfo_exists():
            self.render()

    def _failed(self, _error):
        # the window already wrote the reason into the log at the bottom; for
        # the curated list there is still the copy that came with the program
        if self.var_source.get() == KNOWN and not self.known:
            self.known = cat.local_catalog()
        if self.winfo_exists():
            self.render()

    def entries(self):
        source = self.var_source.get()
        if source == FAVOURITES:
            return list(self.app.favorites)
        return list(self.own if source == OWN else self.known)

    # -- drawing -----------------------------------------------------------

    def render(self):
        self.listing.clear()
        body = self.listing.body
        body.columnconfigure(0, weight=1)
        source = self.var_source.get()
        self.hint.configure(text=self._hint_text())
        entries = self.entries()
        if not entries:
            ttk.Label(body, style="Hint.TLabel", wraplength=520,
                      justify="left", text=self._empty_text()).grid(
                row=0, column=0, sticky="w", pady=(8, 0))
            return
        for index, entry in enumerate(entries):
            self._row(body, entry, source).grid(row=index, column=0,
                                                sticky="ew", pady=(0, 6))

    def _hint_text(self):
        source = self.var_source.get()
        if source == KNOWN:
            return ("Gepflegt im Repository dieses Programms — Stacks, deren "
                    "Compose-Datei an der angegebenen Stelle liegt. ★ legt "
                    "einen davon zu den eigenen Favoriten.")
        if source == FAVOURITES:
            return ("Selbst hinterlegt, in derselben Datei wie die Systeme. "
                    "Kein Zugangsdatum steht hier drin — der Token kommt beim "
                    "Deployen aus dem passenden Git-Konto.")
        account = self._account()
        return (f"Alles, was der Token von {account.get('name')} sehen darf, "
                f"neu zuerst. Beim Deployen werden Benutzer und Token dieses "
                f"Kontos eingesetzt." if account else
                "Für die eigenen Repositories fehlt ein Git-Konto.")

    def _empty_text(self):
        source = self.var_source.get()
        if source == FAVOURITES:
            return ("Noch nichts gemerkt. „＋ Eigener Favorit“ unten legt "
                    "einen an, und ★ an einer der anderen Listen übernimmt "
                    "einen von dort.")
        if source == OWN and not self._account():
            return ("Unter ⚙ ein Git-Konto anlegen — Adresse, Benutzername "
                    "und ein Token, das lesen darf. Dann steht hier, was es "
                    "sehen kann.")
        return "Nichts gefunden. ↻ versucht es noch einmal."

    def _row(self, parent, entry, source):
        card = tk.Frame(parent, bg=self.colors["surface2"], padx=12, pady=10)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=entry["name"], style="Host.TLabel").grid(
            row=0, column=0, sticky="w")
        if entry.get("private"):
            ttk.Label(card, text="privat", style="BadgeMuted.TLabel").grid(
                row=0, column=1, padx=(8, 0))

        buttons = ttk.Frame(card, style="Sub.TFrame")
        buttons.grid(row=0, column=2, rowspan=3, padx=(10, 0))
        ttk.Button(buttons, text="Deployen", style="Accent.TButton",
                   command=lambda e=entry: self._deploy(e)).grid(row=0, column=0)
        if source == FAVOURITES:
            ttk.Button(buttons, text="Ändern", style="Del.TButton",
                       command=lambda e=entry: self._edit_favourite(e)).grid(
                row=0, column=1, padx=(6, 0))
            ttk.Button(buttons, text="Entfernen", style="Del.TButton",
                       command=lambda e=entry: self._drop_favourite(e)).grid(
                row=0, column=2, padx=(6, 0))
        else:
            kept = cat.is_favourite(self.app.favorites, entry)
            star = ttk.Button(buttons, text="★" if kept else "☆", width=3,
                              style="Del.TButton",
                              command=lambda e=entry: self._keep(e))
            star.grid(row=0, column=1, padx=(6, 0))
            ui.Tooltip(star, "Steht schon unter den Favoriten" if kept
                       else "Zu den eigenen Favoriten legen")

        ttk.Label(card, text=entry.get("description") or "keine Beschreibung",
                  style="RowHint.TLabel", wraplength=430,
                  justify="left").grid(row=1, column=0, columnspan=2,
                                       sticky="w", pady=(2, 0))
        where = entry["repository"]
        if entry.get("reference"):
            where += f"  ({entry['reference']})"
        if entry.get("compose_file"):
            where += f"  ·  {entry['compose_file']}"
        ttk.Label(card, text=where, style="Target.TLabel", wraplength=430,
                  justify="left").grid(row=2, column=0, columnspan=2,
                                       sticky="w", pady=(2, 0))
        return card

    # -- what the buttons do -----------------------------------------------

    def _deploy(self, entry):
        self.tab.deploy_entry(entry)

    def _keep(self, entry):
        if cat.is_favourite(self.app.favorites, entry):
            self.var_source.set(FAVOURITES)
            self._source_changed()
            return
        self.app.remember_favourite(entry)
        self.render()

    def _new_favourite(self):
        self._edit_favourite({})

    def _edit_favourite(self, entry):
        taken = [known["name"] for known in self.app.favorites
                 if known["name"] != entry.get("name")]
        dialog = FavouriteDialog(self, self.colors, entry, taken)
        self.wait_window(dialog)
        if dialog.result:
            self.app.remember_favourite(dialog.result, entry.get("name", ""))
            self.var_source.set(FAVOURITES)
            self._source_changed()

    def _drop_favourite(self, entry):
        if messagebox.askyesno(
                ui.APP_TITLE,
                f"„{entry['name']}“ aus den Favoriten entfernen?\n\nEs wird "
                "nur der Eintrag gelöscht; ein laufender Stack bleibt davon "
                "unberührt.", icon="warning", parent=self):
            self.app.forget_favourite(entry["name"])
            self.render()


class FavouriteDialog(tk.Toplevel):
    """One entry of one's own: what it is called, and where it comes from."""

    def __init__(self, parent, colors, entry, taken_names=()):
        super().__init__(parent)
        self.colors = colors
        self.result = None
        self.taken = set(taken_names)
        self.title("Favorit bearbeiten" if entry.get("name")
                   else "Favorit anlegen")
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()
        ttk.Label(body, text="Favorit", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="Ein Repository, das du wieder deployen willst. "
                       "Zugangsdaten kommen nicht hier hinein — die holt das "
                       "Programm beim Deployen aus dem Git-Konto, dessen "
                       "Adresse zu diesem Repository passt.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 12))

        self.vars = {}
        for label, key, hint in (
                ("Name", "name", "wie der Stack heißen soll, z.B. immich"),
                ("Beschreibung", "description", "wofür er gut ist"),
                ("Repository", "repository", "https://github.com/… "),
                ("Branch oder Tag", "reference",
                 "leer = der Standardbranch"),
                ("Datei im Repository", "compose_file",
                 f"leer = {pcore.DEFAULT_COMPOSE_FILE}")):
            self.vars[key] = tk.StringVar(value=str(entry.get(key, "") or ""))
            ttk.Label(body, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(8, 3))
            ttk.Entry(body, textvariable=self.vars[key], width=46,
                      style="Card.TEntry").grid(row=next(rows), column=0,
                                                sticky="ew")
            ttk.Label(body, text=hint, style="Hint.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(2, 0))

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=0, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Speichern", style="Accent.TButton",
                   command=self._go).grid(row=0, column=1)

        self.bind("<Return>", lambda _e: self._go())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _centre(self, parent)
        self.grab_set()

    def _go(self):
        values = {key: var.get().strip() for key, var in self.vars.items()}
        entry = cat.clean_entry(values)
        if not entry:
            messagebox.showwarning(
                "Unvollständig",
                "Ein Favorit braucht einen Namen und ein Repository, das mit "
                "http:// oder https:// anfängt — so klont Portainer es.",
                parent=self)
            return
        if entry["name"] in self.taken:
            messagebox.showwarning(
                "Name schon vergeben",
                f"Es gibt bereits einen Favoriten namens „{entry['name']}“.",
                parent=self)
            return
        self.result = entry
        self.destroy()


class RemoveDialog(tk.Toplevel):
    """What goes when this stack goes -- and what to do about the way in.

    Deleting a stack in Portainer leaves the HAProxy side untouched: the rule
    keeps pointing at a port nothing answers on, and the name keeps resolving
    to it. So the hosts that lead here are listed by name, and taking them with
    it is one checkbox rather than a second round through the other tab.
    """

    def __init__(self, parent, colors, stack, hosts, note=""):
        super().__init__(parent)
        self.title("Stack löschen")
        self.colors = colors
        self.result = None
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text=f"{stack['name']} löschen", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                  text="Portainer stoppt die Container und entfernt den Stack "
                       "samt seinen Netzwerken. Benannte Volumes bleiben "
                       "liegen — die Daten sind also nicht weg.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 12))

        listed = [f"• {container['name']}"
                  for container in stack["containers"][:8]]
        rest = len(stack["containers"]) - len(listed)
        if rest > 0:
            listed.append(f"• … und {rest} weitere")
        if not listed:
            listed = ["• kein laufender Container"]
        ports = ", ".join(str(port["host_port"]) for port in stack["ports"])
        card = tk.Frame(body, bg=colors["surface2"], padx=12, pady=10)
        card.grid(row=next(rows), column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="\n".join(listed), style="Target.TLabel",
                  justify="left").grid(row=0, column=0, sticky="w")
        if ports:
            ttk.Label(card, style="RowHint.TLabel", wraplength=400,
                      justify="left",
                      text=f"Freigegebene Host-Ports: {ports}").grid(
                row=1, column=0, sticky="w", pady=(6, 0))

        self.haproxy = tk.BooleanVar(value=bool(hosts))
        ttk.Separator(body, orient="horizontal").grid(row=next(rows), column=0,
                                                      sticky="ew", pady=14)
        if hosts:
            names = ", ".join(rule["target"] for rule in hosts)
            ttk.Checkbutton(body, variable=self.haproxy,
                            style="Card.TCheckbutton",
                            text="die HAProxy-Einträge dazu ebenfalls "
                                 "entfernen").grid(row=next(rows), column=0,
                                                   sticky="w")
            ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                      text=f"Betrifft {names} — Real Server, Backend Pool, "
                           "Condition und Rule, und den DNS-Eintrag, wenn ein "
                           "AdGuard gewählt ist. Ohne Haken bleiben sie "
                           "stehen und zeigen ins Leere.").grid(
                row=next(rows), column=0, sticky="w", pady=(2, 0))
        else:
            ttk.Label(body, style="Hint.TLabel", wraplength=420, justify="left",
                      text=note or "Auf die Ports dieses Stacks zeigt kein "
                                   "HAProxy-Eintrag — es bleibt nichts "
                                   "zurück.").grid(row=next(rows), column=0,
                                                   sticky="w")

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=0, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Löschen", style="Del.TButton",
                   command=self._go).grid(row=0, column=1)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        _centre(self, parent)
        self.grab_set()

    def _go(self):
        self.result = {"haproxy": bool(self.haproxy.get())}
        self.destroy()


class LinkDialog(tk.Toplevel):
    """The bridge between the two tabs: a container port becomes a host name."""

    def __init__(self, parent, colors, suggestion, target, port):
        super().__init__(parent)
        self.title("Über HAProxy erreichbar machen")
        self.app = parent
        self.result = None
        self.transient(parent)
        self.configure(bg=colors["bg"])
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self, style="Card.TFrame", padding=20)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        rows = itertools.count()

        ttk.Label(body, text="Neuer Host", style="H2.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(body, style="Hint.TLabel", wraplength=380, justify="left",
                  text=f"Port {port['host_port']} auf {target} bekommt einen "
                       f"Namen und wird über den Public Service erreichbar.").grid(
            row=next(rows), column=0, sticky="w", pady=(3, 14))

        self.var_target = tk.StringVar(value=suggestion)
        self.var_ip = tk.StringVar(value=target)
        self.var_port = tk.StringVar(value=str(port["host_port"]))
        self.var_base = tk.StringVar(value=parent.var_base.get())
        self.var_frontend = tk.StringVar(value=parent.var_frontend.get())
        self.var_healthcheck = tk.StringVar(value=NO_HEALTHCHECK)
        self.var_ssl = tk.BooleanVar(value=False)
        self.var_dns = tk.BooleanVar(value=bool(parent.adguard))

        ttk.Label(body, text="Name", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(0, 3))
        entry = ttk.Entry(body, textvariable=self.var_target, style="Card.TEntry")
        entry.grid(row=next(rows), column=0, sticky="ew")

        ttk.Label(body, text="Basis-Domain", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(10, 3))
        bases = [ui.NO_BASE] + [entry["domain"] for entry in parent.domains]
        if self.var_base.get() not in bases:
            self.var_base.set(ui.NO_BASE)
        ttk.Combobox(body, textvariable=self.var_base, values=bases,
                     state="readonly", style="Card.TCombobox").grid(
            row=next(rows), column=0, sticky="ew")

        self.preview = ttk.Label(body, style="Hint.TLabel", wraplength=380,
                                 justify="left")
        self.preview.grid(row=next(rows), column=0, sticky="w", pady=(4, 0))

        pair = ttk.Frame(body, style="Card.TFrame")
        pair.grid(row=next(rows), column=0, sticky="ew", pady=(10, 0))
        pair.columnconfigure(0, weight=3)
        pair.columnconfigure(1, weight=1)
        ttk.Label(pair, text="Ziel-IP", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 3))
        ttk.Label(pair, text="Port", style="FieldLabel.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 3))
        ttk.Entry(pair, textvariable=self.var_ip, style="Card.TEntry").grid(
            row=1, column=0, sticky="ew")
        ttk.Entry(pair, textvariable=self.var_port, style="Card.TEntry",
                  width=8).grid(row=1, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(body, text="Public Service", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(10, 3))
        names = [service["name"] for service in parent.services]
        if self.var_frontend.get() not in names:
            self.var_frontend.set(names[0] if names else "")
        ttk.Combobox(body, textvariable=self.var_frontend, values=names,
                     state="readonly", style="Card.TCombobox").grid(
            row=next(rows), column=0, sticky="ew")

        ttk.Label(body, text="Health Monitor", style="FieldLabel.TLabel").grid(
            row=next(rows), column=0, sticky="w", pady=(10, 3))
        ttk.Combobox(body, textvariable=self.var_healthcheck,
                     values=[NO_HEALTHCHECK] + list(parent.healthchecks),
                     state="readonly", style="Card.TCombobox").grid(
            row=next(rows), column=0, sticky="ew")

        ttk.Checkbutton(body, text="Der Container spricht selbst HTTPS",
                        variable=self.var_ssl, style="Card.TCheckbutton").grid(
            row=next(rows), column=0, sticky="w", pady=(12, 0))
        if parent.adguard:
            ttk.Checkbutton(body, text="Passenden DNS-Eintrag in AdGuard anlegen",
                            variable=self.var_dns,
                            style="Card.TCheckbutton").grid(row=next(rows),
                                                            column=0, sticky="w",
                                                            pady=(6, 0))

        footer = ttk.Frame(self, style="Card.TFrame", padding=(20, 12, 20, 16))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style="Card.TFrame")
        buttons.grid(row=0, column=0, sticky="e")
        ttk.Button(buttons, text="Abbrechen", style="Ghost.TButton",
                   command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Anlegen", style="Accent.TButton",
                   command=self._go).grid(row=0, column=1)

        for var in (self.var_target, self.var_base):
            var.trace_add("write", lambda *_a: self._show_name())
        self._show_name()
        self.bind("<Return>", lambda _e: self._go())
        self.bind("<Escape>", lambda _e: self.destroy())
        entry.focus_set()
        self.update_idletasks()
        _centre(self, parent)
        self.grab_set()

    def _show_name(self):
        """Say the name that will exist, the same way the first tab does."""
        base = "" if self.var_base.get() == ui.NO_BASE else self.var_base.get()
        raw = core.with_base(self.var_target.get(), base)
        host = raw.split("/", 1)[0].strip()
        full = core.build_fqdn(host, base) if host else ""
        self.preview.configure(text=f"wird zu  {full}" if full
                               else "noch kein Name")

    def _go(self):
        target = self.var_target.get().strip()
        if not target:
            messagebox.showwarning(ui.APP_TITLE, "Bitte einen Namen eintragen.",
                                   parent=self)
            return
        if not self.var_ip.get().strip():
            messagebox.showwarning(ui.APP_TITLE, "Bitte die Ziel-IP eintragen.",
                                   parent=self)
            return
        try:
            port = int(self.var_port.get().strip())
        except ValueError:
            messagebox.showwarning(ui.APP_TITLE, "Der Port muss eine Zahl sein.",
                                   parent=self)
            return
        healthcheck = self.var_healthcheck.get()
        self.result = {
            "target": target,
            "ip": self.var_ip.get().strip(),
            "port": port,
            "base_domain": "" if self.var_base.get() == ui.NO_BASE
            else self.var_base.get(),
            "frontend": self.var_frontend.get() or None,
            "healthcheck": None if healthcheck.startswith("—") else healthcheck,
            "ssl": self.var_ssl.get(),
            "dns": self.var_dns.get(),
        }
        self.destroy()


def _centre(window, parent):
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 3
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
