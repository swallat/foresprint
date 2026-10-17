# Konzept: Verbesserungen am Kern (ohne Ticketsystem)

Status: Entwurf, noch nichts umgesetzt. Dieses Dokument sammelt alles, was **unabhängig von
einem Ticketsystem** gilt: Berechnung, Bedienung, Einrichtung, Datenordner und Synchronisation.
Die Ticketanbindung steht in [konzept-ticketsystem.md](konzept-ticketsystem.md); sie ist
optional und baut auf diesen Punkten auf (insbesondere A und D).

Die Punkte stammen aus zwei unabhängigen kritischen Prüfungen des bestehenden Produkts. Sie sind
**Empfehlungen** und noch nicht entschieden. Die Priorität ist die der Prüfenden
(kritisch / wichtig / nice-to-have).

## Grundsatz

Das System muss **ohne** Ticketsystem vollständig funktionieren. Alles in diesem Dokument ist
davon unberührt.

## A. Berechnung

| # | Punkt | Priorität | Empfehlung |
|---|---|---|---|
| A1 | Standard-Trend (`classic`/`linear`) extrapoliert Rauschen, kann sinken oder negativ werden, und liegt ab dem dritten Zukunftssprint unter der eigenen Bandbreite. | kritisch | `flat` (oder Median) als Standard; `classic`/`linear` nur ausdrücklich gewählt, mit Warnhinweis; negative Ergebnisse abfangen |
| A2 | Ohne bestätigte Fehltage und ohne `absence_history` wird die **Kapazität** per Trend fortgeschrieben, obwohl Personen, Feiertage und Sprintlänge bekannt sind. | kritisch | Kapazität immer aus Kalender und Personen; nur die unbekannten Fehltage schätzen (`absence_history` mit sinnvollem Standard); Trend nur für Teams ohne Personenliste |
| A3 | Der Punktwert steht ohne Unsicherheit auf der Hauptseite; „85 % Sicherheit“ ist bei wenigen Werten zu stark; Monte Carlo läuft schon mit zwei Messwerten. | kritisch | Bandbreite und Stichprobengröße direkt an der Forecast-Kachel; Warnung bei wenig Daten; Formulierung „modellabhängige Häufigkeit“ |
| A4 | Bei genau `window` Sprints Historie liefern `classic`/`linear` keinen Forecast; `rolling_average` zählt Positionen statt Werte, Lücken werden still übergangen. | wichtig | Fallback auf `flat` mit Hinweis „Historie dünn“; einheitliche Regel für Lücken, sichtbar gemacht |
| A5 | Die Fehltage-Historie überspringt bestätigte Null-Sprints und verzerrt so die Quote; sie nutzt nicht dieselbe Definition wie `absences_known`. | wichtig | dieselbe Definition verwenden; die tatsächlich verwendeten Sprints anzeigen |
| A6 | Teilzeit und Arbeitswoche: Wer eine 80-%-Stelle mit vier vollen Tagen als `workweek=mon,tue,wed,thu` und `fte=0.8` einträgt, wird doppelt abgezogen (8 × 0,8). | wichtig | Bedeutung von FTE festlegen und mit Beispielen erklären (FTE = Anteil an den Arbeitstagen der Person oder des Teams) |
| A7 | Bei FTE-Wechseln im Sprint werden Fehltage mit der mittleren FTE gewichtet (Näherung). | wichtig | Näherung sichtbar machen |
| A8 | Overhead: feste Overhead-Tage ersetzen den Prozentabzug (README beschreibt sie als zusätzlich); bei erwarteten Fehltagen wird die Reihenfolge anders gerechnet. | wichtig | eine gemeinsame Berechnung für bestätigte und erwartete Fehltage; README angleichen |
| A9 | Die Puffer-Empfehlung vergleicht unterschiedliche Bezugsgrößen (Scope Creep bezogen auf Eingeplantes, Kleinkram bezogen auf den Gesamtforecast). | wichtig | gleiche Bezugsgröße verwenden |
| A10 | Produktanteile: zwei feste Anteile von je 60 % werden nicht abgelehnt; fehlende Erledigt-Werte zählen im Saldo wie 0. | wichtig | Summenprüfung; „fehlt“ von „0“ unterscheiden |
| A11 | Produktionszugriff: „niemand markiert“ ist `None`, nicht 0; die Übersetzung in Liefermenge ist grob. | wichtig | unbekannte Konfiguration und fehlende Berechtigte unterscheiden; als Engpasshinweis kennzeichnen |
| A12 | Die Aussage „Fokusfaktor ist zwischen Teams vergleichbar“ ist bei Story Points falsch. | wichtig | Aussage entfernen |
| A13 | Die Referenzkapazität kürzt sich in der Rechnung heraus und ist nur ein Darstellungsmaßstab; Fokusfaktor und normierte Velocity sind dieselbe Größe unter zwei Namen. | wichtig | Referenzkapazität entfernen oder erklären; eine normierte Größe |
| A14 | Rundung: `round_down` überall ist ein systematischer Bias; die Kapazität wird abgerundet und danach als Nenner genutzt. | nice-to-have | Rundung erst bei der Ausgabe; bewusste Wahl im Hilfetext begründen |
| A15 | `trend()` vergleicht mit `is TrendMode.X`; ein Text landet im Zweig `linear`. | nice-to-have | Wert am Anfang in `TrendMode` umwandeln |
| A16 | Definition von „Erledigt“: Teilanteile offener Tickets zählen mit (Teampraxis). Ohne Dokumentation ist die Zahl zwischen Teams nicht vergleichbar. | wichtig | Definition in Hilfe und README festhalten. Ein Stichtag für einen Wechsel der Zählweise (wie `unit_since`) ist nur für Teams nötig, die ihre Zählweise ändern, und daher später und optional |

