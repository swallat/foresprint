// Entry page of the mocks: every flow from docs/redesign/flows.md, each playable step by step.
FS.view("flows", {
  title: "Abläufe durchspielen",
  render() {
    const order = (id) => (id[0] === "F" ? 0 : 1) * 100 + Number(id.slice(1));
    const flows = [...FS.flows].sort((a, b) => order(a.id) - order(b.id));
    return `
      <div class="page-head"><div><h1>Abläufe durchspielen</h1>
        <p class="lead">Klickbare Mockups zu den Abläufen aus flows.md. "Durchspielen" führt Schritt für Schritt durch die Seiten; die gelbe Markierung zeigt, wo geklickt wird. Alle Daten gehören zum erfundenen Team Atlas. Nichts wird gespeichert.</p></div></div>
      <div class="tw"><table class="t">
        <thead><tr><th>Ablauf</th><th>Worum es geht</th><th class="num">Schritte</th><th></th></tr></thead>
        <tbody>${flows.map((f) => `<tr><td><span class="data">${f.id}</span> ${FS.esc(f.title)}</td><td class="muted" style="white-space:normal">${FS.esc(f.summary || "")}</td><td class="num">${f.steps.length}</td>
          <td><button class="btn primary" type="button" data-flow="${f.id}">${FS.icon("play_arrow")}Durchspielen</button></td></tr>`).join("")}</tbody>
      </table></div>
      <p class="small muted" style="margin-top:12px">Tastatur: Tickets mit Alt+Pfeil hoch/runter umsortieren, Alt+Pfeil links/rechts in die Nachbarspalte schieben. Ticketschlüssel öffnen ${DEMO.team.tracker}. Kontrast-Knopf oben rechts wechselt hell und dunkel.</p>`;
  },
  wire(main) {
    main.querySelectorAll("[data-flow]").forEach((b) => (b.onclick = () => FS.startFlow(b.dataset.flow)));
  },
});
