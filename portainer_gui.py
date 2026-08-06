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

import tkinter as tk
from tkinter import messagebox, ttk

import haproxy_gui as ui
import opnsense_haproxy as core
import portainer as pcore

AUTO_OFF = "aus"
AUTO_INTERVAL = "regelmäßig nachsehen"
AUTO_WEBHOOK = "auf Webhook warten"
AUTO_MODES = (AUTO_OFF, AUTO_INTERVAL, AUTO_WEBHOOK)

NO_HEALTHCHECK = "— keiner —"


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

        self.columnconfigure(0, weight=0, minsize=380)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_form()
        self._build_list()

    # -- layout ------------------------------------------------------------

    def _build_form(self):
        holder = ttk.Frame(self, style="Card.TFrame")
        holder.grid(row=0, column=0, sticky="nsew", padx=(18, 9), pady=(0, 9))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.form_scroll = ui.ScrollFrame(holder, self.app.colors)
        self.form_scroll.grid(row=0, column=0, sticky="nsew")
        self.form_scroll.body.columnconfigure(0, weight=1)

        outer = ttk.Frame(self.form_scroll.body, style="Card.TFrame",
                          padding=(18, 16))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="Neuer Stack", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
                  text="Holt eine docker-compose.yml aus einem GitHub- oder "
                       "GitLab-Repository und lässt Portainer sie "
                       "ausrollen.").grid(row=1, column=0, sticky="w",
                                          pady=(3, 14))

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

        rows = itertools.count(2)

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
        head.grid(row=next(rows), column=0, sticky="ew", pady=(12, 3))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Umgebungsvariablen",
                  style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.env_button = ttk.Button(head, text="aus dem Repository",
                                     style="Del.TButton", command=self._load_env)
        self.env_button.grid(row=0, column=1, sticky="e")
        ui.Tooltip(self.env_button,
                   "Liest die Compose-Datei und eine .env daneben und trägt "
                   "ein, was der Stack braucht — dann sind nur noch die Werte "
                   "anzupassen")
        self.env_text = tk.Text(outer, height=8, wrap="none", bd=0,
                                highlightthickness=1, padx=8, pady=6,
                                font=self.app.font_mono)
        self.env_text.grid(row=next(rows), column=0, sticky="ew")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
                  text="Eine Zeile je Variable, KEY=wert — genau wie im "
                       "Textfeld von Portainer.").grid(
            row=next(rows), column=0, sticky="w", pady=(2, 0))

        ttk.Separator(outer, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=14)

        ttk.Label(outer, text="Privates Repository", style="Group.TLabel").grid(
            row=next(rows), column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
                  text="Nur ausfüllen, wenn das Repository nicht öffentlich "
                       "ist. Die Angaben gehen an Portainer und werden hier "
                       "nicht gespeichert.").grid(row=next(rows), column=0,
                                                  sticky="w", pady=(3, 6))
        for label, var, secret in (("Benutzer", self.var_user, False),
                                   ("Passwort oder Token", self.var_token, True)):
            ttk.Label(outer, text=label, style="FieldLabel.TLabel").grid(
                row=next(rows), column=0, sticky="w", pady=(6, 3))
            ttk.Entry(outer, textvariable=var, style="Card.TEntry",
                      show="•" if secret else "").grid(row=next(rows), column=0,
                                                       sticky="ew")
        ttk.Checkbutton(outer, text="TLS-Zertifikat des Git-Servers prüfen",
                        variable=self.var_git_tls,
                        style="Card.TCheckbutton").grid(row=next(rows), column=0,
                                                        sticky="w", pady=(8, 0))

        ttk.Separator(outer, orient="horizontal").grid(
            row=next(rows), column=0, sticky="ew", pady=14)

        ttk.Label(outer, text="Automatisch aktualisieren",
                  style="Group.TLabel").grid(row=next(rows), column=0, sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
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
            row=next(rows), column=0, sticky="ew", pady=14)

        ttk.Checkbutton(outer,
                        text="danach den Weg über HAProxy anbieten",
                        variable=self.var_link,
                        style="Card.TCheckbutton").grid(row=next(rows), column=0,
                                                        sticky="w")
        ttk.Label(outer, style="Hint.TLabel", wraplength=320, justify="left",
                  text="Sobald der Stack läuft, wird für den ersten "
                       "veröffentlichten Port ein HAProxy-Eintrag "
                       "vorgeschlagen.").grid(row=next(rows), column=0,
                                              sticky="w", pady=(2, 12))

        buttons = ttk.Frame(outer, style="Card.TFrame")
        buttons.grid(row=next(rows), column=0, sticky="ew", pady=(4, 0))
        buttons.columnconfigure(0, weight=1)
        self.deploy_button = ttk.Button(buttons, text="Stack deployen",
                                        style="Accent.TButton",
                                        command=self._deploy)
        self.deploy_button.grid(row=0, column=0, sticky="ew")

    def _build_list(self):
        outer = ttk.Frame(self, style="Card.TFrame", padding=(16, 16, 8, 12))
        outer.grid(row=0, column=1, sticky="nsew", padx=(9, 18), pady=(0, 9))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        head = ttk.Frame(outer, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Stacks und Ports", style="H2.TLabel").grid(
            row=0, column=0, sticky="w")
        self.var_endpoint = tk.StringVar()
        self.endpoint_box = ttk.Combobox(head, textvariable=self.var_endpoint,
                                         state="readonly", width=18,
                                         style="Card.TCombobox")
        self.endpoint_box.grid(row=0, column=2, sticky="e")
        self.endpoint_box.bind("<<ComboboxSelected>>",
                               lambda _e: self._endpoint_changed())
        self.endpoint_box.grid_remove()

        ttk.Label(outer, style="Hint.TLabel",
                  text="Welche Ports nach außen offen sind — und damit die, "
                       "die HAProxy ansprechen kann.").grid(row=1, column=0,
                                                            sticky="w",
                                                            pady=(3, 12))

        self.listing = ui.ScrollFrame(outer, self.app.colors)
        self.listing.grid(row=2, column=0, sticky="nsew")

    def apply_theme(self):
        colors = self.app.colors
        self.listing.apply_theme(colors)
        self.form_scroll.apply_theme(colors)
        self.env_text.configure(bg=colors["surface2"], fg=colors["text"],
                                insertbackground=colors["text"],
                                selectbackground=colors["accent_soft"],
                                highlightbackground=colors["border"],
                                highlightcolor=colors["accent"])
        self.render()

    # -- connection --------------------------------------------------------

    def use_profile(self, profile):
        """Take up the Portainer part of the connection that was just chosen."""
        self.connected = False
        self.state = None
        self.client, self.settings = pcore.client_from_config(
            profile, insecure=getattr(self.app.args, "insecure", False))
        self.problem = self.settings.get("error", "")
        remembered = (self.app.prefs.get("portainer_endpoint") or {}).get(
            profile.get("name", ""))
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
        self.render()
        if self.last_deploy:
            self._offer_link(self.last_deploy)
            self.last_deploy = None

    def _endpoint_changed(self):
        chosen = self.var_endpoint.get()
        for entry in (self.state or {}).get("endpoints", []):
            if entry["name"] == chosen and entry["id"] != self.endpoint_id:
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
                self.problem or "Trage unter ⚙ die Adresse deines Portainers "
                                "ein, dann erscheinen hier alle Stacks mit "
                                "ihren Ports.",
                "Verbindung bearbeiten", self.app.open_settings)
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
        for index, port in enumerate(stack["ports"]):
            self._port_row(ports, port, stack["name"]).grid(
                row=index, column=0, sticky="ew", pady=(0, 2))
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
        for index, port in enumerate(container["ports"]):
            entry = {**port, "container": container["name"],
                     "service": container["name"]}
            self._port_row(ports, entry, "").grid(row=index, column=0,
                                                  sticky="ew", pady=(0, 2))
        return card

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

    def busy_buttons(self):
        """What the window switches off while something is running."""
        return self.deploy_button, self.env_button

    def _load_env(self):
        """Ask the repository what this stack expects, before deploying it."""
        if self.app.busy:
            return
        if not self.connected:
            messagebox.showinfo(ui.APP_TITLE,
                                "Bitte zuerst verbinden — das Repository wird "
                                "von Portainer gelesen, nicht von hier.")
            return
        if not self.var_repo.get().strip():
            messagebox.showwarning(ui.APP_TITLE,
                                   "Bitte die Adresse des Repositories eintragen.")
            return
        opts = argparse.Namespace(
            repository=self.var_repo.get().strip(),
            reference=self.var_ref.get().strip(),
            compose_file=self.var_compose.get().strip(),
            username=self.var_user.get().strip(),
            password=self.var_token.get(),
            skip_tls_verify=not self.var_git_tls.get(),
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

        found = result["result"]
        # what is already in the box wins: those values were typed on purpose
        try:
            taken = {entry["name"] for entry in
                     pcore.parse_env(self.env_text.get("1.0", "end"))}
        except core.UsageError:
            taken = set()
        block = self._env_block(found, taken)
        if not block:
            lines.append({"text": "= im Feld steht schon alles, was gebraucht "
                                  "wird", "level": "info"})
            self.app.write_log("Nichts zu ergänzen", lines, True)
            return
        if self.env_text.get("1.0", "end").strip():
            self.env_text.insert("end", "\n")
        self.env_text.insert("end", block)
        self.env_text.see("end")  # what was just added is what one wants to see
        added = sum(1 for line in block.splitlines()
                    if line and not line.startswith("#"))
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

    def _deploy(self):
        if self.app.busy:
            return
        if not self.connected:
            messagebox.showinfo(
                ui.APP_TITLE,
                "Bitte zuerst verbinden — ohne die Umgebung aus Portainer "
                "weiß das Programm nicht, wohin der Stack soll.")
            return
        name = self.var_name.get().strip()
        if not name:
            messagebox.showwarning(ui.APP_TITLE, "Bitte einen Namen vergeben.")
            return
        if not self.var_repo.get().strip():
            messagebox.showwarning(ui.APP_TITLE,
                                   "Bitte die Adresse des Repositories eintragen.")
            return
        if pcore.stack_name_taken(self.state, name):
            messagebox.showwarning(
                ui.APP_TITLE,
                f"Es gibt auf dieser Umgebung schon einen Stack namens "
                f"'{name}'.\n\nZum Aktualisieren „Neu deployen“ in der Liste "
                f"rechts benutzen.")
            return
        try:
            variables = pcore.parse_env(self.env_text.get("1.0", "end"))
        except core.UsageError as exc:
            messagebox.showwarning("Umgebungsvariablen", str(exc))
            return

        mode = {AUTO_OFF: "off", AUTO_INTERVAL: "interval",
                AUTO_WEBHOOK: "webhook"}[self.var_auto.get()]
        auto = pcore.auto_update_settings(mode, self.var_interval.get(),
                                          self.var_force_pull.get())
        opts = argparse.Namespace(
            endpoint_id=self.endpoint_id,
            name=name,
            repository=self.var_repo.get().strip(),
            reference=self.var_ref.get().strip(),
            compose_file=self.var_compose.get().strip(),
            env_text=pcore.env_text(variables),
            username=self.var_user.get().strip(),
            password=self.var_token.get(),
            auto_update=auto,
            skip_tls_verify=not self.var_git_tls.get(),
        )
        client = self.client
        self.app.run_async(
            lambda report: pcore.run_step(pcore.deploy, client, opts,
                                          log=ui.LiveLog(report)),
            self._deployed, activity=f"deploye {name} …")

    def _deployed(self, result):
        self.app.set_busy(False)
        lines = list(result["log"])
        if result.get("error"):
            lines.append({"text": result["error"], "level": "error"})
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
        self.last_deploy = name if self.var_link.get() else None
        self.var_name.set("")
        self.var_repo.set("")
        self.var_ref.set("")
        self.var_user.set("")
        self.var_token.set("")
        self.env_text.delete("1.0", "end")
        self.after(1200, self.reload)

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
                "erreichen ist. Trage sie unter ⚙ im Abschnitt Portainer ein.")
            return
        suggestion = port.get("service") or stack_name or ""
        dialog = LinkDialog(self.app, self.app.colors, suggestion, target, port)
        self.app.wait_window(dialog)
        if dialog.result:
            self.app.provision_host(dialog.result)


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