### Tests (Teil von K1)

Die vorhandenen Konsistenztests bleiben (Stärke: Seiten laufen nicht auseinander), prüfen aber
nur, ob die Implementierung mit sich selbst übereinstimmt. Dazu kommen **fachliche Tests**:

- Eigenschaftstests: konstante Velocity ergibt konstanten Forecast in jedem Trend-Modus; der Plan
  liegt in der Bandbreite; ein Feiertagssprint hat weniger Kapazität als ein Normalsprint; mehr
  Personen ergeben nie weniger Kapazität; Randfälle „genau `window` Sprints“, FTE 0, leere
  Historie, unterschiedliche Sprintlängen; der Forecast ist nie negativ.
- Rückblickende Prüfung (Backtest): Für jeden Sprint einer Historie wird mit den damals
  verfügbaren Daten prognostiziert und mit dem tatsächlichen Wert verglichen; die Modi werden
  gegen einen einfachen konstanten Forecast (Mittel/Median der letzten Werte) verglichen. Als
  Test mit synthetischen Reihen (stationär, Trend, Sprung) und der Demo-Historie. Die
  Trefferquote behaupteter Wahrscheinlichkeiten ist ein Ziel für lange Historien, keine
  Voraussetzung für K1.
- Handgerechnete Beispiele für Feiertage, FTE, Overhead und Fehltage bleiben als Vorbild.

## B. Bedienung und Begriffe

