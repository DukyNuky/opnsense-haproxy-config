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
  hostFilter: "", allHosts: false,
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

function renderMain(extra) {
  const ov = S.ov, f = S.form;
  const preview = h("div", { class: "preview" });
  const go = h("button", { class: "btn big" }, "Anlegen");

  const updatePreview = () => {
    const label = f.label.trim().toLowerCase().replace(/\.+$/, "");
    const fqdn = label && f.domain ? (label.endsWith("." + f.domain) || label === f.domain ? label : label + "." + f.domain) : "";
    preview.replaceChildren(fqdn ? h("span", {}, "wird ", h("b", {}, fqdn)) : "Wie soll dein neuer Host heißen?");
    go.disabled = !(f.label.trim() && f.domain.trim() && f.target.trim() && f.listener);
  };

  const label = h("input", { type: "text", placeholder: "wiki", autocomplete: "off", autocapitalize: "off", spellcheck: "false", value: f.label,
    oninput: (e) => { f.label = e.target.value; fit(); updatePreview(); } });
  const fit = () => { label.style.width = "calc(" + Math.max(5, label.value.length + 1) + "ch + 24px)"; };
  setTimeout(fit, 0);

  let domainField;
  if (ov.domains.length > 1) {
    domainField = h("select", { onchange: (e) => { f.domain = e.target.value; updatePreview(); } },
      ov.domains.map((d) => h("option", { value: d.domain, selected: d.domain === f.domain }, d.domain)));
  } else if (ov.domains.length === 1) {
    domainField = h("div", { class: "static" }, ov.domains[0].domain);
  } else {
    domainField = h("input", { type: "text", placeholder: "example.com", value: f.domain, style: "padding-left:8px",
      oninput: (e) => { f.domain = e.target.value.trim(); updatePreview(); } });
  }

  const target = comboTarget(updatePreview);

  const via = ov.listeners.length > 1
    ? h("div", { class: "via" }, "Eingang",
        h("select", { onchange: (e) => { f.listener = e.target.value; } },
          ov.listeners.map((l) => h("option", { value: l.uuid, selected: l.uuid === f.listener }, listenerLabel(l)))))
    : (ov.listeners[0] ? h("div", { class: "via" }, "Eingang", h("span", { class: "chip" }, listenerLabel(ov.listeners[0]))) : null);

  const notices = [];
  if (!ov.listeners.length) notices.push(h("div", { class: "notice bad" }, "Auf dieser OPNsense gibt es noch keinen Public Service. Lege in HAProxy zuerst einen an (Services → HAProxy → Einstellungen), dann geht es hier weiter."));
  if (!ov.domains.length && ov.listeners.length) notices.push(h("div", { class: "notice info" }, "Keine Zertifikate gefunden — tippe die Domain selbst ein."));
  if (!ov.dns.enabled) notices.push(h("div", { class: "notice info" }, "Ohne AdGuard musst du den DNS-Eintrag selbst anlegen. ", h("button", { class: "link", onclick: () => startWizard({ edit: S.cfg.profiles.find((p) => p.name === S.cfg.active), step: 2 }) }, "AdGuard einrichten")));
  for (const [what, text] of Object.entries(ov.problems || {})) notices.push(h("div", { class: "notice" }, what + ": " + text));

  go.addEventListener("click", () => submit());

  const card = h("div", { class: "card", id: "compose" },
    h("h1", {}, "Neuer Host"),
    h("p", { class: "lead" }, "Name wählen, Ziel angeben, anlegen."),
    h("div", { class: "composer" }, label, h("span", { class: "dot" }, "."), domainField),
    preview,
    h("label", { class: "field" }, h("span", {}, "Wohin soll er zeigen?"), target),
    via, extra, notices, go);

  mount(header(), card, hostList());
  updatePreview();
  label.focus();
}

