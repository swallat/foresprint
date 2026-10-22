// Entry page of the mocks: every flow from docs/redesign/flows.md, each playable step by step.
FS.view("flows", {
  title: "Abläufe durchspielen",
  render() {
    const order = (id) => (id[0] === "F" ? 0 : 1) * 100 + Number(id.slice(1));
    const flows = [...FS.flows].sort((a, b) => order(a.id) - order(b.id));
    return `
      <div class="page-head"><div><h1>Abläufe durchspielen</h1>
        <p class="lead">Klickbare Mockups zu den Abläufen aus flows.md. "Durchspielen" führt Schritt für Schritt durch die Seiten; die gelbe Markierung zeigt, wo geklickt wird. Alle Daten gehören zum erfundenen Team Atlas. Nichts wird gespeichert.</p></div></div>
      <div class="card" id="demo-mode" style="margin-bottom:16px"><div class="row"><strong style="flex:1;min-width:200px">Demo-Team</strong><div class="row" role="group" aria-label="Demo-Team">
        <button type="button" class="chip filter ${FS.state.simple ? "" : "on"}" data-simple="0" aria-pressed="${!FS.state.simple}">${FS.icon("tune", "small")}Team Atlas, alle Funktionen</button>
        <button type="button" class="chip filter ${FS.state.simple ? "on" : ""}" data-simple="1" aria-pressed="${!!FS.state.simple}">${FS.icon("filter_none", "small")}Einfaches Team</button></div></div>
        <p class="small muted" style="margin:8px 0 0">${FS.state.simple ? "Einfaches Team: ein PO, ein Produkt, ohne Produktionszugang. Produktspalten, PO-Summen, Regeln je Produkt, \"davon Prod\", Bilanz je Produkt und \"Produkte im Verlauf\" sind ausgeblendet. Projekte, Kontingente und Jira bleiben. Schritte, die ausgeblendete Teile zeigen, sagen das im Text." : "Team Atlas nutzt alles: zwei POs, vier Produkte, Produktionszugang. \"Einfaches Team\" zeigt, wie dieselben Abläufe ohne diese Funktionen aussehen."}</p></div>
      <div class="tw"><table class="t">
        <thead><tr><th>Ablauf</th><th>Worum es geht</th><th class="num">Schritte</th><th></th></tr></thead>
        <tbody>${flows.map((f) => `<tr><td><span class="data">${f.id}</span> ${FS.esc(f.title)}</td><td class="muted" style="white-space:normal">${FS.esc(f.summary || "")}</td><td class="num">${f.steps.length}</td>
          <td><button class="btn primary" type="button" data-flow="${f.id}">${FS.icon("play_arrow")}Durchspielen</button></td></tr>`).join("")}</tbody>
      </table></div>
      <p class="small muted" style="margin-top:12px">Tastatur: Tickets mit Alt+Pfeil hoch/runter umsortieren, Alt+Pfeil links/rechts in die Nachbarspalte schieben. Ticketschlüssel öffnen ${DEMO.team.tracker}. Kontrast-Knopf oben rechts wechselt hell und dunkel.</p>`;
  },
  wire(main) {
    main.querySelectorAll("[data-simple]").forEach((b) => (b.onclick = () => { FS.setSimple(b.dataset.simple === "1"); FS.render(); FS.toast(FS.state.simple ? "Einfaches Team: ein PO, ein Produkt, ohne Produktionszugang." : "Team Atlas mit allen Funktionen."); }));
    main.querySelectorAll("[data-flow]").forEach((b) => (b.onclick = () => FS.startFlow(b.dataset.flow)));
  },
});