| # | Punkt | Priorität | Empfehlung |
|---|---|---|---|
| B1 | „Forecast PLAN“ bedeutet je nach Seite die aktuelle Berechnung oder den eingefrorenen Stand. | kritisch | überall „Prognose aktuell“, „Prognose beim Planning“ und die Differenz zeigen |
| B2 | „Weiter ohne Eintrag“ im Planning setzt Fehltage stillschweigend auf „niemand fehlt“; unbekannt und 0 sind zu leicht verwechselbar. | kritisch | expliziter Zustand je Sprint (unbekannt / voraussichtlich / bestätigt) statt der Dateiheuristik; ausdrückliche Bestätigung „niemand fehlt“ |
| B3 | „Forecast IST“ ist die Zusage zu Sprintbeginn, kein Ergebnis. „Roadmap“ bezeichnet einen reservierten Anteil. „erwartete“ und „voraussichtliche“ Fehltage sind zwei Mechanismen mit fast gleichem Namen. | wichtig | z. B. „Zusage“; „Roadmap“-Anteil umbenennen; die beiden Fehltage-Begriffe unterscheidbar machen |
| B4 (umgesetzt, #43) | 15 bis 16 Seiten mit konkurrierenden Wegen (Produktwerte auf „Produktverteilung“ und auf allen Boards; Sprintauswahl uneinheitlich). | wichtig | Einstieg über Aufgaben („Sprint vorbereiten“, „Planning“, „Sprint abschließen“); Produktverteilung als Auswertung; Stammdaten unter „Team verwalten“ |
| B5 | Unsicherheit steht abseits der Entscheidung (Seite „Analyse“). | wichtig | Spanne, Stichprobengröße und Kapazitätsquelle direkt an der Kachel |
| B6 | Die Formelansicht zeigt nicht die eingesetzten Zahlen; die Formeln der Trend-Modi sind für Nichtfachleute schwer lesbar. | wichtig | kurze Erklärung in Alltagssprache, ausklappbar die eingesetzten Werte und Quellen |
| B7 | Der Einstieg verlangt ein Git-Repository und 6+ Reviews, bevor ein Forecast erscheint. | wichtig | Forecast schon ab 2 bis 3 Sprints (`flat`) mit Hinweis „Historie dünn“ |
| B8 (umgesetzt) | Das Was-wäre-wenn-Panel gibt es zweimal mit leicht anderem Text; die Prognosen-Historie ist ein Audit-Log mit 8 Spalten. | nice-to-have | eine Stelle; letzte Prognose und Abweichung im Review genügen |
| B9 (umgesetzt) | Sprintkalender-Texte behaupten Mo–Fr trotz konfigurierter Arbeitswoche; Fehltage in „Tagen“ (Halbtagskraft) sind missverständlich. | nice-to-have | Texte anpassen; Spaltenhilfe ergänzen |
| B10 | Aktionen „FTE ändern“ und „Austritt erfassen“ statt manuellem Aufteilen von Zeilen. | nice-to-have | später |

## C. Einrichtung

- Die Schritte Team, Kalender, Kapazität, Forecast, Personen und Produkte gibt es als Seiten. Ein
  durchgehender Einrichtungs-Assistent mit kurzer Erklärung je Schritt und Zusammenfassung ist ein
  mögliches späteres Ziel (zusammen mit einer PO-Startseite „Nächsten Sprint vorbereiten“), aber
  keine Voraussetzung für die übrigen Punkte.
- Sinnvolle Standards statt vieler Schalter; abhängige Einstellungen nur bei Bedarf zeigen;
  ungültige Kombinationen ablehnen.

## D. Datenordner und Synchronisation

- Die App kann den Datenordner im Betrieb wechseln (Seite „Datenordner“: wählen, neu anlegen,
  klonen). Geplant: aktives Repo und Team dauerhaft anzeigen, eine Liste der zuletzt benutzten
  Ordner als Umschalter; beim Wechsel ungespeicherte Eingaben behandeln und alte Formularzustände
  verwerfen.
- Wer die App für ein Team ohne gemeinsame Product Owner nutzt, verwendet ein eigenes Daten-Repo.
- Fehltage je Person sind für POs zugänglich, weil sie zur Sprintplanung gehören.
- **Synchronisation über Git.** Heute gibt es Commit in der App. Mindestumfang, damit es für
  Nicht-Techniker alltagstauglich ist, sobald mehrere Personen am selben Daten-Repo arbeiten:
  1. Ein Knopf „Speichern und teilen“ (Pull, Commit, Push) mit Anzeige des Stands (voraus,
     hinterher, offline) und der Änderungen anderer seit dem letzten Laden.
  2. Veraltete Formulare vor dem Speichern erkennen; eigene Änderungen sichern, bevor
     synchronisiert wird.
  3. Konfliktdateien erkennen, **bevor** die YAML geladen wird; die betroffene Bearbeitung ist
     gesperrt, eine geführte Wiederherstellung wird angeboten.
  4. Zusammenführen auf Schlüsselebene (verschiedene Schlüssel derselben Datei werden
     vereinigt); nur echte Wertkonflikte gehen an den Menschen, in der App mit „meine/andere
     Änderung“, danach läuft die Datenprüfung.
  5. Dateien stabil formatiert und sortiert schreiben, damit Konflikte selten werden.
  6. Die Git-Anmeldung eigens einrichten (Credential Manager, SSH-Rückfragen, Dateisperren,
     Zeilenenden unter Windows).
- Ein erreichbarer Git-Ansprechpartner ist hilfreich, ersetzt aber nicht die terminalfreie
  Abnahme: Sie erfolgt mit zwei gleichzeitig arbeitenden Personen und absichtlich erzeugten
  Konflikten.
- „Ein Sprint pro Datei“ hält Konflikte nur dann selten, wenn je Sprint eine Person schreibt.
- Nach jedem Zusammenführen läuft die Gesamtvalidierung: Ein Schlüssel-Merge kann technisch
  gelingen und fachlich ungültig sein (zwei Personen ändern verschiedene Produktanteile, die
  zusammen 120 % ergeben). Dazu gehören gesicherte lokale Änderungen, Abbruch und Wiederaufnahme
  sowie der Umgang mit erneuten Änderungen auf dem Remote beim Push.

### Umfang: alle Alltags-Git-Vorgänge ohne Terminal

Ziel ist, dass eine Person die Daten-Repos vollständig aus der App heraus pflegen kann. Dazu
gehören neben „Speichern und teilen“ und der Konfliktlösung:

- **Änderungen verwerfen** (einzelne Datei oder alles), mit Rückfrage und Anzeige, was verloren
  geht.
- **Verlauf** je Team, Sprint oder Datei anzeigen (wer hat wann was geändert) und einen früheren
  Stand wiederherstellen; die Wiederherstellung ist selbst eine Änderung und rückgängig machbar.
- **Tags** verwalten, nicht nur setzen (anzeigen, nachträglich setzen, löschen).
- **Datenordner** wählen, neu anlegen, klonen und zwischen zuletzt benutzten Ordnern umschalten
  (ein Teil davon gibt es bereits). Dazu gehört der **Server (Remote)**: Adresse eintragen oder
  ändern, validieren und die Verbindung prüfen (`git ls-remote`), statt im Terminal
  `git remote` aufzurufen. Zugangsdaten gehören nie in die Adresse und werden nicht gespeichert
  oder angezeigt; SSH-Schlüssel und globale Git-Konfiguration bleiben außerhalb der App.
- **Anmelde-Hilfe:** fehlende Authentifizierung erkennen und verständlich erklären, was zu tun
  ist (Zugangstoken oder SSH-Schlüssel hinterlegen, Credential Manager).
- **Fehlerzustände** mit klaren Meldungen und nächstem Schritt: offline, Push abgelehnt, Git
  nicht installiert, gesperrte Datei, unvollständiger Merge, detached HEAD.
- Die App ruft weiterhin das Programm `git` auf (keine eigene Git-Bibliothek): Das nutzt die
  Anmeldung des Rechners und ist stabiler. Fehlt Git, erklärt die App die Installation.

Bewusst nicht Teil der App: Branches, Rebase, Force-Push, Stash, Submodule und Ähnliches. Das
Modell bleibt „ein Branch, immer synchron halten“. Wer mehr braucht, nutzt ein Terminal oder
einen Git-Client.

Abnahme: Alle genannten Alltagsvorgänge funktionieren in einem Test mit zwei Personen und
absichtlich erzeugten Konflikten ohne Terminal, einschließlich der Fehlerfälle (offline,
abgelehnter Push, fehlende Anmeldung).

## E. Performance (Phase P)

Die Anwendung ist in erster Linie eine GUI und fühlt sich langsam an. Zwei unabhängige
Messungen (Windows, Python 3.14, Demo-Team mit 22 Sprints und 25 YAML-Dateien) zeigen: Der
Rechenkern braucht etwa 0,25 bis 1,3 ms, ein Team zu laden etwa 18 ms. Die Langsamkeit entsteht
vor und nach der Berechnung, nicht in der Sprache. Gemessen sind nicht: Browserstart,
Frontend-Rendering und Roundtrip.

Maßnahmen (in dieser Reihenfolge):

1. Die Update-Anzeige wartet nicht mehr auf den Hintergrundthread (`result(wait=4.0)` blockiert
   sonst potenziell jeden Durchlauf bis zu 4 Sekunden); das Ergebnis erscheint beim nächsten
   Durchlauf.
2. Der Git-Status wird nicht bei jedem Durchlauf abgefragt, sondern kurz zwischengespeichert und
   nach Speichern, Commit und Synchronisation ungültig gemacht (gemessen: Median etwa 61 ms).
3. Das Team wird nach Dateiversion (inklusive neuer und gelöschter Dateien) zwischengespeichert,
   der Forecast zusätzlich nach Datenstand und Stichtag; nach Speichern und Synchronisation wird
   neu geladen. Seiten laden nur, was sie brauchen.
4. YAML mit dem C-Loader, falls verfügbar (gemessen: etwa 18 auf 6 ms).
5. `pandas`, `altair` und die CLI-Importe werden erst geladen, wo sie gebraucht werden (rund
   1 bis 1,5 Sekunden Kaltstart).
6. Unabhängige Bereiche als Fragmente, Eingaben in Formularen bündeln.

Ziele: Start unter 3 Sekunden, normale Eingaben unter 200 ms. Vorher und nachher wird mit
Stoppuhr auf einem normalen Arbeitsrechner gemessen; das Messprotokoll gehört zum PR.

## F. Technologie

Bewertung durch zwei unabhängige Prüfungen:

- **Python bleibt.** Der Kern ist reines, getestetes Python; die Feiertagsbibliothek `holidays`
  (rund 200 Länder mit Regionen) hat in Rust und Go kein gleichwertiges Gegenstück. Ein Neubau
  in Rust oder Go würde mehrere Monate kosten und die Langsamkeit nicht beheben, weil sie in der
  Architektur (Neuberechnung, Laden, Aufrufe) liegt. Auch dort fehlt ein fertiger Tabellen-Editor.
- **Streamlit bleibt vorerst.** Für Tabellen, Formulare, Diagramme und Sprint-Spalten mit
  Auswahlfeldern reicht es. Grenzen: Neuausführung der Seite bei jeder Eingabe, Zustandsführung,
  Drag-and-drop, Fensterverhalten.
- **Alternative: NiceGUI** (ereignisgesteuert, Tabellen mit AG Grid, Diagramme mit ECharts,
  nativer Modus). Weitere Kandidaten: PySide6/Qt; bei verbindlichem Drag-and-drop oder Roadmap
  FastAPI mit Vue/React; bei gleichzeitiger Zusammenarbeit als Hauptnutzen eine gemeinsame
  Server-Web-App.
- **Technologie-Gate** (nach Phase P, vor K2 und K3): Die gemessenen Zeiten werden gegen die Ziele
  aus E geprüft, und genau ein kritischer Ablauf (Fehltage-Matrix, Forecast-Kachel, ein
  Auslastungsbalken, ungespeicherter Entwurf, Repo-Wechsel) wird als NiceGUI-Spike gebaut und
  gemessen. Erfüllt Streamlit die Ziele, bleibt es. Scheitert es an der Interaktionsarchitektur,
  wird schrittweise migriert; die Kernlogik bleibt dabei unverändert. Rust oder Go erst, wenn
  repräsentative Profile echte CPU-Engpässe zeigen.
- **Entscheidung (Owner):** Streamlit bleibt zunächst. Ein Wechsel wird erst erwogen, wenn er
  notwendig wird (konkrete Probleme aus Nutzertests oder harter Bedarf wie Drag-and-drop). Auf
  weitere Zeitmessungen wird bis dahin verzichtet.
- Zusätzlich: Eine getestete Release-Kombination der Abhängigkeiten festlegen. Die Untergrenze
  `requires-python` wird gesondert entschieden.

## G. Phasen und Reihenfolge

Das Ticketsystem (siehe [konzept-ticketsystem.md](konzept-ticketsystem.md)) beginnt erst, wenn
der Kern vollständig umgesetzt und gut getestet ist.

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **P Performance** | Abschnitt E | Messprotokoll vorher/nachher; Ziele aus E erreicht oder Rest benannt |
| **K1 Berechnung und Zustände** | A1 bis A6, A8, A10, A16, B1, B2 samt fachlichen Tests (Eigenschaftstests, Backtest) | Alle fachlichen Tests grün; der Plan liegt in der Bandbreite; unbekannte und bestätigte Fehltage sind unterscheidbar |
| **Gate Technologie** | Abschnitt F | Messung auf einem Arbeitsrechner; Entscheidung bleiben/migrieren dokumentiert |
| **K2 Begriffe und Anzeige** | B3 bis B7, A7, A9, A11 bis A13 | Eine Person ohne Einweisung trägt Fehltage ein und sieht, wie viel in den nächsten Sprint passt |
| **K3 Datenordner und Sync** | Abschnitt D inklusive Umfang „Alltags-Git ohne Terminal“ (mehrere PRs) | Zwei Personen arbeiten parallel, einschließlich absichtlicher Konflikte, ohne Terminal und ohne Datenverlust; alle Alltagsvorgänge und Fehlerfälle funktionieren in der App; nach jedem Zusammenführen läuft die Gesamtvalidierung |

Die übrigen Punkte (A14, A15, B8 bis B10) können nebenbei oder später folgen.
