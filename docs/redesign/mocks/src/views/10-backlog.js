// Views "today" (state-aware start page) and "backlog" (ranked ticket list with sprint lanes), flow F2.
(function () {
  const D = DEMO;
  const LANES = ["2026.22", "2026.23", "2026.24"];
  // Tickets whose product rule found no match (demo of the rule hint in F2)
  const RULE = { "ATL-440": "Komponente \"Zertifikate\" gehört zu keiner Produktregel", "ATL-446": "Zwei Regeln treffen zu: Kundenportal und Mobile App", "ATL-448": "Label \"monitoring\" gehört zu keiner Produktregel" };
  const BASE = { products: [], projects: [], refined: "all", flag: "", q: "" };
  const VIEWS = [["alle", "Alle", {}], ["tag", "Tagesgeschäft", { projects: [""] }], ["ref", "Refinement", { refined: "open" }], ["unz", "Nicht zugeordnet", { flag: "unassigned" }], ["vor", "Vorgemerkt", { flag: "earmarked" }]];
  const B = (FS.state.bl ??= { ...BASE, group: "none", sel: [], menu: false, stale: false, notracker: FS.trk() !== "jira" });
  const esc = FS.esc, fmt = FS.fmt;
  const go = (view, o = {}) => { if (o.sprint) FS.state.sprint = o.sprint; if (o.bl) setView(o.bl); if (location.hash.slice(1) === view) FS.render(); else location.hash = view; };
  function setView(id) { Object.assign(B, { ...BASE, sel: [] }, VIEWS.find((v) => v[0] === id)[2]); }
  const sig = (s) => JSON.stringify([[...s.products].sort(), [...s.projects].sort(), s.refined, s.flag]);
  const activeView = () => (VIEWS.find((v) => sig({ ...BASE, ...v[2] }) === sig(B)) || [])[0];
  const calcBtn = (attrs, label = "Rechenweg") => `<button class="btn icon ghost" type="button" ${attrs} title="${label}" aria-label="${label}">${FS.icon("calculate")}</button>`;

  function matches(t) {
    if (B.flag === "earmarked" ? !LANES.includes(t.sprint) : t.sprint) return false;
    if (B.products.length && !B.products.includes(t.product)) return false;
    if (B.projects.length && !B.projects.includes(t.project || "")) return false;
    if (B.refined === "yes" && !t.refined) return false;
    if (B.refined === "open" && t.refined) return false;
    if (B.flag === "unassigned" && !RULE[t.key]) return false;
    if (B.q) { const hay = `${t.key} ${t.title} ${FS.product(t.product)?.name} ${FS.project(t.project)?.name || "Tagesgeschäft"}`.toLowerCase(); if (!B.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false; }
    return true;
  }

  function row(t, o = {}) {
    let h = FS.ticketRow(t, { drag: true, ...o });
    if (t.key.startsWith("AP-")) h = h.replace(/<span class="key">.*?<\/a><\/span>/, `<span class="key" title="Von Hand angelegt, kein Tracker">${t.key}</span>`);
    const flags = (t.est == null ? `<span class="chip warn">${FS.icon("help", "small")}ohne Schätzung</span>` : "") +
      (RULE[t.key] && FS.multiProduct() && FS.trk() === "jira" ? `<button type="button" class="chip warn bl-ruleflag" data-rule="${t.key}" title="${esc(RULE[t.key])}">${FS.icon("rule", "small")}Regel ohne Treffer</button>` : "") +
      (B.flag === "earmarked" && t.sprint ? `<span class="chip">${FS.icon("event", "small")}${t.sprint}</span>` : "");
    h = h.replace('<span class="meta">', `<span class="meta">${flags}`).replace('<span class="handle">', `<input type="checkbox" class="bl-sel" data-key="${t.key}" aria-label="${FS.dk(t.key)} auswählen" ${B.sel.includes(t.key) ? "checked" : ""}><span class="handle">`);
    return B.sel.includes(t.key) ? h.replace('class="ticket"', 'class="ticket selected"') : h;
  }

  function listBody(items) {
    if (!items.length) return `<div class="bl-empty"><p class="muted">Kein Ticket passt zu diesem Filter.</p><button class="btn" type="button" data-act="reset">${FS.icon("filter_alt_off")}Filter zurücksetzen</button></div>`;
    if (B.group === "none") return items.map((t) => row(t)).join("");
    const byProject = B.group === "project";
    const ids = byProject ? [...D.projects.map((p) => p.id), ""] : D.products.map((p) => p.id);
    return ids.map((id) => {
      const g = items.filter((t) => (byProject ? t.project || "" : t.product) === id);
      if (!g.length) return "";
      const name = byProject ? (id ? FS.project(id).name : "Tagesgeschäft") : FS.product(id).name;
      return `<div class="bl-gh">${byProject ? FS.icon(id ? "flag" : "inventory_2", "small") : `<span class="dot" style="background:${FS.product(id).color}"></span>`}${esc(name)}<span class="muted data">${g.length} ${g.length === 1 ? "Ticket" : "Tickets"}, ${FS.sum(g, (t) => t.est)} Punkte</span></div>${g.map((t) => row(t, byProject ? { noProject: true } : { noProduct: true })).join("")}`;
    }).join("");
  }

  function laneHtml(id) {
    const s = FS.sprint(id), ts = D.tickets.filter((t) => t.sprint === id);
    const used = FS.sum(ts, (t) => t.est), over = used > s.high, noEst = ts.filter((t) => t.est == null).length, open = ts.filter((t) => !t.refined).length;
    const pp = D.productPlan[id];
    const abs = { announced: `<span class="chip warn">${FS.icon("event_busy", "small")}Abwesenheiten angekündigt</span>`, unknown: `<span class="chip">${FS.icon("event_busy", "small")}Abwesenheiten offen</span>`, confirmed: `<span class="chip ok">${FS.icon("check", "small")}bestätigt</span>` }[s.absences];
    const prods = D.products.map((p) => {
      const u = FS.sum(ts.filter((t) => t.product === p.id), (t) => t.est), pre = pp?.[p.id]?.pre;
      return `<span class="chip" title="${p.name}${pre != null ? `: Tickets ${u}, Vorplanung ${pre}` : ""}"><span class="dot" style="background:${p.color}"></span>${esc(p.name.split(" ")[0])} <span class="data ${pre != null && u > pre ? "bl-over" : ""}">${u}${pre != null ? ` / ${pre}` : ""}</span></span>`;
    }).join("");
    return `<div class="lane" data-zone="${id}"><div class="lane-head">
      <div class="row"><strong class="data">${id}</strong><span class="muted small data">${FS.fmtDate(s.start)} bis ${FS.fmtDate(s.end)}</span><span style="flex:1"></span>${abs}<a class="small" href="#preplan" data-go="preplan" data-sprint="${id}">Vorplanen</a></div>
      ${FS.capBar(used, s.forecast, s.low, s.high)}
      <div class="row small"><span class="data"><strong>${used}</strong> Punkte vorgemerkt, Forecast ${s.forecast} (Spanne ${s.low} bis ${s.high})</span>${calcBtn(`data-calc="${id}"`)}</div>
      <div class="row only-multiprod">${prods}</div>
      ${over ? `<div class="banner bad" style="margin:0"><span>${FS.icon("warning")}</span><div class="grow">Über der Obergrenze: ${used} Punkte, Spanne endet bei ${s.high}. Das ist eine Warnung, kein Stopp.</div></div>` : ""}
      ${noEst || open ? `<div class="row small muted">${FS.icon("help", "small")}${open} nicht refined, ${noEst} ohne Schätzung (zählen 0)</div>` : ""}
    </div><div class="lane-body">${ts.length ? ts.map((t) => row(t, { noProject: true })).join("") : `<p class="muted small bl-empty">Noch nichts vorgemerkt. Ticket hierher ziehen oder Vormerken für... wählen.</p>`}</div></div>`;
  }

  function calcPanel(id) {
    const s = FS.sprint(id), ts = D.tickets.filter((t) => t.sprint === id), used = FS.sum(ts, (t) => t.est);
    FS.openPanel(`Rechenweg ${id}`, `<div class="tw"><table class="t"><tbody>
      <tr><td>Summe der Schätzungen (${ts.length} Tickets)</td><td class="num">${used}</td></tr>
      <tr><td>davon ohne Schätzung (zählen 0)</td><td class="num">${ts.filter((t) => t.est == null).length} Tickets</td></tr>
      <tr><td>Forecast PLAN: ${s.capacityPD} PT mal Rate ${fmt(D.rate, 2)}</td><td class="num">${fmt(s.capacityPD * D.rate, 1)} gerundet ${s.forecast}</td></tr>
      <tr><td>Spanne</td><td class="num">${s.low} bis ${s.high}</td></tr>
      <tr class="sum"><td>Abstand zur Obergrenze</td><td class="num">${s.high - used}</td></tr></tbody></table></div>
      <p class="small muted">Verfügbare Personentage (PT) kommen aus Abwesenheiten, Rate aus der normierten Velocity. ${s.absences === "confirmed" ? "" : "Abwesenheiten sind noch nicht bestätigt, der Forecast kann sich ändern."}</p>`);
  }

  function ruleFlagPanel(key) {
    const t = FS.ticket(key);
    const el = FS.openPanel(`Regel ohne Treffer: ${key}`, `<p>${esc(RULE[key])}.</p>
      <p class="small muted">Das Produkt der Regel entscheidet, du kannst es für dieses Ticket von Hand setzen. Projekt und Produkt dürfen sich unterscheiden, dann erscheint nur dieser Hinweis.</p>
      <div class="field"><label for="rf-p">Produkt für ${key}</label><select class="input" id="rf-p">${D.products.map((p) => `<option value="${p.id}" ${p.id === t.product ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>
      <div class="row"><button class="btn primary" type="button" id="rf-ok">${FS.icon("check")}Produkt übernehmen</button><button class="btn" type="button" id="rf-rule">Regel bearbeiten</button></div>`);
    el.querySelector("#rf-ok").onclick = () => { t.product = el.querySelector("#rf-p").value; delete RULE[key]; FS.closePanel(); FS.toast(`${key}: Produkt von Hand gesetzt.`); paint(); };
    el.querySelector("#rf-rule").onclick = () => go("products");
  }

  function workItemPanel() {
    const el = FS.openPanel("Arbeitspaket anlegen", `<p class="small muted">Ohne Tracker legst du Arbeit hier von Hand an. Sie liegt in der Datei tickets.yaml im Datenordner.</p>
      <div class="field"><label for="wi-t">Titel</label><input class="input" id="wi-t" placeholder="z. B. Release-Notizen schreiben"></div>
      <div class="field only-multiprod"><label for="wi-p">Produkt</label><select class="input" id="wi-p">${D.products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></div>
      <div class="field"><label for="wi-j">Projekt</label><select class="input" id="wi-j"><option value="">Tagesgeschäft</option>${D.projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></div>
      <div class="field"><label for="wi-e">Schätzung in Punkten</label><input class="input data" id="wi-e" type="number" min="1" value="3"></div>
      <button class="btn primary" type="button" id="wi-ok">${FS.icon("add")}Anlegen</button>`);
    el.querySelector("#wi-ok").onclick = () => {
      const n = D.tickets.filter((t) => t.key.startsWith("AP-")).length + 1, key = `AP-${String(n).padStart(2, "0")}`;
      D.tickets.push({ key, title: el.querySelector("#wi-t").value.trim() || "Neues Arbeitspaket", product: el.querySelector("#wi-p").value, project: el.querySelector("#wi-j").value || null, est: Number(el.querySelector("#wi-e").value) || null, refined: false, status: "Neu", sprint: null, rank: 0 });
      FS.moveTicket(key, "backlog", "ATL-424");
      FS.closePanel(); FS.toast(`${key} angelegt und oben im Backlog eingeordnet.`); paint();
    };
  }


  // Pro-forma sprints: tracker sprints marked as "not a real sprint" in Settings > Jira (none, one or several).
  function proformaHtml() {
    const pf = D.trackerSprints.filter((s) => s.proforma);
    if (!pf.length) return "";
    B.pfOpen ??= Object.fromEntries(pf.map((s, i) => [s.name, i === 0]));
    return pf.map((s) => {
      const ts = D.tickets.filter((t) => t.sprint === s.name);
      const open = B.pfOpen[s.name];
      return `<div class="lane bl-pf" data-zone="${esc(s.name)}"><div class="lane-head"><div class="row">
        <button class="btn ghost icon" type="button" data-pf="${esc(s.name)}" aria-expanded="${open}" aria-label="${open ? "Zuklappen" : "Aufklappen"}">${FS.icon(open ? "expand_less" : "expand_more")}</button>
        <strong>${esc(s.name)}</strong><span class="chip">${FS.icon("inventory_2", "small")}Pro forma</span><span class="chip data">${ts.length}</span><span class="muted small data">${FS.sum(ts, (t) => t.est)} Punkte</span></div>
        <span class="small muted">${esc(s.note || "")}. ${B.notracker ? "Ablage in Foresprint" : `Sprint aus ${D.team.tracker}`}, zählt nicht für Kapazität und Forecast. ${B.notracker ? "" : '<a href="#jira">Festlegen, was pro forma ist</a>'}</span></div>
        ${open ? `<div class="lane-body">${ts.length ? ts.map((t) => row(t)).join("") : `<p class="muted small" style="padding:8px 12px;margin:0">Leer. Tickets hierher ziehen.</p>`}</div>` : ""}</div>`;
    }).join("");
  }

  // ---------- backlog view ----------
  let main;
  function chipsHtml() {
    const tog = (arr, v) => (arr.includes(v) ? "on" : "");
    const av = activeView();
    return `<div class="tabs" id="bl-tabs" role="tablist" aria-label="Gespeicherte Ansichten">${VIEWS.map(([id, name]) => `<a href="#backlog" role="tab" data-view="${id}" class="${av === id ? "active" : ""}">${name}</a>`).join("")}${av ? "" : `<a href="#backlog" data-act="saveview">${FS.icon("bookmark_add")}Als Ansicht speichern</a>`}</div>
      <div class="row only-multiprod" style="margin-bottom:8px"><span class="small muted">Produkt</span>${D.products.map((p) => `<button type="button" class="chip filter ${tog(B.products, p.id)}" data-f="products:${p.id}" aria-pressed="${B.products.includes(p.id)}"><span class="dot" style="background:${p.color}"></span>${esc(p.name)}</button>`).join("")}</div>
      <div class="row" style="margin-bottom:8px"><span class="small muted">Projekt</span>${D.projects.map((p) => `<button type="button" class="chip filter ${tog(B.projects, p.id)}" data-f="projects:${p.id}" aria-pressed="${B.projects.includes(p.id)}">${FS.icon("flag", "small")}${esc(p.name)}</button>`).join("")}<button type="button" class="chip filter ${tog(B.projects, "")}" data-f="projects:" aria-pressed="${B.projects.includes("")}">Tagesgeschäft</button>
        <span class="small muted" style="margin-left:8px">Stand</span><button type="button" class="chip filter ${B.refined === "yes" ? "on" : ""}" data-f="refined:yes">Refined</button><button type="button" class="chip filter ${B.refined === "open" ? "on" : ""}" data-f="refined:open">${FS.icon("help", "small")}Offen</button>
        <span class="small muted" style="margin-left:8px">Gruppieren</span>${[["none", "Keine"], ["project", "Projekt"], ...(FS.multiProduct() ? [["product", "Produkt"]] : [])].map(([v, l]) => `<button type="button" class="chip filter ${B.group === v ? "on" : ""}" data-group="${v}">${l}</button>`).join("")}</div>`;
  }
  function barHtml() {
    if (!B.sel.length) return "";
    return `<div class="banner info" role="region" aria-label="Auswahl"><span>${FS.icon("checklist")}</span><div class="grow"><strong class="data">${B.sel.length}</strong> ausgewählt
      <span class="row" style="margin-top:6px"><button class="btn primary" type="button" data-act="menu" aria-expanded="${B.menu}">${FS.icon("event")}Vormerken für...${FS.icon("expand_more")}</button><button class="btn ghost" type="button" data-act="clear">Auswahl aufheben</button></span>
      ${B.menu ? `<span class="row" style="margin-top:6px" role="menu">${LANES.map((l) => `<button class="btn" type="button" role="menuitem" data-to="${l}">${FS.icon("event")}Sprint ${l}</button>`).join("")}<button class="btn" type="button" role="menuitem" data-to="backlog">${FS.icon("undo")}Zurück in den Backlog</button></span>` : ""}</div></div>`;
  }
  function paint() {
    const items = D.tickets.filter(matches);
    main.querySelector("#bl-chips").innerHTML = chipsHtml();
    main.querySelector("#bl-bar").innerHTML = barHtml();
    const q = main.querySelector("#bl-q"); if (q.value !== B.q) q.value = B.q;
    const total = D.tickets.filter((t) => !t.sprint).length;
    main.querySelector("#bl-board").innerHTML = `<div class="stack"><div class="lane" data-zone="backlog"><div class="lane-head"><div class="row"><strong>Backlog</strong><span class="chip data">${items.length} von ${B.flag === "earmarked" ? items.length : total}</span><span class="muted small data">${FS.sum(items, (t) => t.est)} Punkte</span>${calcBtn('data-calc-list="1"')}</div><span class="small muted">Reihenfolge = Rang, oben zuerst. Ziehen am Griff, oder Alt+Pfeil hoch oder runter. Alt+Pfeil rechts schiebt in den nächsten Sprint.</span></div><div class="lane-body">${listBody(items)}</div></div>${proformaHtml()}</div>
      <div class="stack bl-lanes" aria-label="Kommende Sprints">${LANES.map(laneHtml).join("")}<p class="small muted" style="margin:0">Die Sprints zeigen immer alle vorgemerkten Tickets, unabhängig vom Filter links.</p></div>`;
    main.querySelectorAll("[data-pf]").forEach((x) => (x.onclick = () => { B.pfOpen[x.dataset.pf] = !B.pfOpen[x.dataset.pf]; paint(); }));
    FS.dnd(main.querySelector("#bl-board"), {
      onDrop(key, zone, before, kb) {
        const undo = FS.moveTicket(key, zone, before);
        const s = FS.sprint(zone), used = s ? FS.sum(D.tickets.filter((t) => t.sprint === zone), (t) => t.est) : 0;
        paint();
        FS.toast(`${key} ${zone === "backlog" ? "im Backlog einsortiert" : `${FS.sprint(zone) ? "für " + zone + " vorgemerkt" : "nach " + zone + " gelegt (pro forma, lokal; erscheint unter In Jira anpassen)"}`}${s && used > s.high ? `. Achtung: ${used} Punkte, über der Obergrenze ${s.high}` : ""}.`, () => { undo(); paint(); });
        if (kb) main.querySelector(`.ticket[data-key="${key}"]`)?.focus();
      },
    });
  }
  function syncLine() {
    if (B.notracker) return `<p class="small muted" id="bl-sync">${FS.icon("sync_disabled", "small")} Kein Tracker verbunden, kein Abruf.</p>`;
    if (B.stale || FS.state.trackerOk === false) return `<div class="banner warn" id="bl-sync"><span>${FS.icon("sync_problem")}</span><div class="grow">Der Abruf aus ${D.team.tracker} ist fehlgeschlagen (Zeitüberschreitung). Du arbeitest mit den Daten von heute 08:12.</div><button class="btn" type="button" data-act="retry">${FS.icon("refresh")}Erneut versuchen</button></div>`;
    return `<p class="small muted" id="bl-sync">${FS.icon("sync", "small")} ${D.team.tracker}: letzter Abruf ${D.trackerSync.last}, ${D.trackerSync.tickets} Tickets, ${D.trackerSync.changed} geändert.</p>`;
  }

  FS.view("backlog", {
    title: "Backlog",
    render() {
      if (FS.trk() === "none") return `<div class="page-head"><div><h1>Backlog</h1><p class="lead">Ohne Tickets gibt es keinen Backlog.</p></div></div>
        <div class="banner info">${FS.icon("info")}<div class="grow">Dein Team plant ohne Tickets: Beträge je Produkt und Projekt in <a href="#preplan">Vorplanen</a>, die Zusage als Zahl in <a href="#plan">Planen</a>. Willst du Arbeit einzeln führen, stelle unter <a href="#jira">Einstellungen, Tickets und Tracker</a> auf Arbeitspakete oder einen Tracker um.</div></div>`;
      return `<style>
        .bl-board{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:16px;align-items:start}
        .bl-board .ticket{grid-template-columns:22px 20px 92px minmax(0,1fr);row-gap:2px}.bl-board .ticket .title{white-space:normal}.bl-board .ticket .meta{grid-column:3 / -1;flex-wrap:wrap}.bl-board .ticket .est{margin-left:auto}
        .bl-board .bl-sel{margin:0;width:16px;height:16px;accent-color:var(--primary)}
        .bl-gh{display:flex;gap:8px;align-items:center;padding:6px 8px;background:var(--surface-2);font-weight:600;border-bottom:1px solid var(--border)}
        .bl-gh .data{font-weight:400;font-size:12px}
        .bl-empty{padding:16px;display:flex;flex-direction:column;gap:8px;align-items:flex-start}
        .bl-ruleflag{cursor:pointer;border:0}
        .bl-over{color:var(--bad);font-weight:600}
        .bl-lanes .lane-body{min-height:56px}
        .bl-q{display:flex;align-items:center;gap:6px;flex:1;min-width:200px;max-width:360px}.bl-q .input{flex:1}
        @media (max-width:1100px){.bl-board{grid-template-columns:minmax(0,1fr)}}
        @media (max-width:700px){.bl-board .ticket{grid-template-columns:22px 20px minmax(0,1fr)}.bl-board .ticket .key,.bl-board .ticket .title{grid-column:3}.bl-board .ticket .handle,.bl-board .ticket .bl-sel{grid-row:1 / span 3}}
      </style>
      <div class="page-head"><div><h1>Backlog</h1><p class="lead">Alle ${B.notracker ? "Arbeitspakete" : "Tickets"} in einer Reihenfolge. Ansichten sind Filter derselben Liste. Rechts siehst du, was für die nächsten Sprints vorgemerkt ist und ob es in die Spanne passt.</p></div>
        <div class="actions">${B.notracker ? `<button class="btn primary" type="button" data-act="workitem">${FS.icon("add")}Arbeitspaket anlegen</button>` : ""}</div></div>
      <div id="bl-syncwrap">${syncLine()}</div>
      ${B.notracker ? `<div class="banner info"><span>${FS.icon("info")}</span><div class="grow"><strong>Arbeitspakete in Foresprint, ohne Tracker.</strong> Es gibt keinen Abruf. Arbeitspakete legst du von Hand an (Schlüssel AP-…, kein Link nach außen). Schätzung, Produkt und Projekt pflegst du im Panel. Filter, Reihenfolge und Sprint-Lanes funktionieren wie mit Tracker. Umstellen: <a href="#jira">Einstellungen, Tickets und Tracker</a>.</div></div>` : ""}
      <div id="bl-chips"></div>
      <div class="row" style="margin-bottom:12px"><div class="bl-q"><label class="small muted" for="bl-q">${FS.icon("search")}</label><input class="input" id="bl-q" type="search" placeholder="Suchen: Schlüssel, Titel, Produkt, Projekt" autocomplete="off"></div></div>
      <div id="bl-bar"></div>
      <div class="bl-board" id="bl-board"></div>`;
    },
    wire(m) {
      if (FS.trk() === "none") return;
      main = m;
      paint();
      const sel = (key, on) => { B.sel = on ? [...new Set([...B.sel, key])] : B.sel.filter((k) => k !== key); paint(); };
      m.addEventListener("change", (e) => { if (e.target.matches(".bl-sel")) sel(e.target.dataset.key, e.target.checked); });
      m.querySelector("#bl-q").addEventListener("input", (e) => { B.q = e.target.value; paint(); });
      m.addEventListener("click", (e) => {
        const c = (s) => e.target.closest(s);
        let el;
        if ((el = c("[data-view]"))) { e.preventDefault(); setView(el.dataset.view); paint(); }
        else if ((el = c("[data-f]"))) { const [k, v] = el.dataset.f.split(":"); if (k === "refined") B.refined = B.refined === v ? "all" : v; else B[k] = B[k].includes(v) ? B[k].filter((x) => x !== v) : [...B[k], v]; paint(); }
        else if ((el = c("[data-group]"))) { B.group = el.dataset.group; paint(); }
        else if ((el = c("[data-calc]"))) calcPanel(el.dataset.calc);
        else if (c("[data-calc-list]")) { const n = D.tickets.filter((t) => !t.sprint); FS.openPanel("Rechenweg Backlog", `<div class="tw"><table class="t"><tbody><tr><td>Tickets im Backlog</td><td class="num">${n.length}</td></tr><tr><td>Summe der Schätzungen</td><td class="num">${FS.sum(n, (t) => t.est)}</td></tr><tr><td>ohne Schätzung (zählen 0)</td><td class="num">${n.filter((t) => t.est == null).length}</td></tr><tr class="sum"><td>Nicht refined</td><td class="num">${n.filter((t) => !t.refined).length}</td></tr></tbody></table></div>`); }
        else if ((el = c("[data-rule]"))) ruleFlagPanel(el.dataset.rule);
        else if ((el = c("[data-go]"))) { e.preventDefault(); go(el.dataset.go, { sprint: el.dataset.sprint }); }
        else if ((el = c("[data-to]"))) {
          const keys = [...B.sel], undos = keys.map((k) => FS.moveTicket(k, el.dataset.to, null));
          B.sel = []; B.menu = false; paint();
          const s = FS.sprint(el.dataset.to), used = s ? FS.sum(D.tickets.filter((t) => t.sprint === s.id), (t) => t.est) : 0;
          FS.toast(`${keys.length} Tickets ${s ? `für ${s.id} vorgemerkt` : "zurück in den Backlog"}${s && used > s.high ? `. Achtung: ${used} Punkte, über der Obergrenze ${s.high}` : ""}.`, () => { undos.reverse().forEach((u) => u()); paint(); });
        }
        else if ((el = c("[data-act]"))) {
          const a = el.dataset.act;
          if (a === "menu") { B.menu = !B.menu; paint(); }
          else if (a === "clear") { B.sel = []; B.menu = false; paint(); }
          else if (a === "reset") { setView("alle"); paint(); }
          else if (a === "saveview") FS.toast("Ansicht gespeichert (im Mockup nur angedeutet).");
          else if (a === "retry") { B.stale = false; m.querySelector("#bl-syncwrap").innerHTML = syncLine(); FS.toast(`${D.team.tracker}: Abruf erfolgreich, 4 Tickets geändert.`); }
          else if (a === "workitem") workItemPanel();
        }
      });
    },
  });

  // ---------- today view ----------
  const light = (ok, okTxt, warnTxt) => (ok ? FS.lightChip("ok", okTxt) : FS.lightChip("warn", warnTxt));
  const goBtn = (label, view, o = {}) => `<button class="btn" type="button" data-go="${view}" ${o.sprint ? `data-sprint="${o.sprint}"` : ""} ${o.bl ? `data-bl="${o.bl}"` : ""}>${label}${FS.icon("arrow_forward")}</button>`;

  FS.view("today", {
    title: "Heute",
    render() {
      const cur = FS.sprint("2026.21"), ts = D.tickets.filter((t) => t.sprint === "2026.21");
      const total = FS.sum(ts, (t) => t.est), done = FS.sum(ts.filter((t) => t.status === "Fertig"), (t) => t.est);
      const noEst = D.tickets.filter((t) => t.est == null), earmarkedOpen = D.tickets.filter((t) => LANES.includes(t.sprint) && !t.refined);
      const lg = FS.project("login"), lgSum = lg.usedPD + lg.plannedPD;
      const sprint22Abs = Object.keys(D.absences["2026.22"] || {}).length;
      const inc = D.storage.incoming;
      const finding = (chip, text, btn, cls = "") => `<li class="row ${cls}" style="padding:8px 0;border-bottom:1px solid var(--border);align-items:flex-start"><span>${chip}</span><span style="flex:1;min-width:200px">${text}</span>${btn}</li>`;
      return `<div class="page-head"><div><h1>Heute, ${FS.fmtDate(D.today)}</h1><p class="lead">Was als Nächstes ansteht, was andere geändert haben und was auffällt. Jeder Punkt führt in die passende Ansicht. Nichts davon ist Pflicht und nichts sperrt eine Seite.</p></div></div>
      <div class="grid cols-2" style="margin-bottom:16px">
        <section class="card stack" aria-labelledby="td-h21"><div class="row"><h2 id="td-h21" style="margin:0">Sprint <span class="data">2026.21</span></h2><span class="chip fc">läuft</span><span class="muted small data">${FS.fmtDate(cur.start)} bis ${FS.fmtDate(cur.end)}</span></div>
          ${FS.trk() === "none" ? `<div class="row small"><span>Zusage <span class="data">${cur.plan}</span> Punkte. Ohne Tickets steht das Ergebnis erst im Review fest.</span></div>` : `${FS.capBar(done, cur.plan, null, null, cur.plan * 1.15)}
          <div class="row small"><span class="data">${done} von ${cur.plan} Punkten erledigt (${ts.length} ${FS.trk() === "jira" ? "Tickets" : "Arbeitspakete"} im Sprint)</span>${calcBtn('data-calc21="1"')}</div>`}
          <div class="banner warn" style="margin:0"><span>${FS.icon("event_upcoming")}</span><div class="grow"><strong>Review fällig am 27.10.</strong> Noch 6 Tage. Velocity, Scope-Änderung und Erledigtes je Produkt eintragen.</div></div>
          <div class="row">${goBtn("Zum Review", "review", { sprint: "2026.21" })}${goBtn("Sprint-Übersicht", "sprints")}</div></section>
        <section class="card stack" aria-labelledby="td-h22"><div class="row"><h2 id="td-h22" style="margin:0">Sprint <span class="data">2026.22</span></h2><span class="chip">offen</span><span class="muted small data">Start 28.10., Planung 28.10.</span></div>
          <div class="stack" style="gap:0">
            ${[["event_busy", "Abwesenheiten", light(false, "", `nur angekündigt (${sprint22Abs} Personen)`), goBtn("Bestätigen", "prepare", { sprint: "2026.22" })],
               ["low_priority", "Vorplanung", light(false, "", "2 von 4 Produkten"), goBtn("Vorplanen", "preplan", { sprint: "2026.22" })],
               ...(FS.trk() === "none" ? [] : [["help", "Refinement", light(false, "", "2 Tickets nicht refined"), goBtn("Backlog", "backlog", { bl: "ref" })]]),
               ["checklist", "Planung", `<span class="chip">28.10.</span>`, goBtn("Planung", "plan", { sprint: "2026.22" })]].map(([ic, l, c, b]) => `<div class="row" style="padding:6px 0;border-bottom:1px solid var(--border)"><span style="flex:1;min-width:130px">${FS.icon(ic, "small")} ${l}</span>${c}${b}</div>`).join("")}</div>
          <p class="small muted" style="margin:0">Kundenportal und Mobile App sind vorgeplant, Abrechnung und Plattform fehlen noch. Die Planung geht trotzdem, mit den Daten von jetzt. Danach folgen <span class="data">2026.23</span> ${FS.trk() === "none" ? "" : "(3 Tickets vorgemerkt)"} und <span class="data">2026.24</span> (noch leer).</p></section>
      </div>
      <div class="grid cols-3" style="margin-bottom:16px">
        <section class="card stack" aria-labelledby="td-hi"><h2 id="td-hi" style="margin:0">${FS.icon("cloud_download")} Änderungen von anderen</h2>
          ${FS.state.storageState === "saved" ? `<p class="muted" style="margin:0">Alles aktuell. Nichts Neues von anderen.</p>` : `<ul class="stack" style="margin:0;padding:0;list-style:none">${inc.map((c) => `<li><strong>${esc(c.who)}</strong>: ${esc(c.what)} <span class="muted small">${c.when}</span></li>`).join("")}</ul>
          <div class="row"><button class="btn primary" type="button" id="td-refresh">${FS.icon("download")}Aktualisieren</button><a class="small" href="#data">Details in Daten</a></div>`}</section>
        <section class="card stack only-jira" aria-labelledby="td-hs"><h2 id="td-hs" style="margin:0">${FS.icon("sync")} ${D.team.tracker}-Abruf</h2>
          <dl class="kv" style="grid-template-columns:110px minmax(0,1fr)"><dt>Letzter Abruf</dt><dd>${D.trackerSync.last}</dd><dt>Tickets</dt><dd class="data">${D.trackerSync.tickets}</dd><dt>Geändert</dt><dd class="data">${D.trackerSync.changed} seit dem letzten Abruf</dd></dl>
          <div class="row"><button class="btn" type="button" id="td-sync">${FS.icon("sync")}Jetzt abrufen</button><a class="small" href="#jira">Jira und Tickets</a></div>
          <p class="small muted" style="margin:0">Ohne Tracker entfällt diese Karte. Dann pflegst du Arbeitspakete von Hand im <a href="#backlog">Backlog</a>.</p></section>
        <section class="card stack need-tickets" aria-labelledby="td-ha"><h2 id="td-ha" style="margin:0">${FS.icon("view_list")} Backlog</h2>
          <dl class="kv" style="grid-template-columns:150px minmax(0,1fr)"><dt>Im Backlog</dt><dd class="data">${D.tickets.filter((t) => !t.sprint).length} Tickets</dd><dt>Vorgemerkt</dt><dd class="data">${D.tickets.filter((t) => LANES.includes(t.sprint)).length} Tickets für 3 Sprints</dd><dt>Nicht refined</dt><dd class="data">${D.tickets.filter((t) => !t.sprint && !t.refined).length} Tickets</dd></dl>
          ${goBtn("Backlog öffnen", "backlog", { bl: "alle" })}</section>
      </div>
      <section class="card" aria-labelledby="td-hf"><h2 id="td-hf">${FS.icon("fact_check")} Befunde <span class="chip data">${{ jira: 5, local: 4, none: 2 }[FS.trk()]}</span></h2>
        <ul style="margin:0;padding:0;list-style:none">
          ${finding(FS.lightChip("bad", "Gefährdet"), `Projekt <strong>${esc(lg.name)}</strong>: Meilenstein "${esc(lg.milestones[0].name)}" am ${FS.fmtDate(lg.milestones[0].date)} gefährdet, ${FS.trk() === "none" ? "Ampel von Hand gesetzt." : `${lg.milestones[0].done} von ${lg.milestones[0].tickets} Tickets erledigt.`} Kontingent: ${lg.usedPD} PT gebucht plus ${lg.plannedPD} PT geplant = ${lgSum} von ${lg.contingentPD} PT ${calcBtn('data-calc-login="1"')}`, goBtn("Projekt", "projects"))}
          ${finding(FS.lightChip("warn", "Hinweis"), `Ticket ohne Schätzung: ${noEst.map((t) => `${FS.keyLink(t)} ${esc(t.title)}`).join(", ")}. Zählt im Sprint als 0 Punkte.`, goBtn("Im Backlog", "backlog", { bl: "alle" }), "need-tickets")}
          ${finding(FS.lightChip("warn", "Hinweis"), `${earmarkedOpen.length} vorgemerktes Ticket nicht refined: ${earmarkedOpen.map((t) => `${FS.keyLink(t)} (${t.sprint})`).join(", ")}.`, goBtn("Refinement", "backlog", { bl: "ref" }), "need-tickets")}
          ${finding(FS.lightChip("warn", "Hinweis"), `Abwesenheiten für 2026.22 sind nur angekündigt. Der Forecast rechnet mit ${FS.sprint("2026.22").capacityPD} PT und ändert sich bei Bestätigung.`, goBtn("Bestätigen", "prepare", { sprint: "2026.22" }))}
          ${finding(FS.lightChip("warn", "Hinweis"), `${Object.keys(RULE).length} Tickets ohne eindeutiges Produkt (Regel ohne Treffer).`, goBtn("Zuordnen", "backlog", { bl: "unz" }), "only-jira")}
        </ul></section>`;
    },
    wire(m) {
      m.addEventListener("click", (e) => {
        const g = e.target.closest("[data-go]");
        if (g) return go(g.dataset.go, { sprint: g.dataset.sprint, bl: g.dataset.bl });
        if (e.target.closest("[data-calc21]")) {
          const ts = D.tickets.filter((t) => t.sprint === "2026.21");
          FS.openPanel("Rechenweg Sprint 2026.21", `<div class="tw"><table class="t"><tbody><tr><td>Summe der Schätzungen im Sprint</td><td class="num">${FS.sum(ts, (t) => t.est)}</td></tr><tr><td>davon Status Fertig</td><td class="num">${FS.sum(ts.filter((t) => t.status === "Fertig"), (t) => t.est)}</td></tr><tr class="sum"><td>Plan (eingefroren)</td><td class="num">${FS.sprint("2026.21").plan}</td></tr></tbody></table></div>`);
        }
        if (e.target.closest("[data-calc-login]")) {
          const p = FS.project("login");
          FS.openPanel("Rechenweg Kontingent", `<div class="tw"><table class="t"><tbody><tr><td>Gebucht und verbraucht</td><td class="num">${p.usedPD} PT</td></tr><tr><td>Geplant (Punkte durch Rate ${FS.fmt(D.rate, 2)}, Schätzung)</td><td class="num">${p.plannedPD} PT</td></tr><tr><td>Zusammen</td><td class="num">${p.usedPD + p.plannedPD} PT</td></tr><tr class="sum"><td>Kontingent</td><td class="num">${p.contingentPD} PT</td></tr></tbody></table></div><p class="small muted">Umrechnung von Punkten in Personentage ist eine Schätzung.</p>`);
        }
      });
      const r = m.querySelector("#td-refresh");
      if (r) r.onclick = () => { FS.state.storageState = "saved"; FS.render(); FS.toast("2 Änderungen von Lea und Kim übernommen."); };
      m.querySelector("#td-sync").onclick = () => FS.toast(`${D.team.tracker}: Abruf erfolgreich, ${D.trackerSync.changed} Tickets geändert.`);
    },
  });

  // ---------- flow F2 ----------
  FS.flow({
    id: "F2", title: "Backlog pflegen",
    summary: "Abruf prüfen, filtern, Tickets ordnen und vormerken, Ticket-Panel pflegen, Regelhinweise klären.",
    steps: [
      { view: "backlog", hl: "#bl-sync", text: "Zuerst der Abruf-Status. Ist er veraltet oder fehlgeschlagen, steht hier ein Banner mit \"Erneut versuchen\". Die Arbeit geht mit den letzten Daten weiter, nichts ist gesperrt.", before() { setView("alle"); B.stale = true; FS.setTrk("jira"); B.group = "none"; } },
      { view: "backlog", hl: "#bl-chips", text: "Frischer Abruf: Wähle eine gespeicherte Ansicht (zum Beispiel Refinement) oder klicke Filter an. Die Liste reagiert sofort, auch mit der Suche.", before() { B.stale = false; setView("alle"); } },
      { view: "backlog", hl: ".bl-board [data-zone=backlog] .lane-body > .ticket:first-of-type", text: "Ordnen: Ticket am Griff nach oben oder unten ziehen oder Alt+Pfeil nutzen. In einen Sprint rechts ziehen merkt es vor, ein Toast bietet Rückgängig. Ohne Maus: mehrere ankreuzen und \"Vormerken für...\".", before() { setView("alle"); B.sel = []; } },
      { view: "backlog", hl: ".bl-board [data-zone=backlog] .lane-body > .ticket:first-of-type .title", text: "Ein Klick auf den Titel öffnet das Ticket-Panel. Schlüssel und Pfeil öffnen " + D.team.tracker + "." },
      { view: "backlog", text: "Im Panel pflegst du Schätzung, Produkt, Projekt und Vormerkung und siehst, ob das Ticket refined ist. Der Verlauf steht darunter.", before() { setTimeout(() => FS.ticketPanel("ATL-434"), 250); } },
      { view: "backlog", hl: ".bl-ruleflag", text: "Entscheidung Regelkonflikt: Trifft keine oder mehr als eine Produktregel zu, markiert die Zeile es. Der Hinweis erklärt den Grund, das Produkt der Regel entscheidet, du kannst es für dieses Ticket von Hand setzen. Dann zurück zum Backlog.", before() { setView("unz"); } },
      { view: "backlog", hl: "#bl-syncwrap", text: "Ohne Tracker: Unter Einstellungen, Tickets und Tracker wählt das Team \"Arbeitspakete in Foresprint\". Dann gibt es keinen Abruf, Arbeitspakete legst du hier von Hand an, alles andere bleibt gleich. Zum Ansehen oben in den Abläufen den Schalter Tickets nutzen.", before() { setView("alle"); } },
    ],
  });
})();
