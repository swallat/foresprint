// Sprint workspace: Sprints, Prepare, Pre-plan, Plan, Review, Minutes (flows F3, F4, F5).
(function () {
  const D = window.DEMO;
  const sum = FS.sum, fmt = FS.fmt, esc = FS.esc, ic = FS.icon;
  const st = () => (FS.state.sp ??= { frozen: {}, closed: {}, noTracker: false, amt: {}, commit: {}, rv: {}, label: true, tagOn: true, mdFilter: "sprint" });

  // ---------- model ----------
  const BASE = {};
  D.sprints.forEach((s) => { BASE[s.id] = s.capacityPD + sum(Object.values(D.absences[s.id] || {}), (x) => x.d); });
  const absOf = (sid) => (D.absences[sid] ??= {});
  const absDays = (sid) => sum(Object.values(absOf(sid)), (x) => x.d);
  const absState = (sid) => { const s = FS.sprint(sid); return s.state === "past" ? "confirmed" : s.absences || "unknown"; };
  const stateOf = (sid) => { const s = FS.sprint(sid); if (st().closed[sid]) return "past"; if (st().frozen[sid] && s.state === "open") return "planned"; return s.state; };
  const STATE = { past: ["", "abgeschlossen", "check"], current: ["fc", "läuft", "play_arrow"], planned: ["ok", "geplant", "lock"], open: ["", "offen", "radio_button_unchecked"] };
  const stateChip = (sid) => { const m = STATE[stateOf(sid)]; return `<span class="chip ${m[0]}">${ic(m[2], "small")}${m[1]}</span>`; };
  const ABS = { confirmed: ["ok", "bestätigt"], announced: ["warn", "angekündigt"], unknown: ["", "unbekannt"] };
  const absChip = (sid) => { const m = ABS[absState(sid)]; return `<span class="chip ${m[0]}">${m[1]}</span>`; };

  const RATES = D.sprints.filter((s) => s.velocity != null).map((s) => s.velocity / s.capacityPD);
  const REFCAP = Math.round(FS.sum(D.people, (p) => p.fte) * 10);
  const RLO = Math.min(...RATES), RHI = Math.max(...RATES);
  function calc(sid) {
    const s = FS.sprint(sid), abs = absDays(sid), base = BASE[sid];
    if (s.state === "past" || st().closed[sid]) return { s, base, abs, cap: s.capacityPD, fc: s.plan, low: null, high: null, past: true };
    const cap = base - abs, fc = Math.round(cap * D.rate);
    return { s, base, abs, cap, fc, low: Math.round(cap * RLO), high: Math.round(cap * RHI) };
  }
  const tix = (sid) => D.tickets.filter((t) => t.sprint === sid);
  const pts = (l) => sum(l, (t) => t.est);
  const pp = (sid, pid) => { const pl = (D.productPlan[sid] ??= {}); return (pl[pid] ??= { def: Math.round(FS.product(pid).share * calc(sid).fc), pre: null }); };
  const preSum = (sid) => sum(D.products, (p) => pp(sid, p.id).pre);
  const earmark = (sid, pid) => pts(tix(sid).filter((t) => t.product === pid));
  const pd = (p) => p / D.rate;
  function projHints(sid) {
    return D.projects.map((pr) => {
      const l = tix(sid).filter((t) => t.project === pr.id);
      if (!l.length) return null;
      const p = pts(l), need = pd(p), free = pr.contingentPD - pr.usedPD, rest = free - need;
      const light = rest < 0 ? "bad" : rest < pr.contingentPD * 0.15 ? "warn" : "ok";
      return { pr, n: l.length, p, need, free, rest, light };
    }).filter(Boolean);
  }
  function rerender() {
    const m = document.getElementById("main"), y = m ? m.scrollTop : 0;
    FS.render();
    const m2 = document.getElementById("main");
    if (m2) m2.scrollTop = y;
  }

  // ---------- shared pieces ----------
  const CSS = `<style>
    .sp-sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}
    .sp-sum h3{margin:0 0 4px;font:600 12px/16px var(--font-ui);color:var(--text-muted)}
    .sp-sum .big{font:600 22px/28px var(--font-data)}
    .sp-sum .proj{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px}
    .sp-sum .cap{margin:6px 0 2px}
    .sp-btn{min-width:60px;height:28px;padding:0 10px;border-radius:999px;border:1.5px solid var(--primary);background:transparent;color:var(--primary);font:13px var(--font-data);cursor:pointer}
    .sp-btn.c{background:var(--primary);color:var(--on-primary)}
    .sp-btn.e{border:1.5px dashed var(--border);color:var(--text-muted)}
    .sp-btn:hover{filter:brightness(.95)}
    table.t td.sp-c,table.t th.sp-c{text-align:center}
    table.t td.sp-c .btn{white-space:normal;height:auto;min-height:32px;padding:4px 8px;max-width:170px}
    .sp-lb{max-height:460px;overflow:auto}
    .sp-po td{background:var(--surface-2);font-size:12px;color:var(--text-muted);font-weight:600}
    .sp-cur td{background:var(--primary-weak)}
    .sp-lane-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .sp-md h1{font:600 18px/24px var(--font-ui);margin:0 0 8px}
    .sp-md h2{margin:16px 0 6px}
    .sp-md ul{margin:0 0 8px;padding-left:18px}
    .sp-md code{background:var(--surface-2);padding:0 4px;border-radius:4px}
    .sp-step-chip{margin-left:4px}
    .sp-nowrap{white-space:normal !important}
  </style>`;
  // Tracker reconciliation on the plan step. Read-only by default: a list to adjust by hand.
  // With "write sprint back" switched on (Settings > Jira): preview, confirm, undo.
  const W = () => FS.state.jira?.write || { sprint: false, removed: "backlog" };
  const removedTarget = (sid) => ({ backlog: null, proforma: "Refinement", next: D.sprints[D.sprints.findIndex((s) => s.id === sid) + 1]?.id || null }[W().removed]);
  const tName = (x) => (x ? `Sprint ${x}` : "Backlog");
  function jiraCard(sid, l, out, fz) {
    const trk = D.team.tracker, w = W().sprint;
    const add = l.filter((t) => t.inTrackerSprint !== sid);
    const row = (t, from, to, btns) => `<div class="row" style="border-top:1px solid var(--border);padding:6px 0">${FS.keyLink(t)}<span style="flex:1;min-width:180px">${esc(t.title)}</span><span class="small muted data">${from} → ${to}</span>${btns}</div>`;
    if (!w) return `<div class="card" id="sp-jira" style="margin-bottom:16px"><h2>In ${trk} anpassen</h2>
        ${out.length ? `<p class="small muted" style="margin-top:0">Diese Tickets stehen in ${trk} noch im Sprint ${sid}, wurden hier aber herausgenommen. Das Tracker-Ticket bleibt unverändert, die Liste kommt ins Planungsprotokoll.</p>${out.map((t) => row(t, tName(sid), "herausgenommen", `<button class="btn" type="button" data-back="${t.key}">${ic("undo")}Zurück in den Sprint</button><button class="btn" type="button" data-jdone="${t.key}">${ic("check")}In ${trk} angepasst</button>`)).join("")}` : `<p class="muted" style="margin:0">Nichts anzupassen: ${trk} und Plan stimmen überein. Nimm zum Beispiel ATL-421 aus dem Sprint, dann erscheint es hier.</p>`}
        <p class="small muted" style="margin:8px 0 0">Wenn ihr komplett in Foresprint plant, kann Foresprint den Sprint auch zurückschreiben: <a href="#jira">Einstellungen > Jira und Tickets</a>.</p></div>`;
    const n = add.length + out.length;
    return `<div class="card" id="sp-jira" style="margin-bottom:16px"><div class="row"><h2 style="margin:0;flex:1">Abgleich mit ${trk}</h2>${n ? `<span class="chip warn">${n} Änderungen offen</span>` : FS.lightChip("ok", "stimmt überein")}
        <button class="btn ${fz ? "primary" : ""}" type="button" id="sp-jwrite" ${n ? "" : "disabled"}>${ic("upload")}In ${trk} übernehmen</button></div>
      <p class="small muted" style="margin:8px 0">Foresprint schreibt nur das Sprintfeld, erst nach deiner Bestätigung in der Vorschau. Am besten nach dem Einfrieren.</p>
      ${add.map((t) => row(t, tName(t.inTrackerSprint), `Sprint ${sid}`, "")).join("")}
      ${out.map((t) => row(t, `Sprint ${sid}`, tName(removedTarget(sid)), `<button class="btn" type="button" data-back="${t.key}">${ic("undo")}Zurück in den Sprint</button>`)).join("")}</div>`;
  }
  function jiraPreview(sid, rerender) {
    const l = tix(sid), trk = D.team.tracker;
    const ch = [...l.filter((t) => t.inTrackerSprint !== sid).map((t) => [t, t.inTrackerSprint || null, sid]), ...D.tickets.filter((t) => t.inTrackerSprint === sid && t.sprint !== sid).map((t) => [t, sid, removedTarget(sid)])];
    const el = FS.openPanel(`In ${trk} übernehmen: Sprint ${sid}`, `
      <p style="margin:0">Diese Änderungen schreibt Foresprint nach ${trk}. Abwählen, was so bleiben soll.</p>
      ${tw(`<table class="t"><thead><tr><th></th><th>Ticket</th><th>jetzt</th><th>danach</th></tr></thead><tbody>${ch.map(([t, a, b], i) => `<tr><td><input type="checkbox" data-jw="${i}" checked aria-label="${t.key} übernehmen"></td><td>${FS.keyLink(t)}</td><td class="data small">${tName(a)}</td><td class="data small"><strong>${tName(b)}</strong></td></tr>`).join("")}</tbody></table>`)}
      <p class="small muted" style="margin:0">Nur das Sprintfeld. Reihenfolge, Schätzung, Status und Texte bleiben. Der Vorgang kommt ins Planungsprotokoll und lässt sich direkt danach rückgängig machen.</p>
      <div class="row"><button class="btn primary" type="button" id="jw-go">${ic("upload")}<span id="jw-n">${ch.length}</span> Änderungen schreiben</button><button class="btn ghost" type="button" id="jw-cancel">Abbrechen</button></div>`);
    if (!el) return;
    const sel = () => ch.filter((_, i) => el.querySelector(`[data-jw="${i}"]`).checked);
    el.querySelectorAll("[data-jw]").forEach((c) => (c.onchange = () => (el.querySelector("#jw-n").textContent = sel().length)));
    el.querySelector("#jw-cancel").onclick = FS.closePanel;
    el.querySelector("#jw-go").onclick = () => {
      const done = sel(); done.forEach(([t, a, b]) => (t.inTrackerSprint = b));
      (st().jiraLog ??= []).push({ sid, n: done.length });
      FS.closePanel(); rerender();
      FS.toast(`${done.length} Tickets in ${trk} angepasst. Steht im Planungsprotokoll.`, () => { done.forEach(([t, a]) => (t.inTrackerSprint = a)); st().jiraLog.pop(); rerender(); FS.toast(`In ${trk} zurückgesetzt.`); });
    };
  }
  const STAGES = [["prepare", "Vorbereiten"], ["preplan", "Vorplanen"], ["plan", "Planen"], ["review", "Review"], ["minutes", "Protokolle"]];
  const LEAD = {
    prepare: "Abwesenheiten eintragen und bestätigen, dann sehen, was für die Planung noch fehlt.",
    preplan: "Tickets vormerken und den Betrag je Produkt festlegen. Geht jederzeit, auch für spätere Sprints.",
    plan: "Tickets gemeinsam in den Sprint nehmen, bis Summe, Produkte und Projekte passen.",
    review: "Velocity, Scope-Änderung und Erledigtes je Produkt festhalten.",
    minutes: "Jedes Speichern von Vorplanung, Planung und Review schreibt ein Protokoll.",
  };
  function missing(sid, stage) {
    const stt = stateOf(sid);
    if (stage === "prepare") return absState(sid) !== "confirmed" ? "Abwesenheiten sind nicht bestätigt." : null;
    if (stage === "preplan") { const n = D.products.filter((p) => pp(sid, p.id).pre == null).length; return stt !== "past" && n ? `Vorplanung fehlt für ${n} Produkt${n > 1 ? "e" : ""}.` : null; }
    if (stage === "plan") return stt === "open" ? "Plan ist noch nicht eingefroren." : null;
    if (stage === "review") return stt === "current" ? "Review ist noch nicht abgeschlossen." : null;
    if (stage === "minutes") return D.minutes.some((m) => m.sprint === sid) ? null : "Noch kein Protokoll vorhanden.";
  }
  function header(sid, stage, actions = "") {
    const s = FS.sprint(sid), title = STAGES.find((x) => x[0] === stage)[1];
    const hint = stage !== "plan" && missing(sid, stage);
    return `${CSS}
    <div class="page-head"><div><h1>${title}: Sprint <span class="data">${sid}</span> ${stateChip(sid)}</h1>
      <p class="lead"><span class="data">${FS.fmtDate(s.start)} bis ${FS.fmtDate(s.end)}</span> · ${s.days} Arbeitstage. ${LEAD[stage]}</p></div>
      <div class="actions">${actions}</div></div>
    <nav class="stepper" aria-label="Stufen des Sprints">${STAGES.map(([id, label], i) => {
      const m = missing(sid, id), done = !m && id !== "minutes" && (id !== "review" || stateOf(sid) === "past");
      return `<a href="#${id}" class="${id === stage ? "active" : ""} ${done ? "done" : ""}" ${id === stage ? 'aria-current="step"' : ""}><span class="n">${done ? ic("check", "small") : i + 1}</span>${label}${m ? `<span class="chip warn sp-step-chip" title="${esc(m)}">fehlt noch</span>` : ""}</a>`;
    }).join("")}</nav>
    ${hint ? `<div class="banner info">${ic("info")}<div class="grow">${hint} Die Ansicht funktioniert trotzdem mit den vorhandenen Daten.</div></div>` : ""}`;
  }
  const calcBtn = (k, arg = "") => `<button class="btn icon ghost" type="button" data-calc="${k}" data-arg="${arg}" aria-label="Rechenweg anzeigen" title="Rechenweg">${ic("calculate")}</button>`;
  function summary(sid) {
    const c = calc(sid), l = tix(sid), p = pts(l), pre = preSum(sid), hints = projHints(sid);
    const commit = st().frozen[sid]?.commit ?? c.s.plan;
    return `<div class="card sp-sumbar" style="margin-bottom:16px"><div class="sp-sum">
      <div><h3>Kapazität</h3><div class="row"><span class="big">${fmt(c.cap)} PT</span>${calcBtn("cap")}</div>
        <div class="small muted">${c.abs ? `${fmt(c.abs)} PT Abwesenheit (${ABS[absState(sid)][1]})` : `keine Abwesenheit erfasst`}</div></div>
      <div><h3>Forecast PLAN</h3><div class="row"><span class="big" style="color:var(--forecast)">${fmt(c.fc)} Punkte</span>${calcBtn("fc")}</div>
        <div class="small muted">${c.low != null ? `Spanne <span class="data">${c.low} bis ${c.high}</span> · Rate <span class="data">${fmt(D.rate, 2)}</span> je PT` : "Plan des abgeschlossenen Sprints"}</div></div>
      <div><h3>Geplant</h3><div class="row"><span class="big">${fmt(p)} Punkte</span></div>
        ${FS.capBar(p, c.fc, c.low, c.high)}
        <div class="small muted">${commit != null ? `Zusage <span class="data">${commit}</span> · ` : ""}Vorgeplant <span class="data">${pre || "–"}</span> · ${l.length} Tickets</div></div>
      <div><h3>Kontingente je Projekt <span class="chip small">Schätzung</span></h3>
        ${hints.length ? hints.map((h) => `<div class="proj"><span class="chip">${ic("flag", "small")}${esc(h.pr.name)}</span><span class="data small">≈ ${fmt(h.need)} PT</span>${FS.lightChip(h.light, h.rest < 0 ? `${fmt(-h.rest)} PT drüber` : `Rest ${fmt(h.rest)} PT`)}</div>`).join("") : `<div class="small muted">Keine Projekttickets im Sprint.</div>`}</div>
    </div></div>`;
  }
  const tw = (inner) => `<div class="tw">${inner}</div>`;
  const calcTable = (rows) => tw(`<table class="t"><tbody>${rows.map(([a, b, bold]) => `<tr class="${bold ? "sum" : ""}"><td class="sp-nowrap" style="white-space:normal">${a}</td><td class="num">${b}</td></tr>`).join("")}</tbody></table>`);
  function calcPanel(kind, arg) {
    const sid = FS.state.sprint, c = calc(sid);
    if (kind === "cap") FS.openPanel(`Rechenweg: Kapazität ${sid}`, calcTable([["Personentage nach Kalender, FTE und Overhead, ohne Abwesenheit", `${fmt(c.base)} PT`], ["minus Abwesenheiten (" + ABS[absState(sid)][1] + ")", `− ${fmt(c.abs)} PT`], ["Kapazität", `${fmt(c.cap)} PT`, 1]]) + `<p class="small muted">Feiertage der Region ${D.team.region} sind in den Personentagen schon abgezogen.</p>`);
    if (kind === "fc") FS.openPanel(`Rechenweg: Forecast PLAN ${sid}`, calcTable([["Kapazität", `${fmt(c.cap)} PT`], ["mal Rate (normierte Velocity)", `${fmt(D.rate, 2)} Punkte je PT`], ["Forecast PLAN", `${fmt(c.fc)} Punkte`, 1], ["untere Grenze (niedrigste Rate " + fmt(RLO, 2) + " × Kapazität)", fmt(c.low)], ["obere Grenze (höchste Rate " + fmt(RHI, 2) + " × Kapazität)", fmt(c.high)]]) + `<p class="small muted">Die Spanne kommt aus der niedrigsten und höchsten Rate der letzten Sprints.</p>`);
    if (kind === "pd") { const h = projHints(sid).find((x) => x.pr.id === arg); FS.openPanel(`Rechenweg: ${h.pr.name} (Schätzung)`, calcTable([[`Punkte im Sprint ${sid}`, fmt(h.p)], ["geteilt durch Rate (Punkte je PT)", fmt(D.rate, 2)], ["entspricht etwa", `${fmt(h.need, 1)} PT`, 1], ["Kontingent gebucht", `${h.pr.contingentPD} PT`], ["bereits verbraucht", `− ${h.pr.usedPD} PT`], ["Rest nach diesem Sprint", `${fmt(h.rest, 1)} PT`, 1]]) + `<p class="small muted">Umrechnung mit der Forecast-Rate des Sprints. Erledigtes wird nach dem Review mit der tatsächlichen Rate gerechnet.</p>`); }
    if (kind === "vel") { const r = rvOf(sid); FS.openPanel(`Rechenweg: Velocity ${sid}`, calcTable([["Zusage (Plan)", fmt(r.plan)], ["minus nicht erledigt", `− ${fmt(r.notDone)}`], ["plus zusätzlich erledigt", `+ ${fmt(r.extra)}`], ["Velocity", `${fmt(r.plan - r.notDone + r.extra)} Punkte`, 1]])); }
    if (kind === "rate") { const r = rvOf(sid), v = r.plan - r.notDone + r.extra; FS.openPanel(`Rechenweg: tatsächliche Rate ${sid}`, calcTable([["Velocity", `${fmt(v)} Punkte`], ["geteilt durch eingefrorene Personentage", `${fmt(r.freeze)} PT`], ["tatsächliche Rate", `${fmt(v / r.freeze, 2)} Punkte je PT`, 1], ["Planrate zum Vergleich", fmt(D.rate, 2)]]) + `<p class="small muted">Diese Rate rechnet Erledigtes in Projektkontingent um (Schätzung).</p>`); }
  }
  function wireCommon(main) {
    main.addEventListener("click", (e) => {
      const b = e.target.closest("[data-calc]");
      if (b) return calcPanel(b.dataset.calc, b.dataset.arg);
      const a = e.target.closest("a[data-sprint]");
      if (a) {
        e.preventDefault();
        FS.state.sprint = a.dataset.sprint;
        if (location.hash === a.getAttribute("href")) FS.render(); else location.hash = a.getAttribute("href");
      }
    });
  }
  function poRows(cols, rowFn, sumFn) {
    let out = "";
    D.pos.forEach((po) => {
      const ps = D.products.filter((p) => p.po === po.id);
      out += `<tr class="sp-po"><td colspan="${cols}">PO ${esc(po.name)}</td></tr>${ps.map((p) => `<tr>${rowFn(p)}</tr>`).join("")}<tr class="sum"><td>Summe ${esc(po.name)}</td>${sumFn(ps)}</tr>`;
    });
    return out + `<tr class="sum"><td>Gesamt</td>${sumFn(D.products)}</tr>`;
  }
  const n = (v) => (v == null ? `<span class="muted">–</span>` : fmt(v));
  const signed = (v) => (v > 0 ? `+${fmt(v)}` : v < 0 ? `−${fmt(-v)}` : "0");

  // ---------- Sprints ----------
  FS.view("sprints", {
    title: "Sprint-Übersicht",
    render() {
      const cur = FS.state.sprint;
      const next = (s) => {
        const stt = stateOf(s.id);
        if (stt === "past") return "–";
        if (stt === "current") return "Review vorbereiten";
        if (stt === "planned") return "Plan eingefroren";
        if (absState(s.id) !== "confirmed") return "Abwesenheiten bestätigen";
        if (D.products.some((p) => pp(s.id, p.id).pre == null)) return "Vorplanen";
        return "Planen";
      };
      const stageLinks = [["prepare", "event_available", "Vorbereiten"], ["preplan", "low_priority", "Vorplanen"], ["plan", "checklist", "Planen"], ["review", "task_alt", "Review"], ["minutes", "description", "Protokolle"]];
      return `${CSS}<div class="page-head"><div><h1>Sprint-Übersicht</h1><p class="lead">Alle Sprints auf einen Blick. Von hier springst du in jede Stufe, auch in spätere Sprints. Nichts ist gesperrt.</p></div></div>
      ${tw(`<table class="t"><thead><tr><th>Sprint</th><th>Zeitraum</th><th>Status</th><th>Abwesenheiten</th><th class="num">Kapazität PT</th><th class="num">Forecast PLAN</th><th class="num">Plan</th><th class="num">Velocity</th><th class="num" title="Velocity umgerechnet auf die volle Teamkapazität (Referenz), damit Sprints mit Urlaub vergleichbar sind">Normierte Velocity</th><th>Nächster Schritt</th><th>Stufen</th></tr></thead><tbody>
      ${D.sprints.map((s) => { const c = calc(s.id), stt = stateOf(s.id), plan = st().frozen[s.id]?.commit ?? s.plan, vel = st().closed[s.id] ? rvVel(s.id) : s.velocity; return `<tr class="${s.id === cur ? "sp-cur" : ""}">
        <td><span class="data"><strong>${s.id}</strong></span></td><td class="data">${FS.fmtDate(s.start)} bis ${FS.fmtDate(s.end)}</td><td>${stateChip(s.id)}</td><td>${absChip(s.id)}</td>
        <td class="num">${fmt(c.cap)}</td>
        <td class="num">${stt === "past" ? "–" : `${fmt(c.fc)} <span class="muted small">(${c.low} bis ${c.high})</span>`}</td>
        <td class="num">${n(plan)}</td><td class="num">${n(vel)}</td><td class="num">${vel != null && stt === "past" ? `${fmt(vel / s.capacityPD * REFCAP, 1)} <span class="muted small">(${fmt(vel / s.capacityPD, 2)} je PT)</span>` : "–"}</td><td>${next(s)}</td>
        <td><div class="row" style="gap:2px;flex-wrap:nowrap">${stageLinks.map(([id, icon, l]) => `<a class="btn icon ghost" href="#${id}" data-sprint="${s.id}" title="${l} für ${s.id}" aria-label="${l} für ${s.id}">${ic(icon)}</a>`).join("")}</div></td></tr>`; }).join("")}
      </tbody></table>`)}
      <p class="small muted">Normierte Velocity = Velocity ÷ Kapazität × Referenzkapazität (volles Team ohne Abwesenheit, ${fmt(REFCAP)} PT). In Klammern die Rate je PT, aus der der Forecast rechnet. <a href="#help">Hilfe > Rechenwege</a></p>
      <p class="small muted" style="margin-top:12px">Gewählter Sprint hervorgehoben. Kapazität und Forecast PLAN folgen den Abwesenheiten live. Zusagen und Velocity zeigen abgeschlossene und geplante Sprints.</p>`;
    },
    wire(main) { wireCommon(main); },
  });

  // ---------- Prepare ----------
  FS.view("prepare", {
    title: "Sprint vorbereiten",
    render() {
      const sid = FS.state.sprint, i = D.sprints.findIndex((s) => s.id === sid), cols = D.sprints.slice(i, i + 4);
      const cellCls = (c) => (!c ? "e" : c.s === "c" ? "c" : "");
      const cur = calc(sid), c0 = BASE[sid] - 0;
      const ready = readiness(sid);
      return `${header(sid, "prepare")}${summary(sid)}
      <div class="card" style="margin-bottom:16px"><div class="row" style="margin-bottom:8px"><h2 style="margin:0;flex:1">Abwesenheiten in Personentagen</h2>
        <span class="small muted">Klick wechselt: leer, <span class="chip" style="border:1.5px dashed var(--border)">angekündigt</span> (Rahmen), <span class="chip" style="background:var(--primary);color:var(--on-primary)">bestätigt</span> (gefüllt). Mit + und − ändert sich die Zahl der Tage.</span></div>
      ${tw(`<table class="t" id="sp-abs-grid"><thead><tr><th>Person</th><th class="num">FTE</th>${cols.map((s) => `<th class="sp-c ${s.id === sid ? "sp-cur" : ""}"><span class="data">${s.id}</span><br><span class="muted small">${FS.fmtDate(s.start)} ${absChip(s.id)}</span></th>`).join("")}</tr></thead><tbody>
      ${D.people.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${fmt(p.fte, 1)}</td>${cols.map((s) => { const c = absOf(s.id)[p.id]; return `<td class="sp-c"><button type="button" class="sp-btn ${cellCls(c)}" data-cell="${s.id}|${p.id}" aria-label="${esc(p.name)}, ${s.id}: ${c ? `${c.d} Tage, ${c.s === "c" ? "bestätigt" : "angekündigt"}` : "keine Abwesenheit"}" title="${c ? (c.s === "c" ? "bestätigt" : "angekündigt") : "leer"}: Klick wechselt den Status">${c ? `${c.d} T` : "–"}</button></td>`; }).join("")}</tr>`).join("")}
      <tr class="sum"><td>Abwesend gesamt</td><td></td>${cols.map((s) => `<td class="sp-c data">${fmt(absDays(s.id))} PT</td>`).join("")}</tr>
      <tr class="sum"><td>Kapazität</td><td></td>${cols.map((s) => `<td class="sp-c data">${fmt(calc(s.id).cap)} PT</td>`).join("")}</tr>
      <tr class="sum"><td>Forecast PLAN</td><td></td>${cols.map((s) => { const c = calc(s.id); return `<td class="sp-c data" style="color:var(--forecast)">${c.past ? "–" : `${fmt(c.fc)} <span class="muted small">(${c.low} bis ${c.high})</span>`}</td>`; }).join("")}</tr>
      <tr><td>Bestätigen</td><td></td>${cols.map((s) => { const cells = Object.keys(absOf(s.id)).length; return `<td class="sp-c"><div class="stack" style="align-items:center">${cells && absState(s.id) !== "confirmed" ? `<button class="btn" type="button" data-confirm="${s.id}">${ic("done_all")}Angekündigte bestätigen</button>` : ""}<button class="btn ${cells ? "ghost" : ""}" type="button" data-nobody="${s.id}">${ic("person_off")}Niemand abwesend bestätigen</button></div></td>`; }).join("")}</tr>
      </tbody></table>`)}</div>
      <div class="grid cols-2">
        <div class="card" id="sp-ready"><h2>Bereit für die Planung?</h2><div class="stack">${ready.map((r) => `<div class="row">${FS.lightChip(r.light, r.state)}<span style="flex:1;min-width:160px"><strong>${r.title}</strong><br><span class="small muted">${r.text}</span></span>${r.link ? `<a class="btn" href="${r.link[0]}">${r.link[1]}</a>` : ""}</div>`).join("")}</div>
          <p class="small muted" style="margin-top:12px">Offene Punkte sperren nichts. Planen geht jederzeit mit den Daten, die da sind.</p></div>
        <div class="card"><h2>Vorschau für ${sid}</h2>
          <dl class="kv"><dt>Ohne Abwesenheit</dt><dd class="data">${fmt(BASE[sid])} PT · ${fmt(Math.round(BASE[sid] * D.rate))} Punkte</dd>
          <dt>Mit Abwesenheit</dt><dd class="data"><strong>${fmt(cur.cap)} PT</strong> · <strong style="color:var(--forecast)">${fmt(cur.fc)} Punkte</strong> ${calcBtn("fc")}</dd>
          <dt>Spanne</dt><dd class="data">${cur.low} bis ${cur.high} Punkte</dd>
          <dt>Veränderung</dt><dd class="data">${signed(cur.cap - BASE[sid])} PT · ${signed(cur.fc - Math.round(BASE[sid] * D.rate))} Punkte</dd></dl>
          ${FS.capBar(preSum(sid), cur.fc, cur.low, cur.high)}<p class="small muted">Balken: vorgeplante Punkte (${preSum(sid) || 0}) gegen die Spanne des Forecast PLAN.</p></div>
      </div>`;
    },
    wire(main) {
      wireCommon(main);
      main.querySelectorAll("[data-cell]").forEach((b) => {
        const [sid, pid] = b.dataset.cell.split("|");
        const touch = () => { const cells = Object.values(absOf(sid)); FS.sprint(sid).absences = !cells.length ? "unknown" : cells.every((c) => c.s === "c") ? "confirmed" : "announced"; rerender(); main = document.getElementById("main"); main.querySelector(`[data-cell="${sid}|${pid}"]`)?.focus(); };
        b.onclick = () => { const a = absOf(sid), c = a[pid]; if (!c) a[pid] = { d: 1, s: "a" }; else if (c.s === "a") c.s = "c"; else delete a[pid]; touch(); };
        b.onkeydown = (e) => { const c = absOf(sid)[pid]; if (!c || !["+", "-"].includes(e.key)) return; c.d = Math.max(1, Math.min(10, c.d + (e.key === "+" ? 1 : -1))); touch(); };
      });
      main.querySelectorAll("[data-confirm]").forEach((b) => (b.onclick = () => { confirmAbs(b.dataset.confirm); rerender(); FS.toast(`Abwesenheiten für ${b.dataset.confirm} bestätigt.`); }));
      main.querySelectorAll("[data-nobody]").forEach((b) => (b.onclick = () => { const sid = b.dataset.nobody, prev = JSON.stringify(absOf(sid)), ps = FS.sprint(sid).absences; nobody(sid); rerender(); FS.toast(`Für ${sid}: niemand abwesend, bestätigt.`, () => { D.absences[sid] = JSON.parse(prev); FS.sprint(sid).absences = ps; rerender(); }); }));
    },
  });
  function confirmAbs(sid) { Object.values(absOf(sid)).forEach((c) => (c.s = "c")); FS.sprint(sid).absences = "confirmed"; }
  function nobody(sid) { D.absences[sid] = {}; FS.sprint(sid).absences = "confirmed"; }
  function readiness(sid) {
    const unref = tix(sid).filter((t) => !t.refined), noPre = D.products.filter((p) => pp(sid, p.id).pre == null), dev = D.products.filter((p) => pp(sid, p.id).pre != null && earmark(sid, p.id) > pp(sid, p.id).pre);
    const a = absState(sid);
    return [
      { light: a === "confirmed" ? "ok" : "warn", state: a === "confirmed" ? "erledigt" : "offen", title: "Abwesenheiten", text: a === "confirmed" ? "Alle Abwesenheiten sind bestätigt." : a === "announced" ? `${Object.keys(absOf(sid)).length} Personen angekündigt, noch nicht bestätigt. Bestätigen oben in der Tabelle.` : "Noch nichts erfasst. Eintragen oder oben \"Niemand abwesend bestätigen\"." },
      { light: unref.length ? "warn" : "ok", state: unref.length ? "offen" : "erledigt", title: "Refinement", text: unref.length ? `${unref.length} vorgemerkte Tickets sind nicht refined: ${unref.map((t) => t.key).join(", ")}.` : "Alle vorgemerkten Tickets sind refined und geschätzt.", link: unref.length ? ["#backlog", "Im Backlog öffnen"] : null },
      { light: noPre.length || dev.length ? "warn" : "ok", state: noPre.length || dev.length ? "offen" : "erledigt", title: "Vorplanung je Produkt", text: noPre.length ? `Kein Betrag für ${noPre.map((p) => p.name).join(", ")}.` : dev.length ? `Vormerkungen liegen über dem Betrag: ${dev.map((p) => p.name).join(", ")}.` : "Jedes Produkt hat einen Betrag, die Vormerkungen passen.", link: ["#preplan", "Vorplanen"] },
    ];
  }

  // ---------- Pre-plan ----------
  FS.view("preplan", {
    title: "Sprint vorplanen",
    render() {
      const sid = FS.state.sprint, c = calc(sid), l = tix(sid), pre = preSum(sid), ear = pts(l), prod = D.team.prodAccess !== false;
      const over = c.high != null && Math.max(pre, ear) > c.high;
      const rows = poRows(8, (p) => { const r = pp(sid, p.id), e = earmark(sid, p.id), dv = r.pre == null ? null : r.pre - e; return `<td>${FS.productChip(p.id)}</td><td class="num">${n(r.def)}</td>
        <td class="num edit"><input aria-label="Vorgeplant ${esc(p.name)}" data-pre="${p.id}" inputmode="numeric" value="${r.pre ?? ""}" placeholder="–"></td><td class="num">${fmt(e)}</td>
        <td class="num">${dv == null ? n(null) : `<span class="${dv < 0 ? "chip warn" : ""}">${signed(dv)}</span>`}</td><td class="num">${n(r.plan)}</td><td class="num">${n(r.prodPlan)}</td><td class="num">${n(r.done)}</td>`; },
        (ps) => { const s = (f) => sum(ps, f), pr = s((p) => pp(sid, p.id).pre), e = s((p) => earmark(sid, p.id)); return `<td class="num">${fmt(s((p) => pp(sid, p.id).def))}</td><td class="num">${fmt(pr)}</td><td class="num">${fmt(e)}</td><td class="num">${signed(pr - e)}</td><td class="num">${fmt(s((p) => pp(sid, p.id).plan))}</td><td class="num">${fmt(s((p) => pp(sid, p.id).prodPlan))}</td><td class="num">${fmt(s((p) => pp(sid, p.id).done))}</td>`; });
      const groups = [...D.projects.map((p) => p.id), null].map((pid) => ({ pid, list: l.filter((t) => (t.project || null) === pid) })).filter((g) => g.list.length);
      return `${header(sid, "preplan", `<button class="btn" type="button" id="sp-take">${ic("playlist_add")}Vormerkungen übernehmen</button><button class="btn" type="button" id="sp-std">${ic("restart_alt")}Standard übernehmen</button>`)}${summary(sid)}
      ${over ? `<div class="banner warn" id="sp-overcap">${ic("warning")}<div class="grow">Vorgeplant <span class="data">${pre}</span> und vorgemerkt <span class="data">${ear}</span> Punkte liegen über der oberen Grenze <span class="data">${c.high}</span> des Forecast PLAN (${c.fc}). Das ist nur eine Warnung. Du kannst weiterarbeiten, im Planning entscheidet das Team.</div></div>` : ""}
      <h2>Betrag je Produkt</h2>
      ${tw(`<table class="t" id="sp-prod-table"><thead><tr><th>Produkt</th><th class="num">Standard</th><th class="num">Vorgeplant</th><th class="num">Vormerkungen</th><th class="num">Abweichung</th><th class="num">Geplant</th><th class="num">davon Prod</th><th class="num">Erledigt</th></tr></thead><tbody>${rows}</tbody></table>`)}
      <p class="small muted" style="margin:8px 0 24px">Hier editierbar: Vorgeplant. Standard kommt aus dem Budgetanteil, Vormerkungen sind die Summe der vorgemerkten Tickets (Vorschlag). Geplant, davon Prod und Erledigt füllen Planning und Review, hier nur lesbar.</p>
      <div id="sp-earmarks"><div class="row" style="margin-bottom:8px"><h2 style="margin:0;flex:1">Vorgemerkte Tickets nach Projekt</h2><a class="btn" href="#backlog">${ic("view_list")}Im Backlog vormerken</a></div>
      ${groups.length ? `<div class="stack" style="gap:16px">${groups.map((g) => { const pr = g.pid && FS.project(g.pid), h = pr && projHints(sid).find((x) => x.pr.id === g.pid), p = pts(g.list); return `<div class="card" style="padding:0"><div class="row" style="padding:10px 12px;border-bottom:1px solid var(--border)">${FS.projectChip(g.pid)}<span class="small muted">${g.list.length} Tickets · <span class="data">${fmt(p)}</span> Punkte</span>
        <span style="flex:1"></span>${h ? `<span class="small">≈ <span class="data">${fmt(h.need, 1)} PT</span> <span class="chip small">Schätzung</span> von ${pr.contingentPD} PT gebucht, ${pr.usedPD} verbraucht</span>${FS.lightChip(h.light, h.rest < 0 ? `${fmt(-h.rest)} PT über Kontingent` : `Rest ${fmt(h.rest)} PT`)}${calcBtn("pd", g.pid)}` : `<span class="small muted">Tagesgeschäft: kein Kontingent, läuft über die Produktbeträge</span>`}</div>
        ${g.list.map((t) => FS.ticketRow(t, { noProject: true })).join("")}</div>`; }).join("")}</div>` : `<div class="banner">${ic("inbox")}<div class="grow">Noch nichts für ${sid} vorgemerkt. Im Backlog Tickets in die Spalte dieses Sprints ziehen.</div></div>`}</div>`;
    },
    wire(main) {
      wireCommon(main);
      const sid = FS.state.sprint;
      main.querySelectorAll("[data-pre]").forEach((i) => (i.onchange = () => { const v = parseInt(i.value, 10); pp(sid, i.dataset.pre).pre = isNaN(v) ? null : Math.max(0, v); rerender(); }));
      main.querySelector("#sp-take").onclick = () => { const prev = D.products.map((p) => pp(sid, p.id).pre); D.products.forEach((p) => (pp(sid, p.id).pre = earmark(sid, p.id))); rerender(); FS.toast("Beträge aus den Vormerkungen übernommen.", () => { D.products.forEach((p, i) => (pp(sid, p.id).pre = prev[i])); rerender(); }); };
      main.querySelector("#sp-std").onclick = () => { const prev = D.products.map((p) => pp(sid, p.id).pre); D.products.forEach((p) => (pp(sid, p.id).pre = pp(sid, p.id).def)); rerender(); FS.toast("Standardbeträge übernommen.", () => { D.products.forEach((p, i) => (pp(sid, p.id).pre = prev[i])); rerender(); }); };
    },
  });

  // ---------- Plan ----------
  const nowStr = () => `${D.today} 14:05`;
  function freeze(sid) {
    const S = st(), l = tix(sid), noT = S.noTracker;
    const amt = (p) => (noT ? amtOf(sid, p.id) : earmark(sid, p.id));
    D.products.forEach((p) => { pp(sid, p.id).plan = amt(p); pp(sid, p.id).prodPlan ??= 0; });
    const commit = noT ? commitOf(sid) : pts(l);
    S.frozen[sid] = { keys: l.map((t) => t.key), commit, at: nowStr(), noT };
    D.minutes.filter((m) => m.sprint === sid && m.kind === "Planning").forEach((m) => (m.obsolete = true));
    const m = { sprint: sid, kind: "Planning", at: nowStr(), by: "Kim Berger", file: `protokolle/${sid}-planning-${D.today.replace(/-/g, "")}-140500.md` };
    D.minutes.unshift(m);
    m.md = minuteMd(m);
    FS.sprint(sid).plan = commit;
  }
  const amtOf = (sid, pid) => (st().amt[sid] ??= {})[pid] ?? pp(sid, pid).pre ?? pp(sid, pid).def;
  const commitOf = (sid) => st().commit[sid] ?? sum(D.products, (p) => amtOf(sid, p.id));

  FS.view("plan", {
    title: "Sprint planen",
    render() {
      const sid = FS.state.sprint, S = st(), c = calc(sid), fz = S.frozen[sid], l = tix(sid), p = pts(l), noT = S.noTracker;
      const cands = D.tickets.filter((t) => t.status !== "Fertig" && (t.sprint == null || t.sprint > sid) && t.sprint !== sid);
      const abs = absState(sid), cells = Object.entries(absOf(sid));
      const unref = l.filter((t) => !t.refined).length, noEst = l.filter((t) => t.est == null).length;
      const jira = D.tickets.filter((t) => t.inTrackerSprint === sid && t.sprint !== sid && !t.jiraDone);
      const hints = projHints(sid);
      const actions = `${noT ? "" : `<button class="btn" type="button" id="sp-present" title="Tickets groß im Fenster zeigen, zum Teilen im Meeting">${ic("fit_screen")}Großansicht</button>`}<button class="btn primary" type="button" id="sp-freeze" ${fz ? "disabled" : ""}>${ic("lock")}Einigung festhalten und einfrieren</button>`;
      const laneTop = noT ? "" : `<div id="sp-lanes" class="grid cols-2" style="margin-bottom:16px">
        <div class="lane" data-zone="backlog"><div class="lane-head"><div class="sp-lane-h"><strong style="flex:1">Kandidaten</strong><span class="small muted data">${cands.length} Tickets · ${fmt(pts(cands))} Punkte</span></div><span class="small muted">Backlog und für spätere Sprints vorgemerkt</span></div>
          <div class="lane-body sp-lb">${cands.map((t) => FS.ticketRow(t, { drag: !fz })).join("") || `<div class="small muted" style="padding:12px">Keine Kandidaten übrig.</div>`}</div></div>
        <div class="lane" data-zone="${sid}"><div class="lane-head"><div class="sp-lane-h"><strong style="flex:1">Sprint <span class="data">${sid}</span></strong><span class="data"><strong>${fmt(p)}</strong> von ${fmt(c.fc)} <span class="muted small">(${c.low} bis ${c.high})</span></span>${calcBtn("fc")}</div>
          ${FS.capBar(p, c.fc, c.low, c.high)}
          <div class="row small">${p > c.high ? FS.lightChip("bad", `${p - c.high} über Spanne`) : p < c.low ? `<span class="chip fc">${c.low - p} bis zur Spanne</span>` : FS.lightChip("ok", "in der Spanne")}${unref ? `<span class="chip warn">${unref} nicht refined</span>` : ""}${noEst ? `<span class="chip warn">${noEst} ohne Schätzung (zählen 0)</span>` : ""}</div></div>
          <div class="lane-body sp-lb">${l.map((t) => FS.ticketRow(t, { drag: !fz })).join("") || `<div class="small muted" style="padding:12px">Noch leer. Tickets hierher ziehen.</div>`}</div></div></div>
        <p class="small muted" style="margin:-8px 0 16px">Ziehen oder Alt+Pfeil links/rechts verschiebt zwischen den Spalten, Alt+Pfeil hoch/runter sortiert. Doppelklick öffnet das Ticket.</p>`;
      const prodTbl = `<div class="card"><h2>Produkt gegen Budget</h2>${tw(`<table class="t"><thead><tr><th>Produkt</th><th class="num">Budget</th><th class="num">${noT ? "Betrag" : "Tickets"}</th><th class="num">Differenz</th></tr></thead><tbody>
        ${D.products.map((pr) => { const b = pp(sid, pr.id).pre ?? pp(sid, pr.id).def, u = noT ? amtOf(sid, pr.id) : earmark(sid, pr.id), d = u - b; return `<tr><td>${FS.productChip(pr.id)}</td><td class="num">${b}</td><td class="num">${u}</td><td class="num">${d > 0 ? `<span class="chip warn">+${d}</span>` : d < 0 ? `<span class="muted">${signed(d)} frei</span>` : `<span class="chip ok">passt</span>`}</td></tr>`; }).join("")}
        <tr class="sum"><td>Gesamt</td><td class="num">${sum(D.products, (x) => pp(sid, x.id).pre ?? pp(sid, x.id).def)}</td><td class="num">${noT ? sum(D.products, (x) => amtOf(sid, x.id)) : p}</td><td></td></tr></tbody></table>`)}<p class="small muted">Budget ist der vorgeplante Betrag. Abweichungen warnen, sperren aber nichts.</p></div>`;
      const projTbl = `<div class="card"><h2>Projekt gegen Kontingent <span class="chip small">Schätzung</span></h2>${hints.length ? tw(`<table class="t"><thead><tr><th>Projekt</th><th class="num">Punkte</th><th class="num">PT</th><th class="num">Rest</th><th></th></tr></thead><tbody>
        ${hints.map((h) => `<tr><td>${FS.projectChip(h.pr.id)}</td><td class="num">${fmt(h.p)}</td><td class="num">≈ ${fmt(h.need, 1)}</td><td class="num">${fmt(h.rest, 1)}</td><td>${FS.lightChip(h.light, h.rest < 0 ? "über Kontingent" : h.light === "warn" ? "knapp" : "im Plan")}${calcBtn("pd", h.pr.id)}</td></tr>`).join("")}</tbody></table>`) : `<p class="muted">Keine Projekttickets im Sprint.</p>`}
        <p class="small muted">Tagesgeschäft ohne Projekt: ${fmt(pts(l.filter((t) => !t.project)))} Punkte. Umrechnung mit Rate ${fmt(D.rate, 2)} Punkte je PT.</p></div>`;
      const noTrackerCard = `<div class="card" style="margin-bottom:16px"><div class="banner info">${ic("info")}<div class="grow">Ohne Tracker gibt es keine Tickets im Planning. Das Team einigt sich auf einen Betrag je Produkt und eine Zusage (Commitment) als eigene Zahl. Mit Tracker ergibt sich die Zusage aus den gewählten Tickets.</div></div>
        ${tw(`<table class="t"><thead><tr><th>Produkt</th><th class="num">Vorgeplant</th><th class="num">Betrag geplant</th></tr></thead><tbody>${D.products.map((pr) => `<tr><td>${FS.productChip(pr.id)}</td><td class="num">${n(pp(sid, pr.id).pre)}</td><td class="num edit"><input data-amt="${pr.id}" inputmode="numeric" aria-label="Betrag ${esc(pr.name)}" value="${amtOf(sid, pr.id)}" ${fz ? "disabled" : ""}></td></tr>`).join("")}
        <tr class="sum"><td>Summe</td><td class="num">${preSum(sid)}</td><td class="num">${sum(D.products, (x) => amtOf(sid, x.id))}</td></tr></tbody></table>`)}
        <div class="row" style="margin-top:12px"><div class="field"><label for="sp-commit">Zusage (Commitment) in Punkten</label><input class="input data" id="sp-commit" inputmode="numeric" value="${commitOf(sid)}" ${fz ? "disabled" : ""} style="width:120px"></div>
        <div style="flex:1;min-width:200px">${FS.capBar(commitOf(sid), c.fc, c.low, c.high)}<span class="small muted">Zusage gegen Forecast PLAN ${c.fc} (${c.low} bis ${c.high})</span></div></div></div>`;
      return `${header(sid, "plan", actions)}${summary(sid)}
      ${abs !== "confirmed" ? `<div class="banner warn sp-abs-banner">${ic("event_busy")}<div class="grow"><strong>Abwesenheiten sind für ${sid} noch nicht bestätigt.</strong> ${cells.length ? `Angekündigt: ${cells.map(([pid, a]) => `${esc(FS.person(pid).name)} (${a.d} T)`).join(", ")}.` : "Noch nichts erfasst."} Kapazität und Forecast PLAN können sich noch ändern. Das blockiert nichts.<div class="row" style="margin-top:8px">${cells.length ? `<button class="btn" type="button" data-confirm="${sid}">${ic("done_all")}Bestätigen</button>` : ""}<button class="btn" type="button" data-nobody="${sid}">${ic("person_off")}Niemand abwesend bestätigen</button><a class="btn ghost" href="#prepare">Im Raster ändern</a></div></div></div>` : ""}
      ${fz ? `<div class="banner info">${ic("lock")}<div class="grow">Eingefroren am <span class="data">${fz.at}</span>: ${fz.noT ? "Zusage" : `${fz.keys.length} Tickets, Zusage`} <span class="data">${fz.commit}</span> Punkte. Planungsprotokoll ist geschrieben.<div class="row" style="margin-top:8px"><button class="btn" type="button" id="sp-reopen">${ic("lock_open")}Plan wieder öffnen</button><a class="btn" href="#minutes">${ic("description")}Protokoll ansehen</a></div></div></div>` : ""}
      <div class="row" id="sp-mode" style="margin-bottom:12px"><button class="chip filter ${noT ? "" : "on"}" type="button" data-mode="trk">${ic("confirmation_number", "small")}Mit Tracker: Tickets</button><button class="chip filter ${noT ? "on" : ""}" type="button" data-mode="amt">${ic("pin", "small")}Ohne Tracker: Beträge und Zusage</button></div>
      ${noT ? noTrackerCard : laneTop}
      <div class="grid cols-2" id="sp-live" style="margin-bottom:16px">${prodTbl}${projTbl}</div>
      ${noT ? "" : jiraCard(sid, l, jira, fz)}
      <div class="card"><div class="row"><label class="row" style="gap:8px"><input type="checkbox" id="sp-label" ${S.label ? "checked" : ""}> Label <span class="data">planned_for_${sid.replace(".", "_")}</span> in ${D.team.tracker} setzen (optional)</label></div>
        <p class="small muted" style="margin:8px 0 0">Der Knopf oben rechts friert die Einigung ein, speichert die Ticketliste lokal und schreibt das Planungsprotokoll.</p></div>`;
    },
    wire(main) {
      wireCommon(main);
      const sid = FS.state.sprint, S = st();
      main.querySelectorAll("[data-confirm]").forEach((b) => (b.onclick = () => { confirmAbs(sid); rerender(); FS.toast("Abwesenheiten bestätigt. Kapazität und Forecast PLAN sind aktuell."); }));
      main.querySelectorAll("[data-nobody]").forEach((b) => (b.onclick = () => { nobody(sid); rerender(); FS.toast("Niemand abwesend, bestätigt."); }));
      main.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => { S.noTracker = b.dataset.mode === "amt"; rerender(); }));
      main.querySelectorAll("[data-amt]").forEach((i) => (i.onchange = () => { const v = parseInt(i.value, 10); (S.amt[sid] ??= {})[i.dataset.amt] = isNaN(v) ? 0 : v; delete S.commit[sid]; rerender(); }));
      const cm = main.querySelector("#sp-commit"); if (cm) cm.onchange = () => { const v = parseInt(cm.value, 10); S.commit[sid] = isNaN(v) ? 0 : v; rerender(); };
      const lb = main.querySelector("#sp-label"); if (lb) lb.onchange = () => (S.label = lb.checked);
      main.querySelectorAll("[data-back]").forEach((b) => (b.onclick = () => { FS.moveTicket(b.dataset.back, sid, null); rerender(); }));
      main.querySelectorAll("[data-jdone]").forEach((b) => (b.onclick = () => { FS.ticket(b.dataset.jdone).jiraDone = true; rerender(); FS.toast(`${b.dataset.jdone}: in ${D.team.tracker} angepasst, aus der Liste entfernt.`); }));
      main.querySelector("#sp-freeze").onclick = () => {
        freeze(sid); rerender();
        FS.toast(`Plan ${sid} eingefroren. Planungsprotokoll geschrieben${S.label ? `, Label planned_for_${sid.replace(".", "_")} wird gesetzt` : ", Label planned_for_" + sid.replace(".", "_") + " bleibt optional (nicht gesetzt)"}.`);
      };
      const jw = main.querySelector("#sp-jwrite"); if (jw) jw.onclick = () => jiraPreview(sid, rerender);
      const pr = main.querySelector("#sp-present"); if (pr) pr.onclick = () => { const q = (z) => [...main.querySelectorAll(`#sp-lanes [data-zone="${z}"] .ticket[data-key]`)].map((e) => e.dataset.key); const k = [...q(sid), ...q("backlog")]; const first = k.find((x) => D.details[x]) || k[0]; if (first) FS.presentTicket(first, k); };
      const ro = main.querySelector("#sp-reopen"); if (ro) ro.onclick = () => { delete S.frozen[sid]; rerender(); FS.toast("Plan wieder geöffnet. Beim nächsten Einfrieren wird das alte Protokoll als überholt markiert."); };
      const lanes = main.querySelector("#sp-lanes");
      if (lanes) FS.dnd(lanes, { onDrop(key, zone, before, kb) {
        const undo = FS.moveTicket(key, zone, before);
        rerender();
        if (kb) document.querySelector(`.ticket[data-key="${key}"]`)?.focus();
        FS.toast(`${key} ${zone === "backlog" ? "aus dem Sprint genommen" : "in den Sprint genommen"}.`, () => { undo(); rerender(); });
      } });
    },
  });

  // ---------- Review ----------
  function rvOf(sid) {
    const S = st(), s = FS.sprint(sid);
    if (S.rv[sid]) return S.rv[sid];
    const plan = s.plan ?? S.frozen[sid]?.commit ?? (preSum(sid) || 0), vel = s.velocity ?? (sid === "2026.21" ? 38 : plan);
    let r = { plan, notDone: Math.max(0, plan - vel), extra: Math.max(0, vel - plan), freeze: s.capacityPD, done: {}, tag: `sprint-${sid}` };
    if (sid === "2026.21") { r.notDone = 4; r.extra = 2; r.freeze = 47; r.done = { portal: { d: 13, prod: 3 }, billing: { d: 8, prod: 1 }, mobile: { d: 9, prod: 2 }, platform: { d: 8, prod: 1 } }; }
    else { let left = vel; D.products.forEach((p, i) => { const d = i === D.products.length - 1 ? left : Math.round(vel * p.share / 1); left -= d; r.done[p.id] = { d: sid >= "2026.22" ? 0 : Math.max(0, d), prod: 0 }; }); if (sid < "2026.21") { const t = sum(Object.values(r.done), (x) => x.d); r.done.portal.d += vel - t; } }
    return (S.rv[sid] = r);
  }
  const rvVel = (sid) => { const r = rvOf(sid); return r.plan - r.notDone + r.extra; };

  FS.view("review", {
    title: "Sprint abschließen",
    render() {
      const sid = FS.state.sprint, S = st(), stt = stateOf(sid), r = rvOf(sid), closed = stt === "past", vel = r.plan - r.notDone + r.extra;
      const doneSum = sum(D.products, (p) => r.done[p.id]?.d), prodSum = sum(D.products, (p) => r.done[p.id]?.prod);
      const ro = closed ? "disabled" : "";
      const rows = poRows(6, (p) => { const d = r.done[p.id] || { d: 0, prod: 0 }, pl = pp(sid, p.id).plan ?? pp(sid, p.id).pre ?? pp(sid, p.id).def; return `<td>${FS.productChip(p.id)}</td><td class="num">${fmt(pl)}</td><td class="num edit"><input data-done="${p.id}" inputmode="numeric" aria-label="Erledigt ${esc(p.name)}" value="${d.d}" ${ro}></td><td class="num edit"><input data-prod="${p.id}" inputmode="numeric" aria-label="davon Prod ${esc(p.name)}" value="${d.prod}" ${ro}></td><td class="num">${signed(d.d - pl)}</td>`; },
        (ps) => { const s = (f) => sum(ps, f), pl = s((p) => pp(sid, p.id).plan ?? pp(sid, p.id).pre ?? pp(sid, p.id).def), dn = s((p) => r.done[p.id]?.d); return `<td class="num">${fmt(pl)}</td><td class="num">${fmt(dn)}</td><td class="num">${fmt(s((p) => r.done[p.id]?.prod))}</td><td class="num">${signed(dn - pl)}</td>`; });
      return `${header(sid, "review", closed ? `<button class="btn" type="button" id="sp-reopen-rv" ${FS.sprint(sid).state === "past" ? "disabled" : ""}>${ic("lock_open")}Review wieder öffnen</button>` : `<button class="btn primary" type="button" id="sp-close">${ic("task_alt")}Sprint abschließen</button>`)}${summary(sid)}
      ${stt === "open" || stt === "planned" ? `<div class="banner warn">${ic("schedule")}<div class="grow">Der Sprint hat noch nicht begonnen. Die Zahlen unten sind Platzhalter. Das Review-Beispiel zeigt Sprint 2026.21. <a href="#review" data-sprint="2026.21">Zu 2026.21 wechseln</a></div></div>` : ""}
      <div class="grid cols-2" style="margin-bottom:16px">
        <div class="card" id="sp-velocity"><h2>Velocity</h2><div class="row"><span class="big data" style="font-size:28px;font-weight:600;color:var(--forecast)">${fmt(vel)}</span><span class="muted">Punkte erledigt</span>${calcBtn("vel")}</div>
          <p class="small muted">Zusage ${fmt(r.plan)} minus nicht erledigt plus zusätzlich erledigt. Die Velocity fließt in den Forecast der nächsten Sprints ein.</p></div>
        <div class="card" id="sp-scope"><h2>Scope-Änderung</h2><div class="row"><div class="field"><label for="rv-nd">Nicht erledigt (Punkte)</label><input class="input data" id="rv-nd" data-rv="notDone" inputmode="numeric" value="${r.notDone}" ${ro} style="width:110px"></div><div class="field"><label for="rv-ex">Zusätzlich erledigt (Punkte)</label><input class="input data" id="rv-ex" data-rv="extra" inputmode="numeric" value="${r.extra}" ${ro} style="width:110px"></div></div>
          <p class="small muted">Nicht erledigte Tickets wandern zurück ins Backlog, zusätzlich erledigte kamen während des Sprints dazu.</p></div></div>
      <div id="sp-done"><h2>Erledigt je Produkt</h2>${tw(`<table class="t"><thead><tr><th>Produkt</th><th class="num">Geplant</th><th class="num">Erledigt</th><th class="num">davon Prod</th><th class="num">Differenz</th></tr></thead><tbody>${rows}</tbody></table>`)}
      <p class="small" style="margin:8px 0 16px">${doneSum === vel ? FS.lightChip("ok", "Summe passt zur Velocity") : FS.lightChip("warn", `Summe ${doneSum} weicht um ${signed(doneSum - vel)} von der Velocity ab`)} <span class="muted">Der Prod-Anteil (${prodSum}) wird nur angezeigt, nicht erzwungen.</span></p></div>
      <div class="grid cols-2">
        <div class="card" id="sp-freezepd"><h2>Personentage einfrieren</h2><div class="row"><div class="field"><label for="rv-fz">Verfügbare Personentage im Sprint</label><input class="input data" id="rv-fz" data-rv="freeze" inputmode="numeric" value="${r.freeze}" ${ro} style="width:110px"></div>
          <div><div class="data" style="font-size:18px">${fmt(vel / r.freeze, 2)} Punkte je PT</div><span class="small muted">tatsächliche Rate (Schätzung)</span>${calcBtn("rate")}</div></div>
          <p class="small muted">Geplant waren ${fmt(calc(sid).cap)} PT. Die eingefrorenen Tage bleiben mit dem Sprint gespeichert, auch wenn sich Abwesenheiten später ändern.</p></div>
        <div class="card" id="sp-tag"><h2>Tag und teilen</h2><label class="row" style="gap:8px"><input type="checkbox" id="rv-tag" ${S.tagOn ? "checked" : ""} ${ro}> Sprint taggen und mit dem Team teilen</label>
          <div class="field" style="margin-top:8px"><label for="rv-tagname">Name</label><input class="input data" id="rv-tagname" value="${esc(r.tag)}" ${ro} style="max-width:260px"></div></div></div>`;
    },
    wire(main) {
      wireCommon(main);
      const sid = FS.state.sprint, S = st(), r = rvOf(sid);
      const num = (v) => Math.max(0, parseInt(v, 10) || 0);
      main.querySelectorAll("[data-rv]").forEach((i) => (i.onchange = () => { r[i.dataset.rv] = num(i.value) || (i.dataset.rv === "freeze" ? 1 : 0); rerender(); }));
      main.querySelectorAll("[data-done]").forEach((i) => (i.onchange = () => { (r.done[i.dataset.done] ??= { d: 0, prod: 0 }).d = num(i.value); rerender(); }));
      main.querySelectorAll("[data-prod]").forEach((i) => (i.onchange = () => { (r.done[i.dataset.prod] ??= { d: 0, prod: 0 }).prod = num(i.value); rerender(); }));
      const tg = main.querySelector("#rv-tag"); if (tg) tg.onchange = () => (S.tagOn = tg.checked);
      const tn = main.querySelector("#rv-tagname"); if (tn) tn.onchange = () => (r.tag = tn.value);
      const cl = main.querySelector("#sp-close");
      if (cl) cl.onclick = () => {
        S.closed[sid] = true;
        D.products.forEach((p) => { const x = pp(sid, p.id), d = r.done[p.id] || { d: 0, prod: 0 }; x.done = d.d; x.prodDone = d.prod; });
        const m = { sprint: sid, kind: "Review", at: nowStr(), by: "Kim Berger", file: `protokolle/${sid}-review-${D.today.replace(/-/g, "")}-140500.md` };
        D.minutes.unshift(m); m.md = minuteMd(m);
        rerender();
        const next = D.sprints[D.sprints.findIndex((s) => s.id === sid) + 1];
        FS.toast(`Sprint ${sid} abgeschlossen. Review-Protokoll geschrieben${S.tagOn ? `, Tag ${esc(r.tag)} gesetzt` : ""}.${next ? ` ${next.id} erscheint nun auf Heute.` : ""}`);
      };
      const rr = main.querySelector("#sp-reopen-rv"); if (rr) rr.onclick = () => { delete S.closed[sid]; rerender(); };
    },
  });

  // ---------- Minutes ----------
  function minuteMd(m) {
    const sid = m.sprint, S = st(), c = calc(sid), L = [];
    const tk = (t) => `- [${t.key}](${D.team.trackerUrl}${t.key}) ${t.title} (${t.est ?? "?"} Punkte, ${FS.product(t.product).name}${t.project ? ", " + FS.project(t.project).name : ""})`;
    L.push(`# ${m.kind} ${sid}`, "", `Geschrieben am ${m.at} von ${m.by}. Team ${D.team.name}.`, "");
    if (m.kind === "Review") {
      const r = rvOf(sid);
      L.push("## Ergebnis", "", `- Zusage: **${r.plan}** Punkte`, `- Nicht erledigt: ${r.notDone}, zusätzlich erledigt: ${r.extra}`, `- Velocity: **${r.plan - r.notDone + r.extra}** Punkte bei ${r.freeze} Personentagen`, "", "## Erledigt je Produkt", "", "| Produkt | Erledigt | davon Prod |", "| --- | --- | --- |", ...D.products.map((p) => `| ${p.name} | ${r.done[p.id]?.d ?? 0} | ${r.done[p.id]?.prod ?? 0} |`));
      return L.join("\n");
    }
    L.push("## Rahmen", "", `- Kapazität: **${c.cap} PT** (Abwesenheiten ${c.abs} PT)`, c.low != null ? `- Forecast PLAN: **${c.fc}** Punkte, Spanne ${c.low} bis ${c.high}` : `- Plan: ${c.fc} Punkte`, "", "## Beträge je Produkt", "", "| Produkt | Standard | Vorgeplant | Geplant |", "| --- | --- | --- | --- |", ...D.products.map((p) => { const x = pp(sid, p.id); return `| ${p.name} | ${x.def} | ${x.pre ?? "–"} | ${x.plan ?? "–"} |`; }));
    const l = m.kind === "Planning" ? (S.frozen[sid] ? S.frozen[sid].keys.map(FS.ticket) : tix(sid)) : tix(sid);
    if (!(m.kind === "Planning" && S.frozen[sid]?.noT)) L.push("", m.kind === "Planning" ? "## Vereinbarte Tickets" : "## Vorgemerkte Tickets", "", ...l.map(tk), "", `Summe: **${pts(l)}** Punkte`);
    if (m.kind === "Planning") { const j = D.tickets.filter((t) => t.inTrackerSprint === sid && t.sprint !== sid); L.push("", "## In Jira anpassen", "", ...(j.length ? j.map((t) => `- [${t.key}](${D.team.trackerUrl}${t.key}) steht in Jira noch im Sprint, wurde im Planning herausgenommen`) : ["- nichts"])); }
    return L.join("\n");
  }
  function md(src) {
    const inl = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>').replace(/`([^`]+)`/g, "<code>$1</code>");
    const lines = src.split("\n"), out = [];
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      if (/^# /.test(ln)) out.push(`<h1>${inl(ln.slice(2))}</h1>`);
      else if (/^## /.test(ln)) out.push(`<h2>${inl(ln.slice(3))}</h2>`);
      else if (/^- /.test(ln)) { const li = []; while (i < lines.length && /^- /.test(lines[i])) li.push(`<li>${inl(lines[i++].slice(2))}</li>`); i--; out.push(`<ul>${li.join("")}</ul>`); }
      else if (/^\|/.test(ln)) { const rows = []; while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]); i--; const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((x) => x.trim()); const [h, , ...b] = rows; out.push(`<div class="tw"><table class="t"><thead><tr>${cells(h).map((x) => `<th>${inl(x)}</th>`).join("")}</tr></thead><tbody>${b.map((r) => `<tr>${cells(r).map((x) => `<td>${inl(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`); }
      else if (ln.trim()) out.push(`<p>${inl(ln)}</p>`);
    }
    return `<div class="sp-md">${CSS}${out.join("")}</div>`;
  }
  FS.view("minutes", {
    title: "Sprint-Protokolle",
    render() {
      const sid = FS.state.sprint, S = st(), all = S.mdFilter === "all", list = D.minutes.filter((m) => all || m.sprint === sid);
      return `${header(sid, "minutes")}${summary(sid)}
      <div class="row" style="margin-bottom:12px"><button class="chip filter ${all ? "" : "on"}" type="button" data-mf="sprint">Nur Sprint ${sid}</button><button class="chip filter ${all ? "on" : ""}" type="button" data-mf="all">Alle Sprints</button>
        <span class="small muted" style="margin-left:auto">Dateien liegen im Ordner <span class="data">protokolle/</span> und gehen mit Speichern ans Team.</span></div>
      ${list.length ? tw(`<table class="t"><thead><tr><th>Sprint</th><th>Art</th><th>Zeitpunkt</th><th>Von</th><th>Datei</th><th>Stand</th><th></th></tr></thead><tbody>${list.map((m) => { const i = D.minutes.indexOf(m); return `<tr style="${m.obsolete ? "color:var(--text-muted)" : ""}"><td class="data">${m.sprint}</td><td>${m.kind}</td><td class="data">${m.at}</td><td>${esc(m.by)}</td><td class="data" style="${m.obsolete ? "text-decoration:line-through" : ""}">${esc(m.file)}</td>
        <td>${m.obsolete ? `<span class="chip warn">${ic("history", "small")}überholt</span>` : `<span class="chip ok">aktuell</span>`}</td><td><button class="btn" type="button" data-open="${i}">${ic("visibility")}Öffnen</button></td></tr>`; }).join("")}</tbody></table>`) : `<div class="banner">${ic("description")}<div class="grow">Für ${sid} gibt es noch kein Protokoll. Es entsteht beim Speichern der Vorplanung, der Planung oder des Reviews.</div></div>`}
      <p class="small muted" style="margin-top:12px">Überholte Fassungen bleiben erhalten und sind markiert, wenn eine neuere Fassung derselben Art existiert.</p>`;
    },
    wire(main) {
      wireCommon(main);
      main.querySelectorAll("[data-mf]").forEach((b) => (b.onclick = () => { st().mdFilter = b.dataset.mf; rerender(); }));
      main.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => {
        const m = D.minutes[+b.dataset.open];
        FS.openPanel(`${m.kind} ${m.sprint}`, `${m.obsolete ? `<div class="banner warn">${ic("history")}<div class="grow">Diese Fassung ist überholt. Eine neuere Fassung ersetzt sie.</div></div>` : ""}<div class="small muted data">${esc(m.file)}</div>${md(m.md || minuteMd(m))}<div class="row"><button class="btn" type="button" onclick="FS.toast('Datei im Datenordner geöffnet (im Mockup nicht ausgeführt).')">${ic("folder_open")}Als Datei öffnen</button></div>`);
      }));
    },
  });

  // ---------- Flows ----------
  FS.flow({ id: "F3", title: "Sprint vorbereiten und vorplanen", summary: "Abwesenheiten klären, Bereitschaft prüfen und den Betrag je Produkt aus den Vormerkungen festlegen.", steps: [
    { view: "prepare", before() { FS.state.sprint = "2026.22"; }, hl: ".stepper", text: "Heute zeigt: Sprint 2026.22 braucht Vorbereitung. Oben siehst du alle Stufen als Links. \"fehlt noch\" ist nur ein Hinweis, nichts ist gesperrt." },
    { view: "prepare", hl: "#sp-abs-grid", text: "Das Raster zeigt Abwesenheiten für diesen und die nächsten drei Sprints. Klick auf eine Zelle wechselt zwischen leer, angekündigt (Rahmen) und bestätigt (gefüllt). Kapazität und Forecast PLAN unten in der Tabelle ziehen sofort mit." },
    { view: "prepare", hl: "[data-nobody]", text: "Hat niemand frei, genügt \"Niemand abwesend bestätigen\" je Sprint. Mit \"Angekündigte bestätigen\" werden vorhandene Einträge fest." },
    { view: "prepare", hl: "#sp-ready", text: "Die Bereitschaft fasst zusammen: Abwesenheiten, Refinement und Vorplanung je Produkt. Offene Punkte warnen nur, du kannst jederzeit weiter." },
    { view: "preplan", hl: "#sp-earmarks", text: "Vorplanen geht jederzeit, auch für spätere Sprints. Die Vormerkungen aus dem Backlog stehen hier nach Projekt und Tagesgeschäft, mit Kontingenthinweis in PT (Schätzung)." },
    { view: "preplan", hl: "#sp-prod-table", text: "Eine Tabelle je Sprint: Vorgeplant trägst du hier ein, \"Vormerkungen übernehmen\" macht daraus einen Vorschlag. Geplant und Erledigt sind in dieser Stufe nur lesbar." },
    { view: "preplan", hl: "#sp-prod-table", text: "Probiere es aus: Trägst du bei Abrechnung 12 ein, liegt die Summe über dem Forecast PLAN und eine Warnung erscheint. Sie blockiert nicht. Passt alles, ist der Sprint bereit für die Planung." },
  ] });
  FS.flow({ id: "F4", title: "Sprint planen", summary: "Abwesenheiten bestätigen, Tickets live gegen Forecast, Produkte und Kontingente abwägen, Einigung einfrieren.", steps: [
    { view: "plan", before() { FS.state.sprint = "2026.22"; delete st().frozen["2026.22"]; st().noTracker = false; }, hl: ".sp-abs-banner", text: "Zuerst die Abwesenheiten: Sind sie nur angekündigt, bestätigst du sie direkt hier. Ohne Bestätigung kannst du trotzdem planen." },
    { view: "plan", hl: ".sp-sumbar", text: "Oben steht der Forecast PLAN mit Spanne. Der Knopf mit dem Taschenrechner zeigt den Rechenweg." },
    { view: "plan", hl: "#sp-lanes", text: "Links die Kandidaten, rechts der Sprint, vorbelegt aus den Vormerkungen. Ticket ziehen oder mit Alt+Pfeil links/rechts verschieben." },
    { view: "plan", hl: "#sp-live", text: "Live: Summe gegen die Spanne, Produkte gegen Budget, Projekte gegen Kontingent in PT (Schätzung). Login-Umstellung liegt über dem Kontingent. Das ist ein Hinweis für das Team, kein Stopp." },
    { view: "plan", hl: "#sp-lanes .ticket[data-key=ATL-421]", text: "Das Team will ATL-421 nicht im Sprint? Nimm es mit Alt+Pfeil links heraus. Es taucht in der Liste \"In Jira anpassen\" auf." },
    { view: "plan", hl: "#sp-mode", text: "Ohne Tracker sieht der Schritt anders aus: ein Betrag je Produkt und eine Zusage als eigene Zahl. Probiere den Schalter aus und wechsle zurück." },
    { view: "plan", hl: "#sp-freeze", text: "Sind sich alle einig, friert \"Einigung festhalten und einfrieren\" den Plan ein. Es entsteht ein Planungsprotokoll, optional kommt das Label planned_for_2026_22 ans Jira-Ticket." },
  ] });
  FS.flow({ id: "F5", title: "Sprint abschließen", summary: "Velocity, Scope-Änderung und Erledigtes je Produkt festhalten, Personentage einfrieren und taggen.", steps: [
    { view: "review", before() { FS.state.sprint = "2026.21"; delete st().closed["2026.21"]; }, hl: "#sp-velocity", text: "Review für Sprint 2026.21: Die Velocity ergibt sich aus Zusage, nicht erledigt und zusätzlich erledigt." },
    { view: "review", hl: "#sp-scope", text: "Trage die Scope-Änderung ein: nicht erledigte und zusätzlich erledigte Punkte. Die Velocity oben rechnet mit." },
    { view: "review", hl: "#sp-done", text: "Erledigt je Produkt, mit dem Anteil davon Prod. Die Summe sollte zur Velocity passen, sonst warnt ein Hinweis." },
    { view: "review", hl: "#sp-freezepd", text: "Die verfügbaren Personentage werden eingefroren. Daraus ergibt sich die tatsächliche Rate für Kontingente (Schätzung)." },
    { view: "review", hl: "#sp-tag", text: "Optional: Sprint taggen und mit dem Team teilen." },
    { view: "review", hl: "#sp-close", text: "\"Sprint abschließen\" schreibt das Review-Protokoll. Danach erscheint der nächste Sprint auf Heute." },
  ] });
  FS.flow({ id: "F10", title: "Tickets im Meeting zeigen", summary: "Ein Fenster teilen: Ticketdetails aus Jira groß zeigen, blättern und dabei planen.", steps: [
    { view: "plan", before() { FS.state.sprint = "2026.22"; }, hl: "#sp-present", text: "Im Planning teilst du nur Foresprint. \"Großansicht\" zeigt die Tickets aus Sprint und Kandidaten groß im Fenster." },
    { view: "plan", before() { setTimeout(() => FS.presentTicket("ATL-421"), 250); }, text: "Beschreibung, Akzeptanzkriterien, Unteraufgaben, Verknüpfungen, Kommentare und Anhänge kommen beim Abruf aus Jira mit. Pfeiltasten blättern, die Leertaste nimmt das Ticket in den Sprint oder heraus." },
    { view: "backlog", before() { FS.presentClose?.(); setTimeout(() => FS.ticketPanel("ATL-415"), 250); }, text: "Dieselben Details stehen überall im Ticket-Panel, zum Beispiel im Backlog. Von dort öffnet \"Großansicht\" die Präsentation." },
  ] });
  FS.flow({ id: "F11", title: "Geplanten Sprint nach Jira übernehmen", summary: "Optional: Sprintzuordnung aus der Planung nach Jira schreiben, mit Vorschau und Rückgängig.", steps: [
    { view: "jira", before() { FS.presentClose?.(); }, hl: "#j-write", text: "Standard ist nur lesen. Hier schaltet ihr das Rückschreiben für das Team ein und legt fest, wohin herausgenommene Tickets in Jira gehen." },
    { view: "plan", before() { FS.state.jira.write.sprint = true; }, hl: "#sp-jira", text: "In Planen zeigt \"Abgleich mit Jira\", welche Tickets in Jira in den Sprint kommen oder ihn verlassen." },
    { view: "plan", before() { setTimeout(() => document.querySelector("#sp-jwrite")?.click(), 250); }, text: "\"In Jira übernehmen\" öffnet die Vorschau. Abwählen, was bleiben soll, dann schreiben. Geschrieben wird nur das Sprintfeld; der Vorgang landet im Planungsprotokoll und lässt sich rückgängig machen." },
  ] });
})();
