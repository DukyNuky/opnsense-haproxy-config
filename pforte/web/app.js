"use strict";

/* ---------- Kleinkram ---------- */

const ICON = {
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  bang: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"><path d="M12 6v7M12 18v.01"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
};

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === false || value == null) continue;
    if (key === "class") el.className = value;
    else if (key === "html") el.innerHTML = value; // nur feste Symbole, nie Nutzerdaten
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "value" || key === "checked" || key === "disabled") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, body, method) {
  const options = { method: method || (body === undefined ? "GET" : "POST") };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  let reply;
  try {
    reply = await fetch(path, options);
  } catch (e) {
    throw new Error("Pforte läuft nicht mehr — bitte neu starten.");
  }
  const data = await reply.json().catch(() => ({}));
  if (!reply.ok) throw Object.assign(new Error(data.error || "Fehler " + reply.status), { code: data.code || "" });
  return data;
}

function toast(text) {
  const el = h("div", { class: "toast" }, text);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), 3200);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const root = () => document.getElementById("app");

/* ---------- Zustand ---------- */

const S = {
  cfg: null,       // /api/state
  ov: null,        // /api/overview
  form: { label: "", domain: "", target: "", listener: "" },
  hostFilter: "", allHosts: false, editing: null,
  update: null,    // /api/update
  wiz: null,
};

function mount(...nodes) {
  const app = root();
  app.replaceChildren(...nodes.flat().filter(Boolean));
  window.scrollTo({ top: 0 });
}

/* ---------- Kopf ---------- */

function header() {
  const profiles = S.cfg ? S.cfg.profiles : [];
  const kids = [
    h("div", { class: "brand" }, h("img", { src: "logo.svg", alt: "" }), "Pforte"),
    h("div", { class: "spacer" }),
  ];
  if (S.update && S.update.available) {
    kids.push(h("button", { class: "pill update", title: "Neue Version verfügbar", onclick: renderUpdate }, "Update " + S.update.version));
  }
  if (profiles.length) {
    const name = S.cfg.active;
    kids.push(h("button", { class: "pill", onclick: profileMenu }, name, h("span", { html: ICON.chevron })));
    kids.push(h("button", { class: "icon-btn", title: "Einstellungen", html: ICON.gear, onclick: () => startWizard({ edit: S.cfg.profiles.find((p) => p.name === S.cfg.active) }) }));
  }
  return h("header", {}, kids);
}

function profileMenu(event) {
  const old = document.getElementById("menu");
  if (old) return old.remove();
  const pill = event.currentTarget;
  const menu = h("div", { id: "menu", class: "combo" });
  const list = h("div", { class: "list", style: "left:auto;right:0;min-width:240px;top:46px" });
  for (const p of S.cfg.profiles) {
    list.append(h("div", { class: "item" + (p.name === S.cfg.active ? " on" : ""), onclick: async () => {
      S.cfg = await api("/api/active", { name: p.name });
      loadMain();
    } }, h("span", {}, p.name)));
  }
  list.append(h("div", { class: "item", onclick: () => startWizard({ add: true }) }, h("span", {}, "+ Weitere OPNsense")));
  menu.append(list);
  pill.parentElement.style.position = "relative";
  pill.parentElement.append(menu);
  setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }), 0);
}

/* ---------- Updates ---------- */

async function checkUpdate(force) {
  try {
    S.update = await api("/api/update" + (force ? "?force=1" : ""));
  } catch (e) {
    S.update = null;
  }
  return S.update;
}

function footer() {
  return h("div", { class: "foot" }, "Version " + (S.cfg ? S.cfg.version : ""), " · ",
    h("button", { class: "link", onclick: async () => {
      const info = await checkUpdate(true);
      if (info && info.available) return renderUpdate();
      toast(info && info.error ? info.error : "Du hast die neueste Version.");
      refreshHeader();
    } }, "Nach Updates suchen"));
}

function refreshHeader() {
  const old = document.querySelector("header");
  if (old) old.replaceWith(header());
}

function renderUpdate() {
  const u = S.update;
  const go = h("button", { class: "btn", disabled: !!u.blocked, onclick: installUpdate }, "Jetzt aktualisieren");
  mount(header(), h("div", { class: "card" },
    h("h1", {}, "Version " + u.version + " ist da"),
    h("p", { class: "lead" }, "Installiert ist " + u.current + ". Deine Zugangsdaten bleiben erhalten, die alte Version wird gesichert."),
    u.notes ? h("div", { class: "notes" }, u.notes) : null,
    u.blocked ? h("div", { class: "notice" }, u.blocked) : null,
    h("div", { class: "row between", style: "margin-top:18px" },
      h("button", { class: "link", onclick: () => (S.ov ? renderMain() : loadMain()) }, "Später"), go)));
}

async function installUpdate() {
  const result = await runJob("Aktualisiere", () => api("/api/update/install", {}));
  if (!result.ok) {
    return mount(header(), h("div", { class: "card" }, h("h1", {}, "Das hat nicht geklappt"),
      h("div", { class: "notice bad" }, result.error),
      h("p", { class: "muted" }, "Es wurde nichts verändert, was nicht gesichert wäre."),
      h("button", { class: "btn ghost", onclick: () => (S.ov ? renderMain() : loadMain()) }, "Zurück")));
  }
  mount(h("div", { class: "card success" },
    h("div", { html: '<svg class="check" viewBox="0 0 84 84"><circle cx="42" cy="42" r="30"/><path d="M29 43l9 9 18-19"/></svg>' }),
    h("h1", {}, "Version " + result.result.version + " ist installiert"),
    h("p", { class: "lead" }, "Zum Benutzen muss Pforte einmal neu starten."),
    h("button", { class: "btn", onclick: restart }, "Neu starten")));
}

async function restart() {
  try { await api("/api/restart", {}); } catch (e) { /* der Server geht gleich aus */ }
  mount(h("div", { class: "card success" }, h("h1", {}, "Startet neu …"),
    h("p", { class: "lead" }, "Ein neues Fenster öffnet sich gleich. Dieses darf zu.")));
}

