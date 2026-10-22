// Views: projects (portfolio), project (detail), forecast (always available). Flows F6 and F8.
// Hand-drawn inline SVG with theme tokens only. Derived numbers get a Rechenweg panel.
(function () {
  const D = window.DEMO;
  const esc = FS.esc, ic = FS.icon, fmt = FS.fmt, sum = FS.sum;
  FS.state.project ??= "ss2";
  FS.state.fcTab ??= "forecast";
  FS.state.prognosen ??= [];

  // ---------- extra demo data (own to this file) ----------
  // Contingent split per month (optional) for Self-Service 2.0; other projects only have a total.
  D.projectMonths ??= { ss2: { "2026-09": { b: 8, u: 11 }, "2026-10": { b: 12, u: 20 }, "2026-11": { b: 14, u: 0 }, "2026-12": { b: 14, u: 0 }, "2027-01": { b: 12, u: 0 } } };
  // Product table per sprint: [Standard, Vorgeplant, Geplant, Erledigt, davon Prod geplant, davon Prod erledigt]
  D.productHistory ??= {
    "2026.17": { portal: [14, 13, 14, 15, 3, 3], billing: [8, 9, 8, 8, 1, 1], mobile: [10, 10, 10, 10, 2, 2], platform: [8, 8, 8, 8, 2, 2] },
    "2026.18": { portal: [13, 13, 13, 12, 3, 2], billing: [7, 8, 8, 7, 1, 1], mobile: [9, 9, 9, 8, 2, 2], platform: [7, 7, 7, 8, 1, 2] },
    "2026.19": { portal: [15, 15, 15, 16, 4, 4], billing: [8, 8, 8, 9, 1, 1], mobile: [10, 10, 11, 11, 2, 2], platform: [8, 8, 8, 8, 2, 2] },
    "2026.20": { portal: [12, 12, 12, 13, 3, 3], billing: [7, 7, 7, 7, 1, 1], mobile: [9, 9, 9, 9, 2, 2], platform: [8, 8, 8, 8, 2, 2] },
    "2026.21": { portal: [14, 13, 14, null, 3, null], billing: [8, 9, 8, null, 1, null], mobile: [10, 10, 10, null, 2, null], platform: [8, 8, 8, null, 2, null] },
    "2026.22": { portal: [12, 13, null, null, null, null], billing: [7, 6, null, null, null, null], mobile: [9, 8, null, null, null, null], platform: [7, 8, null, null, null, null] },
  };

  // ---------- helpers ----------
  const dayNum = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / 864e5; };
  const addDays = (iso, n) => new Date((dayNum(iso) + n) * 864e5).toISOString().slice(0, 10);
  const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  const monthLabel = (ym) => `${MONTHS[Number(ym.slice(5)) - 1]} ${ym.slice(2, 4)}`;
  const pd = (pts) => pts / D.rate;
  const rateTxt = () => fmt(D.rate, 2);
  const LIGHT_ORDER = { ok: 0, warn: 1, bad: 2 };
  const LIGHT_TXT = { ok: "im Plan", warn: "knapp", bad: "gefährdet" };
  const est = `<span class="chip fc" title="Aus Punkten umgerechnet, keine gebuchte Zeit">${ic("calculate")}Schätzung</span>`;
  const calcBtn = (kind, id) => `<button class="btn icon ghost" type="button" data-calc="${kind}" data-id="${id || ""}" aria-label="Rechenweg zeigen" title="Rechenweg">${ic("calculate")}</button>`;
  const calcPanel = (title, rows, note) => FS.openPanel(title, `
    <div class="tw"><table class="t"><tbody>${rows.map(([k, v, cls]) => `<tr class="${cls || ""}"><td style="white-space:normal">${k}</td><td class="num">${v}</td></tr>`).join("")}</tbody></table></div>
    ${note ? `<p class="small muted" style="margin:0">${note}</p>` : ""}`);

  function allSprints() {
    const base = D.sprints.slice();
    const fut = base.filter((s) => s.forecast != null);
    const avg = (k) => sum(fut, (s) => s[k]) / fut.length;
    let last = base[base.length - 1];
    for (let k = 26; k <= 30; k++) {
      const start = addDays(last.end, 1);
      last = { id: `2026.${k}`, start, end: addDays(start, 13), days: 10, state: "open", ext: true, forecast: avg("forecast"), low: avg("low"), high: avg("high") };
      base.push(last);
    }
    return base;
  }
  const sprintOfMonth = (s) => s.end.slice(0, 7);

  function projStats(p) {
    // Without tickets the project's plan is the hand-kept amount per sprint; the open scope is a number on the project.
    const none = FS.trk() === "none";
    const ts = none ? D.sprints.filter((s) => s.state !== "past").map((s) => ({ key: "", sprint: s.id, est: FS.projPts(s.id, p.id), status: "Offen", refined: true })).filter((t) => t.est) : D.tickets.filter((t) => t.project === p.id);
    const open = ts.filter((t) => t.status !== "Fertig");
    const plannedPts = sum(open.filter((t) => FS.sprint(t.sprint)), (t) => t.est);
    const donePts = sum(ts.filter((t) => t.status === "Fertig"), (t) => t.est);
    const plannedPD = pd(plannedPts);
    const total = p.usedPD + plannedPD;
    return { ts, plannedPts, donePts, plannedPD, used: p.usedPD, total, left: p.contingentPD - total, remPts: none ? p.restPts ?? 0 : sum(open, (t) => t.est), nOpen: open.length, none };
  }

  function meter(p, st) {
    const max = Math.max(p.contingentPD, st.total) * 1.02 || 1;
    const pct = (v) => (v / max) * 100;
    const overPD = st.total - p.contingentPD;
    return `<div class="pf-meter-wrap"><div class="pf-meter" role="img" aria-label="Verbraucht ${fmt(st.used)} PT, geplant ${fmt(st.plannedPD)} PT von ${fmt(p.contingentPD)} PT">
      <i class="u" style="width:${pct(st.used)}%"></i><i class="p ${overPD > 0 ? "over" : ""}" style="left:${pct(st.used)}%;width:${pct(st.plannedPD)}%"></i><b class="t" style="left:${pct(p.contingentPD)}%" title="Kontingent ${fmt(p.contingentPD)} PT"></b></div>
      <span class="small ${overPD > 0 ? "pf-over" : "muted"}">${overPD > 0 ? `${ic("warning")}${fmt(overPD)} PT über Kontingent` : `${fmt(-overPD)} PT frei`}</span></div>`;
  }

  const STYLE = `<style>
    .pf-scroll { overflow-x: auto; }
    .pf-scroll svg { display: block; width: 100%; height: auto; min-width: 760px; }
    .pf-scroll svg text { font-family: var(--font-ui); fill: var(--text); }
    .pf-scroll svg .d { font-family: var(--font-data); }
    .pf-scroll svg .m { fill: var(--text-muted); }
    .pf-row { cursor: pointer; } .pf-row:hover .pf-bar { fill: var(--primary); fill-opacity: .28; }
    .pf-meter-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 130px; white-space: normal; }
    .pf-table td:nth-child(2) { white-space: normal; min-width: 200px; }
    .pf-meter { position: relative; height: 10px; border-radius: 5px; background: var(--surface-3); }
    .pf-meter .u { position: absolute; top: 0; bottom: 0; left: 0; background: var(--primary); border-radius: 5px 0 0 5px; }
    .pf-meter .p { position: absolute; top: 0; bottom: 0; border: 1.5px dashed var(--forecast); background: var(--forecast-weak); box-sizing: border-box; }
    .pf-meter .p.over { border-color: var(--bad); background: var(--bad-weak); }
    .pf-meter .t { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--text); }
    .pf-over { color: var(--bad); display: inline-flex; align-items: center; gap: 2px; }
    .pf-over .ms { font-size: 14px; }
    .pf-legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 8px; color: var(--text-muted); font-size: 12px; align-items: center; }
    .pf-legend span { display: inline-flex; align-items: center; gap: 6px; }
    .pf-sw { width: 18px; height: 0; border-top: 2px solid var(--primary); display: inline-block; }
    .pf-sw.fc { border-top: 2px dashed var(--forecast); } .pf-sw.wi { border-top: 2px dashed var(--secondary); }
    .pf-sw.bar { height: 10px; width: 18px; border: 1px solid var(--primary); background: var(--primary-weak); border-radius: 2px; }
    .pf-pre { margin: 0; padding: 12px; background: var(--surface-2); border-radius: var(--r-ctl); font: 13px/20px var(--font-data); white-space: pre-wrap; overflow-x: auto; }
    .pf-sub td { background: var(--surface-2); font-weight: 600; }
    .pj-lane .lane-body { overflow-x: auto; } .pj-lane .ticket { min-width: 560px; }
    .pf-form fieldset { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
    .pf-err { color: var(--bad); display: none; align-items: center; gap: 4px; } .pf-err.on { display: flex; }
    .pf-hint { display: flex; gap: 6px; align-items: center; color: var(--text-muted); }
    .pf-big { font: 600 22px/28px var(--font-data); }
    input[type=range].pf-range { width: 100%; accent-color: var(--primary); }
  </style>`;

  // diamond with a glyph so the traffic light never relies on colour alone
  function diamond(x, y, light, title) {
    const col = `var(--${light})`;
    const g = { ok: `<path d="M${x - 3.5} ${y + .5}l2.5 2.5l5-5"/>`, warn: `<path d="M${x} ${y - 3.5}v4"/><circle cx="${x}" cy="${y + 3.4}" r=".6"/>`, bad: `<path d="M${x - 3} ${y - 3}l6 6M${x + 3} ${y - 3}l-6 6"/>` }[light];
    return `<g><title>${esc(title)}</title><path d="M${x} ${y - 9}L${x + 9} ${y}L${x} ${y + 9}L${x - 9} ${y}Z" style="fill:${col};stroke:var(--surface);stroke-width:1.5"/><g style="stroke:var(--surface);stroke-width:1.8;fill:var(--surface);stroke-linecap:round;stroke-linejoin:round">${g}</g></g>`;
  }

  // ---------- portfolio timeline ----------
  // Labels left of the bars never run into the plot: they wrap inside the label column and the row grows.
  const wrap = (items, n) => items.reduce((ls, it) => { const last = ls[ls.length - 1]; if (last && last.len + 2 + it.len <= n) { last.items.push(it); last.len += 2 + it.len; } else ls.push({ items: [it], len: it.len }); return ls; }, []);
  // Visible window: from the start of the running sprint to N months after today, or to the last project end.
  const TL_RANGES = [["2", "2 Monate"], ["3", "3 Monate"], ["6", "6 Monate"], ["all", "Bis Projektende"]];
  const addMonths = (iso, n) => { const [y, m, d] = iso.split("-").map(Number); const t = new Date(Date.UTC(y, m - 1 + n, d)); return t.toISOString().slice(0, 10); };
  function tlWindow() {
    const r = FS.state.tlRange ?? "all", cur = D.sprints.find((sp) => sp.start <= D.today && D.today <= sp.end) || D.sprints[0];
    const lastEnd = D.projects.reduce((a, p) => [p.end, ...p.milestones.map((m) => m.date)].reduce((b, d) => (d > b ? d : b), a), D.today);
    const from = cur.start, to = r === "custom" ? FS.state.tlTo : r === "all" ? addDays(lastEnd, 3) : addMonths(D.today, Number(r));
    return { r, from, to: to > addDays(from, 14) ? to : addDays(from, 14) };
  }
  // Sprint bands: known sprints, then the regular cadence continued so long windows still show sprints.
  function tlSprints(to) {
    const out = D.sprints.map((sp) => ({ id: sp.id, start: sp.start, end: sp.end }));
    let last = out[out.length - 1];
    while (last.end < to) { const [y, n] = last.id.split(".").map(Number); last = { id: `${y}.${String(n + 1).padStart(2, "0")}`, start: addDays(last.end, 1), end: addDays(last.end, 14), ext: true }; out.push(last); }
    return out;
  }
  function timelineSvg() {
    const W = 960, L = 210, R = 20, T = 48, rowH = 58, plotW = W - L - R;
    const win = tlWindow(), t0 = dayNum(win.from), t1 = dayNum(win.to), inWin = (iso) => iso >= win.from && iso <= win.to;
    const x = (iso) => L + ((dayNum(iso) - t0) / (t1 - t0)) * plotW;
    const NAME_CH = Math.floor((L - 20) / 8), SUB_CH = Math.floor((L - 20) / 6.6);
    const lab = D.projects.map((p) => {
      const name = wrap(p.name.split(" ").map((w) => ({ t: w, len: w.length })), NAME_CH).map((l) => l.items.map((i) => i.t).join(" "));
      const prods = wrap(p.products.map((id) => { const pr = FS.product(id); return { pr, len: pr.name.length + 2 }; }), SUB_CH);
      // milestone labels: centred under the diamond (right-aligned near the edge); a label that would touch the
      // previous one in its line moves to the next line, so nothing overlaps at any zoom level
      const ends = [], ms = p.milestones.filter((m) => inWin(m.date)).sort((a, b) => (a.date < b.date ? -1 : 1)).map((m) => {
        const mx = Math.min(x(m.date), W - R - 9), w = (m.name.length + 9) * 6.7, anchor = mx + w / 2 > W - R ? "end" : "middle";
        const a0 = anchor === "end" ? mx + 9 - w : mx - w / 2, a1 = a0 + w;
        let line = ends.findIndex((e) => e + 10 < a0); if (line < 0) { line = ends.length; ends.push(a1); } else ends[line] = a1;
        return { m, mx, anchor, line };
      });
      return { name, prods, ms, h: Math.max(rowH + Math.max(0, ends.length - 1) * 14, 14 + name.length * 16 + prods.length * 14 + 14) };
    });
    const Y0 = lab.reduce((a, l, i) => (a.push(i ? a[i - 1] + lab[i - 1].h : T), a), []);
    const H = T + sum(lab, (l) => l.h) + 14;
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Zeitachse der Projekte von ${FS.fmtDate(win.from)} bis ${FS.fmtDate(win.to)} mit Meilensteinen und Ampel">`;
    const sps = tlSprints(win.to).filter((sp) => sp.end >= win.from && sp.start <= win.to), every = Math.ceil(62 / (plotW * 14 / (t1 - t0)));
    sps.forEach((sp, i) => {
      const x0 = Math.max(L, x(sp.start)), x1 = Math.min(W - R, x(addDays(sp.end, 1)));
      s += `<rect x="${x0}" y="${T - 6}" width="${x1 - x0}" height="${H - T + 2}" style="fill:${i % 2 ? "transparent" : "var(--surface-2)"}"/>${i % every === 0 && (x0 + x1) / 2 + 26 < W ? `<text class="d m" x="${(x0 + x1) / 2}" y="16" font-size="11" text-anchor="middle">${sp.ext ? `<tspan font-style="italic">${sp.id}</tspan>` : sp.id}</text>` : ""}`;
    });
    // month lines; the first label sits at the left edge, later ones only if they do not collide
    const months = []; for (let m = addMonths(win.from.slice(0, 8) + "01", 1); m <= win.to; m = addMonths(m, 1)) months.push(m);
    let lastLx = L + 4 + 44;
    s += `<text class="m" x="${L + 4}" y="36" font-size="11">${monthLabel(win.from.slice(0, 7))}</text>`;
    months.forEach((m) => {
      s += `<line x1="${x(m)}" x2="${x(m)}" y1="22" y2="${H - 8}" style="stroke:var(--border)"/>`;
      if (x(m) + 4 > lastLx + 6 && x(m) + 48 < W) { s += `<text class="m" x="${x(m) + 4}" y="36" font-size="11">${monthLabel(m.slice(0, 7))}</text>`; lastLx = x(m) + 48; }
    });
    D.projects.forEach((p, i) => {
      const y0 = Y0[i], yc = y0 + 20, lb = lab[i];
      const cut = p.end > win.to, xe = Math.min(x(p.end), W - R), later = p.milestones.filter((m) => m.date > win.to);
      s += `<g class="pf-row" data-project="${p.id}" tabindex="0" role="link" aria-label="Projekt ${esc(p.name)} öffnen"><title>${esc(p.name)}: Ende ${FS.fmtDate(p.end)}</title>
        <line x1="8" x2="${W - R}" y1="${y0 + lb.h - 6}" y2="${y0 + lb.h - 6}" style="stroke:var(--border)"/>
        ${lb.name.map((t, k) => `<text x="8" y="${yc - 2 + k * 16}" font-size="13" font-weight="600">${esc(t)}</text>`).join("")}${lb.prods.map((l, k) => `<text class="m" x="8" y="${yc + 14 + (lb.name.length - 1) * 16 + k * 14}" font-size="11">${l.items.map((it) => `<tspan style="fill:${it.pr.color}">●</tspan> ${esc(it.pr.name)}`).join("  ")}</text>`).join("")}
        <rect class="pf-bar" x="${L}" y="${yc - 7}" width="${xe - L}" height="14" rx="3" style="fill:var(--primary-weak);stroke:var(--primary);stroke-width:1.5"/>
        ${cut ? `<path d="M${xe - 2} ${yc - 9}l8 9l-8 9" style="fill:none;stroke:var(--primary);stroke-width:2.5;stroke-linejoin:round"/>` : `<line x1="${xe}" x2="${xe}" y1="${yc - 11}" y2="${yc + 11}" style="stroke:var(--primary);stroke-width:2.5"/>`}
        ${later.length ? `<text class="m" font-size="11" x="${W - R}" y="${yc - 14}" text-anchor="end" style="paint-order:stroke;stroke:var(--surface);stroke-width:4px">${cut ? `Ende ${FS.fmtDate(p.end)}, ` : ""}${later.length === 1 ? "1 Meilenstein" : `${later.length} Meilensteine`} danach</text>` : cut ? `<text class="m" font-size="11" x="${W - R}" y="${yc - 14}" text-anchor="end" style="paint-order:stroke;stroke:var(--surface);stroke-width:4px">Ende ${FS.fmtDate(p.end)}</text>` : ""}`;
      lb.ms.forEach(({ m, mx, anchor, line }) => {
        s += diamond(mx, yc, m.light, `${m.name}, ${FS.fmtDate(m.date)}: ${LIGHT_TXT[m.light]}`);
        s += `<text font-size="11" x="${anchor === "end" ? mx + 9 : mx}" y="${yc + 27 + line * 14}" text-anchor="${anchor}">${esc(m.name)} <tspan class="d m">${FS.fmtDate(m.date)}</tspan></text>`;
      });
      s += `</g>`;
    });
    const tx = x(D.today);
    s += `<line x1="${tx}" x2="${tx}" y1="40" y2="${H - 8}" style="stroke:var(--highlight);stroke-width:2.5"/><rect x="${tx - 30}" y="${H - 8}" width="60" height="0"/>`;
    s += `<text class="d" x="${tx + 5}" y="${T - 10 + 12}" font-size="11" font-weight="600" style="paint-order:stroke;stroke:var(--surface);stroke-width:3px">heute ${FS.fmtDate(D.today).slice(0, 5)}</text>`;
    return s + `</svg>`;
  }

  // ---------- conflict analysis (recommendations only) ----------
  function conflictData() {
    const sid = D.productPlan[FS.state.sprint] && FS.state.sprint !== "2026.21" ? FS.state.sprint : "2026.22";
    const plan = D.productPlan[sid];
    const rows = D.products.map((pr) => {
      const budget = plan[pr.id].pre;
      const dem = D.projects.map((p) => ({ p, pts: FS.projPts(sid, p.id, pr.id) }));
      const proj = sum(dem, (d) => d.pts);
      const rest = budget - proj;
      const cand = FS.trk() === "none" ? null : D.tickets.filter((t) => t.sprint === sid && t.product === pr.id && t.project).sort((a, b) => LIGHT_ORDER[FS.project(a.project).light] - LIGHT_ORDER[FS.project(b.project).light] || b.rank - a.rank)[0];
      return { pr, budget, dem, proj, rest, light: rest <= 0 ? "bad" : rest <= 2 ? "warn" : "ok", cand: cand && FS.project(cand.project).light !== "bad" ? cand : null, hasProj: proj > 0 };
    });
    return { sid, rows };
  }

  function conflictHtml() {
    const { sid, rows } = conflictData();
    const bad = rows.filter((r) => r.light !== "ok");
    return `<div class="card pf-conflict" style="margin-top:16px">
      <div class="row"><h2 style="margin:0;flex:1">Konfliktansicht: Bedarf, Produktbudget, Kontingent</h2><span class="chip">${ic("event")}Sprint <span class="data">${sid}</span></span></div>
      <p class="muted" style="margin:4px 0 12px">Was die Projekte im Sprint verlangen, gegen das vorgeplante Budget je Produkt und gegen das gebuchte Kontingent. Alles hier ist eine Empfehlung. Das PO entscheidet.</p>
      ${bad.length ? `<div class="banner ${bad.some((r) => r.light === "bad") ? "bad" : "warn"}">${ic("call_split")}<div class="grow"><strong>${bad.length} von ${rows.length} Produkten</strong> haben fast oder gar keinen Platz mehr für Tagesgeschäft, weil Projekte den Sprint füllen.</div></div>` : ""}
      <div class="tw"><table class="t"><thead><tr><th>Produkt</th><th class="num">Budget vorgeplant (Pkt)</th>${D.projects.map((p) => `<th class="num">${esc(p.name)}</th>`).join("")}<th class="num">Rest Tagesgeschäft</th><th>Bewertung</th><th>Empfehlung</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${FS.productChip(r.pr.id)}</td><td class="num">${r.budget}</td>${r.dem.map((d) => `<td class="num">${d.pts || "–"}</td>`).join("")}<td class="num"><strong>${r.rest}</strong></td>
        <td>${r.light === "ok" ? FS.lightChip("ok", "Platz vorhanden") : r.light === "warn" ? FS.lightChip("warn", "knapp") : FS.lightChip("bad", "kein Platz")}</td>
        <td style="white-space:normal;min-width:260px" class="small">${r.light === "ok" ? "Keine Maßnahme nötig." : r.cand ? `${FS.keyLink(r.cand)} (${esc(FS.project(r.cand.project).name)}, Ampel ${LIGHT_TXT[FS.project(r.cand.project).light]}) um einen Sprint verschieben schafft ${r.cand.est} Punkte Platz.` : (FS.trk() === "none" ? "Einen Projektbetrag in einen späteren Sprint schieben oder mit der Projektleitung sprechen." : "Alle Projekte mit Ticket hier sind gefährdet. Mit der Projektleitung sprechen.")}</td></tr>`).join("")}</tbody></table></div>
      <h2 style="margin:16px 0 8px">Kontingent der Projekte</h2>
      <div class="tw"><table class="t"><thead><tr><th>Projekt</th><th class="num">Rest im Kontingent (PT)</th><th class="num">Bedarf ab ${sid} (PT)</th><th>Bewertung</th></tr></thead><tbody>
      ${D.projects.map((p) => { const st = projStats(p); const rest = p.contingentPD - p.usedPD; const need = st.plannedPD; const l = need > rest ? "bad" : need > rest * 0.8 ? "warn" : "ok";
        return `<tr><td><a href="#project" data-project="${p.id}">${esc(p.name)}</a></td><td class="num">${fmt(rest)}</td><td class="num">${fmt(need, 1)} ${calcBtn("proj", p.id)}</td><td>${l === "ok" ? FS.lightChip("ok", "reicht") : l === "warn" ? FS.lightChip("warn", "reicht knapp") : FS.lightChip("bad", `${fmt(need - rest, 1)} PT zu wenig`)}</td></tr>`; }).join("")}
      </tbody></table></div>
      <div class="banner info" style="margin:16px 0 0">${ic("gavel")}<div class="grow"><strong>PO entscheidet.</strong> Foresprint ändert hier nichts. Mögliche Wege:
        <div class="row" style="margin-top:8px">${FS.trk() === "none" ? `<button class="btn" type="button" data-decide="Beträge verschieben">${ic("event_repeat")}Beträge verschieben</button>` : `<button class="btn" type="button" data-decide="Tickets verschieben">${ic("event_repeat")}Tickets verschieben</button>`}<button class="btn" type="button" data-decide="Risiko akzeptieren">${ic("warning")}Risiko akzeptieren</button><button class="btn" type="button" data-decide="Mit Projektleitung sprechen">${ic("forum")}Mit Projektleitung sprechen</button><a class="btn" href="#preplan">${ic("low_priority")}Zum Vorplanen</a></div></div></div></div>`;
  }

  // ---------- projects view ----------
  function projectsRender() {
    const light = D.projects.filter((p) => p.light !== "ok").length;
    return `${STYLE}
    <div class="page-head"><div><h1>Projekte</h1><p class="lead">Alle Projekte auf einer Zeitachse, mit Meilensteinen, Ampel und Kontingent. Projekte und Meilensteine pflegen Sie hier selbst, auch ohne ${D.team.tracker} und offline.</p></div>
      <div class="actions"><button class="btn primary" type="button" id="pf-new">${ic("add")}Neues Projekt</button></div></div>
    ${light ? `<div class="banner warn">${ic("flag")}<div class="grow"><strong>${light} von ${D.projects.length} Projekten</strong> sind knapp oder gefährdet. Details in der Tabelle und in der Konfliktansicht darunter.</div></div>` : ""}
    <div class="card pf-timeline"><div class="row" style="margin-bottom:8px"><h2 style="margin:0;flex:1">Zeitachse</h2>
      <div class="row" id="pf-range" role="group" aria-label="Sichtbarer Zeitraum" style="gap:6px"><span class="small muted">Zeitraum</span>${TL_RANGES.map(([k, l]) => `<button type="button" class="chip filter ${tlWindow().r === k ? "on" : ""}" data-tl="${k}" aria-pressed="${tlWindow().r === k}">${l}</button>`).join("")}<label class="small muted" for="pf-to">bis</label><input class="input data" type="date" id="pf-to" value="${tlWindow().to}" min="${addDays(D.today, 14)}" style="width:150px" aria-label="Zeitachse bis Datum"></div></div>
      <p class="small muted" style="margin:0 0 8px">${FS.fmtDate(tlWindow().from)} bis ${FS.fmtDate(tlWindow().to)}. Kursive Sprints sind im Kalender noch nicht angelegt und folgen dem üblichen Takt. Die Wahl gilt nur für dich und bleibt beim nächsten Start erhalten.</p>
      <div class="pf-scroll">${timelineSvg()}</div>
      <div class="pf-legend"><span><i class="pf-sw bar"></i>Laufzeit bis Ende</span><span>${ic("check_circle")}Meilenstein im Plan</span><span>${ic("error")}knapp</span><span>${ic("cancel")}gefährdet</span><span><i class="pf-sw" style="border-color:var(--highlight);border-top-width:3px"></i>heute</span><span>Klick auf eine Zeile öffnet das Projekt</span></div></div>
    <h2 style="margin:24px 0 8px">${FS.multiProduct() ? "Kontingent und Produkte" : "Kontingent"}</h2>
    <div class="tw pf-table"><table class="t"><thead><tr><th>Projekt</th><th class="only-multiprod">Produkte</th><th>Ende</th><th>Ampel</th><th class="num">gebucht (PT)</th><th class="num">verbraucht (PT)</th><th class="num">geplant (PT)</th><th>Verbrauch</th></tr></thead><tbody>
      ${D.projects.map((p) => { const st = projStats(p); return `<tr><td><span class="row" style="flex-wrap:nowrap;gap:4px"><a href="#project" data-project="${p.id}"><strong>${esc(p.name)}</strong></a><button class="btn icon ghost" type="button" data-pjclose="${p.id}" aria-label="${esc(p.name)} ${projHasHistory(p) ? "abschließen" : "löschen"}" title="${projHasHistory(p) ? "Abschließen (Verlauf bleibt)" : "Löschen"}">${ic(projHasHistory(p) ? "archive" : "delete")}</button></span></td><td class="only-multiprod">${p.products.map(FS.productChip).join(" ")}</td><td class="data">${FS.fmtDate(p.end)}</td><td>${FS.lightChip(p.light)}</td>
        <td class="num">${fmt(p.contingentPD)}</td><td class="num">${fmt(st.used)}</td><td class="num">${fmt(st.plannedPD, 1)} ${calcBtn("proj", p.id)}</td><td>${meter(p, st)}</td></tr>`; }).join("")}
      <tr class="pf-sub"><td colspan="8">${FS.multiProduct() ? "Tagesgeschäft je Produkt" : "Tagesgeschäft"}, ohne Ampel: Budget aus der Vorplanung, nicht aus einem Projekt</td></tr>
      ${D.products.map((pr) => { const sid = "2026.22"; const budget = pd(D.productPlan[sid][pr.id].pre); const used = pd(sum(D.tickets.filter((t) => t.product === pr.id && !t.project && t.sprint === "2026.21"), (t) => t.est)); const planned = FS.trk() === "none" ? pd(Math.max(0, D.productPlan[sid][pr.id].pre - sum(D.projects, (pj) => FS.projPts(sid, pj.id, pr.id)))) : pd(sum(D.tickets.filter((t) => t.product === pr.id && !t.project && t.sprint === sid), (t) => t.est));
        return `<tr><td>${FS.projectChip(null)}</td><td class="only-multiprod">${FS.productChip(pr.id)}</td><td class="muted">laufend</td><td class="muted">${ic("remove")}keine Ampel</td><td class="num">${fmt(budget, 1)}</td><td class="num">${fmt(used, 1)}</td><td class="num">${fmt(planned, 1)}</td>
          <td><span class="small muted">Budget je Sprint ${sid}; verbraucht = Sprint 2026.21</span></td></tr>`; }).join("")}
    </tbody></table></div>
    <p class="small muted" style="margin:8px 0 0">${est} Geplante und zugeordnete PT sind aus Punkten berechnet: Punkte geteilt durch ${rateTxt()} Punkte je Personentag. Verbraucht und gebucht sind eingetragene PT.</p>
    ${conflictHtml()}
    ${D.closedProjects.length ? `<details class="card" id="pf-closed" style="margin-top:16px"><summary style="cursor:pointer"><strong>Abgeschlossene Projekte</strong> <span class="muted small">${D.closedProjects.length}</span></summary>
      <div class="tw" style="margin-top:8px"><table class="t"><thead><tr><th>Projekt</th><th>Stand</th><th>Ende</th><th class="num">verbraucht (PT)</th><th class="num">von (PT)</th><th></th></tr></thead><tbody>${D.closedProjects.map((x) => `<tr><td>${esc(x.name)}</td><td>${x.closed === "abgebrochen" ? FS.lightChip("warn", "abgebrochen") : FS.lightChip("ok", "abgeschlossen")}</td><td class="data">${FS.fmtDate(x.closedAt)}</td><td class="num">${fmt(x.usedPD)}</td><td class="num">${fmt(x.contingentPD)}</td><td><button class="btn" type="button" data-pjback="${x.id}">${ic("unarchive")}Wieder öffnen</button></td></tr>`).join("")}</tbody></table></div>
      <p class="small muted" style="margin:8px 0 0">Berichte, Protokolle und vergangene Sprints zeigen abgeschlossene Projekte weiter. Ihre Regeln greifen nicht mehr.</p></details>` : ""}`;
  }

  // Removing a project: with history (booked or used PD, tickets) it is closed as finished or cancelled, not deleted.
  // Reports, minutes and past sprints keep it; open tickets go to daily business or another project.
  D.closedProjects ??= [];
  const projHasHistory = (p) => p.usedPD > 0 || D.tickets.some((t) => t.project === p.id);
  function closeProjectPanel(id) {
    const p = FS.project(id), hist = projHasHistory(p), open = D.tickets.filter((t) => t.project === id && t.status !== "Fertig"), unit = FS.trk() === "jira" ? "Tickets" : "Arbeitspakete";
    const el = FS.openPanel(`${p.name} ${hist ? "abschließen" : "löschen"}`, hist ? `<p style="margin:0">${esc(p.name)} hat Verlauf (${fmt(p.usedPD)} von ${fmt(p.contingentPD)} PT verbraucht). Es wird <strong>abgeschlossen, nicht gelöscht</strong>: Berichte, Protokolle und vergangene Sprints behalten es. Abgeschlossene Projekte stehen unten auf der Seite und lassen sich wieder öffnen.</p>
      <fieldset><legend class="small muted" style="padding:0">Wie endet das Projekt?</legend><div class="row"><label class="row" style="gap:6px"><input type="radio" name="pj-how" value="abgeschlossen" checked>abgeschlossen</label><label class="row" style="gap:6px"><input type="radio" name="pj-how" value="abgebrochen">abgebrochen</label></div></fieldset>
      <div class="field"><label for="pj-at">Ende</label><input class="input" id="pj-at" type="date" value="${D.today}" style="max-width:180px"></div>
      ${FS.trk() === "none" ? `<p class="small muted" style="margin:0">Offener Umfang ${fmt(p.restPts ?? 0)} Punkte entfällt. Projektbeträge in künftigen Sprints gehen ans Tagesgeschäft.</p>` : `<div class="field"><label for="pj-to">Offene ${unit} (${open.length}) gehen an</label><select class="input" id="pj-to" style="max-width:280px"><option value="">Tagesgeschäft</option>${D.projects.filter((x) => x.id !== id).map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>`}
      <p class="small muted" style="margin:0">Restkontingent ${fmt(p.contingentPD - p.usedPD)} PT wird im Abschlussbericht ausgewiesen, nicht weiterverplant.</p>
      <div class="row"><button class="btn danger" type="button" id="pj-ok">${ic("archive")}Projekt abschließen</button><button class="btn ghost" type="button" id="pj-cancel">Abbrechen</button></div>`
      : `<p style="margin:0">${esc(p.name)} hat noch keinen Verbrauch und keine ${unit}. Es wird gelöscht.</p><div class="row"><button class="btn danger" type="button" id="pj-ok">${ic("delete")}Löschen</button><button class="btn ghost" type="button" id="pj-cancel">Abbrechen</button></div>`);
    if (!el) return;
    el.querySelector("#pj-cancel").onclick = FS.closePanel;
    el.querySelector("#pj-ok").onclick = () => {
      const how = el.querySelector('[name="pj-how"]:checked')?.value, at = el.querySelector("#pj-at")?.value, to = el.querySelector("#pj-to")?.value || null;
      const snap = { idx: D.projects.indexOf(p), tickets: open.map((t) => t.project) };
      open.forEach((t) => (t.project = to));
      D.projects.splice(snap.idx, 1);
      if (hist) D.closedProjects.push(Object.assign(p, { closed: how, closedAt: at }));
      FS.addUnsaved?.(hist ? `Projekt ${how}: ${p.name}` : `Projekt gelöscht: ${p.name}`, "aktiv", hist ? FS.fmtDate(at) : "–", "projekte.yaml");
      FS.closePanel(); if (location.hash === "#project") location.hash = "projects"; else FS.render();
      FS.toast(`${p.name} ${hist ? how : "gelöscht"}.${open.length && FS.trk() !== "none" ? ` ${open.length} offene ${unit} ${to ? `an ${FS.project(to).name}` : "ins Tagesgeschäft"}.` : ""} Bis Speichern rückgängig.`, () => {
        D.projects.splice(snap.idx, 0, p); const i = D.closedProjects.indexOf(p); if (i >= 0) D.closedProjects.splice(i, 1); delete p.closed; delete p.closedAt; open.forEach((t, k) => (t.project = snap.tickets[k])); FS.render(); });
    };
  }

  function newProjectPanel() {
    const monthsList = ["2026-11", "2026-12", "2027-01"];
    const el = FS.openPanel("Neues Projekt", `
      <form class="stack pf-form" id="np" novalidate>
        <div class="banner info" style="margin:0">${ic("cloud_off")}<div class="grow">Funktioniert ohne ${D.team.tracker} und offline. Das Projekt wird in den Daten des Teams gespeichert, sobald Sie oben auf Speichern klicken.</div></div>
        <div class="field"><label for="np-name">Name</label><input class="input" id="np-name" placeholder="z. B. Neues Partnerportal"></div>
        <fieldset class="only-multiprod"><legend class="small muted" style="padding:0">Produkte (mehrere möglich)</legend><div class="row" id="np-prods">${D.products.map((p) => `<button type="button" class="chip filter" data-prod="${p.id}" aria-pressed="false"><span class="dot" style="background:${p.color}"></span>${esc(p.name)}</button>`).join("")}</div></fieldset>
        <div class="field"><label for="np-end">Enddatum</label><input class="input" id="np-end" type="date" value="2027-03-31"></div>
        <fieldset><legend class="small muted" style="padding:0">Meilensteine (Datum, Tickets optional)</legend><div class="stack" id="np-ms"></div><div><button class="btn" type="button" id="np-addms">${ic("add")}Meilenstein</button></div></fieldset>
        <div class="field"><label for="np-pd">Kontingent gesamt (Personentage)</label><input class="input data" id="np-pd" type="number" min="0" step="1" value="40" style="max-width:140px"></div>
        <details><summary style="cursor:pointer">Aufteilung pro Monat (optional)</summary><div class="stack" style="margin-top:8px">${monthsList.map((m) => `<div class="row"><label class="muted" style="width:72px" for="np-m-${m}">${monthLabel(m)}</label><input class="input data" id="np-m-${m}" data-month="${m}" type="number" min="0" style="width:96px" placeholder="PT"></div>`).join("")}<span class="small muted">Leer lassen, wenn nur das Gesamtkontingent gebucht ist.</span></div></details>
        <div class="field"><label for="np-rule">Regel aus ${D.team.tracker} (optional)</label><input class="input data" id="np-rule" placeholder='z. B. epic = "SSV-12" OR label = "self-service"'><span class="small muted">Ohne Regel ordnen Sie Tickets und Arbeitspunkte von Hand zu.</span></div>
        <div class="field"><label for="np-note">Notiz</label><textarea class="input" id="np-note" rows="2" placeholder="z. B. Ansprechpartner, Absprachen"></textarea></div>
        <div class="pf-err" id="np-err" role="alert">${ic("error")}<span></span></div>
        <div class="row"><button class="btn primary" type="submit">${ic("check")}Projekt anlegen</button><button class="btn ghost" type="button" id="np-cancel">Abbrechen</button></div>
      </form>`);
    const msBox = el.querySelector("#np-ms");
    const addMs = (n = "", d = "") => { const r = document.createElement("div"); r.className = "row"; r.innerHTML = `<input class="input" placeholder="Name" value="${esc(n)}" style="flex:1;min-width:120px" aria-label="Meilenstein Name"><input class="input data" type="date" value="${d}" aria-label="Meilenstein Datum"><button class="btn icon ghost" type="button" aria-label="Meilenstein entfernen">${ic("close")}</button>`; r.querySelector("button").onclick = () => r.remove(); msBox.appendChild(r); };
    addMs("Erste Lieferung", "2026-12-18");
    el.querySelector("#np-addms").onclick = () => addMs();
    el.querySelectorAll("[data-prod]").forEach((b) => (b.onclick = () => { const on = !b.classList.contains("on"); b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); }));
    el.querySelector("#np-cancel").onclick = FS.closePanel;
    el.querySelector("#np").onsubmit = (e) => {
      e.preventDefault();
      const name = el.querySelector("#np-name").value.trim();
      const products = FS.multiProduct() ? [...el.querySelectorAll("[data-prod].on")].map((b) => b.dataset.prod) : [D.products[0].id];
      const end = el.querySelector("#np-end").value;
      const err = el.querySelector("#np-err");
      const msg = !name ? "Bitte einen Namen eingeben." : !products.length ? "Bitte mindestens ein Produkt wählen." : !end ? "Bitte ein Enddatum wählen." : "";
      err.classList.toggle("on", !!msg); err.querySelector("span").textContent = msg;
      if (msg) return;
      const months = {};
      el.querySelectorAll("[data-month]").forEach((i) => { if (i.value) months[i.dataset.month] = { b: Number(i.value), u: 0 }; });
      const id = "p" + (D.projects.length + 1);
      const milestones = [...msBox.children].map((r) => { const [n, d] = r.querySelectorAll("input"); return { name: n.value.trim() || "Meilenstein", date: d.value || end, tickets: 0, done: 0, light: "ok" }; });
      D.projects.push({ id, name, products, end, lead: "Noch offen", contingentPD: Number(el.querySelector("#np-pd").value) || 0, usedPD: 0, plannedPD: 0, light: "ok", milestones, rule: el.querySelector("#np-rule").value.trim(), note: el.querySelector("#np-note").value.trim() });
      if (Object.keys(months).length) D.projectMonths[id] = months;
      FS.state.storageState = "incoming";
      FS.closePanel(); FS.render();
      FS.toast(`Projekt "${esc(name)}" lokal angelegt. Speichern macht es für das Team sichtbar.`);
    };
  }

  function openProject(id) { FS.state.project = id; if (location.hash === "#project") FS.render(); else location.hash = "project"; }

  function wireCommon(main) {
    main.querySelectorAll("[data-project]").forEach((el) => {
      el.addEventListener("click", (e) => { e.preventDefault(); openProject(el.dataset.project); });
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); openProject(el.dataset.project); } });
    });
    main.querySelectorAll("[data-calc]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); calcFor(b.dataset.calc, b.dataset.id); }));
  }

  function calcFor(kind, id) {
    if (kind === "proj") {
      const p = FS.project(id), st = projStats(p);
      calcPanel(`Rechenweg: geplant, ${esc(p.name)}`, [
        [`Vorgemerkte Punkte (${st.ts.filter((t) => FS.sprint(t.sprint) && t.status !== "Fertig").length} Tickets)`, `<span class="data">${fmt(st.plannedPts)} Pkt</span>`],
        ["Rate aus der normierten Velocity", `<span class="data">${rateTxt()} Pkt je PT</span>`],
        ["Geplant = Punkte geteilt durch Rate", `<span class="data">${fmt(st.plannedPD, 1)} PT</span>`],
        ["Verbraucht bis heute (eingetragen)", `<span class="data">${fmt(st.used)} PT</span>`],
        ["Verbraucht plus geplant", `<span class="data">${fmt(st.total, 1)} PT</span>`, "sum"],
        [`Kontingent gebucht`, `<span class="data">${fmt(p.contingentPD)} PT</span>`],
      ], "Der Wert ist eine Schätzung: Punkte sind keine Personentage. Ein Sprint nutzt die Rate seiner Forecast-Daten, Erledigtes die Rate des abgeschlossenen Sprints.");
    } else if (kind === "fc") {
      const s = FS.sprint(id);
      calcPanel(`Rechenweg: Forecast PLAN ${s.id}`, [
        ["Kapazität aus Personen, FTE, Abwesenheiten", `<span class="data">${fmt(s.capacityPD)} PT</span>`],
        ["Rate: Mittel der letzten 4 Sprints (Velocity je verfügbarem PT)", `<span class="data">${rateTxt()} Pkt/PT</span>`],
        ["Forecast PLAN = Kapazität mal Rate", `<span class="data">${fmt(s.capacityPD * D.rate, 1)} Pkt</span>`],
        ["Angezeigt (gerundet)", `<span class="data">${fmt(s.forecast)} Pkt</span>`, "sum"],
        ["Spanne aus Streuung der letzten 4 Sprints", `<span class="data">${fmt(s.low)} bis ${fmt(s.high)} Pkt</span>`],
      ], s.absences === "unknown" ? "Für diesen Sprint sind noch keine Abwesenheiten erfasst. Der Forecast rechnet mit voller Kapazität." : "");
    }
  }

  FS.view("projects", {
    title: "Projekte",
    render: projectsRender,
    wire(main) {
      wireCommon(main);
      main.querySelector("#pf-new").onclick = newProjectPanel;
      main.querySelectorAll("[data-pjclose]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); closeProjectPanel(b.dataset.pjclose); }));
      main.querySelectorAll("[data-pjback]").forEach((b) => (b.onclick = () => { const i = D.closedProjects.findIndex((x) => x.id === b.dataset.pjback), x = D.closedProjects.splice(i, 1)[0]; delete x.closed; delete x.closedAt; D.projects.push(x); FS.addUnsaved?.(`Projekt wieder geöffnet: ${x.name}`, "abgeschlossen", "aktiv", "projekte.yaml"); FS.render(); FS.toast(`${x.name} ist wieder offen. Enddatum und Kontingent prüfen.`); }));
      main.querySelectorAll("[data-tl]").forEach((b) => (b.onclick = () => { FS.state.tlRange = b.dataset.tl; FS.render(); }));
      main.querySelector("#pf-to").onchange = (e) => { if (e.target.value) { FS.state.tlRange = "custom"; FS.state.tlTo = e.target.value; FS.render(); } };
      main.querySelectorAll("[data-decide]").forEach((b) => (b.onclick = () => FS.toast(`"${b.dataset.decide}" notiert. Die Entscheidung bleibt beim PO, Foresprint ändert nichts am Plan.`)));
    },
  });

  // ---------- project detail ----------
  function projectRender() {
    const p = FS.project(FS.state.project) || D.projects[0];
    FS.state.project = p.id;
    const st = projStats(p);
    const months = D.projectMonths[p.id];
    const sprints = D.sprints.filter((s) => s.state !== "past");
    const nextMs = p.milestones.filter((m) => m.date >= D.today).sort((a, b) => a.date.localeCompare(b.date))[0];
    const perSprint = (s) => {
      const ts = st.ts.filter((t) => t.sprint === s.id);
      const booked = months ? (months[sprintOfMonth(s)] ? months[sprintOfMonth(s)].b / 2 : 0) : p.contingentPD / 9;
      return { s, ts, booked, planned: pd(sum(ts.filter((t) => t.status !== "Fertig"), (t) => t.est)), done: pd(sum(ts.filter((t) => t.status === "Fertig"), (t) => t.est)) };
    };
    const rep = sprints.map(perSprint);
    const noSprint = st.ts.filter((t) => !FS.sprint(t.sprint));
    const monthRows = months && Object.keys(months).sort().map((ym) => {
      const planned = pd(sum(sprints.filter((s) => sprintOfMonth(s) === ym), (s) => sum(st.ts.filter((t) => t.sprint === s.id && t.status !== "Fertig"), (t) => t.est)));
      const m = months[ym]; return { ym, b: m.b, u: m.u, planned, rest: m.b - m.u - planned };
    });
    return `${STYLE}
    <div class="page-head"><div><div class="small muted"><a href="#projects">Projekte</a> / Projekt</div><h1>${esc(p.name)} ${FS.lightChip(p.light)}</h1>
      <p class="lead">Ansprechpartner: ${esc(p.lead)}. Ende <span class="data">${FS.fmtDate(p.end)}</span>.<span class="only-jira">${p.rule ? ` Regel: <span class="data rule-txt">${esc(p.rule)}</span>` : ` Ohne Regel: Tickets ordnen Sie von Hand zu.`} <button class="link" type="button" id="pj-rule">${p.rule ? "Regel bearbeiten" : "Regel anlegen"}</button></span></p></div>
      <div class="actions"><select class="input" id="pj-pick" aria-label="Projekt wechseln">${D.projects.map((x) => `<option value="${x.id}" ${x.id === p.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
        <button class="btn" type="button" id="pj-edit">${ic("edit")}Bearbeiten</button><button class="btn" type="button" id="pj-close">${ic(projHasHistory(p) ? "archive" : "delete")}${projHasHistory(p) ? "Abschließen" : "Löschen"}</button></div></div>
    <div class="grid cols-3">
      <div class="card"><div class="only-multiprod"><div class="small muted">Produkte</div><div class="row" style="margin-top:6px">${p.products.map(FS.productChip).join("")}</div></div>
        <div class="small muted" style="margin-top:12px">Nächster Meilenstein</div><div style="margin-top:4px">${nextMs ? `${esc(nextMs.name)} <span class="data">${FS.fmtDate(nextMs.date)}</span> ${FS.lightChip(nextMs.light)}` : "keiner mehr"}</div></div>
      <div class="card"><div class="row"><div class="small muted" style="flex:1">Kontingent (PT)</div>${est}${calcBtn("proj", p.id)}</div>
        <div class="pf-big" style="margin:4px 0 8px">${fmt(st.total, 1)} <span class="muted" style="font-size:14px">von ${fmt(p.contingentPD)}</span></div>${meter(p, st)}
        <div class="small muted" style="margin-top:8px">verbraucht <span class="data">${fmt(st.used)}</span>, geplant <span class="data">${fmt(st.plannedPD, 1)}</span></div></div>
      <div class="card"><div class="small muted">Offener Umfang</div>${st.none ? `<div class="row" style="margin:4px 0"><input class="input data" id="pj-rest" inputmode="numeric" value="${fmt(st.remPts)}" aria-label="Offener Umfang in Punkten" style="width:96px;text-align:right;font-size:20px"><span class="muted">Punkte</span></div>
        <div class="small muted">Ohne Tickets von Hand gepflegt, zum Beispiel nach jedem Review.</div>` : `<div class="pf-big" style="margin:4px 0">${fmt(st.remPts)} <span class="muted" style="font-size:14px">Punkte, ${st.nOpen} Tickets</span></div>
        <div class="small muted">${st.ts.filter((t) => !t.refined).length} noch nicht refined, ${noSprint.length} nicht vorgemerkt</div>`}<div style="margin-top:8px"><a href="#forecast" id="pj-when">${ic("insights")}Wann ist es fertig?</a></div></div>
    </div>
    <div class="grid cols-2" style="margin-top:16px">
      <div class="card"><h2>Meilensteine</h2><div class="tw"><table class="t"><thead><tr><th>Meilenstein</th><th>Datum</th><th class="num need-tickets">Tickets</th><th>Ampel</th></tr></thead><tbody>
        ${p.milestones.map((m) => `<tr><td>${esc(m.name)}</td><td class="data">${FS.fmtDate(m.date)}</td><td class="num need-tickets">${m.tickets ? `${m.done} von ${m.tickets} fertig` : "–"}</td><td>${FS.lightChip(m.light)}${m.tickets ? "" : `<div class="small muted">von Hand gesetzt</div>`}</td></tr>`).join("")}</tbody></table></div>
        <p class="small muted" style="margin:8px 0">Mit zugeordneten Tickets bekommt ein Meilenstein eine eigene Ampel aus dem Stand der Tickets, ohne Tickets setzen Sie sie von Hand.</p>
        <button class="btn" type="button" data-toast="Meilenstein-Formular würde sich öffnen (Mockup).">${ic("add")}Meilenstein hinzufügen</button></div>
      <div class="card"><h2>Kontingent pro Monat</h2>${monthRows ? `<div class="tw"><table class="t"><thead><tr><th>Monat</th><th class="num">gebucht</th><th class="num">verbraucht</th><th class="num">geplant ${ic("calculate")}</th><th class="num">Rest</th></tr></thead><tbody>
        ${monthRows.map((r) => `<tr><td>${monthLabel(r.ym)}</td><td class="num">${fmt(r.b)}</td><td class="num">${fmt(r.u)}</td><td class="num">${fmt(r.planned, 1)}</td><td class="num">${r.rest < -0.05 ? `<span class="pf-over">${ic("warning")}${fmt(r.rest, 1)}</span>` : fmt(r.rest, 1)}</td></tr>`).join("")}
        <tr class="sum"><td>Summe</td><td class="num">${fmt(sum(monthRows, (r) => r.b))}</td><td class="num">${fmt(sum(monthRows, (r) => r.u))}</td><td class="num">${fmt(sum(monthRows, (r) => r.planned), 1)}</td><td class="num">${fmt(sum(monthRows, (r) => r.rest), 1)}</td></tr></tbody></table></div>
        <p class="small muted" style="margin:8px 0 0">Alle Werte in Personentagen. Geplant ist geschätzt (Punkte durch ${rateTxt()}), zugeordnet nach Sprintende. Frühe Monate sind überbucht, später ist noch Platz: ein Hinweis, Tickets zu verschieben.</p>`
        : `<div class="banner" style="margin:0">${ic("info")}<div class="grow">Nur ein Gesamtkontingent von <span class="data">${fmt(p.contingentPD)} PT</span> gebucht, keine Aufteilung pro Monat. Das ist erlaubt.</div></div><div style="margin-top:8px"><button class="btn" type="button" data-toast="Monatsaufteilung würde sich öffnen (Mockup).">${ic("add")}Aufteilung pro Monat anlegen</button></div>`}</div>
    </div>
    <div class="pj-tickets need-tickets" style="margin-top:24px"><h2>Tickets nach Sprint</h2>
      ${st.ts.length ? [...sprints.map((s) => [s.id, st.ts.filter((t) => t.sprint === s.id)]), ["offen", noSprint]].filter(([, l]) => l.length).map(([id, l]) => `
        <div class="lane pj-lane" style="margin-bottom:12px"><div class="lane-head"><div class="row"><strong>${id === "offen" ? "Nicht vorgemerkt" : `Sprint <span class="data">${id}</span>`}</strong>${id !== "offen" && FS.sprint(id).state === "current" ? `<span class="chip">läuft</span>` : ""}<span class="muted small">${l.length} Tickets, <span class="data">${sum(l, (t) => t.est)}</span> Punkte, etwa <span class="data">${fmt(pd(sum(l, (t) => t.est)), 1)}</span> PT</span></div></div>
        <div class="lane-body">${l.map((t) => FS.ticketRow(t, { noProject: true })).join("")}</div></div>`).join("")
        : `<div class="banner info">${ic("info")}<div class="grow">Noch keine Tickets zugeordnet. Ohne ${D.team.tracker} ordnen Sie Tickets und Arbeitspunkte im Backlog von Hand zu.</div></div>`}</div>
    <div class="card pj-report" style="margin-top:24px"><div class="row"><h2 style="margin:0;flex:1">Bericht für die Projektleitung</h2><button class="btn primary" type="button" id="pj-export">${ic("ios_share")}Bericht exportieren</button></div>
      <p style="margin:8px 0 12px">Stand ${FS.fmtDate(D.today)}: <span class="data">${fmt(st.used)}</span> von <span class="data">${fmt(p.contingentPD)}</span> PT verbraucht, weitere <span class="data">${fmt(st.plannedPD, 1)}</span> PT geplant (Schätzung). ${nextMs ? `Nächster Meilenstein "${esc(nextMs.name)}" am ${FS.fmtDate(nextMs.date)}, Ampel ${LIGHT_TXT[nextMs.light]}.` : ""}</p>
      <div class="tw"><table class="t"><thead><tr><th>Sprint</th><th class="num">gebucht (PT)</th><th class="num">geplant (PT)</th><th class="num">erledigt (PT)</th><th>Verhältnis</th></tr></thead><tbody>
        ${rep.map((r) => { const over = r.planned + r.done > r.booked + 0.05; return `<tr><td><span class="data">${r.s.id}</span> ${r.s.state === "current" ? `<span class="chip">läuft</span>` : ""}</td><td class="num">${fmt(r.booked, 1)}</td><td class="num">${fmt(r.planned, 1)}</td><td class="num">${fmt(r.done, 1)}</td>
          <td>${r.booked + r.planned + r.done === 0 ? `<span class="muted">nichts</span>` : over ? `<span class="pf-over">${ic("warning")}${fmt(r.planned + r.done - r.booked, 1)} PT über gebucht</span>` : `<span class="muted">${fmt(r.booked - r.planned - r.done, 1)} PT frei</span>`}</td></tr>`; }).join("")}
        <tr class="sum"><td>Summe</td><td class="num">${fmt(sum(rep, (r) => r.booked), 1)}</td><td class="num">${fmt(sum(rep, (r) => r.planned), 1)}</td><td class="num">${fmt(sum(rep, (r) => r.done), 1)}</td><td></td></tr></tbody></table></div>
      <p class="small muted" style="margin:8px 0 0">${est} Gebucht je Sprint: halber Monatswert${months ? "" : " (ohne Monatsaufteilung gleichmäßig verteilt)"}. Geplant und erledigt: Punkte durch ${rateTxt()}. Bisher verbraucht (eingetragen) steht oben.</p></div>`;
  }

  FS.view("project", {
    title: "Projekt",
    render: projectRender,
    wire(main) {
      document.querySelector('[data-nav="projects"]')?.classList.add("active");
      wireCommon(main);
      const rs = main.querySelector("#pj-rest"); if (rs) rs.onchange = () => { const p = FS.project(FS.state.project) || D.projects[0], v = parseInt(rs.value, 10); p.restPts = isNaN(v) ? 0 : Math.max(0, v); FS.render(); };
      main.querySelector("#pj-pick").onchange = (e) => { FS.state.project = e.target.value; FS.render(); };
      main.querySelector("#pj-edit").onclick = () => { newProjectPanel(); };
      main.querySelector("#pj-close").onclick = () => closeProjectPanel(FS.state.project);
      main.querySelector("#pj-rule").onclick = () => {
        const p = FS.project(FS.state.project), others = D.projects.map((x) => ({ id: x.id, name: x.name, rule: x.rule }));
        const el = FS.openPanel(`Zuordnungsregel: ${p.name}`, `${FS.ruleEditor("project", p.id, p.rule, others)}
          <p class="small muted" style="margin:0">Dieselbe Regelsprache wie bei Produkten. Passt ein Ticket auf mehrere Projekte, entscheidet die Reihenfolge unter Einstellungen > Team; der Widerspruch erscheint in der Vorschau. Ohne Regel ordnest du Tickets von Hand zu.</p>
          <div class="row"><button class="btn primary" type="button" id="pr-apply">Regel übernehmen</button><button class="btn ghost" type="button" id="pr-cancel">Abbrechen</button></div>`);
        if (!el) return;
        const get = FS.wireRuleEditor(el, others);
        el.querySelector("#pr-cancel").onclick = FS.closePanel;
        el.querySelector("#pr-apply").onclick = () => { const v = get(); try { FS.parseRule(v); } catch (e) { return FS.toast("Regel ist noch unvollständig: " + e.message); } FS.addUnsaved?.(`Regel ${p.name}`, p.rule || "keine", v || "keine", "projekte.yaml"); p.rule = v; FS.render(); FS.toast("Regel übernommen, noch nicht gespeichert."); };
      };
      main.querySelector("#pj-export").onclick = () => FS.toast(`Bericht "${esc(FS.project(FS.state.project).name)}" als Markdown exportiert (im Mockup nur angezeigt).`);
      main.querySelectorAll("[data-toast]").forEach((b) => (b.onclick = () => FS.toast(b.dataset.toast)));
      main.querySelector("#pj-when").onclick = (e) => { e.preventDefault(); FS.state.fcTab = "analyse"; FS.state.anProject = FS.state.project; FS.state.anShare = null; location.hash = "forecast"; };
    },
  });

  // ---------- forecast ----------
  const wi = { sprint: "all", abs: 0, focus: 100, curDone: null };
  const curSp = () => D.sprints.find((s) => s.state === "current");
  function whatIfAlt() {
    const alt = {};
    const kc = wi.curDone != null && curSp() ? FS.rateFactor(curSp().id, wi.curDone) / FS.rateFactor(curSp().id, curSp().plan) : 1;
    if (!wi.abs && wi.focus === 100 && kc === 1) return alt;
    D.sprints.filter((s) => s.forecast != null).forEach((s) => {
      const own = wi.sprint === "all" || wi.sprint === s.id;
      if (!own && kc === 1) return;
      const a = own ? wi.abs : 0, f = own ? wi.focus : 100;
      const k = (Math.max(0, s.capacityPD - a) * (f / 100) / s.capacityPD) * kc;
      alt[s.id] = { fc: s.forecast * k, lo: s.low * k, hi: s.high * k, cap: Math.max(0, s.capacityPD - a) * (f / 100) };
    });
    return alt;
  }

  const tri = (cx, cy, r = 6) => `M${cx} ${cy - r}L${cx + r} ${cy + r * 0.75}L${cx - r} ${cy + r * 0.75}Z`;
  const lsw = (inner) => `<svg class="pf-lsw" viewBox="0 0 28 16" width="28" height="16" aria-hidden="true">${inner}</svg>`;
  function chartSvg(alt) {
    const sp = D.sprints, n = sp.length, W = 880, H = 280, L = 52, R = 20, T = 20, B = 226, YMAX = 50;
    const x = (i) => L + ((i + 0.5) / n) * (W - L - R);
    const y = (v) => B - (v / YMAX) * (B - T);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Velocity der Sprints 2026.17 bis 2026.20 und Forecast PLAN mit Spanne für 2026.22 bis 2026.25">`;
    for (let v = 0; v <= YMAX; v += 10) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:var(--border)"/><text class="d m" x="${L - 8}" y="${y(v) + 4}" font-size="11" text-anchor="end">${v}</text>`;
    s += `<text class="m" x="8" y="${T - 6}" font-size="11">Punkte</text>`;
    sp.forEach((p, i) => { s += `<text class="d" x="${x(i)}" y="${B + 20}" font-size="12" text-anchor="middle">${p.id}</text><text class="m" x="${x(i)}" y="${B + 36}" font-size="11" text-anchor="middle">${p.state === "past" ? "Ist" : p.state === "current" ? "läuft" : "Prognose"}</text>`; });
    const past = sp.filter((p) => p.velocity != null);
    s += `<polyline fill="none" style="stroke:var(--c-vel);stroke-width:2.5" points="${past.map((p) => `${x(sp.indexOf(p))},${y(p.velocity)}`).join(" ")}"/>`;
    past.forEach((p) => { const i = sp.indexOf(p); s += `<line x1="${x(i) - 11}" x2="${x(i) + 11}" y1="${y(p.plan)}" y2="${y(p.plan)}" style="stroke:var(--text-muted);stroke-width:4;stroke-linecap:round"><title>${p.id}: Commitment ${p.plan}</title></line><circle cx="${x(i)}" cy="${y(p.velocity)}" r="5.5" style="fill:var(--c-vel);stroke:var(--surface);stroke-width:2"><title>${p.id}: Velocity ${p.velocity}, Plan ${p.plan}</title></circle><text class="d" x="${x(i) + 15}" y="${y(p.velocity) + 16}" font-size="12" font-weight="600">${p.velocity}</text>`; });
    s += `<polyline fill="none" style="stroke:var(--c-nv);stroke-width:2" points="${past.map((p) => `${x(sp.indexOf(p))},${y(FS.normVel(p))}`).join(" ")}"/>`;
    past.forEach((p) => { const i = sp.indexOf(p); s += `<path d="${tri(x(i), y(FS.normVel(p)))}" style="fill:var(--c-nv);stroke:var(--surface);stroke-width:1.5"><title>${p.id}: normierte Velocity ${fmt(FS.normVel(p), 1)}</title></path>`; });
    { const lp = past[past.length - 1], tr = trendNV(), xs = sp.filter((p) => p.state !== "past"); s += `<polyline fill="none" style="stroke:var(--c-nv);stroke-width:2;stroke-dasharray:2 4" points="${x(sp.indexOf(lp))},${y(FS.normVel(lp))} ${xs.map((p) => `${x(sp.indexOf(p))},${y(tr)}`).join(" ")}"><title>Trend normierte Velocity ${fmt(tr, 1)}</title></polyline>`; }
    const cur = sp.find((p) => p.state === "current"), ci = sp.indexOf(cur);
    s += `<line x1="${x(ci) - 11}" x2="${x(ci) + 11}" y1="${y(cur.plan)}" y2="${y(cur.plan)}" style="stroke:var(--text-muted);stroke-width:4;stroke-linecap:round"><title>${cur.id}: Commitment ${cur.plan}, läuft noch</title></line><text class="d" x="${x(ci)}" y="${y(cur.plan) - 10}" font-size="12" text-anchor="middle">Commitment ${cur.plan}</text>`;
    const fut = sp.filter((p) => p.forecast != null), last = past[past.length - 1];
    s += `<polyline fill="none" style="stroke:var(--c-fc);stroke-width:2;stroke-dasharray:6 4" points="${x(sp.indexOf(last))},${y(last.velocity)} ${fut.map((p) => `${x(sp.indexOf(p))},${y(p.forecast)}`).join(" ")}"/>`;
    fut.forEach((p) => {
      const i = sp.indexOf(p), cx = x(i);
      s += `<g><title>${p.id}: Forecast PLAN ${p.forecast}, Spanne ${p.low} bis ${p.high}</title><line x1="${cx}" x2="${cx}" y1="${y(p.low)}" y2="${y(p.high)}" style="stroke:var(--c-fc);stroke-width:2;stroke-dasharray:4 3"/>
        <line x1="${cx - 7}" x2="${cx + 7}" y1="${y(p.high)}" y2="${y(p.high)}" style="stroke:var(--c-fc);stroke-width:2"/><line x1="${cx - 7}" x2="${cx + 7}" y1="${y(p.low)}" y2="${y(p.low)}" style="stroke:var(--c-fc);stroke-width:2"/>
        <circle cx="${cx}" cy="${y(p.forecast)}" r="5.5" style="fill:var(--surface);stroke:var(--c-fc);stroke-width:2.5"/></g>
        <text class="d" x="${cx + 11}" y="${y(p.forecast) + 4}" font-size="12" font-weight="600">${p.forecast}</text><text class="d m" x="${cx + 9}" y="${y(p.high) - 4}" font-size="10">${p.high}</text><text class="d m" x="${cx + 9}" y="${y(p.low) + 12}" font-size="10">${p.low}</text>`;
      const a = alt && alt[p.id];
      if (a) { const ax = cx - 18; s += `<g><title>Was wäre wenn, ${p.id}: ${fmt(a.fc, 1)} (Spanne ${fmt(a.lo, 1)} bis ${fmt(a.hi, 1)})</title><line x1="${ax}" x2="${ax}" y1="${y(a.lo)}" y2="${y(a.hi)}" style="stroke:var(--c-wif);stroke-width:2;stroke-dasharray:4 3"/><path d="M${ax} ${y(a.fc) - 7}l7 7l-7 7l-7 -7z" style="fill:var(--c-wif);stroke:var(--surface);stroke-width:1.5"/></g><text class="d" x="${ax - 10}" y="${y(a.fc) + 4}" font-size="12" font-weight="600" text-anchor="end">${fmt(a.fc)}</text>`; }
    });
    return s + `</svg>`;
  }


  // History as in 0.8: commitment, velocity, normalized velocity, average, fulfillment, scope creep
  const WINDOW = 5;
  const pastSprints = () => D.sprints.filter((s) => s.velocity != null);
  const avgNV = (s) => { const p = pastSprints(), i = p.indexOf(s), w = p.slice(Math.max(0, i - WINDOW + 1), i + 1); return sum(w, FS.normVel) / w.length; };
  const trendNV = () => avgNV(pastSprints().at(-1));
  const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)} %`);
  function pastHtml() {
    const cur = D.sprints.find((s) => s.state === "current");
    return `<div class="card" id="fp-history" style="margin-top:16px"><h2>Verlauf</h2>
      <div class="tw"><table class="t"><thead><tr><th>Sprint</th><th class="num">Kapazität (PT)</th><th class="num">Commitment</th><th class="num">Velocity</th><th class="num" title="Velocity ÷ Kapazität × Referenzkapazität ${FS.refCap()} PT">n. Velocity</th><th class="num" title="Mittel der normierten Velocity der letzten ${WINDOW} Sprints">Ø n. Velocity</th><th class="num" title="Velocity ÷ Commitment">Fulfillment</th><th class="num" title="Nach dem Planning hinzugekommene Arbeit, bezogen auf das Commitment">Scope Creep</th></tr></thead><tbody>
      ${pastSprints().map((s) => `<tr><td class="data">${s.id}</td><td class="num">${fmt(s.capacityPD)}</td><td class="num">${fmt(s.plan)}</td><td class="num">${fmt(s.velocity)}</td><td class="num">${fmt(FS.normVel(s), 2)}</td><td class="num">${fmt(avgNV(s), 2)}</td><td class="num">${pct(s.velocity / s.plan)}</td><td class="num">${pct(s.scope)}</td></tr>`).join("")}
      ${cur ? `<tr><td class="data">${cur.id} <span class="chip small">läuft</span></td><td class="num">${fmt(cur.capacityPD)}</td><td class="num">${fmt(cur.plan)}</td><td class="num muted">–</td><td class="num muted">–</td><td class="num muted">–</td><td class="num muted">–</td><td class="num muted">–</td></tr>` : ""}</tbody></table></div>
      <p class="small muted" style="margin:8px 0 0">Normierte Velocity = Velocity ÷ Kapazität × Referenzkapazität (volles Team ohne Abwesenheit, <span class="data">${FS.refCap()}</span> PT, Einstellung unter Team). Sie macht Sprints mit Urlaub vergleichbar und kürzt sich im Forecast PLAN heraus. <a href="#help">Hilfe > Rechenwege</a></p></div>`;
  }
  function forecastTabHtml() {
    const fut = D.sprints.filter((s) => s.forecast != null);
    const absChip = (a) => a === "confirmed" ? `<span class="chip ok">${ic("lock")}bestätigt</span>` : a === "announced" ? `<span class="chip warn">${ic("lock_open")}angekündigt</span>` : `<span class="chip">${ic("help")}nicht erfasst</span>`;
    const unknown = fut.filter((s) => s.absences === "unknown");
    return `
    ${unknown.length ? `<div class="banner info">${ic("info")}<div class="grow">Für ${unknown.map((s) => `<span class="data">${s.id}</span>`).join(" und ")} sind noch keine Abwesenheiten erfasst. Der Forecast rechnet dort mit voller Kapazität und wird mit jeder Eintragung genauer. <a href="#people">Abwesenheiten erfassen</a></div></div>` : ""}
    <div class="card fp-chart"><h2>Forecast PLAN für die nächsten vier Sprints</h2>
      <div class="pf-scroll" id="fp-chart">${chartSvg(whatIfAlt())}</div>
      <div class="pf-legend"><span>${lsw('<line x1="2" x2="26" y1="8" y2="8" style="stroke:var(--c-vel);stroke-width:2.5"/><circle cx="14" cy="8" r="4.5" style="fill:var(--c-vel)"/>')}Velocity (Ist), Punkt</span><span>${lsw('<line x1="5" x2="23" y1="8" y2="8" style="stroke:var(--text-muted);stroke-width:4;stroke-linecap:round"/>')}Commitment, Balken</span><span>${lsw(`<line x1="2" x2="26" y1="8" y2="8" style="stroke:var(--c-nv);stroke-width:2"/><path d="${tri(14, 8, 5)}" style="fill:var(--c-nv)"/>`)}normierte Velocity, Dreieck (gepunktet: Trend)</span><span>${lsw('<line x1="2" x2="26" y1="8" y2="8" style="stroke:var(--c-fc);stroke-width:2;stroke-dasharray:5 3"/><circle cx="14" cy="8" r="4.5" style="fill:var(--surface);stroke:var(--c-fc);stroke-width:2.5"/>')}Forecast PLAN, Ring mit Spanne niedrig bis hoch</span><span>${lsw('<path d="M14 2l6 6l-6 6l-6 -6z" style="fill:var(--c-wif)"/>')}Was wäre wenn, Raute</span></div></div>
    <div class="stack" style="margin-top:16px;gap:16px">
      <div class="fp-table"><div class="tw"><table class="t"><thead><tr><th>Sprint</th><th class="num">Kapazität (PT)</th><th>Abwesenheiten</th><th class="num" title="Trend der normierten Velocity (Referenzkapazität ${FS.refCap()} PT)">n. Velocity Trend</th><th class="num">Forecast PLAN (Pkt)</th><th class="num">Spanne (Pkt)</th><th class="num" title="(Forecast PLAN minus Übertrag) mal verplanbarer Anteil, abgerundet">Verplanbar (Pkt)</th><th class="num" title="Rest nach Verplanbar und Übertrag">Kleinkram (Pkt)</th><th></th></tr></thead><tbody>
        ${fut.map((s) => `<tr><td><span class="data">${s.id}</span> <span class="small muted data">${FS.fmtDate(s.start).slice(0, 5)}.–${FS.fmtDate(s.end).slice(0, 5)}.</span></td><td class="num">${fmt(s.capacityPD)}</td><td>${absChip(s.absences)}</td><td class="num">${fmt(trendNV(), 2)}</td><td class="num"><strong>${fmt(s.forecast)}</strong></td><td class="num">${s.low} bis ${s.high}</td>${(() => { const co = FS.sum(D.tickets.filter((t) => t.carryTo === s.id), (t) => t.carryRest ?? t.est), x = FS.split(s.forecast - co); return `<td class="num" ${co ? `title="nach ${fmt(co)} Punkten Übertrag"` : ""}>${fmt(x.free)}${co ? "*" : ""}</td><td class="num">${fmt(x.small)}</td>`; })()}<td>${calcBtn("fc", s.id)}</td></tr>`).join("")}
        <tr class="sum"><td>Summe 4 Sprints</td><td class="num">${fmt(sum(fut, (s) => s.capacityPD))}</td><td></td><td></td><td class="num">${fmt(sum(fut, (s) => s.forecast))}</td><td class="num">${sum(fut, (s) => s.low)} bis ${sum(fut, (s) => s.high)}</td><td></td><td></td><td></td></tr></tbody></table></div>
        <p class="small muted" style="margin:8px 0 0">Forecast PLAN = Kapazität mal Rate (${rateTxt()} Pkt je PT). Verplanbar = (Forecast PLAN minus Übertrag, mit * markiert) mal ${Math.round(FS.share() * 100)} %, der Rest ist Kleinkram. Die Spanne zeigt, wie stark die letzten Sprints gestreut haben. Ein Forecast ist eine Erwartung, keine Zusage.</p></div>
      <div class="card fp-whatif"><h2>Was wäre wenn</h2>
        <div class="stack"><div class="field"><label for="wi-sprint">Sprint</label><select class="input" id="wi-sprint"><option value="all">Alle vier Sprints</option>${fut.map((s) => `<option value="${s.id}" ${wi.sprint === s.id ? "selected" : ""}>${s.id}</option>`).join("")}</select></div>
        <div class="field"><label for="wi-abs">Zusätzliche Abwesenheit je Sprint (PT): <span class="data" id="wi-abs-v">${wi.abs}</span></label><input class="pf-range" type="range" id="wi-abs" min="0" max="15" step="1" value="${wi.abs}"></div>
        <div class="field"><label for="wi-focus">Fokus (Anteil der Zeit für Sprintarbeit): <span class="data" id="wi-focus-v">${wi.focus} %</span></label><input class="pf-range" type="range" id="wi-focus" min="70" max="100" step="5" value="${wi.focus}"></div>
        ${curSp() ? `<div class="field"><label for="wi-cur">Erwartet erledigt im laufenden Sprint ${curSp().id} (Punkte, Commitment ${curSp().plan})</label><input class="input data" id="wi-cur" inputmode="decimal" value="${wi.curDone ?? ""}" placeholder="${curSp().plan}" style="width:96px;text-align:right"><span class="small muted">Geht als erwartete Velocity in den Forecast PLAN ein. ${FS.trk() === "none" ? "Mit mehreren Annahmen" : "Je Ticket"} abschätzen: Sprint &gt; Vorplanen.</span></div>` : ""}
        <div id="wi-result">${whatIfResult()}</div>
        <div class="row"><button class="btn primary" type="button" id="wi-save">${ic("bookmark_add")}als Prognose speichern</button><button class="btn ghost" type="button" id="wi-reset">Zurücksetzen</button></div>
        <div id="wi-saved">${savedList()}</div></div></div>
    </div>
    ${pastHtml()}`;
  }

  function whatIfResult() {
    const alt = whatIfAlt(), ids = Object.keys(alt);
    if (!ids.length) return `<p class="small muted" style="margin:0">Ändern Sie Abwesenheit, Fokus oder die Erwartung für den laufenden Sprint. Der Chart zeigt das Ergebnis in Violett neben dem Forecast PLAN. Nichts wird gespeichert, bis Sie "als Prognose speichern" wählen.</p>`;
    return `<div class="tw"><table class="t"><thead><tr><th>Sprint</th><th class="num">Kapazität</th><th class="num">Forecast neu</th><th class="num">Änderung</th></tr></thead><tbody>
      ${ids.map((id) => { const s = FS.sprint(id), a = alt[id], d = a.fc - s.forecast; return `<tr><td class="data">${id}</td><td class="num">${fmt(a.cap, 1)} PT</td><td class="num">${fmt(a.fc, 1)}</td><td class="num">${d < 0 ? `<span class="pf-over">${ic("trending_down")}${fmt(d, 1)}</span>` : fmt(d, 1)}</td></tr>`; }).join("")}</tbody></table></div>`;
  }
  function savedList() {
    return FS.state.prognosen.length ? `<div class="small muted">Gespeicherte Prognosen</div>${FS.state.prognosen.map((p) => `<div class="row small"><span class="chip fc">${ic("bookmark")}${esc(p.name)}</span><span class="muted">${esc(p.text)}</span></div>`).join("")}` : "";
  }

  // "Wann ist es fertig?"
  const defaultShare = (p) => { const f = FS.sprint("2026.22").forecast; const pts = FS.projPts("2026.22", p.id); return Math.max(10, Math.min(80, Math.round((pts / f) * 20) * 5)); };
  function whenData(p, share) {
    const st = projStats(p), rem = st.remPts, rows = [];
    let lo = 0, fc = 0, hi = 0;
    allSprints().filter((s) => s.forecast != null).forEach((s) => { lo += (share / 100) * s.low; fc += (share / 100) * s.forecast; hi += (share / 100) * s.high; rows.push({ s, lo, fc, hi, part: (share / 100) * s.forecast }); });
    const reach = (k) => rows.find((r) => r[k] >= rem);
    return { st, rem, rows, early: reach("hi"), prob: reach("fc"), late: reach("lo") };
  }
  function analysisHtml() {
    const p = FS.project(FS.state.anProject || FS.state.project) || D.projects[0];
    const share = FS.state.anShare ?? defaultShare(p);
    const w = whenData(p, share);
    const pr = w.prob && w.prob.s;
    const slack = pr ? dayNum(p.end) - dayNum(pr.end) : null;
    const light = !pr ? "bad" : slack >= 14 ? "ok" : slack >= 0 ? "warn" : "bad";
    const cut = Math.max(...[w.early, w.prob, w.late].map((r) => (r ? w.rows.indexOf(r) : w.rows.length - 1))) + 1;
    const tag = (r) => [r === w.early ? "frühestens" : "", r === w.prob ? "wahrscheinlich" : "", r === w.late ? "spätestens" : ""].filter(Boolean).join(", ");
    return `<div class="stack">
      <div class="row"><div class="field"><label for="an-proj">Projekt</label><select class="input" id="an-proj">${D.projects.map((x) => `<option value="${x.id}" ${x.id === p.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div>
        <div class="field" style="flex:1;min-width:240px"><label for="an-share">Anteil des Projekts an der Sprintleistung: <span class="data">${share} %</span></label><input class="pf-range" type="range" id="an-share" min="10" max="80" step="5" value="${share}"></div></div>
      <p class="small muted" style="margin:0">Vorbelegt mit dem Anteil, den das Projekt in 2026.22 vorgemerkt hat. Offener Umfang: <span class="data">${fmt(w.rem)}</span> Punkte in ${w.st.nOpen} Tickets. ${w.st.ts.filter((t) => !t.refined && t.status !== "Fertig").length ? `${w.st.ts.filter((t) => !t.refined && t.status !== "Fertig").length} davon noch nicht refined: die Schätzung kann sich ändern.` : ""}</p>
      <div class="card" style="background:var(--surface-2);border:0"><div class="small muted">Voraussichtlich fertig in</div>
        <div class="row" style="margin:4px 0"><span class="pf-big">${pr ? `Sprint ${pr.id}` : "nach 2026.30"}</span>${FS.lightChip(light, light === "ok" ? "vor Projektende" : light === "warn" ? "knapp vor Projektende" : "nach Projektende")}${calcBtn("an", p.id)}</div>
        <div>Spanne: ${w.early ? `ab <span class="data">${w.early.s.id}</span>` : "nicht absehbar"} bis ${w.late ? `<span class="data">${w.late.s.id}</span>` : `nach <span class="data">2026.30</span>`}${pr ? `. Sprintende <span class="data">${FS.fmtDate(pr.end)}</span>, Projektende <span class="data">${FS.fmtDate(p.end)}</span> (${slack >= 0 ? `${Math.round(slack / 7)} Wochen Puffer` : `${Math.round(-slack / 7)} Wochen zu spät`}).` : "."}</div></div>
      <div class="tw"><table class="t"><thead><tr><th>Sprint</th><th class="num">Projekt-Anteil (Pkt)</th><th class="num">kumuliert Forecast</th><th class="num">niedrig bis hoch</th><th class="num">Rest (Pkt)</th><th>Einordnung</th></tr></thead><tbody>
      ${w.rows.slice(0, cut).map((r) => `<tr><td><span class="data">${r.s.id}</span>${r.s.ext ? ` <span class="small muted">Kalender folgt</span>` : ""}</td><td class="num">${fmt(r.part, 1)}</td><td class="num">${fmt(r.fc, 1)}</td><td class="num">${fmt(r.lo, 1)} bis ${fmt(r.hi, 1)}</td><td class="num">${fmt(Math.max(0, w.rem - r.fc), 1)}</td><td>${tag(r) ? `<span class="chip fc">${tag(r)}</span>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  }

  function historyHtml() {
    const stages = [["Standard", 0], ["Vorgeplant", 1], ["Geplant", 2], ["Erledigt", 3]];
    const st = FS.state.fcStage ?? 3, showProd = FS.state.fcProd ?? true;
    const ids = Object.keys(D.productHistory);
    const cell = (sid, pid, grp) => { const v = D.productHistory[sid][pid]; const a = v[st]; const pr = st === 2 ? v[4] : st === 3 ? v[5] : null; return `<td class="num">${a == null ? `<span class="muted">${sid === "2026.21" ? "läuft" : "–"}</span>` : fmt(a)}${showProd && pr != null ? FS.prodSub(pr) : ""}</td>`; };
    const tot = (sid, list, i) => { const vals = list.map((p) => D.productHistory[sid][p.id][i]); return vals.some((v) => v == null) ? null : sum(vals); };
    return `<div class="fp-history"><div class="row" style="margin-bottom:12px"><span class="muted small">Stufe</span>${stages.map(([l, i]) => `<button class="chip filter ${st === i ? "on" : ""}" type="button" data-stage="${i}" aria-pressed="${st === i}">${l}</button>`).join("")}
      <label class="row small col-prod" style="margin-left:auto;gap:6px"><input type="checkbox" id="fp-prod" ${showProd ? "checked" : ""}>Anteil mit Produktionszugang zeigen</label></div>
      <div class="tw"><table class="t"><thead><tr><th>PO</th><th>Produkt</th>${ids.map((id) => `<th class="num">${id}</th>`).join("")}</tr></thead><tbody>
      ${D.pos.map((po) => { const list = D.products.filter((p) => p.po === po.id); return list.map((p, k) => `<tr><td>${k ? "" : esc(po.name)}</td><td>${FS.productChip(p.id)}</td>${ids.map((sid) => cell(sid, p.id)).join("")}</tr>`).join("") +
        `<tr class="sum"><td></td><td>Summe ${esc(po.name.split(" ")[0])}</td>${ids.map((sid) => { const t = tot(sid, list, st); return `<td class="num">${t == null ? "–" : fmt(t)}${showProd && (st === 2 || st === 3) && t != null ? FS.prodSub(tot(sid, list, st + 2)) : ""}</td>`; }).join("")}</tr>`; }).join("")}
      </tbody></table></div>
      <p class="small muted" style="margin:8px 0 0">Eine Tabelle über mehrere Sprints, dieselben Stufen wie in der Sprintansicht, in Punkten. Der graue Zusatz "Prod 3" heißt: 3 dieser Punkte erledigen Personen mit Produktionszugang. Er wird nur angezeigt, nicht erzwungen. Vorgeplant und Geplant weichen oft ab: Vergleichen Sie Geplant mit Erledigt, um Budgets zu prüfen.</p></div>`;
  }

  function reportsHtml() {
    const fut = D.sprints.filter((s) => s.forecast != null);
    const md = `# Forecast ${D.team.name}, Stand ${FS.fmtDate(D.today)}\n\n| Sprint | Kapazität (PT) | Forecast PLAN | Spanne |\n| --- | --- | --- | --- |\n${fut.map((s) => `| ${s.id} | ${s.capacityPD} | ${s.forecast} | ${s.low} bis ${s.high} |`).join("\n")}\n\nRate: ${rateTxt()} Punkte je PT.\nProjekte: ${D.projects.map((p) => `${p.name} (${LIGHT_TXT[p.light]})`).join(", ")}.`;
    return `<div class="grid cols-2" style="align-items:start">
      <div class="card"><div class="row"><h2 style="margin:0;flex:1">Excel-Arbeitsmappe</h2>${ic("table_chart")}</div><p class="muted">Forecast, Produkte im Verlauf und Projekte als Tabellenblätter.</p>
        <div class="stack"><label class="row"><input type="checkbox" checked> Forecast und Kapazität</label><label class="row"><input type="checkbox" checked> Produkte im Verlauf</label><label class="row"><input type="checkbox" checked> Projekte und Kontingent</label></div>
        <div class="row" style="margin-top:12px"><button class="btn primary" type="button" data-toast="Excel-Arbeitsmappe foresprint-atlas-2026.22.xlsx erstellt (im Mockup nicht gespeichert).">${ic("download")}Excel exportieren</button><button class="btn" type="button" data-toast="Import: Datei wählen, Vorschau der Änderungen, dann übernehmen (im Mockup nicht ausgeführt).">${ic("upload")}Excel importieren</button></div></div>
      <div class="card"><div class="row"><h2 style="margin:0;flex:1">Markdown-Bericht</h2>${ic("description")}</div><p class="muted">Kurzer Bericht zum Einfügen in Wiki oder Mail.</p>
        <pre class="pf-pre">${esc(md)}</pre><div class="row" style="margin-top:12px"><button class="btn primary" type="button" data-toast="Markdown-Bericht in die Zwischenablage kopiert.">${ic("content_copy")}Kopieren</button><button class="btn" type="button" data-toast="Bericht als forecast-bericht.md exportiert (im Mockup nicht gespeichert).">${ic("download")}Als Datei</button></div></div></div>`;
  }

  const TABS = [["forecast", "insights", "Forecast"], ["analyse", "query_stats", "Analyse"], ["verlauf", "stacked_bar_chart", "Produkte im Verlauf"], ["berichte", "ios_share", "Berichte und Export"]];
  FS.view("forecast", {
    title: "Forecast",
    render() {
      if (FS.state.fcTab === "verlauf" && !FS.multiProduct()) FS.state.fcTab = "forecast";
      const tab = FS.state.fcTab;
      return `${STYLE}
      <div class="page-head"><div><h1>Forecast</h1><p class="lead">Wie viel schafft das Team in den kommenden Sprints, und wann wird etwas fertig? Immer verfügbar, auch ohne bestätigte Abwesenheiten oder ${D.team.tracker}.</p></div></div>
      <div class="tabs" role="tablist">${TABS.filter(([id]) => id !== "verlauf" || FS.multiProduct()).map(([id, icn, l]) => `<a href="#forecast" role="tab" data-tab="${id}" class="${tab === id ? "active" : ""}" aria-selected="${tab === id}">${ic(icn)}${l}</a>`).join("")}</div>
      ${tab === "forecast" ? forecastTabHtml() : tab === "analyse" ? `<div class="card fp-analysis"><h2>Wann ist es fertig?</h2><div id="an-body">${analysisHtml()}</div></div>` : tab === "verlauf" ? historyHtml() : reportsHtml()}`;
    },
    wire(main) {
      main.querySelectorAll("[data-tab]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); FS.state.fcTab = a.dataset.tab; FS.render(); }));
      wireCommon(main);
      main.querySelectorAll("[data-toast]").forEach((b) => (b.onclick = () => FS.toast(b.dataset.toast)));
      const q = (s) => main.querySelector(s);
      if (q("#wi-abs")) {
        const upd = () => { q("#fp-chart").innerHTML = chartSvg(whatIfAlt()); q("#wi-result").innerHTML = whatIfResult(); q("#wi-abs-v").textContent = wi.abs; q("#wi-focus-v").textContent = wi.focus + " %"; };
        q("#wi-sprint").onchange = (e) => { wi.sprint = e.target.value; upd(); };
        q("#wi-abs").oninput = (e) => { wi.abs = Number(e.target.value); upd(); };
        q("#wi-focus").oninput = (e) => { wi.focus = Number(e.target.value); upd(); };
        if (q("#wi-cur")) q("#wi-cur").onchange = (e) => { const v = parseFloat(e.target.value.replace(",", ".")); wi.curDone = isNaN(v) || v < 0 ? null : v; upd(); };
        q("#wi-reset").onclick = () => { Object.assign(wi, { sprint: "all", abs: 0, focus: 100, curDone: null }); FS.render(); };
        q("#wi-save").onclick = () => {
          if (!Object.keys(whatIfAlt()).length) { FS.toast("Erst eine Annahme ändern, dann als Prognose speichern."); return; }
          const entry = { name: `Prognose ${String.fromCharCode(65 + FS.state.prognosen.length)}`, text: `${wi.sprint === "all" ? "alle Sprints" : wi.sprint}, ${wi.abs} PT weniger, Fokus ${wi.focus} %${wi.curDone != null ? `, ${curSp().id} erwartet ${wi.curDone} erledigt` : ""}` };
          FS.state.prognosen.push(entry); q("#wi-saved").innerHTML = savedList();
          FS.toast(`${entry.name} gespeichert. Sie erscheint im Bericht und beim Planen.`, () => { FS.state.prognosen.pop(); q("#wi-saved").innerHTML = savedList(); });
        };
      }
      if (q("#an-proj")) {
        const redo = () => { q("#an-body").innerHTML = analysisHtml(); wireAn(); };
        const wireAn = () => {
          q("#an-proj").onchange = (e) => { FS.state.anProject = e.target.value; FS.state.anShare = null; redo(); };
          q("#an-share").oninput = (e) => { FS.state.anShare = Number(e.target.value); const pos = e.target.value; redo(); const r = q("#an-share"); r.focus(); r.value = pos; };
          q("#an-body").querySelectorAll("[data-calc]").forEach((b) => (b.onclick = () => {
            const p = FS.project(b.dataset.id), share = FS.state.anShare ?? defaultShare(p), w = whenData(p, share), first = w.rows[0];
            calcPanel("Rechenweg: Wann ist es fertig?", [
              [`Offener Umfang ${esc(p.name)}`, `<span class="data">${fmt(w.rem)} Pkt</span>`],
              ["Anteil an der Sprintleistung", `<span class="data">${share} %</span>`],
              [`Forecast PLAN ${first.s.id} mal Anteil`, `<span class="data">${fmt(first.s.forecast)} mal ${share} % = ${fmt(first.part, 1)} Pkt</span>`],
              ["Je Sprint addieren, bis der Umfang gedeckt ist", `<span class="data">${w.prob ? w.prob.s.id : "nach 2026.30"}</span>`, "sum"],
            ], "Frühestens rechnet mit der oberen, spätestens mit der unteren Grenze der Spanne. Sprints nach 2026.25 nutzen den Mittelwert der vier Prognosen.");
          }));
        };
        wireAn();
      }
      main.querySelectorAll("[data-stage]").forEach((b) => (b.onclick = () => { FS.state.fcStage = Number(b.dataset.stage); FS.render(); }));
      if (q("#fp-prod")) q("#fp-prod").onchange = (e) => { FS.state.fcProd = e.target.checked; FS.render(); };
    },
  });

  // ---------- flows ----------
  FS.flow({
    id: "F6", title: "Wann ist es fertig?",
    summary: "Forecast mit Spanne ansehen, Annahmen durchspielen, ein Projekt prüfen und Zahlen exportieren.",
    steps: [
      { view: "forecast", before() { FS.state.fcTab = "forecast"; }, hl: ".fp-chart", text: "Der Forecast ist immer erreichbar. Der Chart zeigt die Velocity der letzten Sprints (durchgezogen) und den Forecast PLAN der kommenden vier Sprints mit Spanne (mint, gestrichelt)." },
      { view: "forecast", hl: ".fp-table", text: "Die Tabelle nennt Kapazität in PT, Forecast PLAN und Spanne. Für 2026.23 und 2026.24 fehlen Abwesenheiten: Das ist nur ein Hinweis, die Seite bleibt benutzbar. Das Rechenweg-Symbol erklärt jede Zeile." },
      { view: "forecast", hl: ".fp-whatif", text: "Was wäre wenn: Ziehen Sie den Regler für Abwesenheit oder Fokus. Das Ergebnis erscheint im Chart in Violett. Gefällt es, speichern Sie es ausdrücklich als Prognose. Ohne Speichern bleibt der Forecast unverändert." },
      { view: "forecast", before() { FS.state.fcTab = "analyse"; FS.state.anProject = "ss2"; FS.state.anShare = null; }, hl: ".fp-analysis", text: "Analyse: Wählen Sie ein Projekt. Foresprint nennt den wahrscheinlichen Sprint mit Spanne und vergleicht ihn mit dem Projektende." },
      { view: "forecast", before() { FS.state.fcTab = "verlauf"; }, hl: ".fp-history", text: "Produkte im Verlauf: dieselben Stufen wie in der Sprintansicht, über mehrere Sprints und je PO gruppiert. Prüfen Sie, ob Budgets zur Abmachung passen." },
      { view: "forecast", before() { FS.state.fcTab = "berichte"; }, hl: ".grid.cols-2 .card", text: "Berichte und Export: Excel oder Markdown-Bericht. Damit ist die Frage beantwortet und das Ergebnis liegt dort, wo es gebraucht wird." },
    ],
  });

  FS.flow({
    id: "F8", title: "Mit Projekten vorbereiten und berichten",
    summary: "Projekt anlegen, Zeitachse und Kontingent prüfen, Konflikte erkennen, dem Projektleiter berichten.",
    steps: [
      { view: "projects", before() { FS.closePanel(); }, hl: "#pf-new", text: "Neues Projekt anlegen: Name, Produkte, Ende, Meilensteine und Kontingent in PT. Das klappt ohne Tracker und offline. Probieren Sie den Knopf aus." },
      { view: "projects", hl: ".pf-timeline", text: "Die Zeitachse zeigt die Laufzeit, Meilensteine mit Ampel (Symbol und Farbe) und die heutige Linie. Login-Umstellung ist gefährdet." },
      { view: "projects", hl: ".pf-table", text: "Passt der Bedarf zu Budgets und Kontingenten, geht es direkt weiter in Sprint > Vorplanen. Das Kontingent steht in PT, Geplantes ist eine Schätzung. Tagesgeschäft hat je Produkt eine Zeile ohne Ampel." },
      { view: "projects", hl: ".pf-conflict", text: "Passt es nicht, zeigt die Konfliktansicht Bedarf gegen Produktbudget und Kontingent. Das PO entscheidet: Tickets verschieben, Risiko akzeptieren oder mit der Projektleitung sprechen. Foresprint gibt nur Empfehlungen." },
      { view: "project", before() { FS.state.project = "ss2"; }, hl: ".pj-tickets", text: "Im Projekt stehen Meilensteine, Kontingent je Monat und die Tickets nach Sprint. Von hier aus verschieben Sie Tickets im Backlog oder in der Vorplanung." },
      { view: "project", hl: ".pj-report", text: "Der Bericht für die Projektleitung zeigt gebucht, geplant und erledigt je Sprint. Mit Bericht exportieren geben Sie ihn weiter." },
    ],
  });
})();
