// Team (people, products, calendar) and Einstellungen (settings, jira, personal).
(function () {
  const D = window.DEMO;
  const esc = FS.esc;
  const ic = FS.icon;
  const S = FS.state;
  const f1 = (n) => FS.fmt(n, 1);

  // ---------- shared mock state ----------
  S.teamApplied ??= { hist: 6, method: "median", band: "p20", horizon: 4, len: 10, prod: true, projects: true, minutes: true, label: true, absState: true, basis: "forecast" };
  S.teamDraft ??= { ...S.teamApplied };
  S.rules ??= {
    portal: { field: "Komponente", op: "enthält", value: "Portal" },
    billing: { field: "Komponente", op: "enthält", value: "Abrechnung" },
    mobile: { field: "Komponente", op: "enthält", value: "App" },
    platform: { field: "Komponente", op: "enthält", value: "Plattform" },
  };
  S.ruleDraft ??= { product: "portal", ...S.rules.portal };
  S.members ??= { p1: "Mitglied", p2: "Mitglied", p3: "Mitglied", p4: "Mitglied", p5: "Gast", p6: "Mitglied" };
  S.jira ??= { off: false, url: "https://jira.example.com", user: "svc-foresprint", tokenSet: true, jql: "project = ATL AND (sprint is EMPTY OR sprint in openSprints())", interval: "15", checked: null, csv: null,
    map: { est: "Story Points (customfield_10016)", product: "Komponente", project: "Epic Link", refined: "Label: refined", status: "Status" } };
  S.personal ??= { theme: "system", lang: "de", density: "normal" };
  const HOLIDAYS = { "2026-11-01": "Allerheiligen", "2026-12-24": "Heiligabend (Betriebsruhe)", "2026-12-25": "1. Weihnachtstag", "2026-12-26": "2. Weihnachtstag", "2027-01-01": "Neujahr" };
  S.cal ??= [...D.sprints.map((s) => ({ ...s, orig: s.id })), { id: "2026.26", start: "2026-12-23", end: "2027-01-05", days: 7, state: "open", orig: "2026.26" }];

  // ---------- helpers ----------
  const calc = (title, rows, note) => FS.openPanel(`Rechenweg: ${title}`, `<div class="tw"><table class="t"><tbody>${rows.map((r, i) => `<tr class="${i === rows.length - 1 ? "sum" : ""}"><td style="white-space:normal">${esc(r[0])}</td><td class="num">${esc(r[1])}</td></tr>`).join("")}</tbody></table></div>${note ? `<p class="small muted">${note}</p>` : ""}`);
  const nc = (txt, btn) => `<span style="display:inline-flex;align-items:center;gap:4px;justify-content:flex-end">${txt}${btn}</span>`;
  const calcBtn = (id, label = "Rechenweg") => `<button class="btn icon ghost" type="button" data-calc="${id}" aria-label="${label}" title="${label}">${ic("calculate")}</button>`;
  const track = (what, before, after, file) => {
    const u = S.unsaved.find((x) => x.what === what);
    if (u) { if (String(u.before) === String(after)) S.unsaved.splice(S.unsaved.indexOf(u), 1); else u.after = after; } else FS.addUnsaved(what, before, after, file);
  };
  const acts = (main, h) => main.querySelectorAll("[data-act]").forEach((b) => (b.onclick = (e) => h[b.dataset.act]?.(b, e)));
  const calcs = (main, h) => main.querySelectorAll("[data-calc]").forEach((b) => (b.onclick = () => h[b.dataset.calc]?.(b)));
  const head = (t, lead, actions = "") => `<div class="page-head"><div><h1>${t}</h1><p class="lead">${lead}</p></div>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
  const unsavedHint = () => S.unsaved.length ? `<p class="small muted" style="margin:8px 0 0">${ic("edit_note", "small")} <span class="data">${S.unsaved.length}</span> ungespeicherte Änderungen. Mit Speichern oben für das Team sichtbar machen, Details unter <a href="#data">Daten</a>.</p>` : "";
  const parseD = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const isoD = (d) => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = parseD(iso); d.setUTCDate(d.getUTCDate() + n); return isoD(d); };
  const diffDays = (a, b) => Math.round((parseD(b) - parseD(a)) / 864e5);
  const workdays = (a, b) => { let n = 0; for (let d = a; d <= b; d = addDays(d, 1)) { const wd = parseD(d).getUTCDay(); if (wd && wd < 6 && !HOLIDAYS[d]) n++; } return n; };
  const holidaysIn = (a, b) => Object.keys(HOLIDAYS).filter((h) => h >= a && h <= b && ![0, 6].includes(parseD(h).getUTCDay()));
  const fcOf = (id) => FS.sprint(id)?.forecast;
  const FUT = ["2026.22", "2026.23", "2026.24", "2026.25"];

  // ================= people =================
  FS.view("people", {
    title: "Personen und Abwesenheiten",
    render() {
      const prod = S.teamApplied.prod;
      const tot = FS.sum(D.people, (p) => p.fte);
      return `${head("Personen und Abwesenheiten", "Wer im Team ist, mit welchem Anteil, und wann jemand fehlt. Kapazität und Forecast lesen von hier.", `<button class="btn" type="button" data-act="add">${ic("person_add")}Person hinzufügen</button><a class="btn" href="#prepare">${ic("event_available")}Abwesenheiten im Sprint vorbereiten</a>`)}
        <div class="tw" id="ppl"><table class="t"><thead><tr><th>Name</th><th class="num">FTE</th>${prod ? `<th title="Hat Zugang zur Produktion">Produktionszugang</th>` : ""}<th>Zugehörigkeit</th><th class="num">PT je Sprint</th><th></th></tr></thead><tbody>
          ${D.people.map((p) => `<tr data-id="${p.id}"><td>${esc(p.name)}</td><td class="num"><input class="input data" style="width:64px;text-align:right" data-fte="${p.id}" value="${FS.fmt(p.fte, 1)}" inputmode="decimal" aria-label="FTE ${esc(p.name)}"></td>
            ${prod ? `<td><input type="checkbox" data-prod="${p.id}" ${p.prod ? "checked" : ""} aria-label="Produktionszugang ${esc(p.name)}"></td>` : ""}
            <td><select class="input" data-mem="${p.id}" aria-label="Zugehörigkeit ${esc(p.name)}">${["Mitglied", "Gast", "Ausgeschieden zum Sprintende"].map((m) => `<option ${S.members[p.id] === m ? "selected" : ""}>${m}</option>`).join("")}</select></td>
            <td class="num">${f1(p.fte * 10)}</td><td>${calcBtn("pt:" + p.id)}</td></tr>`).join("")}
          <tr class="sum"><td>Team</td><td class="num">${FS.fmt(tot, 1)}</td>${prod ? `<td class="data">${D.people.filter((p) => p.prod).length} von ${D.people.length}</td>` : ""}<td></td><td class="num">${f1(tot * 10)}</td><td></td></tr></tbody></table></div>
        ${prod ? "" : `<p class="small muted">Die Spalte Produktionszugang erscheint, wenn die Funktion unter <a href="#settings">Einstellungen, Team</a> aktiv ist.</p>`}
        <div class="row" style="margin:24px 0 8px"><h2 style="flex:1;margin:0">Abwesenheiten über mehrere Sprints</h2>
          <span class="chip warn" title="angekündigt">${ic("schedule")}angekündigt</span><span class="chip ok">${ic("check")}bestätigt</span></div>
        <p class="small muted" style="margin:0 0 8px">Zahl = Personentage. Eintragen genügt, bestätigt wird im Sprint-Planning. Zellen mit Eintrag sind blau hinterlegt.</p>
        <div class="tw" id="abs"><table class="t"><thead><tr><th>Person</th>${FUT.map((s) => `<th class="num">${s}</th>`).join("")}</tr></thead><tbody>
          ${D.people.map((p) => `<tr><td>${esc(p.name)}</td>${FUT.map((s) => { const a = D.absences[s]?.[p.id]; return `<td class="num ${a ? "edit" : ""}"><input class="input data" style="width:64px;text-align:right" data-abs="${s}|${p.id}" value="${a ? a.d : ""}" placeholder="0" inputmode="numeric" aria-label="Abwesenheit ${esc(p.name)} ${s}"></td>`; }).join("")}</tr>`).join("")}
          <tr class="sum"><td>Verfügbar (PT)</td>${FUT.map((s) => `<td class="num">${nc(FS.fmt(FS.sprint(s).capacityPD), calcBtn("cap:" + s, "Rechenweg " + s))}</td>`).join("")}</tr></tbody></table></div>${unsavedHint()}`;
    },
    wire(main) {
      main.querySelectorAll("[data-fte]").forEach((i) => (i.onchange = () => {
        const p = FS.person(i.dataset.fte); const v = parseFloat(i.value.replace(",", "."));
        if (!(v > 0 && v <= 1)) { FS.toast("FTE zwischen 0,1 und 1,0 eingeben."); return FS.render(); }
        track(`FTE ${p.name}`, FS.fmt(p.fte, 1), FS.fmt(v, 1), "personen.yaml"); p.fte = v; FS.render();
      }));
      main.querySelectorAll("[data-prod]").forEach((i) => (i.onchange = () => { const p = FS.person(i.dataset.prod); track(`Produktionszugang ${p.name}`, p.prod ? "ja" : "nein", i.checked ? "ja" : "nein", "personen.yaml"); p.prod = i.checked; FS.render(); }));
      main.querySelectorAll("[data-mem]").forEach((i) => (i.onchange = () => { const p = FS.person(i.dataset.mem); track(`Zugehörigkeit ${p.name}`, S.members[p.id], i.value, "personen.yaml"); S.members[p.id] = i.value; FS.render(); }));
      main.querySelectorAll("[data-abs]").forEach((i) => (i.onchange = () => {
        const [s, id] = i.dataset.abs.split("|"); const v = parseInt(i.value, 10) || 0; const old = D.absences[s]?.[id]?.d || 0;
        D.absences[s] ??= {}; if (v) D.absences[s][id] = { d: v, s: "a" }; else delete D.absences[s][id];
        track(`Abwesenheit ${FS.person(id).name}, ${s}`, `${old} Tage`, `${v} Tage`, "abwesenheiten.yaml"); FS.render();
      }));
      acts(main, { add: () => { D.people.push({ id: "p" + (D.people.length + 1), name: "Neue Person", fte: 1.0, prod: false }); S.members["p" + D.people.length] = "Mitglied"; FS.addUnsaved("Person hinzugefügt: Neue Person", "–", "1,0 FTE", "personen.yaml"); FS.render(); FS.toast("Person hinzugefügt. Name bitte im nächsten Schritt ergänzen (Mockup: fester Name)."); } });
      main.querySelectorAll("[data-calc]").forEach((b) => (b.onclick = () => {
        const [k, id] = b.dataset.calc.split(":");
        if (k === "pt") { const p = FS.person(id); calc(`${p.name}, PT je Sprint`, [["FTE", FS.fmt(p.fte, 1)], ["Arbeitstage je Sprint", "10"], ["FTE mal Arbeitstage", `${f1(p.fte * 10)} PT`]]); }
        else {
          const s = S.cal.find((x) => x.id === id); const tot = FS.sum(D.people, (p) => p.fte); const abs = FS.sum(D.people, (p) => D.absences[id]?.[p.id]?.d || 0); const cp = FS.sprint(id).capacityPD;
          const other = tot * s.days - abs - cp;
          calc(`Verfügbar ${id}`, [["Team-FTE mal Arbeitstage", `${FS.fmt(tot, 1)} x ${s.days} = ${f1(tot * s.days)} PT`], ["minus Abwesenheiten", `-${FS.fmt(abs)} PT`], ["minus Feiertage, Fortbildungen", `-${f1(other)} PT`], ["Verfügbar", `${FS.fmt(cp)} PT`]]);
        }
      }));
    },
  });

  // ================= products =================
  const comp = { portal: "Portal", billing: "Abrechnung", mobile: "Mobile App", platform: "Plattform" };
  const fieldVals = (t, field) => (field === "Komponente" ? [comp[t.product]] : field === "Label" ? ["team-" + t.product, t.refined ? "refined" : ""] : [t.project ? FS.project(t.project).name : ""]);
  const matches = (rule) => D.tickets.filter((t) => rule.value && fieldVals(t, rule.field).some((v) => v && (rule.op === "ist" ? v.toLowerCase() === rule.value.toLowerCase() : v.toLowerCase().includes(rule.value.toLowerCase()))));
  FS.view("products", {
    title: "Produkte",
    render() {
      const sum = Math.round(FS.sum(D.products, (p) => p.share) * 100);
      const rd = S.ruleDraft, m = matches(rd), other = m.filter((t) => t.product !== rd.product);
      return `${head("Produkte", "Produkte mit Product Owner, Anteil am Sprint und Regel, die Tickets zuordnet.", `<button class="btn" type="button" data-act="add">${ic("add")}Produkt hinzufügen</button>`)}
        ${sum !== 100 ? `<div class="banner warn">${ic("error")}<div class="grow">Die Anteile ergeben <strong class="data">${sum} %</strong>, nicht 100 %. Der Rest wird im Standardanteil nicht verteilt.</div></div>` : ""}
        <div class="tw"><table class="t"><thead><tr><th>Produkt</th><th>Product Owner</th><th class="num">Anteil</th><th>Zuordnungsregel</th><th class="num">Tickets</th><th class="num" title="Forecast 2026.22 mal Anteil">Standard 2026.22</th><th></th></tr></thead><tbody>
          ${D.products.map((p) => { const r = S.rules[p.id]; return `<tr><td>${FS.productChip(p.id)}</td><td><select class="input" data-po="${p.id}" aria-label="PO ${esc(p.name)}">${D.pos.map((o) => `<option value="${o.id}" ${o.id === p.po ? "selected" : ""}>${esc(o.name)}</option>`).join("")}</select></td>
            <td class="num"><input class="input data" style="width:64px;text-align:right" data-share="${p.id}" value="${Math.round(p.share * 100)}" inputmode="numeric" aria-label="Anteil ${esc(p.name)}"> %</td>
            <td><span class="row" style="flex-wrap:nowrap"><span class="data small">${r.field} ${r.op} "${esc(r.value)}"</span> <button class="btn ghost icon" type="button" data-edit="${p.id}" aria-label="Regel bearbeiten" title="Regel bearbeiten">${ic("edit")}</button></span></td>
            <td class="num">${matches(r).length}</td><td class="num">${FS.fmt(Math.round(p.share * fcOf("2026.22")))} Punkte</td><td>${calcBtn("def:" + p.id)}</td></tr>`; }).join("")}
          <tr class="sum"><td>Summe</td><td></td><td class="num">${sum} %</td><td></td><td class="num">${FS.sum(D.products, (p) => matches(S.rules[p.id]).length)}</td><td class="num">${FS.fmt(FS.sum(D.products, (p) => Math.round(p.share * fcOf("2026.22"))))} Punkte</td><td></td></tr></tbody></table></div>
        <p class="small muted">Je PO: ${D.pos.map((o) => `${esc(o.name)} <span class="data">${Math.round(FS.sum(D.products.filter((p) => p.po === o.id), (p) => p.share) * 100)} %</span>`).join(", ")}. Der Anteil ist die Vorgabe, was im Sprint wirklich geplant und erledigt wird, steht in der Sprint-Tabelle.</p>
        <div class="grid cols-2" style="margin-top:16px">
          <div class="card" id="rule-ed"><h2>Zuordnungsregel bearbeiten</h2>
            <div class="grid" style="gap:8px;grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">
              <div class="field"><label for="r-p">Produkt</label><select class="input" id="r-p">${D.products.map((p) => `<option value="${p.id}" ${p.id === rd.product ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div>
              <div class="field"><label for="r-f">Feld im Tracker</label><select class="input" id="r-f">${["Komponente", "Label", "Epic"].map((x) => `<option ${x === rd.field ? "selected" : ""}>${x}</option>`).join("")}</select></div>
              <div class="field"><label for="r-o">Bedingung</label><select class="input" id="r-o">${["enthält", "ist"].map((x) => `<option ${x === rd.op ? "selected" : ""}>${x}</option>`).join("")}</select></div>
              <div class="field"><label for="r-v">Wert</label><input class="input" id="r-v" value="${esc(rd.value)}"></div></div>
            <div class="banner info" style="margin:12px 0 0" id="r-prev">${ic("preview")}<div class="grow"><strong class="data">${m.length}</strong> Tickets passen (<span class="data">${FS.sum(m, (t) => t.est || 0)}</span> Punkte)${other.length ? `, davon <span class="data">${other.length}</span> heute einem anderen Produkt zugeordnet` : ""}.
              <div class="small" style="margin-top:4px">${m.slice(0, 4).map((t) => `${FS.keyLink(t)} `).join("")}${m.length > 4 ? `<span class="muted">und ${m.length - 4} weitere</span>` : ""}</div></div></div>
            <div class="row" style="margin-top:12px"><button class="btn primary" type="button" data-act="apply">Regel übernehmen</button><span class="small muted">Gilt ab dem nächsten Abruf. Ein Produkt per Hand am Ticket hat Vorrang.</span></div></div>
          <div class="card"><h2>Standardanteil je Sprint</h2><p class="small muted" style="margin:0 0 8px">Forecast PLAN mal Anteil, in Punkten.</p>
            <div class="tw"><table class="t"><thead><tr><th>Produkt</th>${FUT.map((s) => `<th class="num">${s}</th>`).join("")}</tr></thead><tbody>
              ${D.products.map((p) => `<tr><td>${FS.productChip(p.id)}</td>${FUT.map((s) => `<td class="num">${FS.fmt(Math.round(p.share * fcOf(s)))}</td>`).join("")}</tr>`).join("")}
              <tr class="sum"><td>Forecast</td>${FUT.map((s) => `<td class="num">${nc(fcOf(s), calcBtn("sp:" + s, "Rechenweg " + s))}</td>`).join("")}</tr></tbody></table></div></div>
        </div>${unsavedHint()}`;
    },
    wire(main) {
      main.querySelectorAll("[data-po]").forEach((i) => (i.onchange = () => { const p = FS.product(i.dataset.po); track(`PO ${p.name}`, FS.po(p.po).name, FS.po(i.value).name, "produkte.yaml"); p.po = i.value; FS.render(); }));
      main.querySelectorAll("[data-share]").forEach((i) => (i.onchange = () => { const p = FS.product(i.dataset.share); const v = Math.max(0, Math.min(100, parseInt(i.value, 10) || 0)); track(`Anteil ${p.name}`, `${Math.round(p.share * 100)} %`, `${v} %`, "produkte.yaml"); p.share = v / 100; FS.render(); }));
      main.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => { S.ruleDraft = { product: b.dataset.edit, ...S.rules[b.dataset.edit] }; FS.render(); main.querySelector("#rule-ed")?.scrollIntoView({ block: "nearest" }); }));
      // live preview without re-render so typing keeps focus
      const live = () => {
        const rd = S.ruleDraft; rd.product = main.querySelector("#r-p").value; rd.field = main.querySelector("#r-f").value; rd.op = main.querySelector("#r-o").value; rd.value = main.querySelector("#r-v").value;
        const m = matches(rd), other = m.filter((t) => t.product !== rd.product);
        main.querySelector("#r-prev .grow").innerHTML = `<strong class="data">${m.length}</strong> Tickets passen (<span class="data">${FS.sum(m, (t) => t.est || 0)}</span> Punkte)${other.length ? `, davon <span class="data">${other.length}</span> heute einem anderen Produkt zugeordnet` : ""}.<div class="small" style="margin-top:4px">${m.slice(0, 4).map((t) => FS.keyLink(t) + " ").join("")}${m.length > 4 ? `<span class="muted">und ${m.length - 4} weitere</span>` : ""}</div>`;
      };
      ["#r-p", "#r-f", "#r-o"].forEach((q) => main.querySelector(q).addEventListener("change", () => { live(); if (q === "#r-p") { Object.assign(S.ruleDraft, S.rules[S.ruleDraft.product]); FS.render(); } }));
      main.querySelector("#r-v").addEventListener("input", live);
      acts(main, {
        apply: () => { const rd = S.ruleDraft, o = S.rules[rd.product]; track(`Regel ${FS.product(rd.product).name}`, `${o.field} ${o.op} "${o.value}"`, `${rd.field} ${rd.op} "${rd.value}"`, "produkte.yaml"); S.rules[rd.product] = { field: rd.field, op: rd.op, value: rd.value }; FS.render(); FS.toast("Regel übernommen, noch nicht gespeichert."); },
        add: () => FS.toast("Produkt hinzufügen: Name, PO, Anteil und Regel (im Mockup nicht ausgeführt)."),
      });
      main.querySelectorAll("[data-calc]").forEach((b) => (b.onclick = () => {
        const [k, id] = b.dataset.calc.split(":");
        if (k === "def") { const p = FS.product(id), fc = fcOf("2026.22"); calc(`Standard ${p.name}, 2026.22`, [["Forecast PLAN 2026.22", `${fc} Punkte`], ["Anteil", `${Math.round(p.share * 100)} %`], ["Forecast mal Anteil", `${f1(fc * p.share)} Punkte`], ["gerundet", `${Math.round(fc * p.share)} Punkte`]]); }
        else { const s = FS.sprint(id); calc(`Forecast ${id}`, [["Kapazität", `${s.capacityPD} PT`], ["Rate (normalisierte Velocity)", `${FS.fmt(D.rate, 2)} Punkte je PT`], ["Kapazität mal Rate", `${f1(s.capacityPD * D.rate)} Punkte`], ["Forecast PLAN, gerundet", `${s.forecast} Punkte (Spanne ${s.low} bis ${s.high})`]]); }
      }));
    },
  });

  // ================= calendar =================
  function cascade(i) {
    const c = S.cal;
    for (let k = i + 1; k < c.length; k++) { const len = diffDays(c[k].start, c[k].end); c[k].start = addDays(c[k - 1].end, 1); c[k].end = addDays(c[k].start, len); c[k].days = workdays(c[k].start, c[k].end); }
  }
  FS.view("calendar", {
    title: "Sprint-Kalender",
    render() {
      return `${head("Sprint-Kalender", `Beginn, Ende und Arbeitstage jedes Sprints. Region <span class="data">${D.team.region}</span> bestimmt die Feiertage. Abgeschlossene Sprints sind gesperrt.`)}
        <div class="tw"><table class="t"><thead><tr><th>Sprint-ID</th><th>Beginn</th><th>Letzter Tag</th><th class="num">Arbeitstage</th><th>Freie Tage</th><th>Zustand</th></tr></thead><tbody>
          ${S.cal.map((s, i) => { const lock = s.state === "past", hol = holidaysIn(s.start, s.end); return `<tr>
            <td>${lock ? `<span class="data">${s.id}</span>` : `<input class="input data" style="width:90px" data-id="${i}" value="${esc(s.id)}" aria-label="Sprint-ID" pattern="\\d{4}\\.\\d{2}">`}</td>
            <td class="data">${FS.fmtDate(s.start)}</td>
            <td>${lock ? `<span class="data">${FS.fmtDate(s.end)}</span> ${ic("lock", "small")}` : `<input class="input data" type="date" data-end="${i}" value="${s.end}" min="${s.start}" aria-label="Letzter Tag ${s.id}">`}</td>
            <td class="num">${nc(s.days, calcBtn("wd:" + i, "Rechenweg Arbeitstage " + s.id))}</td>
            <td class="small">${hol.length ? hol.map((h) => `${FS.fmtDate(h)} ${HOLIDAYS[h]}`).join(", ") : '<span class="muted">keine</span>'}</td>
            <td>${{ past: '<span class="chip">abgeschlossen</span>', current: '<span class="chip ok">läuft</span>', open: '<span class="chip">offen</span>', planned: '<span class="chip fc">geplant</span>' }[s.state]}</td></tr>`; }).join("")}</tbody></table></div>
        <div class="grid cols-2" style="margin-top:16px"><div class="card"><h2>Letzten Tag ändern</h2><p class="small muted" style="margin:0">Ein neuer letzter Tag verschiebt Beginn und Ende aller folgenden Sprints, ihre Länge bleibt. Arbeitstage werden aus Wochenenden und Feiertagen neu berechnet.</p></div>
          <div class="card"><h2>Sprint-ID umbenennen</h2><p class="small muted" style="margin:0">Die ID erscheint in Tickets, Protokollen und im Verlauf. Beim Umbenennen werden alle Verweise mit geändert. Format <span class="data">JJJJ.NN</span>, eindeutig.</p></div></div>${unsavedHint()}`;
    },
    wire(main) {
      main.querySelectorAll("[data-end]").forEach((i) => (i.onchange = () => {
        const k = +i.dataset.end, s = S.cal[k], old = s.end; if (!i.value || i.value < s.start) return FS.render();
        const startsBefore = S.cal.slice(k + 1).map((x) => x.start);
        s.end = i.value; s.days = workdays(s.start, s.end); cascade(k);
        const moved = S.cal.slice(k + 1).filter((x, j) => x.start !== startsBefore[j]).length;
        track(`Letzter Tag Sprint ${s.id}`, FS.fmtDate(old), FS.fmtDate(s.end), "sprints.yaml"); FS.render();
        FS.toast(`Letzter Tag ${FS.fmtDate(s.end)}, ${s.days} Arbeitstage. ${moved} Folgesprints verschoben.`, () => { s.end = old; s.days = workdays(s.start, s.end); cascade(k); FS.render(); });
      }));
      main.querySelectorAll("[data-id]").forEach((i) => (i.onchange = () => {
        const s = S.cal[+i.dataset.id], v = i.value.trim();
        if (!/^\d{4}\.\d{2}$/.test(v)) { FS.toast("Format JJJJ.NN, zum Beispiel 2026.23."); return FS.render(); }
        if (S.cal.some((x) => x !== s && x.id === v)) { FS.toast(`Die ID ${v} gibt es schon.`); return FS.render(); }
        const old = s.id; track(`Sprint-ID ${s.orig}`, s.orig, v, "sprints.yaml"); s.id = v; FS.render(); FS.toast(`Sprint ${old} heißt jetzt ${v}. Verweise in Tickets und Protokollen werden mit umbenannt.`, () => { s.id = old; FS.render(); });
      }));
      main.querySelectorAll("[data-calc]").forEach((b) => (b.onclick = () => {
        const s = S.cal[+b.dataset.calc.split(":")[1]], total = diffDays(s.start, s.end) + 1; let we = 0; for (let d = s.start; d <= s.end; d = addDays(d, 1)) { const wd = parseD(d).getUTCDay(); if (!wd || wd === 6) we++; }
        const hol = holidaysIn(s.start, s.end).length;
        calc(`Arbeitstage ${s.id}`, [["Kalendertage", `${total}`], ["minus Wochenenden", `-${we}`], ["minus Feiertage", `-${hol}`], ["Arbeitstage", `${total - we - hol}`]], s.state === "past" ? "Stand beim Abschluss des Sprints, zusätzlich freie Tage laut Kalender sind eingerechnet." : "");
      }));
    },
  });

  // ================= settings (team) =================
  const SET_LABEL = { hist: "Sprints für die Velocity", method: "Mittelwert-Art", band: "Spanne", horizon: "Forecast-Horizont (Sprints)", len: "Standard-Sprintlänge (Arbeitstage)", prod: "Produktionszugang", projects: "Projekte und Kontingente", minutes: "Protokolle schreiben", label: "Label planned_for im Tracker", absState: "Abwesenheit: angekündigt und bestätigt", basis: "Budgetbasis" };
  const fmtV = (v) => (v === true ? "an" : v === false ? "aus" : { median: "Median", mean: "Mittelwert", p20: "mittlere 60 %", sd: "plus/minus Standardabweichung", forecast: "Forecast PLAN", capacity: "Kapazität mal Rate" }[v] || String(v));
  const settingsDiff = () => Object.keys(S.teamDraft).filter((k) => S.teamDraft[k] !== S.teamApplied[k]);
  FS.view("settings", {
    title: "Einstellungen, Team",
    render() {
      const d = S.teamDraft;
      const sw = (k, t, sub) => `<label class="row" style="align-items:flex-start;flex-wrap:nowrap"><input type="checkbox" data-t="${k}" ${d[k] ? "checked" : ""} style="margin-top:3px"><span><strong>${t}</strong><br><span class="small muted">${sub}</span></span></label>`;
      const sel = (k, label, opts) => `<div class="field"><label for="t-${k}">${label}</label><select class="input" id="t-${k}" data-t="${k}">${opts.map(([v, l]) => `<option value="${v}" ${String(d[k]) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select></div>`;
      return `${head("Einstellungen, Team", "Forecast, Funktionen und Budgetbasis des Teams.")}
        <div class="field" style="max-width:360px;margin-bottom:12px"><label for="s-q">Einstellung suchen</label><input class="input" id="s-q" type="search" placeholder="z. B. Produktion, Spanne"></div>
        <div class="grid cols-2" id="s-cards">
          <div class="card" data-s="forecast velocity spanne horizont sprintlänge mittelwert"><h2>Forecast</h2><div class="grid" style="gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
            ${sel("hist", "Sprints für die Velocity", [[4, "4"], [6, "6"], [8, "8"]])}${sel("method", "Mittelwert-Art", [["median", "Median"], ["mean", "Mittelwert"]])}${sel("band", "Spanne", [["p20", "mittlere 60 %"], ["sd", "plus/minus Standardabweichung"]])}${sel("horizon", "Horizont", [[3, "3 Sprints"], [4, "4 Sprints"], [6, "6 Sprints"]])}${sel("len", "Standard-Sprintlänge", [[9, "9 Arbeitstage"], [10, "10 Arbeitstage"], [15, "15 Arbeitstage"]])}</div>
            <div class="row small" style="margin:12px 0 0"><span>Rate aus dem Verlauf: <strong class="data">${FS.fmt(D.rate, 2)}</strong> Punkte je Personentag</span>${calcBtn("rate")}</div></div>
          <div class="card" data-s="funktionen features produktionszugang projekte protokolle label abwesenheit"><h2>Funktionen</h2><div class="stack" style="gap:12px">
            ${sw("prod", "Produktionszugang", "Zeigt je Person ein Merkmal und die Spalte davon Prod in der Sprint-Tabelle. Wird angezeigt, nicht erzwungen.")}
            ${sw("projects", "Projekte und Kontingente", "Projekte mit Meilensteinen und Kontingent in Personentagen.")}
            ${sw("minutes", "Protokolle schreiben", "Jedes Speichern von Vorplanung, Planung und Review schreibt eine Markdown-Datei.")}
            ${sw("label", "Label planned_for im Tracker setzen", `Einzige Schreibaktion in ${D.team.tracker}, nach dem Einfrieren des Plans.`)}
            ${sw("absState", "Abwesenheiten angekündigt und bestätigt trennen", "Jede Zelle zeigt ihren Zustand.")}</div></div>
          <div class="card" data-s="budget basis anteil"><h2>Budgetbasis</h2><div class="stack">
            <label class="row" style="flex-wrap:nowrap"><input type="radio" name="basis" data-t="basis" value="forecast" ${d.basis === "forecast" ? "checked" : ""}><span><strong>Forecast PLAN</strong> <span class="small muted">(Standard)</span></span></label>
            <label class="row" style="flex-wrap:nowrap"><input type="radio" name="basis" data-t="basis" value="capacity" ${d.basis === "capacity" ? "checked" : ""}><span><strong>Kapazität mal Rate</strong></span></label>
            <div class="row small muted"><span>Beispiel Kundenportal 2026.22: <span class="data">${FS.fmt(Math.round(0.35 * fcOf("2026.22")))}</span> Punkte nach Forecast, <span class="data">${FS.fmt(Math.round(0.35 * FS.sprint("2026.22").capacityPD * D.rate))}</span> nach Kapazität</span>${calcBtn("basis")}</div></div></div>
          <div class="card" id="s-diff" data-keep="1"></div></div><p id="s-none" class="muted" hidden>Keine Einstellung gefunden.</p>`;
    },
    wire(main) {
      const draw = () => {
        const ks = settingsDiff(), box = main.querySelector("#s-diff");
        box.innerHTML = `<h2>Änderungen vor dem Speichern</h2>${ks.length ? `<div class="tw"><table class="t"><thead><tr><th>Einstellung</th><th>Vorher</th><th>Nachher</th></tr></thead><tbody>${ks.map((k) => `<tr><td style="white-space:normal">${SET_LABEL[k]}</td><td class="muted">${fmtV(S.teamApplied[k])}</td><td><strong>${fmtV(S.teamDraft[k])}</strong></td></tr>`).join("")}</tbody></table></div>
          <div class="row" style="margin-top:12px"><button class="btn primary" type="button" data-act="apply">Änderungen übernehmen</button><button class="btn" type="button" data-act="reset">Verwerfen</button></div><p class="small muted" style="margin:8px 0 0">Übernommene Änderungen liegen danach bei den ungespeicherten, Speichern oben gibt sie ans Team.</p>` : `<p class="muted" style="margin:0">Keine Änderungen. Was du hier umstellst, erscheint zuerst in dieser Liste.</p>`}`;
        acts(box, {
          apply: () => { ks.forEach((k) => track(`Einstellung ${SET_LABEL[k]}`, fmtV(S.teamApplied[k]), fmtV(S.teamDraft[k]), "team.yaml")); S.teamApplied = { ...S.teamDraft }; FS.render(); FS.toast("Übernommen, noch nicht gespeichert."); },
          reset: () => { S.teamDraft = { ...S.teamApplied }; FS.render(); },
        });
      };
      main.querySelectorAll("[data-t]").forEach((i) => (i.onchange = () => { const k = i.dataset.t; S.teamDraft[k] = i.type === "checkbox" ? i.checked : i.type === "radio" ? i.value : (isNaN(+i.value) ? i.value : +i.value); draw(); }));
      draw();
      main.querySelector("#s-q").addEventListener("input", (e) => {
        const q = e.target.value.trim().toLowerCase(); let n = 0;
        main.querySelectorAll("#s-cards .card").forEach((c) => { const hit = !q || c.dataset.keep || (c.dataset.s + " " + c.textContent).toLowerCase().includes(q); c.hidden = !hit; if (hit && !c.dataset.keep) n++; });
        main.querySelector("#s-none").hidden = !q || n > 0;
      });
      calcs(main, {
        rate: () => { const w = [1, 2, 3, 4]; const ps = D.sprints.filter((s) => s.state === "past"); calc("Rate aus dem Verlauf", [...ps.map((s, i) => [`${s.id}: ${s.velocity} Punkte / ${s.capacityPD} PT, Gewicht ${w[i]}`, FS.fmt(s.velocity / s.capacityPD, 2)]), ["gewichteter Mittelwert", FS.fmt(D.rate, 2)]], "Jüngere Sprints zählen stärker."); },
        basis: () => { const s = FS.sprint("2026.22"); calc("Budgetbasis Kundenportal", [["Anteil", "35 %"], ["Forecast PLAN mal Anteil", `${f1(0.35 * s.forecast)} Punkte`], [`Kapazität ${s.capacityPD} PT mal Rate ${FS.fmt(D.rate, 2)} mal Anteil`, `${f1(0.35 * s.capacityPD * D.rate)} Punkte`]]); },
      });
    },
  });

  // ================= jira =================
  FS.view("jira", {
    title: "Einstellungen, Jira und Tickets",
    render() {
      const j = S.jira, off = j.off;
      const mapRows = [["Schätzung", "est", ["Story Points (customfield_10016)", "Original Estimate"]], ["Produkt", "product", ["Komponente", "Label", "Eigenes Feld"]], ["Projekt", "project", ["Epic Link", "Label", "Parent"]], ["Refined", "refined", ["Label: refined", "Status: Bereit"]], ["Status", "status", ["Status"]]];
      return `${head("Jira und Tickets", `Verbindung zu ${D.team.tracker}, Abfrage, Feldzuordnung und Import. ${D.team.tracker} wird nur gelesen.`)}
        <div class="card" style="margin-bottom:16px"><label class="row" style="flex-wrap:nowrap;align-items:flex-start"><input type="checkbox" id="j-off" ${off ? "checked" : ""} style="margin-top:3px"><span><strong>Ohne Tracker arbeiten</strong><br><span class="small muted">Projekte, Produkte, Sprints und Planung laufen vollständig ohne Tracker.</span></span></label></div>
        ${off ? `<div class="banner info">${ic("info")}<div class="grow"><strong>So sieht Foresprint ohne Tracker aus:</strong> Das Backlog zeigt nur von Hand gepflegte Tickets, die Planung arbeitet mit Mengen je Produkt statt Tickets, Zuordnungsregeln ruhen, der Jira-Chip oben zeigt "nicht verbunden". Projekte, Meilensteine und Kontingente bleiben unverändert nutzbar.</div></div>` : ""}
        <div class="grid cols-2" style="${off ? "opacity:.45;pointer-events:none" : ""}" ${off ? 'aria-disabled="true" inert' : ""}>
          <div class="card"><h2>Verbindung</h2><div class="stack"><div class="field"><label for="j-url">Adresse</label><input class="input data" id="j-url" value="${esc(j.url)}"></div><div class="field"><label for="j-user">Benutzer</label><input class="input data" id="j-user" value="${esc(j.user)}"></div>
            <div class="field"><label for="j-tok">Token</label><input class="input data" id="j-tok" type="password" autocomplete="new-password" placeholder="${j.tokenSet ? "••••••••••••••••" : "Token einfügen"}"></div>
            <div class="row"><button class="btn" type="button" data-act="test">${ic("network_check")}Verbindung testen</button><button class="btn" type="button" data-act="setTok">Token ersetzen</button><button class="btn danger" type="button" data-act="rmTok" ${j.tokenSet ? "" : "disabled"}>${ic("delete")}Entfernen</button></div>
            <div class="small">${j.checked === "conn" ? FS.lightChip("ok", "verbunden, Benutzer svc-foresprint") : j.tokenSet ? '<span class="muted">Token im Schlüsselbund gespeichert.</span>' : '<span class="chip warn">kein Token</span>'}</div></div></div>
          <div class="card"><h2>Abruf</h2><dl class="kv"><dt>Letzter Abruf</dt><dd class="data" id="j-last">${D.trackerSync.last}</dd><dt>Tickets</dt><dd class="data">${D.trackerSync.tickets} (${D.trackerSync.changed} geändert)</dd><dt>Automatisch</dt><dd><select class="input" id="j-int" aria-label="Intervall">${[["0", "nur von Hand"], ["5", "alle 5 Minuten"], ["15", "alle 15 Minuten"], ["60", "stündlich"]].map(([v, l]) => `<option value="${v}" ${v === j.interval ? "selected" : ""}>${l}</option>`).join("")}</select></dd></dl>
            <div class="row" style="margin-top:12px"><button class="btn" type="button" data-act="sync">${ic("sync")}Jetzt abrufen</button></div></div>
          <div class="card" style="grid-column:1/-1"><h2>Sprints aus ${D.team.tracker}</h2><p class="small muted" style="margin:0 0 8px">Lege fest, welche Sprints nur Ablagen sind (pro forma, z. B. "Refinement"). Sie erscheinen unter dem Backlog und zählen nie für Kapazität oder Forecast. Keiner, einer oder mehrere sind möglich.</p>
            <div class="tw"><table class="t"><thead><tr><th>Sprint in ${D.team.tracker}</th><th>Pro forma</th><th>Entspricht Foresprint-Sprint</th></tr></thead><tbody>${D.trackerSprints.map((s, i) => `<tr><td class="data">${esc(s.name)}</td><td><input type="checkbox" data-pf-i="${i}" ${s.proforma ? "checked" : ""} aria-label="${esc(s.name)} ist pro forma"></td><td class="data">${s.proforma ? '<span class="muted">nein</span>' : esc(s.mapsTo || "automatisch per Name")}</td></tr>`).join("")}</tbody></table></div>
            <p class="small muted" style="margin:8px 0 0">Neue Sprints mit Namen wie "Refinement" oder ohne Start- und Enddatum schlägt Foresprint beim Abruf als pro forma vor.</p></div>
          <div class="card" style="grid-column:1/-1"><h2>Abfrage (JQL)</h2><div class="field"><label for="j-jql">Welche Tickets Foresprint liest</label><textarea class="input data" id="j-jql" rows="2">${esc(j.jql)}</textarea></div>
            <div class="row" style="margin-top:8px"><button class="btn" type="button" data-act="jql">${ic("play_arrow")}Abfrage testen</button><span id="j-jql-res" class="small">${j.checked === "jql" ? FS.lightChip("ok", "46 Tickets, 28 mit Schätzung, 6 ohne Produkt") : ""}</span></div></div>
          <div class="card" style="grid-column:1/-1"><h2>Feldzuordnung</h2><div class="tw"><table class="t"><thead><tr><th>Foresprint</th><th>Feld in ${D.team.tracker}</th></tr></thead><tbody>${mapRows.map(([l, k, o]) => `<tr><td>${l}</td><td><select class="input" data-map="${k}" aria-label="Feld für ${l}">${o.map((x) => `<option ${x === j.map[k] ? "selected" : ""}>${x}</option>`).join("")}</select></td></tr>`).join("")}</tbody></table></div></div>
          <div class="card" style="grid-column:1/-1"><h2>Import aus CSV oder Excel</h2><p class="small muted" style="margin:0 0 8px">Für Tickets aus anderen Quellen oder ohne Tracker. Spalten werden erkannt, du prüfst die Vorschau.</p>
            <div class="row"><label class="btn" for="j-file">${ic("upload_file")}Datei wählen</label><input type="file" id="j-file" accept=".csv,.xlsx" hidden><span class="small">${j.csv ? esc(j.csv) : '<span class="muted">noch keine Datei</span>'}</span></div>
            ${j.csv ? `<div class="tw" style="margin-top:8px"><table class="t"><thead><tr><th>Schlüssel</th><th>Titel</th><th>Produkt</th><th class="num">Punkte</th></tr></thead><tbody><tr><td class="data">ATL-501</td><td>Export als CSV</td><td>Kundenportal</td><td class="num">3</td></tr><tr><td class="data">ATL-502</td><td>Passwort-Regeln anzeigen</td><td>Plattform</td><td class="num">2</td></tr><tr><td class="data">ATL-503</td><td>Beleg-Upload</td><td>Abrechnung</td><td class="num">5</td></tr></tbody></table></div><div class="row" style="margin-top:8px"><button class="btn primary" type="button" data-act="imp">3 Tickets importieren</button><span class="small muted">Spalten erkannt: 4 von 4</span></div>` : ""}</div>
        </div>${unsavedHint()}`;
    },
    wire(main) {
      const j = S.jira;
      main.querySelectorAll("[data-pf-i]").forEach((c) => (c.onchange = () => { const s = D.trackerSprints[c.dataset.pfI]; s.proforma = c.checked; FS.toast(`${s.name} ist ${c.checked ? "jetzt pro forma und erscheint unter dem Backlog" : "kein Pro-forma-Sprint mehr"}.`); FS.render(); }));
      main.querySelector("#j-off").onchange = (e) => { track("Einstellung Ohne Tracker arbeiten", j.off ? "an" : "aus", e.target.checked ? "an" : "aus", "team.yaml"); j.off = e.target.checked; S.trackerOk = j.off ? false : true; FS.render(); };
      main.querySelector("#j-int").onchange = (e) => { track("Abrufintervall", j.interval + " min", e.target.value + " min", "team.yaml"); j.interval = e.target.value; };
      main.querySelector("#j-jql").onchange = (e) => { track("Abfrage (JQL)", "geändert", "geändert", "team.yaml"); j.jql = e.target.value; };
      main.querySelectorAll("[data-map]").forEach((s) => (s.onchange = () => { track(`Feldzuordnung ${s.dataset.map}`, j.map[s.dataset.map], s.value, "team.yaml"); j.map[s.dataset.map] = s.value; }));
      main.querySelector("#j-file").onchange = (e) => { j.csv = e.target.files[0]?.name || "tickets-export.csv"; FS.render(); };
      acts(main, {
        test: () => { j.checked = "conn"; FS.render(); }, jql: () => { j.checked = "jql"; FS.render(); },
        setTok: () => { if (!main.querySelector("#j-tok").value) return FS.toast("Bitte zuerst einen Token einfügen."); j.tokenSet = true; FS.render(); FS.toast("Token im Schlüsselbund ersetzt."); },
        rmTok: () => { j.tokenSet = false; S.trackerOk = false; FS.render(); FS.toast("Token entfernt. Abrufe pausieren.", () => { j.tokenSet = true; S.trackerOk = true; FS.render(); }); },
        sync: () => { D.trackerSync.last = "gerade eben"; main.querySelector("#j-last").textContent = "gerade eben"; FS.toast("46 Tickets abgerufen, 0 geändert."); },
        imp: () => { FS.addUnsaved("Import: 3 Tickets aus " + j.csv, "–", "3 Tickets", "tickets.yaml"); j.csv = null; FS.render(); FS.toast("3 Tickets importiert, noch nicht gespeichert."); },
      });
    },
  });

  // ================= personal =================
  let densityEl;
  const applyDensity = (d) => {
    densityEl ??= Object.assign(document.head.appendChild(document.createElement("style")), { id: "pe-density" });
    const h = { compact: 26, normal: 32, roomy: 40 }[d];
    densityEl.textContent = `table.t th, table.t td { height: ${h}px; } .ticket { min-height: ${h + 4}px; }`;
  };
  const applyTheme = (t) => { const r = document.documentElement; if (t === "system") delete r.dataset.theme; else r.dataset.theme = t; };
  FS.view("personal", {
    title: "Einstellungen, Persönlich",
    render() {
      const p = S.personal;
      const seg = (k, opts) => `<div class="row" role="group">${opts.map(([v, l, i]) => `<button type="button" class="chip filter ${p[k] === v ? "on" : ""}" data-p="${k}" data-v="${v}" aria-pressed="${p[k] === v}">${i ? ic(i, "small") : ""}${l}</button>`).join("")}</div>`;
      return `${head("Persönlich", "Gilt nur für dich auf diesem Rechner und wird nicht mit dem Team geteilt.")}
        <div class="grid cols-2"><div class="card"><h2>Darstellung</h2><div class="stack" style="gap:16px">
            <div><div class="small muted" style="margin-bottom:6px">Erscheinungsbild</div>${seg("theme", [["system", "System", "computer"], ["light", "Hell", "light_mode"], ["dark", "Dunkel", "dark_mode"]])}</div>
            <div><div class="small muted" style="margin-bottom:6px">Dichte der Tabellen</div>${seg("density", [["compact", "Kompakt"], ["normal", "Normal"], ["roomy", "Großzügig"]])}</div></div></div>
          <div class="card"><h2>Sprache</h2><div class="field"><label for="p-lang">Sprache der Oberfläche</label><select class="input" id="p-lang" style="max-width:220px"><option value="de" ${p.lang === "de" ? "selected" : ""}>Deutsch</option><option value="en" ${p.lang === "en" ? "selected" : ""}>English</option></select></div>
            <p class="small muted" style="margin:8px 0 0">Weitere Sprachen sind möglich: Eine Übersetzungsdatei genügt, die Oberfläche selbst bleibt gleich. ${p.lang === "en" ? `<br><span class="chip warn">Mockup bleibt deutsch</span>` : ""}</p></div></div>`;
    },
    wire(main) {
      main.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => { const k = b.dataset.p; S.personal[k] = b.dataset.v; if (k === "theme") applyTheme(b.dataset.v); if (k === "density") applyDensity(b.dataset.v); FS.render(); }));
      main.querySelector("#p-lang").onchange = (e) => { S.personal.lang = e.target.value; FS.render(); if (e.target.value === "en") FS.toast("English: im Mockup nicht übersetzt."); };
    },
  });
})();