/* ---------- Start ---------- */

async function boot() {
  try {
    S.cfg = await api("/api/state");
  } catch (e) {
    return mount(h("div", { class: "card" }, h("h1", {}, "Pforte"), h("div", { class: "notice bad" }, e.message)));
  }
  setInterval(() => fetch("/api/ping").catch(() => {}), 5000);
  window.addEventListener("pagehide", () => navigator.sendBeacon("/api/bye", new Blob(["{}"], { type: "application/json" })));
  const demo = location.hash.match(/^#wizard(?::(\d))?/);
  if (demo) return startWizard({ add: true, step: Number(demo[1] || 0) });
  if (!S.cfg.profiles.length) return startWizard({ first: true });
  checkUpdate().then(refreshHeader);
  loadMain();
}

/* ---------- Hauptbildschirm ---------- */

async function loadMain() {
  mount(header(), h("div", { class: "card" }, h("div", { class: "row" }, h("div", { class: "spinner light" }), h("span", { class: "muted" }, "Lese " + S.cfg.active + " …"))));
  try {
    S.ov = await api("/api/overview?profile=" + encodeURIComponent(S.cfg.active));
  } catch (e) {
    return mount(header(), h("div", { class: "card" },
      h("h1", {}, "Keine Verbindung"),
      h("div", { class: "notice bad" }, e.message),
      h("div", { class: "row", style: "margin-top:18px" },
        h("button", { class: "btn", onclick: loadMain }, "Nochmal versuchen"),
        h("button", { class: "btn ghost", onclick: () => startWizard({ edit: S.cfg.profiles.find((p) => p.name === S.cfg.active) }) }, "Einstellungen"))));
  }
  initForm();
  renderMain();
}

function initForm() {
  const ov = S.ov, f = S.form;
  const known = ov.domains.map((d) => d.domain);
  if (!known.includes(f.domain)) {
    // die Domain, unter der schon die meisten Hosts hängen, sonst die erste
    const count = {};
    for (const host of ov.hosts) for (const d of known) if (host.host.endsWith("." + d)) count[d] = (count[d] || 0) + 1;
    f.domain = known.slice().sort((a, b) => (count[b] || 0) - (count[a] || 0))[0] || "";
  }
  if (!ov.listeners.some((l) => l.uuid === f.listener)) {
    f.listener = (ov.listeners.find((l) => l.recommended) || ov.listeners[0] || {}).uuid || "";
  }
}

function listenerLabel(l) {
  const ports = l.ports.length ? " · Port " + l.ports.join(", ") : "";
  return l.name + ports + " · " + l.rule_count + (l.rule_count === 1 ? " Regel" : " Regeln") + (l.enabled ? "" : " · aus");
}

/* Name . Domain in einer Zeile. ``obj`` hält label und domain, ``onInput`` meldet jede Änderung. */
function composerNode(obj, onInput, domainsExtra) {
  const ov = S.ov;
  const label = h("input", { type: "text", placeholder: "wiki", autocomplete: "off", autocapitalize: "off", spellcheck: "false", value: obj.label,
    oninput: (e) => { obj.label = e.target.value; fit(); onInput(); } });
  const fit = () => { label.style.width = "calc(" + Math.max(5, label.value.length + 1) + "ch + 24px)"; };
  setTimeout(fit, 0);
  const known = ov.domains.map((d) => d.domain);
  if (domainsExtra && domainsExtra.length) for (const d of domainsExtra) if (!known.includes(d)) known.push(d);
  let domainField;
  if (known.length > 1) {
    domainField = h("select", { onchange: (e) => { obj.domain = e.target.value; onInput(); } },
      known.map((d) => h("option", { value: d, selected: d === obj.domain }, d)));
  } else if (known.length === 1) {
    obj.domain = known[0];
    domainField = h("div", { class: "static" }, known[0]);
  } else {
    domainField = h("input", { type: "text", placeholder: "example.com", value: obj.domain, style: "padding-left:8px",
      oninput: (e) => { obj.domain = e.target.value.trim(); onInput(); } });
  }
  return { node: h("div", { class: "composer" }, label, h("span", { class: "dot" }, "."), domainField), focus: () => label.focus() };
}

function fqdnOf(obj) {
  const label = obj.label.trim().toLowerCase().replace(/\.+$/, "");
  if (!label || !obj.domain) return "";
  return label.endsWith("." + obj.domain) || label === obj.domain ? label : label + "." + obj.domain;
}

function listenerSelect(obj) {
  const ls = S.ov.listeners;
  if (ls.length > 1) {
    return h("select", { onchange: (e) => { obj.listener = e.target.value; } },
      ls.map((l) => h("option", { value: l.uuid, selected: l.uuid === obj.listener }, listenerLabel(l))));
  }
  return ls[0] ? h("span", { class: "chip" }, listenerLabel(ls[0])) : null;
}

function layout(left, right) {
  return h("div", { class: "cols" }, h("div", { class: "left" }, left), h("div", { class: "right" }, right));
}

function renderMain(extra) {
  const ov = S.ov, f = S.form;
  const preview = h("div", { class: "preview" });
  const go = h("button", { class: "btn big" }, "Anlegen");

  const updatePreview = () => {
    const fqdn = fqdnOf(f);
    preview.replaceChildren(fqdn ? h("span", {}, "wird ", h("b", {}, fqdn)) : "Wie soll dein neuer Host heißen?");
    go.disabled = !(f.label.trim() && f.domain.trim() && f.target.trim() && f.listener);
  };
  const composer = composerNode(f, updatePreview);
  const target = comboTarget(f, "target", updatePreview);
  const via = ov.listeners.length ? h("div", { class: "via" }, "Eingang", listenerSelect(f)) : null;

  const notices = [];
  if (!ov.listeners.length) notices.push(h("div", { class: "notice bad" }, "Auf dieser OPNsense gibt es noch keinen Public Service. Lege in HAProxy zuerst einen an (Services → HAProxy → Einstellungen), dann geht es hier weiter."));
  if (!ov.domains.length && ov.listeners.length) notices.push(h("div", { class: "notice info" }, "Keine Zertifikate gefunden — tippe die Domain selbst ein."));
  if (!ov.dns.enabled) notices.push(h("div", { class: "notice info" }, "Ohne AdGuard musst du den DNS-Eintrag selbst anlegen. ", h("button", { class: "link", onclick: () => startWizard({ edit: S.cfg.profiles.find((p) => p.name === S.cfg.active), step: "adguard" }) }, "AdGuard einrichten")));
  for (const [what, text] of Object.entries(ov.problems || {})) notices.push(h("div", { class: "notice" }, what + ": " + text));

  go.addEventListener("click", () => submit());

  const card = h("div", { class: "card", id: "compose" },
    h("h1", {}, "Neuer Host"),
    h("p", { class: "lead" }, "Name wählen, Ziel angeben, anlegen."),
    composer.node, preview,
    h("label", { class: "field" }, h("span", {}, "Wohin soll er zeigen?"), target),
    via, extra, notices, go);

  mount(header(), layout(card, hostList()), footer());
  updatePreview();
  composer.focus();
}

function comboTarget(obj, key, onChange) {
  const items = S.ov.suggestions;
  const input = h("input", { type: "text", placeholder: items.length ? "Container wählen oder 192.168.0.5:8080" : "192.168.0.5:8080",
    autocomplete: "off", spellcheck: "false", value: obj[key] });
  const wrap = h("div", { class: "combo" }, input);
  let list = null, index = -1;

  const close = () => { if (list) list.remove(); list = null; index = -1; };
  const pick = (item) => { obj[key] = item.target; input.value = item.target; close(); onChange(); };
  const open = () => {
    const q = input.value.trim().toLowerCase();
    const shown = items.filter((i) => !q || (i.name + " " + i.stack + " " + i.target).toLowerCase().includes(q)).slice(0, 40);
    close();
    if (!shown.length) return;
    list = h("div", { class: "list" }, shown.map((i) => h("div", { class: "item", onmousedown: (e) => { e.preventDefault(); pick(i); } },
      h("span", {}, i.name, i.stack && i.stack !== i.name ? h("small", {}, "  ·  " + i.stack) : null),
      h("code", {}, i.host + ":" + i.port))));
    wrap.append(list);
  };
  input.addEventListener("input", () => { obj[key] = input.value; onChange(); open(); });
  input.addEventListener("focus", open);
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
    if (!list) return;
    const rows = [...list.children];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      index = (index + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length;
      rows.forEach((r, i) => r.classList.toggle("on", i === index));
    } else if (e.key === "Enter" && index >= 0) {
      e.preventDefault();
      rows[index].dispatchEvent(new MouseEvent("mousedown"));
    }
  });
  return wrap;
}

