// Help > Rechenwege: every calculation explained once, with the demo team's numbers substituted.
// Follows docs/calculation.md. The screens keep only a calculator icon (or nothing, or an open
// disclosure, depending on Settings > Personal > Rechenwege) and link here.
(function () {
  const D = DEMO, f = FS.fmt;
  const S22 = () => FS.sprint("2026.22");
  const past = () => D.sprints.filter((s) => s.state === "past");
  const rates = () => past().map((s) => ({ s, r: s.velocity / s.capacityPD }));
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const floor1 = (x) => Math.floor(x * 10) / 10;

  const table = (head, rows, sumRow) => `<div class="tw"><table class="t"><thead><tr>${head.map((h, i) => `<th class="${i ? "num" : ""}">${h}</th>`).join("")}</tr></thead><tbody>
    ${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "num" : ""}">${c}</td>`).join("")}</tr>`).join("")}
    ${sumRow ? `<tr class="sum">${sumRow.map((c, i) => `<td class="${i ? "num" : ""}">${c}</td>`).join("")}</tr>` : ""}</tbody></table></div>`;

  function topics() {
    const s = S22(), abs = D.absences["2026.22"] || {};
    const people = D.people.map((p) => { const a = abs[p.id]?.d || 0; return { p, a, pd: (s.days - a) * p.fte }; });
    const gross = FS.sum(people, (x) => x.pd), over = gross * D.overheadShare, cap = gross - over;
    const rs = rates(), rate = mean(rs.map((x) => x.r)), lo = Math.min(...rs.map((x) => x.r)), hi = Math.max(...rs.map((x) => x.r));
    const plan = floor1(rate * cap);
    const shares = D.products.map((p) => [p.name, `${f(p.share * 100)} %`, f(plan * p.share, 1)]);
    return [
      { id: "kapazitaet", icon: "groups", title: "Kapazität", lead: "Wie viele Personentage (PT) das Team im Sprint wirklich arbeiten kann.",
        formula: "Kapazität = Σ Personen (Arbeitstage − Feiertage − Abwesenheit) × FTE − Overhead",
        example: `Sprint 2026.22, ${s.days} Arbeitstage, Abwesenheiten angekündigt, Overhead ${f(D.overheadShare * 100)} %:` +
          table(["Person", "Abwesend (T)", "FTE", "PT"], people.map((x) => [x.p.name, f(x.a), f(x.p.fte, 1), f(x.pd, 1)]), ["Summe vor Overhead", "", "", f(gross, 1)]) +
          `<p class="small">${f(gross, 1)} − ${f(over, 1)} Overhead = <strong class="data">${f(cap, 1)} PT</strong>, angezeigt gerundet ${f(cap)} PT.</p>`,
        special: ["Bestätigt: die eingetragenen Abwesenheiten zählen. Angekündigt: die Ankündigung aus der Vorplanung zählt. Unbekannt: Foresprint zieht den Durchschnitt der Abwesenheiten aus früheren bestätigten Sprints ab und warnt.",
          "Product Owner zählen nicht mit, außer sie sind unter Team > Personen als \"arbeitet im Team mit\" mit einem Anteil eingetragen.", "Feiertage kommen aus dem Kalender der Region (Team-Einstellung). Brückentage trägst du als Abwesenheit ein.",
          "Die Kapazität bleibt intern ungerundet; gerundet wird nur zur Anzeige und beim Einfrieren im Review."] },
      { id: "rate", icon: "speed", title: "Rate (normierte Velocity)", lead: "Wie viele Punkte das Team je verfügbarem Personentag schafft. Daraus entstehen Forecast und Umrechnungen.",
        formula: "Rate = Velocity ÷ Kapazität      Mittelwert über die letzten Sprints mit Wert (Fenster 5)",
        example: table(["Sprint", "Velocity", "Kapazität (PT)", "Rate"], rs.map((x) => [x.s.id, f(x.s.velocity), f(x.s.capacityPD), f(x.r, 3)]), ["Mittelwert", "", "", f(rate, 3)]) +
          `<p class="small">Gerundet ${f(rate, 2)} Punkte je PT. In 0.8 heißt dieselbe Größe mit der Referenzkapazität multipliziert "normierte Velocity".</p>`,
        special: ["Sprints ohne Velocity zählen nicht; das Fenster reicht dann weiter zurück.", "Ab 3 Sprints mit Velocity gibt es einen ersten Forecast mit dem Hinweis \"wenig Daten\", ab 5 gelten die Aussagen als belastbar.", "Trendmodus (Einstellung): flach (Standard), linear oder klassisch. Linear und klassisch schreiben auch Ausreißer fort."] },
      { id: "forecast", icon: "insights", title: "Forecast PLAN und Spanne", lead: "Was das Team im Sprint voraussichtlich schafft, mit der Bandbreite aus den letzten Sprints.",
        formula: "Forecast PLAN = Rate × Kapazität (abgerundet auf eine Nachkommastelle)      Spanne = niedrigste bis höchste Rate × Kapazität",
        example: table(["", "Rate", "× Kapazität", "Punkte"], [["Forecast PLAN", f(rate, 3), f(cap, 1), f(plan, 1)], ["Untere Grenze", f(lo, 3), f(cap, 1), f(lo * cap, 1)], ["Obere Grenze", f(hi, 3), f(cap, 1), f(hi * cap, 1)]]) +
          `<p class="small">Angezeigt: ${f(plan)} Punkte, Spanne ${f(lo * cap)} bis ${f(hi * cap)}.</p>`,
        special: ["Bei der Planung wird der Forecast PLAN eingefroren. Danach zeigt Foresprint \"aktuell\" und \"bei Planung\" getrennt mit ihrer Differenz.", "Der Forecast ist nie negativ.", "\"In 85 % der Simulationen\" ist eine Häufigkeit aus der Vergangenheit, kein Versprechen."] },
      { id: "standard", icon: "category", title: "Standard je Produkt", lead: "Welcher Anteil des Forecast PLAN jedem Produkt zusteht, bevor der PO etwas anderes vorplant.",
        formula: "Standard = Basis × Anteil des Produkts      Basis = Forecast PLAN oder sein verplanbarer Anteil (Team-Einstellung)",
        example: `Basis = Forecast PLAN ${f(plan, 1)} Punkte:` + table(["Produkt", "Anteil", "Standard (Punkte)"], shares),
        special: ["Produkte ohne festen Anteil teilen sich den Rest zu gleichen Teilen.", "Feste Anteile dürfen zusammen höchstens 100 % ergeben; sonst erscheint ein Hinweis bei den Produkten.", "Es ist ein Vorschlag: Vorgeplant und Geplant dürfen abweichen, die Bilanz zeigt es."] },
      { id: "pt", icon: "swap_horiz", title: "Punkte in Personentage", lead: "Projekte buchen Kontingente in PT, das Team plant in Punkten. Foresprint rechnet mit der eigenen Rate um und kennzeichnet das als Schätzung.",
        formula: "PT ≈ Punkte ÷ Rate      geplant: Forecast-Rate des Sprints, erledigt: tatsächliche Rate des Sprints",
        example: table(["", "Punkte", "÷ Rate", "≈ PT"], [["Self-Service 2.0, vorgemerkt 2026.22", "18", f(D.rate, 2), f(18 / D.rate, 1)], ["Login-Umstellung, vorgemerkt 2026.22", "11", f(D.rate, 2), f(11 / D.rate, 1)]]),
        special: ["Die Umrechnung ist nur so gut wie die Rate. Bei wenig Daten steht ein Hinweis daneben.", "Kontingente sind Empfehlungen für das Gespräch mit der Projektleitung; die Entscheidung trifft der PO."] },
      { id: "ampel", icon: "traffic", title: "Ampel für Projekte und Meilensteine", lead: "Ob die vorgemerkten Tickets eines Projekts oder Meilensteins vor dessen Datum fertig werden.",
        formula: "Zielsprint = letzter Sprint, der vor dem Datum endet      grün: letzter Ticket-Sprint vor dem Zielsprint · gelb: im Zielsprint · rot: danach oder Tickets ohne Sprint",
        example: table(["Meilenstein", "Datum", "Zielsprint", "Letzter Ticket-Sprint", "Ampel"], [["Beta für Pilotkunden", "20.11.26", "2026.23", "2026.23", "gelb"], ["Neuer Anmeldedienst live", "04.12.26", "2026.24", "nicht alle vorgemerkt", "rot"]]),
        special: ["Ein Meilenstein ohne Tickets ist ein reines Datum und hat keine Ampel.", "Nicht refinte oder ungeschätzte Tickets zählen mit und werden markiert."] },
      { id: "fertig", icon: "flag", title: "Wann ist es fertig?", lead: "In welchem Sprint eine Restmenge wahrscheinlich erledigt ist.",
        formula: "Monte-Carlo: viele Durchläufe, je Sprint eine zufällig gezogene Rate aus den letzten Sprints × Kapazität × Projektanteil      Ergebnis: Sprint bei 50 % und 85 % der Durchläufe",
        example: `<p class="small">Self-Service 2.0, Rest 49 Punkte, Projektanteil 40 %: 50 % der Durchläufe fertig in 2026.25, 85 % in 2026.26. Die Stichprobe der Raten steht unter dem Ergebnis.</p>`,
        special: ["Mit festem Startwert, damit das Ergebnis bei gleichen Daten gleich bleibt.", "Ohne Personenliste rechnet Foresprint mit der durchschnittlichen Kapazität."] },
      { id: "bilanz", icon: "balance", title: "Bilanz je Produkt", lead: "Ob ein Produkt über die Sprints mehr oder weniger bekommen hat als sein Standard.",
        formula: "Bilanz = Σ Erledigt − Σ Standard (nur Sprints, in denen Erledigt eingetragen ist)",
        example: table(["Produkt", "Σ Erledigt", "Σ Standard", "Bilanz"], [["Kundenportal", "52", "49", "+3"], ["Abrechnung", "25", "28", "−3"], ["Mobile App", "36", "35", "+1"], ["Plattform", "27", "28", "−1"]]),
        special: ["Fehlende Werte zählen nicht als 0.", "Erledigt umfasst auch erledigte Teile offener Tickets, wenn das Team so zählt; das sollte im Team einheitlich sein."] },
    ];
  }

  FS.view("help", {
    title: "Hilfe, Rechenwege",
    render() {
      const T = topics(), mode = FS.state.calcMode;
      const modes = [["off", "Ausblenden"], ["icon", "Als Symbol"], ["inline", "Immer ausgeklappt"]];
      return `<div class="page-head"><div><h1>Rechenwege</h1><p class="lead">Jede Zahl in Foresprint ist nachvollziehbar. Hier steht jede Rechnung einmal ausführlich, mit den Zahlen von Team Atlas eingesetzt.</p></div></div>
        <div class="banner info"><span>${FS.icon("tune")}</span><div class="grow">Neben den Zahlen: <span class="row" style="display:inline-flex;margin-left:6px">${modes.map(([v, l]) => `<button type="button" class="chip filter ${mode === v ? "on" : ""}" data-help-mode="${v}" aria-pressed="${mode === v}">${l}</button>`).join("")}</span>
          <span class="small muted" style="display:block;margin-top:4px">Gilt nur für dich, auch unter <a href="#personal">Einstellungen > Persönlich</a>. "Als Symbol" zeigt den Rechner neben der Zahl, "Immer ausgeklappt" zeigt den Rechenweg direkt darunter.</span></div></div>
        <div class="grid" style="grid-template-columns:minmax(0,220px) minmax(0,1fr);align-items:start" id="help-grid">
          <nav class="card stack" style="position:sticky;top:0;gap:2px;padding:8px" aria-label="Themen">${T.map((t) => `<a href="#help" data-topic="${t.id}" class="row" style="flex-wrap:nowrap;text-decoration:none;color:var(--text);padding:6px 8px;border-radius:6px">${FS.icon(t.icon, "small")}${t.title}</a>`).join("")}</nav>
          <div class="stack" style="gap:16px">${T.map((t) => `<section class="card help-topic" id="topic-${t.id}"><h2 class="row">${FS.icon(t.icon)}${t.title}</h2>
            <p style="margin:0 0 10px;max-width:70ch">${t.lead}</p>
            <div class="formula" style="margin-bottom:10px">${t.formula}</div>
            <div class="stack">${t.example}</div>
            <details style="margin-top:10px"><summary class="small">Sonderfälle</summary><ul class="small" style="margin:6px 0 0;padding-left:18px">${t.special.map((x) => `<li>${x}</li>`).join("")}</ul></details></section>`).join("")}</div></div>
        <style>@media (max-width:900px){#help-grid{grid-template-columns:minmax(0,1fr)!important}#help-grid nav{position:static!important}}</style>`;
    },
    wire(main) {
      main.querySelectorAll("[data-help-mode]").forEach((b) => (b.onclick = () => { FS.state.calcMode = b.dataset.helpMode; FS.render(); FS.toast(`Rechenwege: ${b.textContent}.`); }));
      main.querySelectorAll("[data-topic]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); main.querySelector(`#topic-${a.dataset.topic}`).scrollIntoView({ block: "start", behavior: "smooth" }); }));
    },
  });

  FS.flow({ id: "F9", title: "Rechenweg nachvollziehen", summary: "Vom Rechner-Symbol an einer Zahl zur ausführlichen Erklärung, und wie man die Anzeige umstellt.", steps: [
    { view: "plan", hl: ".calc-btn", text: "Neben abgeleiteten Zahlen steht ein kleines Rechner-Symbol. Ein Klick öffnet den Rechenweg mit den eingesetzten Zahlen.", before() { FS.state.calcMode = "icon"; } },
    { view: "help", hl: "#topic-forecast", text: "Unter Hilfe > Rechenwege steht jede Rechnung einmal ausführlich: Leitsatz, Formel, Beispiel mit euren Zahlen, Sonderfälle zum Aufklappen." },
    { view: "help", hl: "[data-help-mode]", text: "Wer die Rechenwege immer sehen will, stellt auf \"Immer ausgeklappt\". Wer sie nicht braucht, blendet sie aus. Das gilt nur für dich." },
    { view: "plan", hl: ".calc-inline", text: "So sieht die Planung mit ausgeklappten Rechenwegen aus. Die Oberfläche bleibt gleich, die Erklärungen stehen direkt unter den Zahlen.", before() { FS.state.calcMode = "inline"; } },
    { view: "plan", text: "Zurück zur Standard-Anzeige mit Symbol.", before() { FS.state.calcMode = "icon"; } },
  ] });
})();
