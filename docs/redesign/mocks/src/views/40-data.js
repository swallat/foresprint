// Area "Daten" (data, conflicts, history), Speicher (storage) and first-run wizard (setup).
// Flows: F1, D1 to D6. UI words: Speichern, Aktualisieren, Verlauf. Git words only on "storage".
(function () {
  const D = window.DEMO;
  const esc = FS.esc;
  const ic = FS.icon;
  const S = FS.state;

  // ---------- shared mock state ----------
  S.unsaved ??= [
    { id: "u1", what: "FTE Felix Braun", file: "personen.yaml", before: "0,6", after: "0,5" },
    { id: "u2", what: "Vormerkung ATL-412", file: "tickets.yaml", before: "nicht vorgemerkt", after: "Sprint 2026.22" },
    { id: "u3", what: "Vorgeplant Kundenportal, Sprint 2026.22", file: "sprints/2026.22.yaml", before: "12", after: "13" },
  ];
  // Without tickets there are no reservations; show the matching amount change instead. With work packages the keys read AP-….
  const noneAlt = (o, alt) => { Object.keys(alt).forEach((k) => { const v = o[k]; Object.defineProperty(o, k, { get: () => (FS.trk() === "none" ? alt[k] : typeof v === "string" ? FS.dk(v.replace(/ATL-\d+/g, (m) => FS.dk(m))) : v), enumerable: true, configurable: true }); }); return o; };
  S.unsaved.forEach((u) => u.id === "u2" && !Object.getOwnPropertyDescriptor(u, "what").get && noneAlt(u, { what: "Self-Service 2.0 in Kundenportal, Sprint 2026.22", file: "sprints/2026.22.yaml", before: "–", after: "5 Punkte" }));
  let uid = 10;
  FS.addUnsaved = (what, before, after, file) => S.unsaved.push({ id: "u" + ++uid, what, before, after, file: file || "team.yaml" });
  S.pending ??= 0; // local saves waiting for the server (offline)
  const newConflicts = () => [
    { id: "c1", label: "Abwesenheit Jonas Weber, Sprint 2026.22", file: "abwesenheiten.yaml", unit: "Tage", before: "2", mine: "3", theirs: "4", who: "Lea Hoffmann", when: "vor 12 min", pick: null, custom: "" },
    { id: "c2", label: "Vorgeplant Kundenportal, Sprint 2026.22", file: "sprints/2026.22.yaml", unit: "Punkte", before: "10", mine: "13", theirs: "12", who: "Kim Berger", when: "vor 40 min", pick: null, custom: "" },
  ];
  S.conflicts ??= newConflicts();
  S.histScope ??= { mode: "team", sprint: "2026.22", file: "personen.yaml" };
  S.storageForm ??= { server: "git.example.com/planung/atlas-daten", branch: "main", name: "Kim Berger", email: "kim.berger@atlas.example", eol: "auto", tokenSet: true, kind: "git", checked: null };
  S.setup ??= { step: 0, kind: "clone", team: "demo", jira: "local", testOk: false };
  const st = () => S.storageState || "incoming";

  D.dataDiffs = [
    { rows: [["Abwesenheit Paula Neumann, 2026.22", "0 Tage", "5 Tage"], ["Abwesenheit Mira Schulz, 2026.25", "0 Tage", "5 Tage"]] },
    { rows: [["Meilenstein Beta für Pilotkunden (Self-Service 2.0)", "13.11.26", "20.11.26"]] },
  ];
  D.history = [
    { id: "h1", hash: "a41f9c2", when: "heute 09:42", who: "Du", what: "Vormerkung ATL-415 für Sprint 2026.22", sprint: "2026.22", file: "tickets.yaml" },
    { id: "h2", hash: "7be03d1", when: "heute 09:10", who: "Lea Hoffmann", what: "Abwesenheit Paula Neumann, 2026.22: 0 auf 5 Tage", sprint: "2026.22", file: "abwesenheiten.yaml" },
    { id: "h3", hash: "c58a2e7", when: "gestern 16:48", who: "Kim Berger", what: "Projekt Self-Service 2.0: Kontingent 50 auf 60 PT", sprint: null, file: "projekte.yaml" },
    { id: "h4", hash: "19d7f40", when: "gestern 11:20", who: "Du", what: "FTE Felix Braun: 0,6 auf 0,5", sprint: null, file: "personen.yaml" },
    { id: "h5", hash: "e2c61b8", when: "19.10. 14:05", who: "Lea Hoffmann", what: "Sprint 2026.21: Plan eingefroren", sprint: "2026.21", file: "sprints/2026.21.yaml" },
    { id: "h6", hash: "3f08aa5", when: "14.10. 10:05", who: "Kim Berger", what: "Planning-Protokoll 2026.21 geschrieben", sprint: "2026.21", file: "protokolle/2026.21-planning.md" },
    { id: "h7", hash: "b9441de", when: "13.10. 17:30", who: "Du", what: "Review 2026.20: Velocity 37, Tag gesetzt", sprint: "2026.20", file: "sprints/2026.20.yaml", tag: "2026.20" },
    { id: "h8", hash: "5d1ec93", when: "09.10. 15:20", who: "Lea Hoffmann", what: "Vorplanung 2026.21 Plattform: 7 auf 8", sprint: "2026.21", file: "sprints/2026.21.yaml" },
  ];
  noneAlt(D.history[0], { what: "Self-Service 2.0 in Kundenportal: 5 Punkte für Sprint 2026.22", file: "sprints/2026.22.yaml" });
  D.tags = [
    { name: "2026.20", when: "13.10.26", note: "Review 2026.20", hash: "b9441de" },
    { name: "2026.19", when: "29.09.26", note: "Review 2026.19", hash: "8a30c15" },
    { name: "2026.18", when: "15.09.26", note: "Review 2026.18", hash: "d70be29" },
    { name: "2026.17", when: "01.09.26", note: "Review 2026.17", hash: "41ce7f6" },
  ];

  // ---------- helpers ----------
  const tabs = (a) => `<div class="tabs" role="tablist">${[["data", "Übersicht", "database"], ["conflicts", "Konflikte", "call_split"], ["history", "Verlauf und Tags", "history"]]
    .map(([id, l, i]) => `<a href="#${id}" class="${a === id ? "active" : ""}">${ic(i)}${l}${id === "conflicts" && st() === "conflict" ? ` <span class="chip bad">${S.conflicts.length}</span>` : ""}</a>`).join("")}</div>`;
  const wireActs = (main, h) => main.querySelectorAll("[data-act]").forEach((b) => (b.onclick = (e) => h[b.dataset.act]?.(b, e)));
  const setState = (s) => { S.storageState = s; if (s === "conflict") S.conflicts = newConflicts(); if (s === "mr") S.mrDemo = true; FS.render(); };
  const diffTable = (rows) => `<div class="tw"><table class="t"><thead><tr><th>Wert</th><th class="num">Vorher</th><th class="num">Nachher</th></tr></thead><tbody>${rows.map((r) => `<tr><td style="white-space:normal">${esc(r[0])}</td><td class="num muted">${esc(r[1])}</td><td class="num"><strong>${esc(r[2])}</strong></td></tr>`).join("")}</tbody></table></div>`;
  const segState = () => {
    const m = [["saved", "Gespeichert"], ["incoming", "Neue Änderungen"], ["conflict", "Konflikt"], ["offline", "Offline"], ["mr", "Merge Request"]];
    return `<div class="row" role="group" aria-label="Zustand simulieren" id="sim">${m.map(([k, l]) => `<button type="button" class="chip filter ${st() === k ? "on" : ""}" data-sim="${k}" aria-pressed="${st() === k}">${l}</button>`).join("")}</div>`;
  };
  const wireSim = (main) => main.querySelectorAll("[data-sim]").forEach((b) => (b.onclick = () => setState(b.dataset.sim)));
  const unsavedBanner = () => S.unsaved.length ? `<div class="banner info">${ic("edit_note")}<div class="grow">Du hast <strong class="data">${S.unsaved.length}</strong> ungespeicherte Änderungen. <a href="#data">Ansehen</a> oder oben auf Speichern klicken.</div></div>` : "";

  // Top bar Save / Refresh follow the simulated state (capture phase, runs before the shell handlers)
  document.addEventListener("click", (e) => {
    const save = e.target.closest("#btn-save"), refresh = e.target.closest("#btn-refresh");
    if (!save && !refresh) return;
    const s = st();
    const again = () => setTimeout(() => { if (["data", "conflicts", "history", "storage"].includes(location.hash.slice(1))) FS.render(); }, 0);
    if (save) {
      if (s === "conflict") { e.stopPropagation(); FS.toast("Erst Konflikte lösen, dann Speichern."); location.hash = "conflicts"; return; }
      if (s === "offline") { e.stopPropagation(); S.pending += 1; S.unsaved = []; FS.toast(`Lokal gespeichert. ${S.pending} Speicherung${S.pending > 1 ? "en warten" : " wartet"} auf die Verbindung.`); again(); return; }
      if (s === "mr") { e.stopPropagation(); S.unsaved = []; FS.toast("Gespeichert. Der Merge Request ist aktualisiert."); again(); return; }
      S.unsaved = []; again();
    } else {
      if (s === "offline") { e.stopPropagation(); FS.toast("Keine Verbindung. Du arbeitest mit dem letzten Stand."); return; }
      if (s === "conflict") { e.stopPropagation(); FS.toast("Aktualisieren ist erst nach dem Lösen der Konflikte möglich."); return; }
      if (s === "mr") { e.stopPropagation(); FS.toast("Noch nicht übernommen. Der Merge Request ist offen."); return; }
      again();
    }
  }, true);

  // ================= data =================
  FS.view("data", {
    title: "Daten",
    render() {
      const s = st(), stg = D.storage;
      const banners = {
        saved: `<div class="banner" style="background:var(--ok-weak)">${ic("cloud_done")}<div class="grow">Alles gespeichert. Dein Stand entspricht dem Stand des Teams (${stg.lastSave}).</div></div>`,
        incoming: `<div class="banner warn">${ic("cloud_download")}<div class="grow">Es gibt <strong class="data">${stg.incoming.length}</strong> Änderungen von anderen. Mit Aktualisieren übernimmst du sie. Vorher kannst du unten sehen, was sich ändert.</div></div>`,
        conflict: `<div class="banner bad">${ic("call_split")}<div class="grow"><strong>Konflikt:</strong> ${S.conflicts.length} Werte wurden von dir und anderen unterschiedlich geändert. Alle anderen Seiten bleiben nutzbar, nur die betroffenen Werte warten. <a href="#conflicts">Konflikt lösen</a></div></div>`,
        offline: `<div class="banner">${ic("cloud_off")}<div class="grow"><strong>Keine Verbindung.</strong> Du arbeitest mit dem letzten Stand. Speichern sichert lokal (<span class="data">${S.pending}</span> wartend), sobald die Verbindung da ist, geht alles zum Team.</div></div>`,
        mr: `<div class="banner warn">${ic("merge")}<div class="grow"><strong>Wartet auf Freigabe.</strong> Der Server nimmt Änderungen nur nach Prüfung an. Deine Änderungen sind eingereicht. <a href="https://git.example.com/planung/atlas-daten/-/merge_requests/17" target="_blank" rel="noopener">Freigabe-Anfrage öffnen${ic("open_in_new")}</a></div></div>`,
      };
      const inc = s === "incoming" ? `<div class="card" id="incoming"><h2>Änderungen von anderen</h2><div class="stack">${stg.incoming.map((c, i) => `
          <div><div class="row"><strong>${esc(c.who)}</strong><span class="muted small">${c.when}</span><span class="chip">${esc(c.what)}</span></div>
          <div style="margin-top:6px">${diffTable(D.dataDiffs[i].rows)}</div></div>`).join("")}
        </div><div class="row" style="margin-top:12px"><button class="btn primary" type="button" data-act="refresh">${ic("download")}Aktualisieren</button><span class="small muted">Deine ${S.unsaved.length} ungespeicherten Änderungen bleiben erhalten.</span></div></div>` : "";
      const uns = `<div class="card" id="unsaved"><div class="row"><h2 style="flex:1">Meine ungespeicherten Änderungen</h2>${S.unsaved.length ? `<button class="btn" type="button" data-act="discardAll">Alle verwerfen</button>` : ""}</div>
        ${S.unsaved.length ? `<div class="tw"><table class="t"><thead><tr><th>Was</th><th class="num">Vorher</th><th class="num">Nachher</th><th></th></tr></thead><tbody>${S.unsaved.map((u) => `<tr><td style="white-space:normal">${esc(u.what)}<div class="small muted data">${esc(u.file)}</div></td><td class="num muted">${esc(u.before)}</td><td class="num">${esc(u.after)}</td><td><button class="btn icon ghost" type="button" data-act="discard" data-id="${u.id}" aria-label="Verwerfen: ${esc(u.what)}" title="Verwerfen">${ic("undo")}</button></td></tr>`).join("")}</tbody></table></div>`
          : `<p class="muted">Keine ungespeicherten Änderungen. ${S.pending ? "" : "Alles ist im Speicher."}</p>`}</div>`;
      const recent = `<div class="card"><div class="row"><h2 style="flex:1">Zuletzt gespeichert</h2><a href="#history">Ganzer Verlauf</a></div><div class="tw"><table class="t"><thead><tr><th>Wann</th><th>Wer</th><th>Was</th></tr></thead><tbody>${D.history.slice(0, 4).map((h) => `<tr><td class="data">${h.when}</td><td>${esc(h.who)}</td><td style="white-space:normal">${esc(h.what)}</td></tr>`).join("")}</tbody></table></div></div>`;
      return `<div class="page-head"><div><h1>Daten</h1><p class="lead">Wo die Daten von ${esc(D.team.name)} liegen, ob alles gespeichert ist und was andere geändert haben.</p></div>
        <div class="actions"><button class="btn" type="button" data-act="refresh">${ic("download")}Aktualisieren</button><button class="btn primary" type="button" data-act="save">${ic("save")}Speichern</button></div></div>
        ${tabs("data")}${banners[s]}
        <div class="grid cols-2">
          <div class="card"><h2>Wo die Daten liegen</h2><dl class="kv">
            <dt>Speicher</dt><dd>Git-Repository des Teams ${FS.lightChip("ok", "verbunden")}</dd>
            <dt>Ort</dt><dd class="data" style="overflow-wrap:anywhere">${stg.server}</dd>
            <dt>Zuletzt gespeichert</dt><dd class="data">${stg.lastSave}</dd>
            <dt>Zuletzt aktualisiert</dt><dd class="data">heute 09:41</dd>
            <dt>Wartet auf Versand</dt><dd class="data">${S.pending} Speicherung${S.pending === 1 ? "" : "en"}</dd></dl>
            <p class="small muted" style="margin:12px 0 0">Speicherart, Anmeldung und Name ändern: <a href="#storage">Einstellungen, Speicher</a>.</p></div>
          <div class="card"><h2>Zustand simulieren</h2><p class="small muted" style="margin:0 0 8px">Nur im Mockup: Schalter für den Statuschip oben. Echt wird der Zustand beim Öffnen und im Hintergrund geprüft.</p>${segState()}
            <dl class="kv" style="margin-top:12px"><dt>Statuschip</dt><dd>${FS.storageChip().replace("hide-narrow", "").replace("<a ", "<span style=\"white-space:normal;max-width:100%\" ").replace("</a>", "</span>").replace(' href="#data" id="storage-chip"', "")}</dd></dl></div>
        </div>
        <div class="grid" style="margin-top:16px">${inc}${uns}${recent}</div>`;
    },
    wire(main) {
      wireSim(main);
      wireActs(main, {
        save: () => document.getElementById("btn-save").click(),
        refresh: () => document.getElementById("btn-refresh").click(),
        discard: (b) => { const i = S.unsaved.findIndex((u) => u.id === b.dataset.id); const [u] = S.unsaved.splice(i, 1); FS.render(); FS.toast(`Verworfen: ${esc(u.what)}`, () => { S.unsaved.splice(i, 0, u); FS.render(); }); },
        discardAll: () => { const old = S.unsaved; S.unsaved = []; FS.render(); FS.toast("Alle ungespeicherten Änderungen verworfen.", () => { S.unsaved = old; FS.render(); }); },
      });
    },
  });

  // ================= conflicts =================
  const conflictVal = (c) => (c.pick === "mine" ? c.mine : c.pick === "theirs" ? c.theirs : c.pick === "custom" ? c.custom : null);
  FS.view("conflicts", {
    title: "Konflikte",
    render() {
      const head = `<div class="page-head"><div><h1>Konflikte</h1><p class="lead">Derselbe Wert wurde von zwei Personen geändert. Du entscheidest je Eintrag, nichts geht verloren.</p></div></div>${tabs("conflicts")}`;
      if (st() !== "conflict") return `${head}<div class="card" style="text-align:center;padding:32px">${ic("check_circle")}<h2 style="margin-top:8px">Keine Konflikte</h2><p class="muted">Alle Änderungen konnten automatisch zusammengeführt werden.</p>
        <button class="btn" type="button" data-sim="conflict">${ic("science")}Konflikt simulieren</button></div>`;
      const open = S.conflicts.filter((c) => !c.pick || (c.pick === "custom" && c.custom === "")).length;
      return `${head}<div class="banner bad">${ic("call_split")}<div class="grow">Der Statuschip ist rot, bis alle Einträge entschieden sind. Andere Seiten bleiben nutzbar.</div></div>
        <div class="stack" style="gap:12px">${S.conflicts.map((c) => `
          <div class="card cf-entry" data-id="${c.id}"><div class="row"><strong style="flex:1">${esc(c.label)}</strong><span class="chip data">${esc(c.file)}</span></div>
            <div class="grid cols-3" style="margin:12px 0;gap:8px">
              <div class="card" style="background:var(--surface-2)"><div class="small muted">Vorher</div><div class="data" style="font-size:20px">${c.before} <span class="small muted">${c.unit}</span></div><div class="small muted">gemeinsamer Stand</div></div>
              <div class="card ${c.pick === "mine" ? "hl" : ""}" style="border-color:${c.pick === "mine" ? "var(--primary)" : "var(--border)"}"><div class="small muted">Meine</div><div class="data" style="font-size:20px">${c.mine} <span class="small muted">${c.unit}</span></div><div class="small muted">von dir</div></div>
              <div class="card" style="border-color:${c.pick === "theirs" ? "var(--primary)" : "var(--border)"}"><div class="small muted">Von anderen</div><div class="data" style="font-size:20px">${c.theirs} <span class="small muted">${c.unit}</span></div><div class="small muted">${esc(c.who)}, ${c.when}</div></div>
            </div>
            <div class="row" role="group" aria-label="Entscheidung für ${esc(c.label)}">
              ${[["mine", "Meine übernehmen"], ["theirs", "Von anderen übernehmen"], ["custom", "Selbst eingeben"]].map(([k, l]) => `<button type="button" class="chip filter ${c.pick === k ? "on" : ""}" data-pick="${k}" data-id="${c.id}" aria-pressed="${c.pick === k}">${l}</button>`).join("")}
              ${c.pick === "custom" ? `<input class="input data" style="width:90px" data-custom="${c.id}" value="${esc(c.custom)}" aria-label="Eigener Wert" inputmode="numeric">` : ""}
              <span class="spacer" style="flex:1"></span>
              <span class="small">${conflictVal(c) ? `Ergebnis: <strong class="data">${esc(conflictVal(c))} ${c.unit}</strong>` : `<span class="muted">noch nicht entschieden</span>`}</span>
            </div></div>`).join("")}</div>
        <div class="row" style="margin-top:16px;position:sticky;bottom:0;background:var(--bg);padding:8px 0">
          <span class="small">${open === 0 ? FS.lightChip("ok", "alle entschieden") : `<span class="chip warn">${ic("pending")}${open} von ${S.conflicts.length} offen</span>`}</span><span style="flex:1"></span>
          <button class="btn danger" type="button" data-act="discard">${ic("delete")}Meine verwerfen</button>
          <button class="btn primary" type="button" data-act="resolve" ${open ? "disabled" : ""} id="cf-save">${ic("save")}Alle übernommen: Speichern</button></div>
        <p class="small muted">Meine verwerfen übernimmt für alle Einträge den Wert der anderen.</p>`;
    },
    wire(main) {
      wireSim(main);
      main.querySelectorAll("[data-pick]").forEach((b) => (b.onclick = () => { S.conflicts.find((c) => c.id === b.dataset.id).pick = b.dataset.pick; FS.render(); }));
      main.querySelectorAll("[data-custom]").forEach((i) => (i.onchange = () => { S.conflicts.find((c) => c.id === i.dataset.custom).custom = i.value.trim(); FS.render(); }));
      wireActs(main, {
        resolve: () => { S.storageState = "saved"; S.unsaved = []; S.conflicts = newConflicts(); FS.render(); FS.toast("Konflikt gelöst und gespeichert. Das Team sieht deine Entscheidung."); },
        discard: () => { const old = S.unsaved; S.storageState = "saved"; S.conflicts = newConflicts(); S.unsaved = old.filter((u) => !/Abwesenheit Jonas|Kundenportal/.test(u.what)); FS.render(); FS.toast("Meine Änderungen an diesen Werten verworfen. Die Werte der anderen gelten."); },
      });
    },
  });

  // ================= history =================
  FS.view("history", {
    title: "Verlauf und Tags",
    render() {
      const sc = S.histScope;
      const list = D.history.filter((h) => sc.mode === "team" || (sc.mode === "sprint" ? h.sprint === sc.sprint : h.file === sc.file));
      const files = [...new Set(D.history.map((h) => h.file))];
      const sprints = D.sprints.filter((s) => s.state !== "open" || s.id === "2026.22").map((s) => s.id).reverse();
      return `<div class="page-head"><div><h1>Verlauf und Tags</h1><p class="lead">Wer hat wann was geändert. Eine Änderung zurücknehmen oder einen früheren Stand holen. Beides landet zuerst als ungespeicherte Änderung bei dir.</p></div></div>
        ${tabs("history")}${unsavedBanner()}
        <div class="row" style="margin-bottom:12px" role="group" aria-label="Umfang"><span class="small muted">Umfang</span>
          ${[["team", "Team"], ["sprint", "Sprint"], ["file", "Datei"]].map(([k, l]) => `<button type="button" class="chip filter ${sc.mode === k ? "on" : ""}" data-scope="${k}" aria-pressed="${sc.mode === k}">${l}</button>`).join("")}
          ${sc.mode === "sprint" ? `<select class="input data" id="h-sprint" aria-label="Sprint">${sprints.map((s) => `<option ${s === sc.sprint ? "selected" : ""}>${s}</option>`).join("")}</select>` : ""}
          ${sc.mode === "file" ? `<select class="input data" id="h-file" aria-label="Datei">${files.map((f) => `<option ${f === sc.file ? "selected" : ""}>${f}</option>`).join("")}</select>` : ""}
          <span class="small muted">${list.length} Einträge</span></div>
        <div class="tw" id="h-table"><table class="t"><thead><tr><th>Wann</th><th>Wer</th><th>Was</th><th>Datei</th><th></th></tr></thead><tbody>
          ${list.length ? list.map((h) => `<tr><td class="data">${h.when}</td><td>${esc(h.who)}</td><td style="white-space:normal;min-width:240px">${esc(h.what)}${h.tag ? ` <span class="chip fc">${ic("sell")}${h.tag}</span>` : ""}</td><td class="data muted">${esc(h.file)}</td>
            <td><div class="stack" style="align-items:flex-start;gap:4px"><button class="btn" type="button" data-act="undo" data-id="${h.id}">${ic("undo")}Diese Änderung zurücknehmen</button><button class="btn" type="button" data-act="restore" data-id="${h.id}">${ic("restore")}Diesen Stand wiederherstellen</button></div></td></tr>`).join("")
            : `<tr><td colspan="5" class="muted" style="white-space:normal">Keine Einträge in diesem Umfang.</td></tr>`}</tbody></table></div>
        <h2 style="margin-top:24px">Tags</h2><p class="small muted" style="margin-top:-4px">Jedes Sprint-Review setzt einen Tag. Du kannst jeden früheren Stand wählen, Tags helfen beim Finden.</p>
        <div class="tw"><table class="t"><thead><tr><th>Tag</th><th>Datum</th><th>Anlass</th><th></th></tr></thead><tbody>${D.tags.map((t) => `<tr><td><span class="chip fc">${ic("sell")}<span class="data">${t.name}</span></span></td><td class="data">${t.when}</td><td>${t.note}</td><td><button class="btn" type="button" data-act="tag" data-id="${t.name}">${ic("restore")}Diesen Stand wiederherstellen</button></td></tr>`).join("")}</tbody></table></div>`;
    },
    wire(main) {
      main.querySelectorAll("[data-scope]").forEach((b) => (b.onclick = () => { S.histScope.mode = b.dataset.scope; FS.render(); }));
      main.querySelector("#h-sprint")?.addEventListener("change", (e) => { S.histScope.sprint = e.target.value; FS.render(); });
      main.querySelector("#h-file")?.addEventListener("change", (e) => { S.histScope.file = e.target.value; FS.render(); });
      const done = (what, before, after, file) => { FS.addUnsaved(what, before, after, file); FS.closePanel(); FS.render(); FS.toast("Als ungespeicherte Änderung geladen. Jetzt Speichern.", () => { S.unsaved.pop(); FS.render(); }); };
      wireActs(main, {
        undo: (b) => { const h = D.history.find((x) => x.id === b.dataset.id); FS.addUnsaved(`Zurückgenommen: ${h.what}`, "aktuell", "Stand vor " + h.when, h.file); FS.render(); FS.toast("Änderung zurückgenommen, noch nicht gespeichert.", () => { S.unsaved.pop(); FS.render(); }); },
        restore: (b) => {
          const h = D.history.find((x) => x.id === b.dataset.id);
          const p = FS.openPanel("Stand wiederherstellen", `<p>Stand nach der Änderung vom <strong>${h.when}</strong> von ${esc(h.who)}:</p><p class="muted">${esc(h.what)}</p>
            <p>Betroffen: <span class="data">${esc(h.file)}</span> und alles, was danach geändert wurde (${D.history.indexOf(h)} Änderungen).</p><div class="banner info">${ic("info")}<div class="grow">Nichts geht verloren. Der Stand wird als ungespeicherte Änderung geladen, erst Speichern macht ihn für das Team gültig. Der heutige Stand bleibt im Verlauf.</div></div>
            <button class="btn primary" type="button" id="rs-go">Als ungespeicherte Änderung laden</button>`);
          p.querySelector("#rs-go").onclick = () => done(`Stand wiederhergestellt: ${h.when}, ${h.what}`, "aktueller Stand", "Stand vom " + h.when, h.file);
        },
        tag: (b) => {
          const t = D.tags.find((x) => x.name === b.dataset.id);
          const p = FS.openPanel(`Stand ${t.name} wiederherstellen`, `<p>Gesamter Stand zum Abschluss von Sprint <span class="data">${t.name}</span> (${t.when}).</p>
            <div class="banner warn">${ic("warning")}<div class="grow">Betrifft das ganze Team: spätere Änderungen an Personen, Sprints und Projekten werden zurückgesetzt, bis du Speichern drückst.</div></div>
            <button class="btn primary" type="button" id="rs-go">Als ungespeicherte Änderung laden</button>`);
          p.querySelector("#rs-go").onclick = () => done(`Gesamtstand wiederhergestellt: Tag ${t.name}`, "aktueller Stand", t.when, "alle Dateien");
        },
      });
    },
  });

  // ================= storage (Git words allowed here) =================
  FS.view("storage", {
    title: "Speicher",
    render() {
      const f = S.storageForm, n = S.unsaved.length;
      const kindCard = (on, dis, title, text) => `<div class="card" style="${on ? "border-color:var(--primary);background:var(--primary-weak)" : ""}${dis ? ";opacity:.55" : ""}" ${dis ? 'aria-disabled="true"' : ""}><div class="row"><input type="radio" name="kind" ${on ? "checked" : ""} ${dis ? "disabled" : ""} id="k-${on ? "git" : "dir"}"><label for="k-${on ? "git" : "dir"}"><strong>${title}</strong></label>${dis ? `<span class="chip">nach 1.0</span>` : ""}</div><p class="small muted" style="margin:6px 0 0">${text}</p></div>`;
      return `<div class="page-head"><div><h1>Speicher</h1><p class="lead">Hier stehen die technischen Angaben zum Speicher. Im Alltag brauchst du nur Speichern und Aktualisieren.</p></div>
        <div class="actions"><a class="btn" href="#setup">${ic("auto_fix_high")}Einrichtung erneut starten</a></div></div>
        <div class="grid cols-2">
          <div class="card" data-s="speicherart"><h2>Speicherart</h2><div class="stack">${kindCard(true, false, "Git-Repository", "Verlauf, Wiederherstellen und Datensicherheit. Standard in 1.0.")}${kindCard(false, true, "Geteilter Ordner (nach 1.0)", "Dateiserver oder SharePoint. Kommt nach 1.0 über dieselbe Speicherschnittstelle.")}</div></div>
          <div class="card st-server" data-s="server"><h2>Server</h2><div class="field"><label for="st-server">Adresse des Repositorys</label><input class="input data" id="st-server" value="${esc(f.server)}"></div>
            <div class="row" style="margin-top:8px"><button class="btn" type="button" data-act="testServer">${ic("network_check")}Verbindung testen</button><span id="st-server-res" class="small">${f.checked === "server" ? FS.lightChip("ok", "erreichbar, 48 ms") : ""}</span></div></div>
          <div class="card st-token" data-s="token anmeldung"><h2>Anmeldung (Token)</h2>
            <p class="row" style="margin:0 0 8px">${f.tokenSet ? FS.lightChip("ok", "angemeldet als kberger, gültig bis 14.01.27") : `<span class="chip warn">${ic("key_off")}nicht angemeldet</span>`}</p>
            <div class="field"><label for="st-token">Neuer Token</label><input class="input data" id="st-token" type="password" autocomplete="new-password" placeholder="${f.tokenSet ? "••••••••••••••••" : "Token einfügen"}"></div>
            <div class="row" style="margin-top:8px"><button class="btn" type="button" data-act="testToken">${ic("verified_user")}Anmeldung testen</button><button class="btn" type="button" data-act="setToken">Token ersetzen</button><button class="btn danger" type="button" data-act="removeToken" ${f.tokenSet ? "" : "disabled"}>${ic("delete")}Entfernen</button></div>
            <p class="small muted" style="margin:8px 0 0">Der Token liegt im Schlüsselbund deines Systems (Git credential helper), nicht in den Teamdaten. <span id="st-token-res">${f.checked === "token" ? FS.lightChip("ok", "Anmeldung gültig") : ""}</span></p></div>
          <div class="card" data-s="branch"><h2>Branch</h2><div class="row"><select class="input data" id="st-branch" ${n ? "disabled" : ""} aria-label="Branch">${["main", "foresprint/kberger", "release-2026"].map((b) => `<option ${b === f.branch ? "selected" : ""}>${b}</option>`).join("")}</select><button class="btn" type="button" data-act="branch" ${n ? "disabled" : ""}>Wechseln</button></div>
            ${n ? `<div class="banner warn" style="margin:8px 0 0">${ic("lock")}<div class="grow">Wechsel gesperrt: <span class="data">${n}</span> ungespeicherte Änderungen. Erst <a href="#data">speichern oder verwerfen</a>.</div></div>` : `<p class="small muted" style="margin:8px 0 0">Aktueller Branch: <span class="data">${esc(f.branch)}</span>. Wechsel möglich, da alles gespeichert ist.</p>`}</div>
          <div class="card" data-s="name e-mail"><h2>Name und E-Mail</h2><div class="stack"><div class="field"><label for="st-name">Name in Speicherständen</label><input class="input" id="st-name" value="${esc(f.name)}"></div><div class="field"><label for="st-mail">E-Mail</label><input class="input" id="st-mail" type="email" value="${esc(f.email)}"></div></div><p class="small muted" style="margin:8px 0 0">Wird im Verlauf bei jeder Änderung als Autor angezeigt.</p></div>
          <div class="card st-mr" data-s="merge request"><div class="row"><h2 style="flex:1">Merge Request</h2>${FS.lightChip("ok", "automatisch erkannt")}</div>
            <p style="margin:0 0 8px">Dieser Server nimmt Änderungen am Branch <span class="data">main</span> nur über einen Merge Request an. Foresprint hat das beim ersten Speichern erkannt.</p>
            <ol class="small" style="margin:0 0 8px;padding-left:18px"><li>Speichern schickt deine Änderungen auf einen eigenen Branch <span class="data">foresprint/kberger</span> und legt den Merge Request an.</li><li>Der Statuschip zeigt "Wartet auf Merge Request" mit Link.</li><li>Weitere Speicherungen aktualisieren denselben Merge Request.</li><li>Nach der Freigabe auf dem Server übernimmt Aktualisieren den Stand.</li></ol>
            <div class="row"><button class="btn" type="button" data-act="recheck">${ic("refresh")}Erneut prüfen</button><a class="small" href="https://git.example.com/planung/atlas-daten/-/merge_requests/17" target="_blank" rel="noopener">Offener Merge Request${ic("open_in_new")}</a></div></div>
          <div class="card" data-s="zeilenenden"><h2>Zeilenenden</h2><div class="field"><label for="st-eol">Zeilenenden der Dateien</label><select class="input" id="st-eol"><option value="auto" ${f.eol === "auto" ? "selected" : ""}>Automatisch (empfohlen)</option><option value="lf" ${f.eol === "lf" ? "selected" : ""}>LF (Linux, macOS)</option><option value="crlf" ${f.eol === "crlf" ? "selected" : ""}>CRLF (Windows)</option></select></div><p class="small muted" style="margin:8px 0 0">Gemischte Zeilenenden erzeugen sonst Scheinänderungen im Verlauf.</p></div>
          <div class="card" data-s="ordner"><h2>Zuletzt verwendete Ordner</h2><div class="stack">${["C:\\Planung\\atlas-daten", "C:\\Planung\\demo-team", "D:\\Archiv\\atlas-2025"].map((p, i) => `<div class="row"><span class="data" style="flex:1;overflow-wrap:anywhere">${p}</span>${i === 0 ? `<span class="chip ok">aktiv</span>` : `<button class="btn" type="button" data-act="openDir" data-path="${p}">Öffnen</button>`}</div>`).join("")}</div></div>
        </div>`;
    },
    wire(main) {
      const f = S.storageForm;
      main.querySelector("#st-server").onchange = (e) => (f.server = e.target.value);
      main.querySelector("#st-name").onchange = (e) => (f.name = e.target.value);
      main.querySelector("#st-mail").onchange = (e) => (f.email = e.target.value);
      main.querySelector("#st-eol").onchange = (e) => { f.eol = e.target.value; FS.toast("Zeilenenden geändert. Gilt ab dem nächsten Speichern."); };
      main.querySelector("#st-branch").onchange = (e) => (f.pendingBranch = e.target.value);
      wireActs(main, {
        testServer: () => { f.checked = "server"; FS.render(); },
        testToken: () => { f.checked = "token"; FS.render(); },
        setToken: () => { const v = main.querySelector("#st-token").value; if (!v) return FS.toast("Bitte zuerst einen Token einfügen."); f.tokenSet = true; f.checked = null; FS.render(); FS.toast("Token im Schlüsselbund ersetzt."); },
        removeToken: () => { f.tokenSet = false; FS.render(); FS.toast("Token entfernt. Speichern und Aktualisieren verlangen eine neue Anmeldung.", () => { f.tokenSet = true; FS.render(); }); },
        branch: () => { f.branch = f.pendingBranch || f.branch; FS.render(); FS.toast(`Branch ${f.branch} aktiv.`); },
        recheck: () => FS.toast("Server geprüft: Merge Request weiterhin verlangt."),
        openDir: (b) => FS.toast(`Ordner ${b.dataset.path} wird geöffnet (Mockup).`),
      });
    },
  });

  // ================= setup wizard (F1, D1) =================
  const SU_STEPS = ["Speicher", "Anmeldung", "Team", "Tickets", "Fertig"];
  FS.view("setup", {
    title: "Erster Start",
    render() {
      const w = S.setup, n = w.step;
      const opt = (key, val, title, text, extra = "") => `<div class="card su-opt" style="${w[key] === val ? "border-color:var(--primary);background:var(--primary-weak)" : ""}"><div class="row"><input type="radio" name="${key}" id="${key}-${val}" value="${val}" data-su="${key}" ${w[key] === val ? "checked" : ""}><label for="${key}-${val}"><strong>${title}</strong></label></div><p class="small muted" style="margin:6px 0 0">${text}</p>${w[key] === val ? extra : ""}</div>`;
      const body = [
        `<h2>Wo liegen die Daten des Teams?</h2><div class="stack su-kinds">
          ${opt("kind", "clone", "Von einer Adresse laden", "Das Team hat schon ein Repository auf dem Server. Foresprint lädt es herunter.", `<div class="field" style="margin-top:8px"><label for="su-addr">Adresse</label><input class="input data" id="su-addr" value="${esc(S.storageForm.server)}"></div>`)}
          ${opt("kind", "open", "Vorhandenen Ordner öffnen", "Ein Repository liegt schon auf diesem Rechner.", `<div class="row" style="margin-top:8px"><input class="input data" style="flex:1" value="C:\\Planung\\atlas-daten" aria-label="Ordner"><button class="btn" type="button">${ic("folder_open")}Wählen</button></div>`)}
          ${opt("kind", "new", "Neu anlegen", "Ein leeres Repository für ein neues Team. Die Adresse kannst du später eintragen.")}
          <div class="card" style="opacity:.55" aria-disabled="true"><div class="row"><input type="radio" disabled><strong>Geteilter Ordner</strong><span class="chip">nach 1.0</span></div><p class="small muted" style="margin:6px 0 0">Dateiserver oder SharePoint kommen nach 1.0.</p></div></div>`,
        `<h2>Anmeldung am Server</h2><div class="grid cols-2"><div class="stack"><div class="field"><label for="su-token">Token</label><input class="input data" id="su-token" type="password" autocomplete="new-password" placeholder="Token einfügen"></div>
          <div class="row"><button class="btn" type="button" data-act="test">${ic("verified_user")}Anmeldung testen</button>${w.testOk ? FS.lightChip("ok", "Anmeldung gültig") : ""}</div>
          <p class="small muted" style="margin:0">Der Token wird im Schlüsselbund deines Systems abgelegt, nicht in den Teamdaten. Bei einem öffentlich lesbaren Server kannst du diesen Schritt überspringen.</p></div>
          <div class="stack"><div class="field"><label for="su-name">Dein Name</label><input class="input" id="su-name" value="${esc(S.storageForm.name)}"></div><div class="field"><label for="su-mail">E-Mail</label><input class="input" id="su-mail" value="${esc(S.storageForm.email)}"></div><p class="small muted" style="margin:0">Einmalig. Erscheint im Verlauf bei deinen Änderungen.</p></div></div>`,
        `<h2>Team</h2>${w.kind === "clone" ? `<div class="banner info">${ic("search")}<div class="grow">Im Speicher gefunden: <strong>Team Atlas</strong> mit 6 Personen und 4 Produkten. Du kannst es direkt öffnen.</div></div>` : ""}<div class="stack">
          ${opt("team", "demo", w.kind === "clone" ? "Team Atlas öffnen" : "Demo-Team Atlas öffnen", "Beispieldaten zum Ausprobieren, nichts davon ist echt.")}
          ${opt("team", "new", "Neues Team anlegen", "Name, Region für Feiertage und der erste Sprint.", `<div class="grid cols-2" style="margin-top:8px"><div class="field"><label for="su-tn">Teamname</label><input class="input" id="su-tn" placeholder="z. B. Team Nord"></div><div class="field"><label for="su-region">Region</label><select class="input" id="su-region"><option>DE-NW</option><option>DE-BY</option><option>DE-BE</option><option>AT</option><option>CH-ZH</option></select></div><div class="field"><label for="su-sid">Erster Sprint</label><input class="input data" id="su-sid" value="2026.22"></div><div class="field"><label for="su-sd">Beginn</label><input class="input data" id="su-sd" type="date" value="2026-10-28"></div></div>`)}</div>`,
        `<h2>Woher kommt die Arbeit?</h2><p class="muted">Foresprint funktioniert auch ohne Tracker. Du kannst das später unter Einstellungen, Tickets und Tracker ändern.</p><div class="stack">
          ${opt("jira", "local", "Arbeitspakete in Foresprint", "Kein Tracker. Du legst Arbeitspakete von Hand an, sonst wie mit Tracker.")}
          ${opt("jira", "none", "Ohne Tickets", "Kein Backlog. Geplant werden Beträge je Produkt und Projekt, die Zusage ist eine Zahl.")}
          ${opt("jira", "connect", "Jira jetzt verbinden", "Tickets werden nur gelesen, Jira wird nicht verändert.", `<div class="grid cols-2" style="margin-top:8px"><div class="field"><label for="su-ju">Adresse</label><input class="input data" id="su-ju" value="https://jira.example.com"></div><div class="field"><label for="su-jt">Token</label><input class="input data" id="su-jt" type="password" autocomplete="new-password" placeholder="Token"></div><div class="field" style="grid-column:1/-1"><label for="su-jq">Abfrage (JQL)</label><input class="input data" id="su-jq" value="project = ATL AND sprint is EMPTY OR sprint in openSprints()"></div></div><div class="row" style="margin-top:8px"><button class="btn" type="button" data-act="jtest">${ic("network_check")}Testen und ersten Abruf starten</button><span id="su-jres" class="small"></span></div>`)}</div>`,
        `<h2>Fertig</h2><div class="banner" style="background:var(--ok-weak)">${ic("check_circle")}<div class="grow">Alles eingerichtet. Du kannst jeden Punkt später in den Einstellungen ändern.</div></div>
          <dl class="kv" style="max-width:560px"><dt>Speicher</dt><dd>${{ clone: "Geladen von " + esc(S.storageForm.server), open: "Ordner geöffnet", new: "Neu angelegt" }[w.kind]}</dd><dt>Anmeldung</dt><dd>${w.testOk ? "Token gespeichert" : "übersprungen oder noch nicht getestet"}</dd><dt>Team</dt><dd>${w.team === "demo" ? "Team Atlas" : "Neues Team"}</dd><dt>Arbeit</dt><dd>${{ connect: "aus Jira, verbunden", local: "Arbeitspakete in Foresprint", none: "ohne Tickets" }[w.jira] ?? "Arbeitspakete in Foresprint"}</dd></dl>`,
      ][n];
      return `<div class="page-head"><div><h1>Erster Start</h1><p class="lead">Fünf kurze Schritte. Du kannst jederzeit springen, der Stand bleibt als Entwurf erhalten.</p></div></div>
        <nav class="stepper" aria-label="Schritte">${SU_STEPS.map((l, i) => `<a href="#setup" data-step="${i}" class="${i === n ? "active" : i < n ? "done" : ""}" ${i === n ? 'aria-current="step"' : ""}><span class="n">${i < n ? ic("check") : i + 1}</span>${l}</a>`).join("")}</nav>
        <div class="card su-body" style="max-width:760px">${body}</div>
        <div class="row" style="margin-top:16px;max-width:760px"><button class="btn" type="button" data-act="back" ${n === 0 ? "disabled" : ""}>${ic("arrow_back")}Zurück</button><span style="flex:1" class="small muted">${ic("draft", "small")} Entwurf gespeichert</span>
          ${n === 4 ? `<button class="btn primary" type="button" data-act="finish">Zu Heute${ic("arrow_forward")}</button>` : `${n >= 1 && n <= 3 ? `<button class="btn ghost" type="button" data-act="next">Überspringen</button>` : ""}<button class="btn primary" type="button" data-act="next">Weiter${ic("arrow_forward")}</button>`}</div>`;
    },
    wire(main) {
      const w = S.setup;
      main.querySelectorAll("[data-su]").forEach((r) => (r.onchange = () => { w[r.dataset.su] = r.value; FS.render(); }));
      main.querySelectorAll("[data-step]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); w.step = +a.dataset.step; FS.render(); }));
      wireActs(main, {
        next: () => { w.step = Math.min(4, w.step + 1); FS.render(); },
        back: () => { w.step = Math.max(0, w.step - 1); FS.render(); },
        test: () => { w.testOk = true; FS.render(); },
        jtest: () => { main.querySelector("#su-jres").innerHTML = FS.lightChip("ok", "verbunden, 46 Tickets abgerufen"); },
        finish: () => { S.storageState = "saved"; location.hash = "today"; },
      });
    },
  });

  // ================= flows =================
  const su = (n) => () => { S.setup.step = n; };
  FS.flow({ id: "F1", title: "Erster Start", summary: "Von der leeren App zu Heute: Speicher, Anmeldung, Team und optional Jira.", steps: [
    { view: "setup", text: "Die App kennt noch keinen Speicher, deshalb startet die Einrichtung. Wähle, woher die Daten kommen: von einer Adresse laden, Ordner öffnen oder neu anlegen.", hl: ".su-kinds", before: su(0) },
    { view: "setup", text: "Falls der Server eine Anmeldung verlangt: Token einfügen und testen. Name und E-Mail trägst du einmal ein.", hl: "#su-token", before: su(1) },
    { view: "setup", text: "Gibt es im Speicher schon ein Team, wird es angeboten. Sonst legst du ein Team an (Name, Region, erster Sprint) oder öffnest das Demo-Team.", hl: ".su-opt", before: su(2) },
    { view: "setup", text: "Jira ist optional. Du kannst ohne Tracker starten und später verbinden. Wer verbindet, testet und holt gleich die ersten Tickets.", hl: ".su-opt", before: su(3) },
    { view: "setup", text: "Zusammenfassung. Mit Zu Heute geht es in den Alltag, alle Angaben bleiben in den Einstellungen änderbar.", hl: "[data-act=finish]", before: su(4) },
    { view: "today", text: "Heute zeigt den nächsten Schritt je Sprint. Die Einrichtung ist abgeschlossen." },
  ] });
  FS.flow({ id: "D1", title: "Speicher einrichten", summary: "Git-Repository klonen oder öffnen, anmelden, Name und E-Mail eintragen.", steps: [
    { view: "setup", text: "Wo hält das Team seine Daten? In 1.0 ist es Git: von Adresse laden oder lokales Repository öffnen. Geteilter Ordner ist als Option sichtbar, aber erst nach 1.0 wählbar.", hl: ".su-kinds", before: su(0) },
    { view: "setup", text: "Verlangt der Server eine Anmeldung, kommt der Token über den Git credential helper, danach Test. Ohne Anmeldung geht es direkt weiter. Danach fehlt Name und E-Mail? Einmal eintragen.", hl: "#su-token", before: su(1) },
    { view: "storage", text: "Später änderst du alles unter Einstellungen, Speicher: Server, Token, Branch, Name und E-Mail, Zeilenenden. Die Art Git oder Ordner steht ganz oben.", hl: ".st-server" },
    { view: "today", text: "Fertig. Speichern, Aktualisieren und der Statuschip sind ab jetzt oben immer da." },
  ] });
  FS.flow({ id: "D2", title: "Speichern und aktualisieren", summary: "Änderungen von anderen sehen und übernehmen, eigene Änderungen speichern.", steps: [
    { view: "data", text: "Beim Öffnen prüft die App im Hintergrund auf Änderungen von anderen. Der Statuschip oben zeigt: 2 neue Änderungen von Lea.", hl: "#storage-chip", before() { S.storageState = "incoming"; S.unsaved = S.unsaved.length ? S.unsaved : [{ id: "u1", what: "FTE Felix Braun", file: "personen.yaml", before: "0,6", after: "0,5" }]; } },
    { view: "data", text: "Hier siehst du vorher und nachher. Aktualisieren übernimmt die Änderungen, deine eigenen bleiben erhalten.", hl: "#incoming" },
    { view: "data", text: "Du arbeitest weiter. Meine ungespeicherten Änderungen listet alles, was noch nicht beim Team ist, und jede lässt sich verwerfen.", hl: "#unsaved", before() { S.storageState = "saved"; } },
    { view: "data", text: "Speichern prüft vorher die geänderten Daten. Bei Fehlern erscheint eine Liste mit Links: korrigieren oder trotzdem speichern.", hl: "#btn-save" },
    { view: "data", text: "Haben andere zwischenzeitlich andere Werte geändert, führt Foresprint sie automatisch zusammen. Nur wenn beide denselben Wert änderten, geht es weiter mit D3 Konflikt lösen." },
  ] });
  FS.flow({ id: "D3", title: "Konflikt lösen", summary: "Zwei Personen haben denselben Wert geändert: je Eintrag entscheiden.", steps: [
    { view: "data", text: "Der Statuschip ist rot. Die anderen Seiten bleiben benutzbar, nur die betroffenen Werte warten.", hl: "#storage-chip", before() { S.storageState = "conflict"; S.conflicts = newConflicts(); } },
    { view: "conflicts", text: "Je Eintrag siehst du den Stand vorher, deinen Wert und den der anderen. Beispiel: Abwesenheit Jonas, 3 gegen 4 Tage.", hl: ".cf-entry" },
    { view: "conflicts", text: "Wähle Meine, Von anderen oder gib einen eigenen Wert ein. Für beide Einträge nötig.", hl: ".cf-entry:first-child [data-pick]" },
    { view: "conflicts", text: "Sind alle entschieden, wird Alle übernommen: Speichern aktiv. Alternativ verwirft Meine verwerfen alles und nimmt die Werte der anderen.", hl: "#cf-save" },
  ] });
  FS.flow({ id: "D4", title: "Server verlangt Merge Request", summary: "Der Server lehnt direkte Änderungen ab: Foresprint reicht sie ein und zeigt den Link.", steps: [
    { view: "storage", text: "Foresprint hat beim ersten Speichern erkannt, dass der Server auf main nur Merge Requests annimmt. Das steht hier mit Erklärung.", hl: ".st-mr", before() { S.storageState = "mr"; S.mrDemo = true; } },
    { view: "data", text: "Nach Speichern zeigt der Statuschip Wartet auf Merge Request, dazu der Link zur Freigabe. Foresprint hat keinen eigenen Ablauf dafür.", hl: "#storage-chip" },
    { view: "data", text: "Du arbeitest weiter. Jedes weitere Speichern aktualisiert denselben Merge Request.", hl: "#btn-save" },
    { view: "data", text: "Wurde auf dem Server freigegeben, übernimmt Aktualisieren den Stand. Der Chip wird grün.", hl: "#btn-refresh", before() { S.storageState = "mr"; } },
  ] });
  FS.flow({ id: "D5", title: "Keine Verbindung", summary: "Offline weiterarbeiten, lokal speichern und später abgleichen.", steps: [
    { view: "data", text: "Der Server ist nicht erreichbar. Der Chip zeigt Offline, die App arbeitet mit dem letzten Stand.", hl: "#storage-chip", before() { S.storageState = "offline"; } },
    { view: "data", text: "Speichern sichert lokal. Wie viele Speicherungen warten, steht im Kasten Wo die Daten liegen.", hl: "#btn-save" },
    { view: "data", text: "Ist die Verbindung zurück, holt Aktualisieren die Änderungen und schickt auch die wartenden Speicherungen. Zum Probieren oben Zustand simulieren wählen.", hl: "#sim", before() { S.storageState = "offline"; } },
    { view: "data", text: "Gibt es dabei einen Konflikt, geht es mit D3 weiter. Sonst ist alles aktuell.", hl: "#storage-chip", before() { S.storageState = "saved"; S.pending = 0; } },
  ] });
  FS.flow({ id: "D6", title: "Verlauf und Wiederherstellen", summary: "Nachsehen, wer was geändert hat, und eine Änderung oder einen Stand zurückholen.", steps: [
    { view: "history", text: "Wähle den Umfang: Team, ein Sprint oder eine Datei. Jeder Eintrag zeigt wer, wann, was.", hl: "[data-scope]", before() { S.histScope = { mode: "team", sprint: "2026.22", file: "personen.yaml" }; S.storageState = "saved"; } },
    { view: "history", text: "Diese Änderung zurücknehmen kehrt genau einen Eintrag um, zum Beispiel die FTE von Felix.", hl: "#h-table tbody tr:first-child [data-act=undo]" },
    { view: "history", text: "Diesen Stand wiederherstellen holt den ganzen Zustand nach einem Eintrag. Unten stehen die Tags, etwa 2026.20, als schnelle Ziele.", hl: "[data-act=tag][data-id=\"2026.20\"]" },
    { view: "data", text: "Der Stand liegt als ungespeicherte Änderung bei dir. Erst Speichern macht ihn für das Team gültig.", hl: "#unsaved" },
  ] });
})();