function comboTarget(onChange) {
  const f = S.form, items = S.ov.suggestions;
  const input = h("input", { type: "text", placeholder: items.length ? "Container wählen oder 192.168.0.5:8080" : "192.168.0.5:8080",
    autocomplete: "off", spellcheck: "false", value: f.target });
  const wrap = h("div", { class: "combo" }, input);
  let list = null, index = -1;

  const close = () => { if (list) list.remove(); list = null; index = -1; };
  const pick = (item) => { f.target = item.target; input.value = item.target; close(); onChange(); };
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
  input.addEventListener("input", () => { f.target = input.value; onChange(); open(); });
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

const SHOWN = 8;

function hostList() {
  const hosts = S.ov.hosts;
  const holder = h("div");
  const query = h("input", { type: "text", placeholder: "Hosts durchsuchen …", value: S.hostFilter || "", autocomplete: "off",
    style: "margin-bottom:12px", oninput: (e) => { S.hostFilter = e.target.value; draw(); } });

  const draw = () => {
    const q = (S.hostFilter || "").trim().toLowerCase();
    const matching = hosts.filter((x) => !q || (x.host + " " + x.target).toLowerCase().includes(q));
    const visible = q || S.allHosts ? matching : matching.slice(0, SHOWN);
    const rows = visible.map((host, n) => hostRow(host, n));
    const kids = [];
    if (!hosts.length) kids.push(h("div", { class: "empty" }, "Noch keine Hosts. Der erste ist gleich angelegt."));
    else if (!matching.length) kids.push(h("div", { class: "empty" }, "Nichts gefunden."));
    else kids.push(h("div", { class: "hosts" }, rows));
    if (visible.length < matching.length) {
      kids.push(h("div", { class: "row", style: "justify-content:center;margin-top:12px" },
        h("button", { class: "btn ghost", onclick: () => { S.allHosts = true; draw(); } }, "Alle " + matching.length + " anzeigen")));
    }
    holder.replaceChildren(...kids);
  };
  draw();
  return [h("h2", {}, "Deine Hosts" + (hosts.length ? " (" + hosts.length + ")" : "")), hosts.length > SHOWN ? query : null, holder];
}

function hostRow(host, n) {
  const del = host.managed ? h("button", { class: "icon-btn", title: "Entfernen", html: ICON.trash })
    : h("span", { class: "chip", title: "Nicht von Pforte angelegt — in OPNsense selbst ändern" }, "manuell");
  if (host.managed) {
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) {
        armed = true;
        del.replaceChildren(document.createTextNode("Sicher?"));
        del.style.width = "auto"; del.style.padding = "0 14px"; del.style.borderRadius = "999px"; del.style.color = "var(--bad)";
        setTimeout(() => { if (document.body.contains(del)) { armed = false; del.innerHTML = ICON.trash; del.style.cssText = ""; } }, 3500);
        return;
      }
      removeHost(host);
    });
  }
  return h("div", { class: "host", style: "animation-delay:" + Math.min(n, 8) * 40 + "ms" },
    h("div", { class: "dot" }),
    h("div", { class: "main" },
      h("a", { href: hostUrl(host), target: "_blank", rel: "noopener" }, host.host + (host.path || "")),
      h("div", { class: "sub" }, "→ " + (host.ssl ? "https://" : "") + host.target + (host.listener ? "  ·  " + host.listener : ""))),
    del);
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
    await sleep(250);
  }
  await sleep(350);
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
  const fresh = await api("/api/overview?profile=" + encodeURIComponent(S.cfg.active)).catch(() => null);
  if (fresh) S.ov = fresh;
  const l = S.ov.listeners.find((x) => x.uuid === f.listener);
  const url = (l && l.ports.length && !l.ports.includes(443) && l.ports.includes(80) ? "http://" : "https://") + host;
  mount(header(), h("div", { class: "card success" },
    h("div", { html: '<svg class="check" viewBox="0 0 84 84"><circle cx="42" cy="42" r="30"/><path d="M29 43l9 9 18-19"/></svg>' }),
    h("a", { class: "hostname", href: url, target: "_blank", rel: "noopener" }, host),
    h("p", { class: "lead" }, "ist angelegt und HAProxy hat die neue Konfiguration geladen."),
    warnings.map((w) => h("div", { class: "notice" }, w)),
    h("div", { class: "row", style: "justify-content:center;margin-top:18px" },
      h("a", { class: "btn", href: url, target: "_blank", rel: "noopener" }, "Öffnen"),
      h("button", { class: "btn ghost", onclick: () => renderMain() }, "Noch ein Host"))),
    hostList());
}

async function removeHost(host) {
  const result = await runJob(host.host + " entfernen", () => api("/api/remove", { profile: S.cfg.active, uuid: host.uuid }));
  if (!result.ok) toast(result.error);
  else toast(host.host + " ist entfernt");
  loadMain();
}