function hostUrl(host) {
  const l = S.ov.listeners.find((x) => x.name === host.listener);
  const plain = l && l.ports.length && !l.ports.includes(443) && l.ports.includes(80);
  const port = l && l.ports.find((p) => p !== 80 && p !== 443);
  return (plain ? "http://" : "https://") + host.host + (l && !l.ports.includes(443) && !plain && port ? ":" + port : "") + (host.path || "");
}

const SHOWN = 12;

function hostList() {
  const hosts = S.ov.hosts;
  const holder = h("div");
  const query = h("input", { type: "text", placeholder: "Hosts durchsuchen …", value: S.hostFilter || "", autocomplete: "off",
    style: "margin-bottom:12px", oninput: (e) => { S.hostFilter = e.target.value; draw(); } });

  const draw = () => {
    const q = (S.hostFilter || "").trim().toLowerCase();
    const matching = hosts.filter((x) => !q || (x.host + " " + x.target).toLowerCase().includes(q));
    const visible = q || S.allHosts ? matching : matching.slice(0, SHOWN);
    // der Host, der gerade bearbeitet wird, bleibt immer sichtbar
    if (S.editing && !visible.some((x) => x.uuid === S.editing)) {
      const editing = hosts.find((x) => x.uuid === S.editing);
      if (editing) visible.unshift(editing);
    }
    const kids = [];
    if (!hosts.length) kids.push(h("div", { class: "empty" }, "Noch keine Hosts. Der erste ist gleich angelegt."));
    else if (!matching.length) kids.push(h("div", { class: "empty" }, "Nichts gefunden."));
    else kids.push(h("div", { class: "hosts" }, visible.map((host, n) => hostRow(host, n, draw))));
    if (visible.length < matching.length) {
      kids.push(h("div", { class: "row", style: "justify-content:center;margin-top:12px" },
        h("button", { class: "btn ghost", onclick: () => { S.allHosts = true; draw(); } }, "Alle " + matching.length + " anzeigen")));
    }
    holder.replaceChildren(...kids);
  };
  draw();
  return h("div", { id: "hosts" }, h("h2", { class: "first" }, "Deine Hosts" + (hosts.length ? " (" + hosts.length + ")" : "")), hosts.length > SHOWN ? query : null, holder);
}

/* Liste und Eingänge im Hintergrund neu lesen, ohne den Bildschirm zu wechseln. */
async function refreshOverview() {
  try {
    S.ov = await api("/api/overview?fresh=1&profile=" + encodeURIComponent(S.cfg.active));
  } catch (e) {
    return;
  }
  const old = document.getElementById("hosts");
  if (old) old.replaceWith(hostList());
}

const PENCIL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';

function targetText(host) {
  return (host.ssl ? "https://" : "") + host.target;
}

