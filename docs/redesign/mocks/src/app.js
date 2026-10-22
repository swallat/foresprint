// Shell, router and helpers shared by all mock views.
// Views register with FS.view(id, {...}); flows with FS.flow({...}). Navigation uses bare hash
// tokens (#backlog, #plan) because the artifact viewer passes only those through.
(function () {
  const D = window.DEMO;
  const FS = (window.FS = { views: {}, flows: [], state: { sprint: "2026.22", theme: null, calcMode: "icon" } });

  // ---------- helpers ----------
  FS.esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  FS.icon = (name, extra = "") => `<span class="ms ${extra}" aria-hidden="true">${name}</span>`;
  FS.product = (id) => D.products.find((p) => p.id === id);
  FS.project = (id) => D.projects.find((p) => p.id === id);
  FS.person = (id) => D.people.find((p) => p.id === id);
  FS.po = (id) => D.pos.find((p) => p.id === id);
  FS.sprint = (id) => D.sprints.find((s) => s.id === id);
  FS.ticket = (key) => D.tickets.find((t) => t.key === key);
  FS.fmtDate = (iso) => { const [y, m, d] = iso.split("-"); return `${d}.${m}.${y.slice(2)}`; };
  FS.fmt = (n, digits = 0) => (n == null ? "–" : Number(n).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
  FS.sum = (arr, f = (x) => x) => arr.reduce((a, x) => a + (Number(f(x)) || 0), 0);
  // Reference capacity: full team without absences (display scale of the normalized velocity, as in 0.8)
  // Optional features show up only when configured: several products, several POs, production share.
  FS.multiProduct = () => D.products.length > 1;
  FS.multiPO = () => D.pos.length > 1;
  FS.prodOn = () => FS.state.teamApplied?.prod !== false;
  // Demo switch: Team Atlas with every feature, or a simple team (one PO, one product, no production share)
  FS.setSimple = (on) => {
    FS._full ??= structuredClone(D);
    Object.keys(FS._full).forEach((k) => (D[k] = structuredClone(FS._full[k])));
    FS.state.simple = on;
    FS.state.sp = undefined;
    if (FS.state.bl) { FS.state.bl.products = []; if (FS.state.bl.group === "product") FS.state.bl.group = "none"; }
    if (FS.state.teamApplied) { FS.state.teamApplied.prod = !on; FS.state.teamDraft = { ...FS.state.teamApplied }; }
    if (!on) { FS.state.rules = FS._fullRules ?? FS.state.rules; FS.state.ruleDraft = { product: D.products[0].id }; return; }
    FS._fullRules ??= FS.state.rules;
    const ids = D.products.map((p) => p.id);
    D.products = [{ id: "team", name: D.team.name, po: D.pos[0].id, share: 1, color: "#4646d4" }];
    D.pos = [D.pos[0]];
    D.tickets.forEach((t) => (t.product = "team"));
    D.projects.forEach((p) => (p.products = ["team"]));
    const add = (rows) => rows.reduce((a, r) => { Object.entries(r || {}).forEach(([k, v]) => { if (typeof v === "number") a[k] = (a[k] ?? 0) + v; else if (v == null && !(k in a)) a[k] = null; }); return a; }, {});
    Object.keys(D.productPlan).forEach((sid) => (D.productPlan[sid] = { team: add(ids.map((id) => D.productPlan[sid][id])) }));
    if (D.productHistory) Object.keys(D.productHistory).forEach((sid) => { const r = ids.map((id) => D.productHistory[sid][id]); D.productHistory[sid] = { team: r[0].map((_, i) => (r.some((x) => x[i] == null) ? null : FS.sum(r, (x) => x[i]))) }; });
    FS.state.rules = { team: "" };
    FS.state.ruleDraft = { product: "team" };
  };
  // Absences removed since the last save stay visible as a ghost value until Save, so a slip can be undone
  FS.absGhost = () => (FS.state.absGhost ??= {});
  FS.ghostAbs = (sid, pid, cell) => { if (cell) FS.absGhost()[`${sid}|${pid}`] = { ...cell }; };
  FS.restoreAbs = (sid, pid) => { const g = FS.absGhost()[`${sid}|${pid}`]; if (!g) return; (D.absences[sid] ??= {})[pid] = { ...g }; delete FS.absGhost()[`${sid}|${pid}`]; };
  document.addEventListener("click", (e) => { if (e.target.closest("#btn-save") && Object.keys(FS.absGhost()).length) { FS.state.absGhost = {}; setTimeout(() => ["prepare", "people"].includes(location.hash.slice(1)) && FS.render(), 0); } });
  FS.refCap = () => Math.round(FS.sum(D.people, (p) => p.fte) * 10);
  FS.normVel = (s) => (s.velocity == null ? null : (s.velocity / s.capacityPD) * FS.refCap());

  // Ticket key with tracker link (rule: every ticket links to its tracker)
  FS.keyLink = (t) => `<span class="key"><a href="${D.team.trackerUrl}${t.key}" target="_blank" rel="noopener" title="In ${D.team.tracker} öffnen">${t.key}${FS.icon("open_in_new")}</a></span>`;
  FS.productChip = (id) => { const p = FS.product(id); return p ? `<span class="chip"><span class="dot" style="background:${p.color}"></span>${FS.esc(p.name)}</span>` : ""; };
  FS.projectChip = (id) => { const p = FS.project(id); return p ? `<span class="chip">${FS.icon("flag", "small")}${FS.esc(p.name)}</span>` : `<span class="chip muted">Tagesgeschäft</span>`; };
  FS.lightChip = (l, text) => { const m = { ok: ["ok", "check_circle", "im Plan"], warn: ["warn", "error", "knapp"], bad: ["bad", "cancel", "gefährdet"] }[l]; return `<span class="chip ${m[0]}">${FS.icon(m[1])}${text || m[2]}</span>`; };
  FS.refinedChip = (t) => (t.refined ? "" : `<span class="chip warn" title="Nicht refined">${FS.icon("help")}offen</span>`);
  FS.estHtml = (t) => (t.est == null ? `<span class="est muted" title="Keine Schätzung">?</span>` : `<span class="est">${t.est}</span>`);

  // Standard ticket row; opts.drag adds a drag handle
  FS.ticketRow = (t, opts = {}) => `
    <div class="ticket" data-key="${t.key}" ${opts.drag ? 'draggable="true"' : ""} tabindex="0" aria-label="${t.key} ${FS.esc(t.title)}">
      <span class="handle">${opts.drag ? FS.icon("drag_indicator") : ""}</span>
      ${FS.keyLink(t)}
      <span class="title">${FS.esc(t.title)}</span>
      <span class="meta">${FS.refinedChip(t)}${opts.noProduct || !FS.multiProduct() ? "" : FS.productChip(t.product)}${opts.noProject ? "" : FS.projectChip(t.project)}${FS.estHtml(t)}</span>
    </div>`;

  // Capacity bar: used vs forecast range (all in points)
  FS.capBar = (used, fc, low, high, max) => {
    max = max || Math.max(high || 0, used) * 1.15;
    const pct = (v) => Math.max(0, Math.min(100, (v / max) * 100));
    const over = high != null && used > high;
    return `<div class="cap" title="${FS.fmt(used)} von ${FS.fmt(fc)} Punkten (Spanne ${FS.fmt(low)} bis ${FS.fmt(high)})">
      ${low != null ? `<div class="fc" style="left:${pct(low)}%;width:${pct(high) - pct(low)}%"></div>` : ""}
      <div class="used ${over ? "over" : ""}" style="width:${pct(used)}%"></div></div>`;
  };

  FS.toast = (msg, undo) => {
    document.querySelectorAll(".toast").forEach((t) => t.remove());
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.innerHTML = `<span>${msg}</span>${undo ? `<button type="button">Rückgängig</button>` : ""}`;
    if (undo) el.querySelector("button").onclick = () => { undo(); el.remove(); };
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  };

  FS.openPanel = (title, html) => {
    FS.closePanel();
    const el = document.createElement("aside");
    el.className = "panel";
    el.setAttribute("aria-label", title);
    if (/^Rechenweg/.test(title) && !FS.capturing) html += `<p class="small" style="margin:0"><a href="#help">${FS.icon("help", "small")} Ausführlich erklärt in Hilfe > Rechenwege</a></p>`;
    if (FS.capturing) { FS.captured = html; return null; }
    el.innerHTML = `<div class="panel-head"><strong style="flex:1">${title}</strong><button class="btn icon ghost" type="button" aria-label="Schließen">${FS.icon("close")}</button></div><div class="panel-body">${html}</div>`;
    el.querySelector(".panel-head button").onclick = FS.closePanel;
    document.body.appendChild(el);
    return el;
  };
  FS.closePanel = () => document.querySelectorAll(".panel").forEach((p) => p.remove());

  // Ticket details fetched read-only from the tracker; tickets without demo details get a short stand-in
  FS.detail = (t) => D.details[t.key] || { type: "Story", priority: "Mittel", reporter: "Kim Berger", assignee: null, updated: "17.10.26 11:05", labels: [], components: [FS.product(t.product)?.name || ""], epic: FS.project(t.project)?.name || null,
    description: `${t.title}. Die ausführliche Beschreibung steht im Ticket in ${D.team.tracker} und erscheint hier nach dem Abruf.`, acceptance: [], subtasks: [], links: [], comments: [], commentsTotal: 0, attachments: [] };
  const dText = (txt) => txt.split("\n\n").map((p) => `<p style="margin:0 0 8px">${FS.esc(p)}</p>`).join("");
  const dLinks = (d) => d.links.map(([rel, key, title]) => `<li><span class="muted">${rel}</span> ${FS.keyLink({ key })} ${FS.esc(title)}</li>`).join("");
  const dSubs = (d) => d.subtasks.map(([key, title, st]) => `<li>${FS.keyLink({ key })} ${FS.esc(title)} <span class="chip small">${st}</span></li>`).join("");
  const dComments = (d) => d.comments.map(([who, at, txt]) => `<div class="td-comment"><div class="small"><strong>${FS.esc(who)}</strong> <span class="muted data">${at}</span></div><div>${FS.esc(txt)}</div></div>`).join("") +
    (d.commentsTotal > d.comments.length ? `<p class="small muted" style="margin:0">${d.commentsTotal - d.comments.length} ältere Kommentare ausgeblendet. <button class="link" type="button">Alle zeigen</button></p>` : "");
  const dFiles = (d) => d.attachments.map(([n, kind, size]) => `<li class="row" style="gap:6px">${FS.icon(kind === "Bild" ? "image" : "description", "small")}<span class="data">${FS.esc(n)}</span><span class="muted small">${size}</span></li>`).join("");
  const sect = (title, body, empty) => `<section class="td-sec"><h3>${title}</h3>${body || `<p class="muted small" style="margin:0">${empty}</p>`}</section>`;
  // Jira content blocks shared by the side panel and the presentation view
  FS.trackerBlocks = (t) => {
    const d = FS.detail(t);
    return sect("Beschreibung", dText(d.description)) +
      sect("Akzeptanzkriterien", d.acceptance.length ? `<ul class="td-list">${d.acceptance.map((x) => `<li>${FS.esc(x)}</li>`).join("")}</ul>` : "", "Keine eigenen Akzeptanzkriterien (Feld zuordnen unter Einstellungen > Jira und Tickets).") +
      sect(`Unteraufgaben <span class="muted small">${d.subtasks.length}</span>`, d.subtasks.length ? `<ul class="td-list">${dSubs(d)}</ul>` : "", "Keine.") +
      sect("Verknüpfungen", d.links.length ? `<ul class="td-list">${dLinks(d)}</ul>` : "", "Keine.") +
      sect(`Kommentare <span class="muted small">${d.commentsTotal}</span>`, dComments(d), "Keine.") +
      sect(`Anhänge <span class="muted small">${d.attachments.length}</span>`, d.attachments.length ? `<ul class="td-list" style="list-style:none;padding:0">${dFiles(d)}</ul>` : "", "Keine.");
  };
  const facts = (t) => { const d = FS.detail(t); return `<dl class="kv">
        <dt>Typ, Priorität</dt><dd>${d.type} · ${d.priority}</dd>
        <dt>Zuständig</dt><dd>${d.assignee ? FS.esc(d.assignee) : `<span class="muted">niemand</span>`}</dd>
        <dt>Labels</dt><dd>${d.labels.length ? d.labels.map((l) => `<span class="chip small data">${FS.esc(l)}</span>`).join(" ") : `<span class="muted">keine</span>`}</dd>
        <dt>Stand</dt><dd class="small muted">Abruf ${D.trackerSync.last}, in ${D.team.tracker} geändert ${d.updated}</dd></dl>`; };

  FS.ticketPanel = (key) => {
    const t = FS.ticket(key);
    const opts = (list, cur, label) => list.map((x) => `<option value="${x.id}" ${x.id === cur ? "selected" : ""}>${FS.esc(x.name)}</option>`).join("");
    const el = FS.openPanel(`${t.key}`, `
      <div class="row">${FS.keyLink(t)}<span class="chip">${FS.esc(t.status)}</span><span style="flex:1"></span><button class="btn" type="button" id="tp-present" title="Ticket groß im Fenster zeigen, mit Pfeiltasten blättern">${FS.icon("fit_screen")}Großansicht</button></div>
      <h2 style="margin:0">${FS.esc(t.title)}</h2>
      <dl class="kv">
        <dt class="only-multiprod">Produkt</dt><dd class="only-multiprod"><select class="input" id="tp-product">${opts(D.products, t.product)}</select></dd>
        <dt>Projekt</dt><dd><select class="input" id="tp-project"><option value="">Tagesgeschäft</option>${opts(D.projects, t.project)}</select></dd>
        <dt>Schätzung</dt><dd class="data">${t.est ?? "keine"} Punkte <span class="muted small">aus ${D.team.tracker}</span></dd>
        <dt>Refined</dt><dd>${t.refined ? FS.lightChip("ok", "ja") : FS.lightChip("warn", "nein")}</dd>
        <dt>Vorgemerkt</dt><dd>${t.sprint ? `<span class="chip">${FS.icon("event")}Sprint ${t.sprint}</span>` : `<span class="muted">nicht vorgemerkt</span>`}</dd>
        ${t.inTrackerSprint ? `<dt>Im ${D.team.tracker}-Sprint</dt><dd class="data">${t.inTrackerSprint}</dd>` : ""}
      </dl>
      <div class="field"><label for="tp-note">Notiz zur Vormerkung</label><textarea class="input" id="tp-note" rows="2" placeholder="z. B. mit Kim abgestimmt"></textarea></div>
      <p class="small muted only-multiprod" style="margin:0">Produkt per Regel (Komponente = Portal). Abweichung hier überschreibt die Regel nur für dieses Ticket.</p>
      <h2 style="margin:8px 0 0">Aus ${D.team.tracker} <span class="chip small">nur gelesen</span></h2>
      ${facts(t)}
      ${FS.trackerBlocks(t)}
      <h2>Verlauf in Foresprint</h2>
      <ul class="small" style="margin:0;padding-left:18px"><li>21.10. Kim Berger: vorgemerkt für 2026.22</li><li>18.10. Abruf aus ${D.team.tracker}: Schätzung 5</li></ul>`);
    if (el) el.querySelector("#tp-present").onclick = () => FS.presentTicket(key);
  };

  // Presentation view: one ticket fills the window, arrows step through the list on screen.
  // Built for sharing a single app window in planning and refinement meetings.
  FS.presentTicket = (key, keys) => {
    keys ??= [...new Set([...document.querySelectorAll("#main .ticket[data-key]")].map((e) => e.dataset.key))];
    if (!keys.includes(key)) keys = [key, ...keys];
    FS.closePanel();
    document.querySelectorAll(".present").forEach((p) => p.remove());
    const el = document.createElement("div");
    el.className = "present";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    const draw = () => {
      const t = FS.ticket(key), d = FS.detail(t), i = keys.indexOf(key), sid = FS.state.sprint, inSp = t.sprint === sid;
      const onPlan = location.hash.slice(1) === "plan";
      const inSprint = D.tickets.filter((x) => x.sprint === sid), pts = FS.sum(inSprint, (x) => x.est), sp = FS.sprint(sid);
      el.setAttribute("aria-label", `${t.key} ${t.title}`);
      el.innerHTML = `<div class="present-head">
          ${FS.keyLink(t)}<span class="chip">${FS.esc(t.status)}</span>${FS.refinedChip(t)}${FS.multiProduct() ? FS.productChip(t.product) : ""}${FS.projectChip(t.project)}
          <span style="flex:1"></span>
          <span class="small muted data">${i + 1} von ${keys.length}</span>
          <button class="btn icon" type="button" data-step="-1" aria-label="Vorheriges Ticket" ${i <= 0 ? "disabled" : ""}>${FS.icon("chevron_left")}</button>
          <button class="btn icon" type="button" data-step="1" aria-label="Nächstes Ticket" ${i >= keys.length - 1 ? "disabled" : ""}>${FS.icon("chevron_right")}</button>
          <button class="btn icon ghost" type="button" data-close aria-label="Großansicht schließen">${FS.icon("close")}</button></div>
        <div class="present-body"><div class="present-main">
          <h1>${FS.esc(t.title)}</h1>
          ${FS.trackerBlocks(t)}</div>
          <aside class="present-side">
            <div class="present-est"><span class="data">${t.est ?? "?"}</span><span class="small muted">Punkte</span></div>
            ${onPlan ? `<div class="card stack" style="gap:8px"><div class="small muted">Sprint <span class="data">${sid}</span>: <strong class="data">${pts}</strong> von <span class="data">${sp.forecast}</span> Punkten</div>${FS.capBar(pts, sp.forecast, sp.low, sp.high)}
              <button class="btn ${inSp ? "" : "primary"}" type="button" data-move>${FS.icon(inSp ? "remove" : "add")}${inSp ? "Aus dem Sprint nehmen" : `In Sprint ${sid} nehmen`}</button></div>` : ""}
            ${facts(t)}
            <dl class="kv"><dt>Vorgemerkt</dt><dd>${t.sprint ? `Sprint ${t.sprint}` : `<span class="muted">nicht vorgemerkt</span>`}</dd><dt>Epic</dt><dd>${d.epic ? FS.esc(d.epic) : `<span class="muted">keins</span>`}</dd></dl>
            <p class="small muted" style="margin:0">Pfeiltasten blättern, Esc schließt. ${onPlan ? "Leertaste nimmt das Ticket in den Sprint oder heraus." : ""}</p>
          </aside></div>`;
      el.querySelectorAll("[data-step]").forEach((b) => (b.onclick = () => step(+b.dataset.step)));
      el.querySelector("[data-close]").onclick = close;
      const mv = el.querySelector("[data-move]"); if (mv) mv.onclick = move;
    };
    const step = (n) => { const i = keys.indexOf(key) + n; if (i < 0 || i >= keys.length) return; key = keys[i]; draw(); };
    const move = () => { FS.moveTicket(key, FS.ticket(key).sprint === FS.state.sprint ? "backlog" : FS.state.sprint, null); FS.keepPresent = true; FS.render(); FS.keepPresent = false; draw(); };
    const onKey = (e) => {
      if (e.target.closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") step(1); else if (e.key === "ArrowLeft") step(-1); else if (e.key === "Escape") close();
      else if (e.key === " " && el.querySelector("[data-move]")) { e.preventDefault(); move(); } else return;
    };
    const close = () => { el.remove(); window.removeEventListener("keydown", onKey); FS.presentClose = null; };
    FS.presentClose?.(); FS.presentClose = close;
    window.addEventListener("keydown", onKey);
    document.body.appendChild(el);
    draw();
    el.querySelector("[data-close]").focus();
  };


  // ---------- assignment rules (same language for products and projects, as in 0.8 ruleexpr) ----------
  // Fields: component, label, epic, priority, type, status. Operators: = != ~ !~ IN, NOT IN; AND OR NOT, parentheses.
  const COMP = { portal: "Portal", billing: "Abrechnung", mobile: "Mobile App", platform: "Plattform" };
  FS.ruleFields = ["component", "label", "epic", "priority", "type", "status"];
  FS.ticketFields = (t) => { const d = D.details[t.key]; return { component: [COMP[t.product]], label: ["team-" + t.product, t.refined ? "refined" : "", ...(d?.labels || [])].filter(Boolean), epic: [t.project ? FS.project(t.project).name : ""].filter(Boolean), priority: [d?.priority || "Mittel"], type: [d?.type || "Story"], status: [t.status] }; };
  FS.parseRule = (src) => {
    const toks = []; const re = /\s*(?:("(?:[^"\\]|\\.)*")|(!=|!~|=|~|\(|\)|,)|([A-Za-zÄÖÜäöüß_][\w.-]*))/gy; let m, pos = 0;
    while (pos < src.length) { re.lastIndex = pos; m = re.exec(src); if (!m || m[0].length === 0) { if (/^\s*$/.test(src.slice(pos))) break; throw new Error(`Unerwartetes Zeichen an Stelle ${pos + 1}`); } toks.push(m[1] ? { s: JSON.parse(m[1]) } : m[2] ? { o: m[2] } : { w: m[3] }); pos = re.lastIndex; }
    let i = 0; const peek = () => toks[i], kw = (k) => peek()?.w?.toUpperCase() === k, eat = (o) => { if (peek()?.o !== o) throw new Error(`"${o}" erwartet`); i++; };
    const val = () => { const t = toks[i++]; if (!t || t.o) throw new Error("Wert erwartet"); return t.s ?? t.w; };
    const cond = () => {
      if (kw("NOT")) { i++; return { not: cond() }; }
      if (peek()?.o === "(") { i++; const e = or(); eat(")"); return e; }
      const f = toks[i++]?.w?.toLowerCase(); if (!FS.ruleFields.includes(f)) throw new Error(`Unbekanntes Feld "${f ?? ""}". Felder: ${FS.ruleFields.join(", ")}`);
      let op; if (kw("NOT")) { i++; if (!kw("IN")) throw new Error("NOT IN erwartet"); i++; op = "NOT IN"; } else if (kw("IN")) { i++; op = "IN"; } else { op = toks[i++]?.o; if (!["=", "!=", "~", "!~"].includes(op)) throw new Error(`Operator nach ${f} erwartet (= != ~ !~ IN)`); }
      if (op.endsWith("IN")) { eat("("); const vs = [val()]; while (peek()?.o === ",") { i++; vs.push(val()); } eat(")"); return { f, op, vs }; }
      return { f, op, vs: [val()] };
    };
    const and = () => { let l = cond(); while (kw("AND")) { i++; l = { and: [l, cond()] }; } return l; };
    const or = () => { let l = and(); while (kw("OR")) { i++; l = { or: [l, and()] }; } return l; };
    if (!toks.length) return null; const tree = or(); if (i < toks.length) throw new Error("Ausdruck endet nicht sauber, AND oder OR fehlt?"); return tree;
  };
  const evalTree = (n, fv) => {
    if (n.not) return !evalTree(n.not, fv); if (n.and) return n.and.every((x) => evalTree(x, fv)); if (n.or) return n.or.some((x) => evalTree(x, fv));
    const have = fv[n.f].map((v) => v.toLowerCase()), want = n.vs.map((v) => v.toLowerCase());
    const eq = have.some((h) => want.includes(h)), con = have.some((h) => want.some((w) => h.includes(w)));
    return { "=": eq, IN: eq, "!=": !eq, "NOT IN": !eq, "~": con, "!~": !con }[n.op];
  };
  FS.ruleMatches = (expr) => { try { const tr = FS.parseRule(expr || ""); return tr ? D.tickets.filter((t) => evalTree(tr, FS.ticketFields(t))) : []; } catch (e) { return []; } };
  // Rule editor with live preview. kind: "product" | "project"; others: [{id, name, rule}] of the same kind
  FS.ruleEditor = (kind, owner, expr, others) => `<div class="stack rule-ed" data-rule-kind="${kind}" data-rule-owner="${owner}" style="gap:8px">
      <div class="field"><label for="re-${owner}">Regel für ${FS.esc((kind === "product" ? FS.product(owner) : FS.project(owner))?.name || "")}</label><textarea class="input data" id="re-${owner}" rows="2" spellcheck="false">${FS.esc(expr || "")}</textarea></div>
      <div class="small muted">Felder: ${FS.ruleFields.map((f) => `<button class="link data" type="button" data-ins="${f} = &quot;&quot;">${f}</button>`).join(" ")} · Operatoren <span class="data">= != ~ !~ IN NOT IN AND OR NOT ( )</span> · weitere Felder unter Einstellungen > Jira und Tickets</div>
      <div class="banner info rule-prev" style="margin:0">${FS.icon("preview")}<div class="grow"></div></div></div>`;
  FS.wireRuleEditor = (root, others, onApplyBtn) => {
    const box = root.querySelector(".rule-ed"); if (!box) return;
    const kind = box.dataset.ruleKind, owner = box.dataset.ruleOwner, ta = box.querySelector("textarea"), prev = box.querySelector(".rule-prev .grow");
    const cur = (t) => (kind === "product" ? t.product : t.project);
    const upd = () => {
      let m; try { const tr = FS.parseRule(ta.value); m = tr ? D.tickets.filter((t) => evalTree(tr, FS.ticketFields(t))) : []; } catch (e) { prev.innerHTML = `<strong>Regel unvollständig:</strong> ${FS.esc(e.message)}`; box.querySelector(".rule-prev").className = "banner warn rule-prev"; return; }
      box.querySelector(".rule-prev").className = "banner info rule-prev";
      const clash = m.filter((t) => others.some((o) => o.id !== owner && FS.ruleMatches(o.rule).includes(t)));
      const moved = m.filter((t) => cur(t) && cur(t) !== owner);
      prev.innerHTML = `<strong class="data">${m.length}</strong> Tickets passen (<span class="data">${FS.sum(m, (t) => t.est || 0)}</span> Punkte)${moved.length ? `, <span class="data">${moved.length}</span> davon heute anders zugeordnet` : ""}${clash.length ? `. <span class="chip warn">${clash.length} passen auch auf eine andere Regel</span> (Reihenfolge entscheidet, Widerspruch erscheint in der Vorschau)` : ""}.
        <div class="small" style="margin-top:4px">${m.slice(0, 5).map((t) => FS.keyLink(t) + " ").join("")}${m.length > 5 ? `<span class="muted">und ${m.length - 5} weitere</span>` : ""}</div>`;
    };
    ta.addEventListener("input", upd);
    box.querySelectorAll("[data-ins]").forEach((b) => (b.onclick = () => { const p = ta.selectionStart ?? ta.value.length; const add = (ta.value.trim() && p === ta.value.length ? " AND " : "") + b.dataset.ins; ta.value = ta.value.slice(0, p) + add + ta.value.slice(p); ta.focus(); ta.selectionStart = ta.selectionEnd = p + add.length - 1; upd(); }));
    upd();
    return () => ta.value.trim();
  };

  // ---------- drag and drop with keyboard alternative ----------
  // FS.dnd(root, { onDrop(key, zoneId, beforeKey) }) for .ticket[draggable] inside [data-zone]
  FS.dnd = (root, { onDrop }) => {
    let dragKey = null;
    root.querySelectorAll(".ticket[draggable]").forEach((el) => {
      el.addEventListener("dragstart", (e) => { dragKey = el.dataset.key; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragKey); });
      el.addEventListener("dragend", () => { el.classList.remove("dragging"); root.querySelectorAll(".drop-line").forEach((l) => l.remove()); root.querySelectorAll(".over").forEach((z) => z.classList.remove("over")); });
      el.addEventListener("keydown", (e) => {
        if (!e.altKey) return;
        const zones = [...root.querySelectorAll("[data-zone]")];
        const zone = el.closest("[data-zone]");
        const items = [...zone.querySelectorAll(".ticket")];
        const i = items.indexOf(el);
        if (e.key === "ArrowUp" && i > 0) { e.preventDefault(); onDrop(el.dataset.key, zone.dataset.zone, items[i - 1].dataset.key, true); }
        if (e.key === "ArrowDown" && i < items.length - 1) { e.preventDefault(); onDrop(el.dataset.key, zone.dataset.zone, items[i + 2]?.dataset.key || null, true); }
        const zi = zones.indexOf(zone);
        if (e.key === "ArrowRight" && zi < zones.length - 1) { e.preventDefault(); onDrop(el.dataset.key, zones[zi + 1].dataset.zone, null, true); }
        if (e.key === "ArrowLeft" && zi > 0) { e.preventDefault(); onDrop(el.dataset.key, zones[zi - 1].dataset.zone, null, true); }
      });
    });
    root.querySelectorAll("[data-zone]").forEach((zone) => {
      zone.addEventListener("dragover", (e) => {
        e.preventDefault();
        zone.classList.add("over");
        root.querySelectorAll(".drop-line").forEach((l) => l.remove());
        const after = [...zone.querySelectorAll(".ticket:not(.dragging)")].find((t) => e.clientY < t.getBoundingClientRect().top + t.offsetHeight / 2);
        const line = document.createElement("div");
        line.className = "drop-line";
        if (after) after.before(line); else (zone.querySelector(".lane-body") || zone).appendChild(line);
        zone.dataset.before = after ? after.dataset.key : "";
      });
      zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("over"); });
      zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); if (dragKey) onDrop(dragKey, zone.dataset.zone, zone.dataset.before || null); dragKey = null; });
    });
  };
  // Move ticket in D.tickets (rank order) and set sprint; zone "backlog" = no sprint
  FS.moveTicket = (key, zone, beforeKey) => {
    const list = D.tickets;
    const t = FS.ticket(key);
    const prev = { sprint: t.sprint, idx: list.indexOf(t) };
    t.sprint = zone === "backlog" ? null : zone;
    list.splice(list.indexOf(t), 1);
    const bi = beforeKey ? list.findIndex((x) => x.key === beforeKey) : -1;
    if (bi >= 0) list.splice(bi, 0, t); else list.push(t);
    return () => { t.sprint = prev.sprint; list.splice(list.indexOf(t), 1); list.splice(prev.idx, 0, t); };
  };

  // ---------- registry ----------
  FS.view = (id, def) => (FS.views[id] = { id, ...def });
  FS.flow = (def) => FS.flows.push(def);

  // ---------- navigation model (flows.md section 5) ----------
  const NAV = [
    { group: null, items: [["today", "today", "Heute"], ["backlog", "view_list", "Backlog"]] },
    { group: "Sprints", items: [["sprints", "date_range", "Sprint-Übersicht"], ["prepare", "event_available", "Vorbereiten", true], ["preplan", "low_priority", "Vorplanen", true], ["plan", "checklist", "Planen", true], ["review", "task_alt", "Review", true], ["minutes", "description", "Protokolle", true]] },
    { group: null, items: [["projects", "flag", "Projekte"], ["forecast", "insights", "Forecast"]] },
    { group: "Team", items: [["people", "group", "Personen und Abwesenheiten"], ["products", "category", "Produkte"], ["calendar", "calendar_month", "Sprint-Kalender"]] },
    { group: "Daten", items: [["data", "database", "Übersicht"], ["conflicts", "call_split", "Konflikte"], ["history", "history", "Verlauf und Tags"]] },
    { group: "Einstellungen", items: [["settings", "tune", "Team"], ["jira", "sync", "Jira und Tickets"], ["storage", "cloud", "Speicher"], ["personal", "person", "Persönlich"]] },
    { group: "Hilfe", items: [["help", "calculate", "Rechenwege"]] },
    { group: "Mockups", items: [["flows", "route", "Abläufe durchspielen"]] },
  ];

  const LOGO = `<svg viewBox="0 0 64 64" aria-hidden="true"><defs><clipPath id="rc"><rect width="64" height="64" rx="13"/></clipPath></defs><rect width="64" height="64" rx="13" fill="#5b5bf0"/><path clip-path="url(#rc)" d="M64 10 L10 64 H64Z" fill="#a24df0" opacity=".85"/><rect x="6" y="24" width="14" height="16" rx="3" fill="#fff"/><rect x="23" y="24" width="14" height="16" rx="3" fill="#fff"/><rect x="40" y="24" width="14" height="16" rx="3" fill="none" stroke="#17c3a0" stroke-width="2.5" stroke-dasharray="4 2"/><line x1="54" y1="32" x2="60" y2="32" stroke="#17c3a0" stroke-width="3" stroke-linecap="round"/></svg>`;

  FS.storageChip = () => {
    const st = FS.state.storageState || "incoming";
    const m = {
      saved: ["ok", "cloud_done", "Gespeichert"],
      incoming: ["warn", "cloud_download", `${D.storage.incoming.length} neue Änderungen von Lea`],
      conflict: ["bad", "call_split", "Konflikt"],
      offline: ["", "cloud_off", "Offline, Speichern lokal"],
      mr: ["warn", "merge", "Wartet auf Merge Request"],
    }[st];
    return `<a class="chip-status ${m[0]}" href="#data" id="storage-chip" title="Speicherstatus">${FS.icon(m[1])}<span class="hide-narrow">${m[2]}</span></a>`;
  };

  function shell() {
    const s = FS.sprint(FS.state.sprint);
    return `
    <div class="app">
      <header class="topbar">
        <button class="btn icon ghost rail-toggle" type="button" aria-label="Navigation" id="rail-toggle">${FS.icon("menu")}</button>
        <div class="brand">${LOGO}<span>Foresprint</span></div>
        <button class="sel hide-narrow" type="button" title="Team wechseln">${FS.icon("groups")}${D.team.name}${FS.icon("expand_more")}</button>
        <button class="sel" type="button" id="sprint-sel" title="Sprint wählen">${FS.icon("date_range")}<span class="data">${s.id}</span>${FS.icon("expand_more")}</button>
        <div class="spacer"></div>
        <div class="search" role="button" tabindex="0" title="Suchen und springen (Strg+K)">${FS.icon("search")}<span class="txt">Suchen</span><span class="small data hide-narrow">Strg+K</span></div>
        <a class="chip-status ${FS.state.trackerOk === false ? "bad" : ""}" href="#jira" title="Letzter Abruf aus ${D.team.tracker}">${FS.icon("sync")}<span class="hide-narrow">${D.team.tracker} ${D.trackerSync.last}</span></a>
        ${FS.storageChip()}
        <button class="btn hide-narrow" type="button" id="btn-refresh" title="Änderungen von anderen holen">${FS.icon("download")}Aktualisieren</button>
        <button class="btn primary" type="button" id="btn-save" title="Speichern und für das Team sichtbar machen" aria-label="Speichern">${FS.icon("save")}<span class="hide-narrow">Speichern</span></button>
        <button class="btn icon ghost" type="button" id="btn-theme" aria-label="Hell oder dunkel">${FS.icon("contrast")}</button>
      </header>
      <nav class="rail" id="rail" aria-label="Hauptnavigation">
        ${NAV.map((g) => `${g.group ? `<h6>${g.group}${g.group === "Sprints" ? ` <span class="data">${s.id}</span>` : ""}</h6>` : ""}${g.items.map(([id, ic, label, sub]) => `<a href="#${id}" data-nav="${id}">${FS.icon(ic)}<span>${label}</span>${id === "conflicts" && FS.state.storageState === "conflict" ? '<span class="count" style="color:var(--bad)">2</span>' : ""}</a>`).join("")}`).join("")}
      </nav>
      <main class="main" id="main"></main>
    </div>`;
  }

  function wireShell() {
    document.getElementById("rail-toggle").onclick = () => document.getElementById("rail").classList.toggle("open");
    document.getElementById("btn-save").onclick = () => {
      FS.state.storageState = "saved";
      rerenderTop();
      FS.toast(D.storage.mrEnforced && FS.state.mrDemo ? "Gespeichert. Der Server verlangt einen Merge Request: Link im Statuschip." : "Gespeichert und mit dem Team geteilt.");
    };
    document.getElementById("btn-refresh").onclick = () => { FS.state.storageState = "saved"; rerenderTop(); FS.toast("2 Änderungen von Lea und Kim übernommen."); };
    document.getElementById("btn-theme").onclick = () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
    };
    document.getElementById("sprint-sel").onclick = () => {
      const ids = D.sprints.filter((s) => s.state !== "past").map((s) => s.id);
      FS.state.sprint = ids[(ids.indexOf(FS.state.sprint) + 1) % ids.length];
      render();
      FS.toast(`Sprint ${FS.state.sprint} gewählt (Klick wechselt weiter).`);
    };
  }
  function rerenderTop() { const c = document.getElementById("storage-chip"); if (c) c.outerHTML = FS.storageChip(); }

  // ---------- flow guide ----------
  function guide() {
    document.querySelectorAll(".guide").forEach((g) => g.remove());
    document.querySelectorAll(".hl").forEach((h) => h.classList.remove("hl"));
    const g = FS.state.guide;
    if (!g) return;
    const flow = FS.flows.find((f) => f.id === g.flow);
    const step = flow.steps[g.step];
    const el = document.createElement("div");
    el.className = "guide";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Ablauf");
    el.innerHTML = `<div class="step">${flow.id} ${FS.esc(flow.title)} · Schritt ${g.step + 1} von ${flow.steps.length}</div><p>${step.text}</p>
      <div class="row"><button class="btn" type="button" data-g="prev" ${g.step === 0 ? "disabled" : ""}>${FS.icon("arrow_back")}Zurück</button>
      ${g.step < flow.steps.length - 1 ? `<button class="btn primary" type="button" data-g="next">Weiter${FS.icon("arrow_forward")}</button>` : `<button class="btn primary" type="button" data-g="end">Fertig</button>`}
      <button class="btn ghost" type="button" data-g="end" style="margin-left:auto">Beenden</button></div>`;
    el.onclick = (e) => {
      const b = e.target.closest("[data-g]");
      if (!b) return;
      if (b.dataset.g === "end") { FS.state.guide = null; guide(); return; }
      g.step += b.dataset.g === "next" ? 1 : -1;
      FS.goStep();
    };
    document.body.appendChild(el);
    if (step.hl) [60, 300, 800].forEach((ms) => setTimeout(() => document.querySelectorAll(step.hl).forEach((h) => { if (h.classList.contains("hl")) return; h.classList.add("hl"); h.scrollIntoView({ block: "nearest" }); }), ms));
  }
  FS.startFlow = (id) => { FS.state.guide = { flow: id, step: 0 }; FS.goStep(); };
  FS.goStep = () => {
    const g = FS.state.guide;
    const step = FS.flows.find((f) => f.id === g.flow).steps[g.step];
    if (step.before) step.before();
    if (location.hash.slice(1) === step.view) render(); else location.hash = step.view;
  };

  // ---------- router ----------
  function render() {
    const id = location.hash.slice(1) || "today";
    const v = FS.views[id] || FS.views.missing;
    document.getElementById("app").innerHTML = shell();
    wireShell();
    const navId = { project: "projects", setup: "storage" }[id] || id;
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === navId));
    const main = document.getElementById("main");
    FS.closePanel();
    if (!FS.keepPresent) FS.presentClose?.();
    main.innerHTML = `<div class="page">${v.render()}</div>`;
    if (v.wire) v.wire(main);
    applyCalcMode(main);
    const de = document.documentElement.dataset;
    de.prodshare = FS.prodOn() ? "on" : "off"; de.multiprod = FS.multiProduct() ? "on" : "off"; de.multipo = FS.multiPO() ? "on" : "off";
    main.querySelectorAll(".ticket").forEach((el) => el.addEventListener("dblclick", () => FS.ticketPanel(el.dataset.key)));
    main.querySelectorAll(".ticket .title").forEach((el) => el.addEventListener("click", () => FS.ticketPanel(el.closest(".ticket").dataset.key)));
    document.title = `${v.title || "Foresprint"} · Foresprint Mockups`;
    guide();
  }

  // Calculation affordances: "off" hides them, "icon" shows the calculator button,
  // "inline" renders each calculation as an open disclosure next to its number.
  function applyCalcMode(main) {
    const btns = [...main.querySelectorAll("button")].filter((b) => b.querySelector(".ms")?.textContent === "calculate" && !b.closest("[data-calc-mode]"));
    btns.forEach((b) => b.classList.add("calc-btn"));
    document.documentElement.dataset.calc = FS.state.calcMode;
    if (FS.state.calcMode !== "inline") return;
    btns.forEach((b) => {
      FS.capturing = true; FS.captured = null;
      try { b.click(); } catch (e) { /* ignore */ }
      FS.capturing = false;
      if (!FS.captured) return;
      const d = document.createElement("details");
      d.className = "calc-inline";
      d.open = true;
      d.innerHTML = `<summary>${FS.icon("calculate", "small")} Rechenweg</summary>${FS.captured}`;
      (b.closest("td, .card, .lane-head, div") || b.parentElement).appendChild(d);
    });
  }
  FS.render = render;

  FS.view("missing", { title: "In Arbeit", render: () => `<div class="page-head"><div><h1>Diese Ansicht folgt</h1><p class="lead">Das Mockup für diesen Bereich ist noch in Arbeit.</p></div></div>` });

  window.addEventListener("hashchange", render);
  window.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "k") { e.preventDefault(); FS.toast("Befehlspalette: Seite, Ticket oder Aktion suchen (im Mockup nicht ausgeführt)."); } });
  document.addEventListener("DOMContentLoaded", render);
})();