/* ---------- Einrichtung (Wizard) ---------- */

function startWizard(options) {
  const o = options || {};
  const base = o.edit || null;
  const blank = () => ({ url: "", verify: true });
  S.wiz = {
    first: !!o.first, previous: base ? base.name : null,
    step: o.step != null ? o.step : (o.first ? 0 : 1),
    draft: {
      opnsense: base ? { ...base.opnsense } : { ...blank(), key: "", secret: "" },
      adguard: base && base.adguard ? { ...base.adguard } : { ...blank(), username: "admin", password: "", target: "" },
      portainer: base && base.portainer ? { ...base.portainer } : { ...blank(), api_key: "" },
    },
    use: { adguard: !!(base && base.adguard), portainer: !!(base && base.portainer) },
    tested: {},
    error: null, busy: false,
  };
  if (base) { S.wiz.tested.opnsense = true; }
  renderWizard();
}

const STEPS = ["Willkommen", "OPNsense", "AdGuard", "Portainer"];

function renderWizard() {
  const w = S.wiz;
  const first = w.step === 0;
  const dots = h("div", { class: "dots" }, STEPS.slice(1).map((_, i) => h("i", {
    class: (w.step >= i + 1 ? "on" : "") + (w.previous ? " click" : ""),
    onclick: w.previous ? () => { w.step = i + 1; w.error = null; renderWizard(); } : null })));
  let body;
  if (first) body = stepWelcome();
  else if (w.step === 1) body = stepOpnsense();
  else if (w.step === 2) body = stepAdguard();
  else body = stepPortainer();
  const back = (S.cfg && S.cfg.profiles.length && !w.previous && w.step <= 1)
    ? h("button", { class: "link", onclick: loadMain }, "Abbrechen")
    : (w.previous && w.step >= 1 ? h("button", { class: "link", onclick: loadMain }, "Schließen") : null);
  mount(S.cfg && S.cfg.profiles.length ? header() : h("header", {}, h("div", { class: "brand" }, h("img", { src: "logo.svg", alt: "" }), "Pforte")),
    h("div", { class: "card", id: "wizard" }, first ? null : dots, body), h("div", { class: "row", style: "margin-top:14px;justify-content:center" }, back));
}

function field(label, key, section, opts) {
  const o = opts || {};
  const d = S.wiz.draft[section];
  const secretSet = o.secret && S.wiz.previous && d.has_secret;
  return h("label", { class: "field" }, h("span", {}, label),
    h("input", { type: o.secret ? "password" : "text", placeholder: secretSet ? "unverändert — nur zum Ändern eintippen" : (o.placeholder || ""),
      value: d[key] || "", autocomplete: "off", spellcheck: "false", autocapitalize: "off",
      oninput: (e) => { d[key] = e.target.value; S.wiz.tested[section] = false; } }));
}

function errorBox(section) {
  const w = S.wiz;
  if (!w.error) return null;
  const box = h("div", { class: "notice bad" }, w.error.message);
  if (w.error.code === "tls") {
    box.append(h("div", { style: "margin-top:10px" }, h("button", { class: "btn ghost", onclick: () => {
      w.draft[section].verify = false; w.error = null; advance(section);
    } }, "Trotzdem verbinden")));
  }
  return box;
}

function stepWelcome() {
  const w = S.wiz, imp = S.cfg.importable || [];
  return h("div", {},
    h("div", { class: "hero" }, h("img", { src: "logo.svg", alt: "" }), h("h1", {}, "Willkommen an der Pforte"),
      h("p", { class: "lead" }, "Neue Webseiten im Heimnetz erreichbar machen — ein Name, ein Ziel, ein Klick. Dafür brauche ich einmalig drei Zugänge, zwei davon sind optional.")),
    imp.length ? h("div", { class: "notice info" }, "Es gibt Einstellungen aus der alten Version (" + imp.join(", ") + "). ",
      h("button", { class: "link", onclick: async () => { S.cfg = await api("/api/import", {}); toast("Übernommen"); loadMain(); } }, "Übernehmen")) : null,
    h("button", { class: "btn big", onclick: () => { w.step = 1; renderWizard(); } }, "Los geht’s"));
}