function hostRow(host, n, redraw) {
  const open = S.editing === host.uuid;
  const actions = [];
  if (host.editable) {
    actions.push(h("button", { class: "icon-btn" + (open ? " on" : ""), title: open ? "Schließen" : "Bearbeiten", html: PENCIL,
      onclick: () => { S.editing = open ? null : host.uuid; redraw(); } }));
  } else {
    actions.push(h("span", { class: "chip", title: host.reason || "In OPNsense selbst ändern" }, host.managed ? "gesperrt" : "manuell"));
  }
  const row = h("div", { class: "host", style: "animation-delay:" + Math.min(n, 8) * 40 + "ms" },
    h("div", { class: "dot" }),
    h("div", { class: "main" },
      h("a", { href: hostUrl(host), target: "_blank", rel: "noopener" }, host.host + (host.path || "")),
      h("div", { class: "sub" }, "→ " + targetText(host) + (host.listener ? "  ·  " + host.listener : ""))),
    actions);
  if (!open) return row;
  return h("div", { class: "hostwrap" }, row, editPanel(host, redraw));
}

function splitHost(host) {
  const known = S.ov.domains.map((d) => d.domain).sort((a, b) => b.length - a.length);
  const hit = known.find((d) => host === d || host.endsWith("." + d));
  if (hit) return { label: host === hit ? "@" : host.slice(0, host.length - hit.length - 1), domain: hit, extra: [] };
  const dot = host.indexOf(".");
  const domain = dot > 0 ? host.slice(dot + 1) : "";
  return { label: dot > 0 ? host.slice(0, dot) : host, domain, extra: domain ? [domain] : [] };
}

function editPanel(host, redraw) {
  const split = splitHost(host.host);
  const ed = { label: split.label, domain: split.domain, target: targetText(host), listener: host.listener_uuid };
  const preview = h("div", { class: "preview" });
  const save = h("button", { class: "btn" }, "Speichern");
  const changed = () => ed.label !== split.label || ed.domain !== split.domain || ed.target.trim() !== targetText(host) || ed.listener !== host.listener_uuid;
  const update = () => {
    const fqdn = fqdnOf(ed);
    preview.replaceChildren(fqdn && fqdn !== host.host ? h("span", {}, "wird ", h("b", {}, fqdn)) : "");
    save.disabled = !(ed.label.trim() && ed.domain.trim() && ed.target.trim() && changed());
  };
  const composer = composerNode(ed, update, split.extra);
  const target = comboTarget(ed, "target", update);
  let armed = false;
  const del = h("button", { class: "btn danger" }, "Entfernen");
  del.addEventListener("click", () => {
    if (!host.managed) return toast("Von Hand angelegt — bitte in OPNsense entfernen.");
    if (!armed) {
      armed = true; del.textContent = "Wirklich entfernen?";
      return void setTimeout(() => { armed = false; del.textContent = "Entfernen"; }, 3500);
    }
    removeHost(host);
  });
  save.addEventListener("click", () => saveEdit(host, ed));
  const panel = h("div", { class: "edit" },
    composer.node, preview,
    h("label", { class: "field" }, h("span", {}, "Wohin zeigt er?"), target),
    S.ov.listeners.length > 1 ? h("div", { class: "via" }, "Eingang", listenerSelect(ed)) : null,
    !host.managed ? h("div", { class: "notice info" }, "Von Hand angelegt. Namen und Beschreibungen in OPNsense bleiben, wie sie sind.") : null,
    h("div", { class: "row between" }, host.managed ? del : h("span"),
      h("div", { class: "row" }, h("button", { class: "btn ghost", onclick: () => { S.editing = null; redraw(); } }, "Abbrechen"), save)));
  setTimeout(update, 0);
  return panel;
}

async function saveEdit(host, ed) {
  const result = await runJob(host.host + " ändern", () => api("/api/edit", {
    profile: S.cfg.active, uuid: host.uuid, label: ed.label, domain: ed.domain, target: ed.target,
    listener: ed.listener, dns_target: S.ov.dns.target }));
  if (!result.ok) {
    renderMain(h("div", { class: "notice bad" }, result.error));
    return refreshOverview();
  }
  S.editing = null;
  const warnings = (result.result && result.result.warnings) || [];
  toast(result.result && result.result.changed === false ? "Nichts geändert" : "Gespeichert");
  renderMain(warnings.map((w) => h("div", { class: "notice" }, w)));
  refreshOverview();
}

/* ---------- Anlegen und Entfernen ---------- */

async function runJob(title, start) {
  const list = h("ul", { class: "steps" });
  mount(header(), h("div", { class: "card" }, h("h1", {}, title), h("p", { class: "lead" }, "Einen Moment …"), list));
  let job;
  try {
    job = (await start()).job;
  } catch (e) {
    return { ok: false, error: e.message, steps: [] };
  }
  let shown = 0, state;
  const draw = (steps, done) => {
    list.replaceChildren(...steps.map((s, i) => {
      const last = i === steps.length - 1 && !done;
      const cls = s.level === "warn" ? "warn" : last ? "doing" : "done";
      return h("li", { class: cls }, h("span", { class: "mark", html: last ? "" : (s.level === "warn" ? ICON.bang : ICON.check) },
        last ? h("div", { class: "spinner light" }) : null), s.text);
    }));
  };
  for (;;) {
    state = await api("/api/jobs/" + job);
    if (state.steps.length !== shown) { shown = state.steps.length; draw(state.steps, state.done); }
    if (state.done) { draw(state.steps, true); break; }
    await sleep(120);
  }
  return state;
}

async function submit() {
  const f = S.form, ov = S.ov;
  const result = await runJob("Lege " + (f.label.trim() || "Host") + " an", () => api("/api/hosts", {
    profile: S.cfg.active, label: f.label, domain: f.domain, target: f.target,
    listener: f.listener, dns_target: ov.dns.target }));
  if (!result.ok) {
    return renderMain(h("div", { class: "notice bad" }, result.error));
  }
  const host = result.result.host;
  const warnings = result.result.warnings || [];
  S.form.label = ""; S.form.target = "";
  const l = S.ov.listeners.find((x) => x.uuid === f.listener);
  const url = (l && l.ports.length && !l.ports.includes(443) && l.ports.includes(80) ? "http://" : "https://") + host;
  mount(header(), layout(h("div", { class: "card success" },
    h("div", { html: '<svg class="check" viewBox="0 0 84 84"><circle cx="42" cy="42" r="30"/><path d="M29 43l9 9 18-19"/></svg>' }),
    h("a", { class: "hostname", href: url, target: "_blank", rel: "noopener" }, host),
    h("p", { class: "lead" }, "ist angelegt und HAProxy hat die neue Konfiguration geladen."),
    warnings.map((w) => h("div", { class: "notice" }, w)),
    h("div", { class: "row", style: "justify-content:center;margin-top:18px" },
      h("a", { class: "btn", href: url, target: "_blank", rel: "noopener" }, "Öffnen"),
      h("button", { class: "btn ghost", onclick: () => renderMain() }, "Noch ein Host"))),
    hostList()), footer());
  refreshOverview();
}

async function removeHost(host) {
  const result = await runJob(host.host + " entfernen", () => api("/api/remove", { profile: S.cfg.active, uuid: host.uuid }));
  if (!result.ok) toast(result.error);
  else {
    toast(host.host + " ist entfernt");
    S.ov.hosts = S.ov.hosts.filter((x) => x.uuid !== host.uuid);
  }
  renderMain();
  refreshOverview();
}

/* ---------- Einrichtung (Wizard) ---------- */

// Geführt: jeder Schritt sagt, was wo einzustellen ist. Zum Ändern
// vorhandener Zugänge reicht die kurze Fassung.
const GUIDED = ["welcome", "address", "plugin", "user", "key", "check", "adguard", "portainer", "done"];
const SHORT = ["opnsense", "adguard", "portainer"];
const SILENT = ["welcome", "done"];   // ohne Fortschrittsanzeige

function startWizard(options) {
  const o = options || {};
  const base = o.edit || null;
  const blank = () => ({ url: "", verify: true });
  const flow = base ? SHORT : GUIDED;
  let at = o.first ? 0 : (base ? 0 : 1);
  if (typeof o.step === "string") at = Math.max(0, flow.indexOf(o.step));
  else if (o.step != null) at = Math.min(flow.length - 1, o.step);
  S.wiz = {
    first: !!o.first, previous: base ? base.name : null, flow, at,
    draft: {
      opnsense: base ? { ...base.opnsense } : { ...blank(), key: "", secret: "" },
      adguard: base && base.adguard ? { ...base.adguard } : { ...blank(), username: "admin", password: "", target: "" },
      portainer: base && base.portainer ? { ...base.portainer } : { ...blank(), api_key: "" },
    },
    use: { adguard: !!(base && base.adguard), portainer: !!(base && base.portainer) },
    info: {}, report: null,
    error: null, busy: false,
  };
  renderWizard();
}

function go(id) {
  const w = S.wiz;
  w.at = typeof id === "number" ? w.at + id : w.flow.indexOf(id);
  w.error = null; w.busy = false;
  renderWizard();
}

function renderWizard() {
  const w = S.wiz, id = w.flow[w.at];
  const shown = w.flow.filter((s) => !SILENT.includes(s));
  const pos = shown.indexOf(id);
  const progress = pos < 0 ? null : h("div", {},
    h("div", { class: "stepno" }, "Schritt " + (pos + 1) + " von " + shown.length),
    h("div", { class: "dots" }, shown.map((s, i) => h("i", {
      class: (i <= pos ? "on" : "") + (w.previous ? " click" : ""),
      onclick: w.previous ? () => go(s) : null }))));
  const body = STEP[id]();
  const have = S.cfg && S.cfg.profiles.length;
  const links = [];
  if (!w.previous && w.at > 0 && id !== "done") links.push(h("button", { class: "link", onclick: () => go(-1) }, "Zurück"));
  if (w.previous) links.push(h("button", { class: "link", onclick: loadMain }, "Schließen"));
  else if (have && id !== "done") links.push(h("button", { class: "link", onclick: loadMain }, "Abbrechen"));
  mount(have ? header() : h("header", {}, h("div", { class: "brand" }, h("img", { src: "logo.svg", alt: "" }), "Pforte")),
    h("div", { class: "card", id: "wizard" }, progress, body),
    h("div", { class: "row", style: "margin-top:14px;justify-content:center;gap:18px" }, links));
}

function field(label, key, section, opts) {
  const o = opts || {};
  const d = S.wiz.draft[section];
  const secretSet = o.secret && S.wiz.previous && d.has_secret;
  return h("label", { class: "field" }, h("span", {}, label),
    h("input", { type: o.secret ? "password" : "text", placeholder: secretSet ? "unverändert — nur zum Ändern eintippen" : (o.placeholder || ""),
      value: d[key] || "", autocomplete: "off", spellcheck: "false", autocapitalize: "off", id: o.id,
      oninput: (e) => { d[key] = e.target.value; if (o.oninput) o.oninput(e); } }),
    o.hint ? h("small", { class: "hint" }, o.hint) : null);
}

function errorBox(section, retry) {
  const w = S.wiz;
  if (!w.error) return null;
  const box = h("div", { class: "notice bad" }, w.error.message);
  if (w.error.code === "tls") {
    box.append(h("div", { class: "small", style: "margin-top:8px" }, section === "opnsense"
      ? "Das ist bei einer OPNsense mit selbst erzeugtem Zertifikat normal. Im Heimnetz darf die Prüfung entfallen."
      : "Bei einem selbst erzeugten Zertifikat im Heimnetz darf die Prüfung entfallen."));
    box.append(h("div", { style: "margin-top:10px" }, h("button", { class: "btn ghost", onclick: () => {
      w.draft[section].verify = false; w.error = null; retry();
    } }, "Trotzdem verbinden")));
  }
  return box;
}