function stepOpnsense() {
  const w = S.wiz, d = w.draft.opnsense;
  return h("div", {},
    h("h1", {}, "OPNsense"),
    h("p", { class: "lead" }, "Hier wird HAProxy eingerichtet. Pforte meldet sich mit einem API-Schlüssel an, nicht mit deinem Passwort."),
    field("Adresse der OPNsense", "url", "opnsense", { placeholder: "https://192.168.1.1" }),
    field("API-Key", "key", "opnsense", { secret: true }),
    field("API-Secret", "secret", "opnsense", { secret: true }),
    h("details", {}, h("summary", {}, "Wo bekomme ich den Schlüssel?"),
      h("div", { class: "body" }, h("ol", {},
        h("li", {}, "OPNsense → System → Zugriff → Benutzer → neuen Benutzer anlegen (z. B. „pforte“)."),
        h("li", {}, "Benutzer öffnen, unter „Effektive Berechtigungen“ hinzufügen: „Services: HAProxy“ und „Services: ACME Client“. Speichern."),
        h("li", {}, "In der Benutzerübersicht in der Zeile des Benutzers das Schlüssel-Symbol („API-Schlüssel erstellen“) klicken."),
        h("li", {}, "Die heruntergeladene Datei enthält zwei Zeilen: key=… und secret=… — jeweils nur den Teil hinter dem Gleichheitszeichen eintragen."))),
      h("div", { class: "small", style: "padding:6px 4px" }, "Das Secret zeigt OPNsense nur dieses eine Mal an.")),
    errorBox("opnsense"),
    nav("opnsense", null));
}

function stepAdguard() {
  const w = S.wiz;
  return h("div", {},
    h("h1", {}, "AdGuard Home"),
    h("p", { class: "lead" }, "Damit neue Namen im Heimnetz auch gefunden werden, trägt Pforte den DNS-Eintrag gleich mit ein. Ohne AdGuard machst du das selbst."),
    field("Adresse von AdGuard", "url", "adguard", { placeholder: "http://192.168.1.2:3000" }),
    field("Benutzer", "username", "adguard"),
    field("Passwort", "password", "adguard", { secret: true }),
    field("Neue Namen sollen zeigen auf (IP von HAProxy)", "target", "adguard", { placeholder: "192.168.1.1" }),
    errorBox("adguard"),
    nav("adguard", "Ohne AdGuard weiter"));
}

function stepPortainer() {
  return h("div", {},
    h("h1", {}, "Portainer"),
    h("p", { class: "lead" }, "Optional. Mit Portainer schlägt Pforte beim Ziel deine laufenden Container samt Port vor."),
    field("Adresse von Portainer", "url", "portainer", { placeholder: "https://192.168.1.20:9443" }),
    field("Zugriffstoken", "api_key", "portainer", { secret: true }),
    h("details", {}, h("summary", {}, "Wo bekomme ich den Token?"),
      h("div", { class: "body" }, "Portainer → oben rechts dein Benutzername → „Mein Konto“ → „Zugriffstoken hinzufügen“. Der Token wird nur einmal angezeigt.")),
    errorBox("portainer"),
    nav("portainer", "Ohne Portainer fertig"));
}

function nav(section, skipText) {
  const w = S.wiz;
  const last = section === "portainer";
  const go = h("button", { class: "btn", disabled: w.busy, onclick: () => advance(section) },
    w.busy ? h("div", { class: "spinner" }) : null, w.busy ? "Prüfe …" : (last ? "Fertig" : "Weiter"));
  const row = h("div", { class: "row between", style: "margin-top:6px" },
    skipText ? h("button", { class: "link", onclick: () => skip(section) }, skipText) : h("span"),
    go);
  return row;
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
  w.busy = true; renderWizard();
  try {
    const info = await api("/api/test", { kind: section, settings: d, profile: w.previous });
    w.tested[section] = true;
    if (section === "opnsense" && info.address && !w.draft.adguard.target) w.draft.adguard.target = info.address;
    w.use[section] = true;
  } catch (e) {
    w.busy = false; w.error = e; return renderWizard();
  }
  w.busy = false;
  if (section === "opnsense") { w.step = 2; return renderWizard(); }
  if (section === "adguard") { w.step = 3; return renderWizard(); }
  return finish();
}

function skip(section) {
  const w = S.wiz;
  w.use[section] = false; w.error = null;
  if (section === "adguard") { w.step = 3; return renderWizard(); }
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
  S.wiz = null;
  loadMain();
}

boot();