// Adresse einer Seite in der OPNsense, sobald die Adresse bekannt ist
function osUrl(page) {
  let base = (S.wiz.info.url || S.wiz.draft.opnsense.url || "").trim().replace(/\/+$/, "");
  if (!base) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(base)) base = "https://" + base;
  return base + (page || "");
}

function openLink(text, page) {
  const url = osUrl(page);
  return url ? h("a", { class: "btn ghost small", href: url, target: "_blank", rel: "noopener" }, text, " ↗") : null;
}

function todo(items) {
  return h("ol", { class: "todo" }, items.map((item) => h("li", {}, h("div", {}, item))));
}

function proceed(label, action, opts) {
  const w = S.wiz, o = opts || {};
  return h("div", { class: "row between", style: "margin-top:14px" },
    o.skip ? h("button", { class: "link", onclick: o.skip[1] }, o.skip[0]) : h("span"),
    h("button", { class: "btn", disabled: w.busy || o.disabled, onclick: action },
      w.busy ? h("div", { class: "spinner" }) : null, w.busy ? "Prüfe …" : label));
}

const STEP = {
  welcome() {
    const imp = S.cfg.importable || [];
    return h("div", {},
      h("div", { class: "hero" }, h("img", { src: "logo.svg", alt: "" }), h("h1", {}, "Willkommen an der Pforte"),
        h("p", { class: "lead" }, "Neue Webseiten im Heimnetz erreichbar machen — ein Name, ein Ziel, ein Klick. Die Einrichtung führt Schritt für Schritt durch alles, was dafür in OPNsense einzustellen ist.")),
      h("div", { class: "need" },
        h("div", {}, h("b", {}, "Gebraucht wird"), "eine OPNsense, auf der du dich als Administrator anmelden kannst."),
        h("div", {}, h("b", {}, "Optional"), "AdGuard Home für den DNS-Eintrag und Portainer für Zielvorschläge."),
        h("div", {}, h("b", {}, "Dauer"), "etwa fünf Minuten. Jede Eingabe wird sofort geprüft.")),
      imp.length ? h("div", { class: "notice info" }, "Es gibt Einstellungen aus der alten Version (" + imp.join(", ") + "). ",
        h("button", { class: "link", onclick: async () => { S.cfg = await api("/api/import", {}); toast("Übernommen"); loadMain(); } }, "Übernehmen")) : null,
      h("button", { class: "btn big", onclick: () => go(1) }, "Los geht’s"));
  },

  address() {
    return h("div", {},
      h("h1", {}, "Wo ist deine OPNsense?"),
      h("p", { class: "lead" }, "Gesucht ist die Adresse, unter der du die Oberfläche der OPNsense im Browser öffnest."),
      field("Adresse der OPNsense", "url", "opnsense", { placeholder: "https://192.168.1.1", id: "first",
        hint: "Meist die IP des Routers. Läuft die Oberfläche auf einem anderen Port, gehört er dazu: https://192.168.1.1:8443" }),
      errorBox("opnsense", checkAddress),
      S.wiz.error && S.wiz.error.code !== "tls" ? h("div", { class: "notice info" }, "Lässt sich die Adresse im Browser öffnen? Dann genau so eintragen, wie sie dort in der Adresszeile steht.") : null,
      proceed("Verbindung prüfen", checkAddress));
  },

  plugin() {
    return h("div", {},
      h("h1", {}, "HAProxy in OPNsense"),
      h("p", { class: "lead" }, "Pforte bedient das Plugin os-haproxy. Für die Zertifikate ist os-acme-client üblich. Beides wird in der OPNsense installiert."),
      todo([
        ["Die OPNsense im Browser öffnen und als Administrator anmelden. ", openLink("OPNsense öffnen", "")],
        ["Im Menü: System → Firmware → Plugins (Erweiterungen). ", openLink("Plugins öffnen", "/ui/core/firmware#plugins")],
        "In der Liste os-haproxy suchen und rechts mit + installieren.",
        "Falls noch kein Zertifikat für die eigene Domain vorhanden ist: auf dieselbe Weise os-acme-client installieren.",
        "Seite neu laden. Unter Dienste (Services) stehen jetzt HAProxy und ACME Client.",
      ]),
      h("div", { class: "notice info" }, "Schon installiert? Dann gleich weiter. Ob alles vorhanden ist, prüft Pforte in Schritt 5."),
      proceed("Erledigt, weiter", () => go(1)));
  },

  user() {
    return h("div", {},
      h("h1", {}, "Einen Benutzer für Pforte anlegen"),
      h("p", { class: "lead" }, "Pforte bekommt einen eigenen Benutzer, der nur HAProxy und die Zertifikate sehen darf. Dein Administrator-Passwort wird nie gebraucht."),
      todo([
        ["Im Menü der OPNsense: System → Zugang → Benutzer (englisch: System → Access → Users). ", openLink("OPNsense öffnen", "")],
        "Mit + einen neuen Benutzer anlegen. Benutzername: pforte.",
        "Passwort: ein beliebiges langes Passwort oder den Haken „Zufallspasswort erzeugen“ (Scrambled Password). Pforte meldet sich nicht damit an.",
        "Bei den Rechten (Privileges) zwei Einträge ankreuzen: „Services: HAProxy“ und „Services: ACME Client“. Das Suchfeld über der Liste hilft.",
        "Speichern.",
      ]),
      proceed("Erledigt, weiter", () => go(1)));
  },

  key() {
    const w = S.wiz;
    const pick = h("input", { type: "file", accept: ".txt,text/plain", style: "display:none", onchange: async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      if (useKeyText(await file.text())) toast("Schlüssel übernommen");
      else { w.error = new Error("In dieser Datei stehen keine Zeilen key=… und secret=…"); }
      renderWizard();
    } });
    const paste = (e) => {
      const text = (e.clipboardData || window.clipboardData).getData("text");
      if (/key\s*=/.test(text) && useKeyText(text)) { e.preventDefault(); toast("Schlüssel übernommen"); renderWizard(); }
    };
    return h("div", { onpaste: paste },
      h("h1", {}, "Den API-Schlüssel erzeugen"),
      h("p", { class: "lead" }, "Mit dem Schlüssel meldet sich Pforte als der eben angelegte Benutzer an."),
      todo([
        "In der Benutzerliste der OPNsense in der Zeile von pforte das Symbol „API-Schlüssel erstellen“ anklicken (ältere Versionen: Benutzer öffnen, ganz unten bei „API-Schlüssel“ auf +).",
        "Der Browser lädt eine kleine Textdatei herunter (…apikey.txt). OPNsense zeigt das Secret nur dieses eine Mal.",
        ["Die Datei hier auswählen, oder beide Werte von Hand eintragen. ", h("button", { class: "btn ghost small", onclick: () => pick.click() }, "Schlüsseldatei auswählen")],
      ]),
      pick,
      field("API-Key", "key", "opnsense", { secret: true, hint: "Der Teil hinter key=" }),
      field("API-Secret", "secret", "opnsense", { secret: true, hint: "Der Teil hinter secret=" }),
      errorBox("opnsense", runCheck),
      proceed("Prüfen", runCheck));
  },

  check() {
    const w = S.wiz, r = w.report || { checks: [], ready: false };
    const warn = r.checks.some((c) => c.state === "warn");
    const head = !r.ready ? ["Noch nicht ganz", "Mindestens ein Punkt fehlt. Unter jedem steht, wo er in OPNsense eingestellt wird. Danach erneut prüfen."]
      : warn ? ["Fast alles da", "Die Verbindung steht. Die markierten Punkte schränken Pforte ein und lassen sich jetzt oder später erledigen."]
      : ["Alles bereit", "OPNsense ist vollständig eingerichtet."];
    return h("div", {},
      h("h1", {}, head[0]),
      h("p", { class: "lead" }, head[1]),
      h("div", { class: "checks" }, r.checks.map(checkRow)),
      errorBox("opnsense", runCheck),
      h("div", { class: "row between", style: "margin-top:14px" },
        h("button", { class: "btn ghost", disabled: w.busy, onclick: runCheck }, w.busy ? h("div", { class: "spinner light" }) : null, "Erneut prüfen"),
        h("button", { class: "btn", disabled: !r.ready || w.busy, onclick: () => go(1) }, warn && r.ready ? "Trotzdem weiter" : "Weiter")));
  },

  opnsense() {
    return h("div", {},
      h("h1", {}, "OPNsense"),
      h("p", { class: "lead" }, "Pforte meldet sich mit einem API-Schlüssel an, nicht mit deinem Passwort."),
      field("Adresse der OPNsense", "url", "opnsense", { placeholder: "https://192.168.1.1" }),
      field("API-Key", "key", "opnsense", { secret: true }),
      field("API-Secret", "secret", "opnsense", { secret: true }),
      S.wiz.report ? h("div", { class: "checks" }, S.wiz.report.checks.map(checkRow)) : null,
      errorBox("opnsense", () => advance("opnsense")),
      h("div", { class: "row between", style: "margin-top:14px" },
        h("button", { class: "btn ghost", disabled: S.wiz.busy, onclick: runCheck }, "Einrichtung prüfen"),
        h("button", { class: "btn", disabled: S.wiz.busy, onclick: () => advance("opnsense") }, S.wiz.busy ? h("div", { class: "spinner" }) : null, S.wiz.busy ? "Prüfe …" : "Prüfen und weiter")));
  },

  adguard() {
    const w = S.wiz;
    return h("div", {},
      h("h1", {}, "AdGuard Home"),
      h("p", { class: "lead" }, "Optional. Damit ein neuer Name im Heimnetz gefunden wird, braucht er einen DNS-Eintrag. Mit AdGuard Home legt Pforte ihn selbst an, als DNS-Umschreibung."),
      todo([
        "Die Adresse ist die, unter der du die Oberfläche von AdGuard Home öffnest, samt Port.",
        "Benutzer und Passwort sind dieselben wie bei der Anmeldung an dieser Oberfläche.",
        "Das Ziel ist die IP, auf der HAProxy lauscht. Das ist fast immer die LAN-Adresse der OPNsense.",
      ]),
      field("Adresse von AdGuard", "url", "adguard", { placeholder: "http://192.168.1.2:3000" }),
      field("Benutzer", "username", "adguard"),
      field("Passwort", "password", "adguard", { secret: true }),
      field("Neue Namen zeigen auf (IP von HAProxy)", "target", "adguard", { placeholder: "192.168.1.1",
        hint: w.info.address ? "Vorschlag aus der Adresse der OPNsense: " + w.info.address : "" }),
      h("div", { class: "small muted", style: "margin:0 4px 14px" }, "Die Einträge wirken für alle Geräte, die AdGuard Home als DNS-Server verwenden."),
      errorBox("adguard", () => advance("adguard")),
      proceed("Prüfen und weiter", () => advance("adguard"), { skip: ["Ohne AdGuard weiter", () => skip("adguard")] }));
  },

  portainer() {
    return h("div", {},
      h("h1", {}, "Portainer"),
      h("p", { class: "lead" }, "Optional. Mit Portainer schlägt Pforte beim Ziel die laufenden Container samt Port vor."),
      todo([
        "Portainer öffnen und anmelden.",
        "Oben rechts auf den Benutzernamen klicken, dann „Mein Konto“ (My account).",
        "Unter „Zugriffstoken“ (Access tokens) auf „Zugriffstoken hinzufügen“ klicken, eine Beschreibung wie pforte eintragen und bestätigen.",
        "Den angezeigten Token kopieren. Portainer zeigt ihn nur dieses eine Mal.",
      ]),
      field("Adresse von Portainer", "url", "portainer", { placeholder: "https://192.168.1.20:9443" }),
      field("Zugriffstoken", "api_key", "portainer", { secret: true }),
      errorBox("portainer", () => advance("portainer")),
      proceed(S.wiz.previous ? "Prüfen und fertig" : "Prüfen und weiter", () => advance("portainer"), { skip: ["Ohne Portainer fertig", () => skip("portainer")] }));
  },

  done() {
    const w = S.wiz, r = w.report || { checks: [] };
    const open = r.checks.filter((c) => c.state !== "ok");
    const line = (ok, title, text) => h("div", { class: "check " + (ok ? "ok" : "off") },
      h("span", { class: "mark", html: ok ? ICON.check : "" }), h("div", {}, h("b", {}, title), h("div", { class: "small muted" }, text)));
    return h("div", {},
      h("div", { class: "hero" }, h("h1", {}, "Eingerichtet")),
      h("div", { class: "checks" },
        line(true, "OPNsense", w.info.url || w.draft.opnsense.url),
        line(w.use.adguard, "AdGuard Home", w.use.adguard ? "DNS-Einträge entstehen automatisch." : "Übersprungen. DNS-Einträge legst du selbst an."),
        line(w.use.portainer, "Portainer", w.use.portainer ? "Container werden als Ziel vorgeschlagen." : "Übersprungen.")),
      open.length ? h("div", { class: "notice" }, "Noch offen in OPNsense: " + open.map((c) => c.title).join(", ") + ". Die Anleitung dazu steht jederzeit in den Einstellungen (Zahnrad oben rechts).") : null,
      h("p", { class: "lead", style: "margin-top:18px" }, "Als Nächstes: Namen eintippen, Ziel angeben, anlegen. Die Zugänge lassen sich über das Zahnrad oben rechts ändern."),
      h("button", { class: "btn big", onclick: () => { S.wiz = null; checkUpdate().then(refreshHeader); loadMain(); } }, "Zur Pforte"));
  },
};

function checkRow(c) {
  const cls = c.state === "ok" ? "ok" : (c.state === "warn" ? "warn" : "bad");
  const help = c.steps && c.steps.length ? h("details", { open: c.state === "fail" },
    h("summary", {}, "So wird es eingerichtet"),
    h("div", { class: "body" }, h("ol", {}, c.steps.map((s) => h("li", {}, s))),
      c.page ? h("div", { style: "margin:8px 0 4px" }, openLink("Seite in OPNsense öffnen", c.page)) : null)) : null;
  return h("div", { class: "check " + cls },
    h("span", { class: "mark", html: c.state === "ok" ? ICON.check : ICON.bang }),
    h("div", {}, h("b", {}, c.title), c.text ? h("div", { class: "small muted" }, c.text) : null, help));
}

// „key=…“ und „secret=…“ aus der Schlüsseldatei der OPNsense lesen
function useKeyText(text) {
  const key = /^\s*key\s*=\s*(\S+)/m.exec(text || ""), secret = /^\s*secret\s*=\s*(\S+)/m.exec(text || "");
  if (!key || !secret) return false;
  S.wiz.draft.opnsense.key = key[1];
  S.wiz.draft.opnsense.secret = secret[1];
  S.wiz.error = null;
  return true;
}

async function checkAddress() {
  const w = S.wiz, d = w.draft.opnsense;
  w.error = null;
  if (!(d.url || "").trim()) { w.error = new Error("Bitte die Adresse eintragen."); return renderWizard(); }
  w.busy = true; renderWizard();
  try {
    const info = await api("/api/probe", { settings: d });
    w.info.url = info.url; w.info.address = info.address;
    if (info.address && !w.draft.adguard.target) w.draft.adguard.target = info.address;
  } catch (e) {
    w.busy = false; w.error = e; return renderWizard();
  }
  go(1);
}

async function runCheck() {
  const w = S.wiz, d = w.draft.opnsense;
  w.error = null;
  if (!filled("opnsense")) { w.error = new Error("Key und Secret werden gebraucht."); return renderWizard(); }
  w.busy = true; renderWizard();
  try {
    w.report = await api("/api/diagnose", { settings: d, profile: w.previous });
    w.info.url = w.report.url; w.info.address = w.report.address || w.info.address;
    if (w.info.address && !w.draft.adguard.target) w.draft.adguard.target = w.info.address;
  } catch (e) {
    w.busy = false; w.error = e; return renderWizard();
  }
  w.busy = false;
  if (w.flow.includes("check")) return go("check");
  renderWizard();
  return w.report.ready;
}

function filled(section) {
  const d = S.wiz.draft[section], prev = !!S.wiz.previous;
  if (section === "opnsense") return d.url && ((d.key && d.secret) || (prev && d.has_secret));
  if (section === "adguard") return d.url;
  return d.url && (d.api_key || (prev && d.has_secret));
}

async function advance(section) {
  const w = S.wiz, d = w.draft[section];
  w.error = null;
  if (!filled(section)) {
    w.error = new Error(section === "opnsense" ? "Adresse, Key und Secret werden gebraucht." : "Bitte die Felder ausfüllen — oder überspringen.");
    return renderWizard();
  }
  if (section === "opnsense") {           // kurze Fassung: prüfen, bei Fehlern stehen bleiben
    if (await runCheck()) go(1);
    return;
  }
  w.busy = true; renderWizard();
  try {
    await api("/api/test", { kind: section, settings: d, profile: w.previous });
    w.use[section] = true;
  } catch (e) {
    w.busy = false; w.error = e; return renderWizard();
  }
  w.busy = false;
  if (section === "adguard") return go(1);
  return finish();
}

function skip(section) {
  const w = S.wiz;
  w.use[section] = false; w.error = null;
  if (section === "adguard") return go(1);
  return finish();
}

async function finish() {
  const w = S.wiz, d = w.draft;
  const body = { previous: w.previous, opnsense: d.opnsense,
    adguard: w.use.adguard ? d.adguard : null, portainer: w.use.portainer ? d.portainer : null };
  try {
    S.cfg = await api("/api/profile", body);
  } catch (e) {
    w.error = e; return renderWizard();
  }
  if (w.flow.includes("done")) return go("done");
  S.wiz = null;
  loadMain();
}

boot();
