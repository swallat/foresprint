# Konzept: Verbesserungen am Kern (ohne Ticketsystem)

Status (Stand 18. Oktober 2026, nach #91): Phase P, K1 bis K3 sowie A14, A15, B8 und B9 sind
umgesetzt, im Einzelnen siehe die Spalte „Stand“ der Tabellen und den Abschnitt G. Offen sind
B10 (nur in der Weboberfläche), der Einrichtungs-Assistent (C) und die Reste, die in den
Tabellen stehen. Außerhalb dieser Phasen kamen seitdem hinzu: Sprint-Protokolle je Termin mit
Sperre gegen gleichzeitiges Schreiben (#84, #90), Excel-Export und -Import je Team (#86, #91) und
die genauere Zuordnung von Git-Fehlern (#81); das Ticketsystem folgt in einem eigenen Konzept. Dieses Dokument sammelt alles, was **unabhängig von einem Ticketsystem**
gilt: Berechnung, Bedienung, Einrichtung, Datenordner und Synchronisation.
Die Ticketanbindung steht in [konzept-ticketsystem.md](konzept-ticketsystem.md); sie ist
optional und baut auf diesen Punkten auf (insbesondere A und D).

Die Punkte stammen aus zwei unabhängigen kritischen Prüfungen des bestehenden Produkts. Sie waren
zunächst **Empfehlungen**; was daraus umgesetzt wurde, zeigt die Spalte „Stand“. Die Priorität ist
die der Prüfenden (kritisch / wichtig / nice-to-have). Der Stand wurde im Oktober 2026 gegen Code,
Tests und Hilfetexte geprüft; wo er „teilweise“ lautet, nennt die Spalte den Rest.

## Grundsatz

Das System muss **ohne** Ticketsystem vollständig funktionieren. Alles in diesem Dokument ist
davon unberührt.

## A. Berechnung

| # | Punkt | Priorität | Empfehlung | Stand |
|---|---|---|---|---|
| A1 | Standard-Trend (`classic`/`linear`) extrapoliert Rauschen, kann sinken oder negativ werden, und liegt ab dem dritten Zukunftssprint unter der eigenen Bandbreite. | kritisch | `flat` (oder Median) als Standard; `classic`/`linear` nur ausdrücklich gewählt, mit Warnhinweis; negative Ergebnisse abfangen | umgesetzt. Rest: Teams mit gespeichertem `classic` bleiben darauf (nur Warnhinweis); im laufenden Sprint rechneten Plan und Spanne mit unterschiedlichen Sprints – behoben („Plan in der Bandbreite“, Entscheidung 18.10.2026): `normalized_history` und `sample_count` zählen dieselben Werte wie der Plan, also auch den schon erfassten Review-Wert (Velocity) des laufenden Sprints; `sample_count` ist auf `forecast.window` gedeckelt und die Schwelle „wenig Daten“ bleibt fest bei 5 (`MIN_SAMPLES`); die Simulation braucht weiter mindestens zwei Werte. Folge: Teams mit `window < 5` sehen den Hinweis „Wenig Daten“ immer, ergänzt um den Satz, dass das Prognosefenster klein gestellt ist (falls das stört, Entscheidung des Owners: Schwelle `min(5, window)` oder eigener Hinweis). Der Lücken-Hinweis nutzt dieselben Sprints wie die Rechnung. „Noch kein Forecast“ hängt an `available_count` (alle verfügbaren Werte, ungedeckelt), nicht an der gedeckelten Stichprobe `sample_count`; bei `window` 1 oder 2 erscheint die Meldung daher nicht neben einem vorhandenen Forecast. Geändert haben sich nur Spanne, Stichprobenzahl und Simulation zwischen Review und Sprintende; die Prognose abgeschlossener Sprints bleibt. Offen: (1) der laufende Sprint selbst hat mit erfasster Velocity den Commitment als Plan (Quelle IST) und kann außerhalb der Spanne liegen; (2) die Garantie „Plan in der Spanne“ gilt bis einschließlich dem laufenden Sprint: Die Engine mittelt auch einen künftigen Sprint mit erfasstem Wert (Import/Datei) ein, die Spanne zählt ihn nicht (Beispiel 10, 12, 8, 14, 11, laufender Sprint ohne Wert, Folgesprint mit Velocity 60: Plan 21,0, Spanne 8–14; Entscheidung offen); (3) `classic`/`linear` bleiben ein bekannter Rest |
| A2 | Ohne bestätigte Fehltage und ohne `absence_history` wird die **Kapazität** per Trend fortgeschrieben, obwohl Personen, Feiertage und Sprintlänge bekannt sind. | kritisch | Kapazität immer aus Kalender und Personen; nur die unbekannten Fehltage schätzen (`absence_history` mit sinnvollem Standard); Trend nur für Teams ohne Personenliste | umgesetzt (Rechnung; die drei Hilfetexte Tooltip „Kapazität“, Hinweis bei `kapazitaet` und „Fehltage zurücksetzen“ nennen seit #67 Kalender und Personen). Rest: die Tabelle von `kapazitaet` zeigt bei Sprints ohne Datei Fehltage 0 ohne den geschätzten Abzug (Anzeige, Entscheidung offen) |
| A3 | Der Punktwert steht ohne Unsicherheit auf der Hauptseite; „85 % Sicherheit“ ist bei wenigen Werten zu stark; Monte Carlo läuft schon mit zwei Messwerten. | kritisch | Bandbreite und Stichprobengröße direkt an der Forecast-Kachel; Warnung bei wenig Daten; Formulierung „modellabhängige Häufigkeit“ | teilweise: Forecast-Seite umgesetzt; CLI (`forecast`) und Bericht warnen bei wenig Daten (K1) und zeigen die Spanne im Abschnitt „Ergänzend“ bzw. in `analyse`, aber nicht in der Forecast-Tabelle; die Kacheln auf Planning, Fehltage und Vorplanung ohne Spanne und Warnung; `analyse --rest` ohne Warnung bei wenig Daten |
| A4 | Bei genau `window` Sprints Historie liefern `classic`/`linear` keinen Forecast; `rolling_average` zählt Positionen statt Werte, Lücken werden still übergangen. | wichtig | Fallback auf `flat` mit Hinweis „Historie dünn“; einheitliche Regel für Lücken, sichtbar gemacht | umgesetzt. Rest: der Lücken-Hinweis erscheint nur in der Weboberfläche |
| A5 | Die Fehltage-Historie überspringt bestätigte Null-Sprints und verzerrt so die Quote; sie nutzt nicht dieselbe Definition wie `absences_known`. | wichtig | dieselbe Definition verwenden; die tatsächlich verwendeten Sprints anzeigen | umgesetzt. Rest: ältere Sprintdateien mit Velocity, aber ohne erfasste Fehltage, zählen als „niemand fehlte“ (Entscheidung offen) |
| A6 | Teilzeit und Arbeitswoche: Wer eine 80-%-Stelle mit vier vollen Tagen als `workweek=mon,tue,wed,thu` und `fte=0.8` einträgt, wird doppelt abgezogen (8 × 0,8). | wichtig | Bedeutung von FTE festlegen und mit Beispielen erklären (FTE = Anteil an den Arbeitstagen der Person oder des Teams) | teilweise: Bedeutung festgelegt und in der Hilfe erklärt; die Spaltenhilfe der FTE und der CLI-Text widersprechen noch |
| A7 | Bei FTE-Wechseln im Sprint werden Fehltage mit der mittleren FTE gewichtet (Näherung). | wichtig | Näherung sichtbar machen | umgesetzt |
| A8 | Overhead: feste Overhead-Tage ersetzen den Prozentabzug (README beschreibt sie als zusätzlich); bei erwarteten Fehltagen wird die Reihenfolge anders gerechnet. | wichtig | eine gemeinsame Berechnung für bestätigte und erwartete Fehltage; README angleichen | umgesetzt |
| A9 | Die Puffer-Empfehlung vergleicht unterschiedliche Bezugsgrößen (Scope Creep bezogen auf Eingeplantes, Kleinkram bezogen auf den Gesamtforecast). | wichtig | gleiche Bezugsgröße verwenden | umgesetzt |
| A10 | Produktanteile: zwei feste Anteile von je 60 % werden nicht abgelehnt; fehlende Erledigt-Werte zählen im Saldo wie 0. | wichtig | Summenprüfung; „fehlt“ von „0“ unterscheiden | teilweise: Weboberfläche umgesetzt; CLI und Bericht zeigen fehlende Erledigt-Werte noch als 0 |
| A11 | Produktionszugriff: „niemand markiert“ ist `None`, nicht 0; die Übersetzung in Liefermenge ist grob. | wichtig | unbekannte Konfiguration und fehlende Berechtigte unterscheiden; als Engpasshinweis kennzeichnen | umgesetzt |
| A12 | Die Aussage „Fokusfaktor ist zwischen Teams vergleichbar“ ist bei Story Points falsch. | wichtig | Aussage entfernen | umgesetzt |
| A13 | Die Referenzkapazität kürzt sich in der Rechnung heraus und ist nur ein Darstellungsmaßstab; Fokusfaktor und normierte Velocity sind dieselbe Größe unter zwei Namen. | wichtig | Referenzkapazität entfernen oder erklären; eine normierte Größe | teilweise: Hilfe erklärt die Referenzkapazität; README sagt noch nicht, dass sie sich herauskürzt; zwei Namen für dieselbe Größe bleiben |
| A14 | Rundung: `round_down` überall ist ein systematischer Bias; die Kapazität wird abgerundet und danach als Nenner genutzt. | nice-to-have | Rundung erst bei der Ausgabe; bewusste Wahl im Hilfetext begründen | umgesetzt (#52, #54) |
| A15 | `trend()` vergleicht mit `is TrendMode.X`; ein Text landet im Zweig `linear`. | nice-to-have | Wert am Anfang in `TrendMode` umwandeln | umgesetzt (#50) |
| A16 | Definition von „Erledigt“: Teilanteile offener Tickets zählen mit (Teampraxis). Ohne Dokumentation ist die Zahl zwischen Teams nicht vergleichbar. | wichtig | Definition in Hilfe und README festhalten. Ein Stichtag für einen Wechsel der Zählweise (wie `unit_since`) ist nur für Teams nötig, die ihre Zählweise ändern, und daher später und optional | umgesetzt |

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

| # | Punkt | Priorität | Empfehlung | Stand |
|---|---|---|---|---|
| B1 | „Forecast PLAN“ bedeutet je nach Seite die aktuelle Berechnung oder den eingefrorenen Stand. | kritisch | überall „Prognose aktuell“, „Prognose beim Planning“ und die Differenz zeigen | teilweise: Planning und Vorplanung zeigen „Prognose beim Planning“ mit der Differenz; die Forecast-Kacheln nennen den eingefrorenen Stand nur im Tooltip (die Tabelle darunter zeigt Stand und Differenz); CLI und Bericht ohne „Prognose beim Planning“ |
| B2 | „Weiter ohne Eintrag“ im Planning setzt Fehltage stillschweigend auf „niemand fehlt“; unbekannt und 0 sind zu leicht verwechselbar. | kritisch | expliziter Zustand je Sprint (unbekannt / voraussichtlich / bestätigt) statt der Dateiheuristik; ausdrückliche Bestätigung „niemand fehlt“ | teilweise: Zustand je Sprint umgesetzt; das Review friert bei „unbekannt“ die volle Besetzung ohne Hinweis ein |
| B3 | „Forecast IST“ ist die Zusage zu Sprintbeginn, kein Ergebnis. „Roadmap“ bezeichnet einen reservierten Anteil. „erwartete“ und „voraussichtliche“ Fehltage sind zwei Mechanismen mit fast gleichem Namen. | wichtig | z. B. „Zusage“; „Roadmap“-Anteil umbenennen; die beiden Fehltage-Begriffe unterscheidbar machen | teilweise: „Forecast IST“ heißt „Commitment“; „Roadmap“ ist nicht umbenannt (Name offen) |
| B4 | 15 bis 16 Seiten mit konkurrierenden Wegen (Produktwerte auf „Produktverteilung“ und auf allen Boards; Sprintauswahl uneinheitlich). | wichtig | Einstieg über Aufgaben („Sprint vorbereiten“, „Planning“, „Sprint abschließen“); Produktverteilung als Auswertung; Stammdaten unter „Team verwalten“ | umgesetzt (#43) |
| B5 | Unsicherheit steht abseits der Entscheidung (Seite „Analyse“). | wichtig | Spanne, Stichprobengröße und Kapazitätsquelle direkt an der Kachel | teilweise: Forecast-Seite umgesetzt; Planning, Fehltage, Vorplanung und CLI ohne Spanne |
| B6 | Die Formelansicht zeigt nicht die eingesetzten Zahlen; die Formeln der Trend-Modi sind für Nichtfachleute schwer lesbar. | wichtig | kurze Erklärung in Alltagssprache, ausklappbar die eingesetzten Werte und Quellen | teilweise: Erklärung in Alltagssprache da; die eingesetzten Zahlen fehlen im Popover |
| B7 | Der Einstieg verlangt ein Git-Repository und 6+ Reviews, bevor ein Forecast erscheint. | wichtig | Forecast schon ab 2 bis 3 Sprints (`flat`) mit Hinweis „Historie dünn“ | umgesetzt |
| B8 | Das Was-wäre-wenn-Panel gibt es zweimal mit leicht anderem Text; die Prognosen-Historie ist ein Audit-Log mit 8 Spalten. | nice-to-have | eine Stelle; letzte Prognose und Abweichung im Review genügen | umgesetzt (#51) |
| B9 | Sprintkalender-Texte behaupten Mo–Fr trotz konfigurierter Arbeitswoche; Fehltage in „Tagen“ (Halbtagskraft) sind missverständlich. | nice-to-have | Texte anpassen; Spaltenhilfe ergänzen | umgesetzt (#51) |
| B10 | Aktionen „FTE ändern“ und „Austritt erfassen“ statt manuellem Aufteilen von Zeilen. | nice-to-have | später | teilweise: Kommandozeile umgesetzt (`personen`: Aktionen n = neue Person, f = FTE ändern, a = Austritt); die Weboberfläche verlangt weiter das manuelle Aufteilen der Zeilen |

## C. Einrichtung

- Die Schritte Team, Kalender, Kapazität, Forecast, Personen und Produkte gibt es als Seiten, und
  die Startseite führt über Aufgaben („Sprint vorbereiten“, „Planning“, „Sprint abschließen“)
  durch den Sprint (umgesetzt, B4). Ein durchgehender Einrichtungs-Assistent mit kurzer Erklärung
  je Schritt und Zusammenfassung ist ein mögliches späteres Ziel (offen), aber keine
  Voraussetzung für die übrigen Punkte.
- Sinnvolle Standards statt vieler Schalter; abhängige Einstellungen nur bei Bedarf zeigen;
  ungültige Kombinationen ablehnen. Stand: die Standards gelten (flacher Trend, vier Sprints
  Fehltage-Historie, Rundung erst bei der Ausgabe); das Einstellungsformular zeigt aber noch alle
  Felder flach, und die Kommandozeile prüft Kombinationen erst nach dem Speichern.

## D. Datenordner und Synchronisation

- Die App kann den Datenordner im Betrieb wechseln (Seite „Datenordner“: wählen, neu anlegen,
  klonen). Sie zeigt aktives Repo, Branch und Team dauerhaft an, bietet die zuletzt benutzten
  Ordner als Umschalter an und verwirft beim Wechsel die alten Formularzustände (umgesetzt).
- Wer die App für ein Team ohne gemeinsame Product Owner nutzt, verwendet ein eigenes Daten-Repo.
- Fehltage je Person sind für POs zugänglich, weil sie zur Sprintplanung gehören.
- **Synchronisation über Git** (umgesetzt, bis auf Punkt 6). Mindestumfang, damit es für
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
  5. Dateien stabil formatiert und sortiert schreiben, damit Konflikte selten werden. Rest:
     Die Vorlage für neue Daten-Repos ignoriert Zwischendateien (`*.tmp`) nur bei neu angelegten
     Repositories und legt keine `.gitattributes` mit LF-Zeilenenden an.
  6. Die Git-Anmeldung eigens einrichten (Credential Manager, SSH-Rückfragen, Dateisperren,
     Zeilenenden unter Windows). Teilweise: die App erkennt fehlende Anmeldung und erklärt den
     nächsten Schritt; eine eigene Anmeldung in der App gibt es bewusst nicht.
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

Stand je Vorgang:

- **Änderungen verwerfen** (einzelne Datei oder alles), mit Rückfrage und Anzeige, was verloren
  geht (umgesetzt).
- **Verlauf** je Team, Sprint oder Datei anzeigen (wer hat wann was geändert) und einen früheren
  Stand wiederherstellen; die Wiederherstellung ist selbst eine Änderung und rückgängig machbar.
  Teilweise: gelöschte Dateien lassen sich nicht einzeln wiederherstellen, und der Verlauf zeigt
  nur die letzten 40 Einträge.
- **Tags** verwalten, nicht nur setzen (anzeigen, nachträglich setzen, löschen; umgesetzt).
- **Datenordner** wählen, neu anlegen, klonen und zwischen zuletzt benutzten Ordnern umschalten
  (umgesetzt). Dazu gehört der **Server (Remote)**: Adresse eintragen oder ändern, validieren und
  die Verbindung prüfen (`git ls-remote`), statt im Terminal `git remote` aufzurufen
  (umgesetzt). Zugangsdaten gehören nie in die Adresse und werden nicht gespeichert oder
  angezeigt; SSH-Schlüssel und globale Git-Konfiguration bleiben außerhalb der App.
- **Anmelde-Hilfe:** fehlende Authentifizierung erkennen und verständlich erklären, was zu tun
  ist (Zugangstoken oder SSH-Schlüssel hinterlegen, Credential Manager). Teilweise: beim Klonen
  und Anlegen eines Datenordners fehlt der Anmelde-Hinweis noch.
- **Fehlerzustände** mit klaren Meldungen und nächstem Schritt: offline, Push abgelehnt, Git
  nicht installiert, Repository nicht gefunden (404, „Repository not found“), nicht anerkanntes
  Zertifikat, nicht beschreibbarer Ordner (`not_writable`), unsicherer Ordner („dubious
  ownership“, `unsafe_directory`: nur Erklärung, die App ändert keine Git-Einstellungen) und der
  unbekannte SSH-Fingerabdruck sind seit #81 einzeln zugeordnet, auch bei Abgleich, Hochladen,
  Klonen und Tags. Gesperrte Datei, unvollständiger Merge und detached HEAD nur teilweise (der
  Hinweis zu `locked` erwähnt bei „unable to unlink“ / „Device busy“ weiter die `index.lock`);
  ein nacktes „Could not read from remote repository“ und „unable to access … 503“ zählen weiter
  als „offline“. „Zurück auf den Branch“ mit offenen Änderungen zeigt einen eigenen Hinweis und
  nennt den Rettungsbranch in der Erfolgsmeldung; das Sichern vor dem Wechsel steht als
  Entscheidung des Owners aus. Schreib- und Lesefehler der
  Datendateien (kein Schreibrecht, Datei gesperrt) zeigen seit #63 eine Meldung mit Datei,
  Ursache und nächstem Schritt, ebenso ein falscher Aufbau der YAML-Dateien seit #64. Offen
  bleiben das Anlegen und Klonen eines Datenordners in einem nicht beschreibbaren Ordner und ein
  nicht lesbarer Datenordner.
- Die App ruft weiterhin das Programm `git` auf (keine eigene Git-Bibliothek): Das nutzt die
  Anmeldung des Rechners und ist stabiler. Fehlt Git, erklärt die App die Installation.

Bewusst nicht Teil der App: Branches, Rebase, Force-Push, Stash, Submodule und Ähnliches. Das
Modell bleibt „ein Branch, immer synchron halten“. Wer mehr braucht, nutzt ein Terminal oder
einen Git-Client.

Abnahme: Alle genannten Alltagsvorgänge funktionieren in einem Test mit zwei Personen und
absichtlich erzeugten Konflikten ohne Terminal, einschließlich der Fehlerfälle (offline,
abgelehnter Push, fehlende Anmeldung). Stand: Die Teilschritte sind einzeln getestet (Sync,
Konflikte, Verlauf, Datenordner, Remote) und die Browsertests in `tests/e2e` bedienen die App
mit zwei Klonen gegen ein gemeinsames Repository; ein durchgehendes Abnahme-Szenario für alle
Fehlerfälle gibt es noch nicht.

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
- **Technologie-Gate** (ursprünglich nach Phase P, vor K2 und K3; durch die Entscheidung unten
  erledigt, der NiceGUI-Spike entfällt): Die gemessenen Zeiten wären gegen die Ziele aus E
  geprüft und genau ein kritischer Ablauf (Fehltage-Matrix, Forecast-Kachel, ein
  Auslastungsbalken, ungespeicherter Entwurf, Repo-Wechsel) als NiceGUI-Spike gebaut und gemessen
  worden. Erfüllt Streamlit die Ziele, bleibt es. Scheitert es an der Interaktionsarchitektur,
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

| Phase | Inhalt | Abnahmekriterium | Stand |
|---|---|---|---|
| **P Performance** | Abschnitt E | Messprotokoll vorher/nachher; Ziele aus E erreicht oder Rest benannt | umgesetzt (#34); Rest: die Stoppuhr-Messung im Browser steht aus (`docs/performance.md`), auf weitere Messungen wird laut Entscheidung in F verzichtet |
| **K1 Berechnung und Zustände** | A1 bis A6, A8, A10, A16, B1, B2 samt fachlichen Tests (Eigenschaftstests, Backtest) | Alle fachlichen Tests grün; der Plan liegt in der Bandbreite; unbekannte und bestätigte Fehltage sind unterscheidbar | gemergt (#35); Reste siehe Tabellen A und B |
| **Gate Technologie** | Abschnitt F | Messung auf einem Arbeitsrechner; Entscheidung bleiben/migrieren dokumentiert | entschieden: Streamlit bleibt, der Spike entfällt (Abschnitt F) |
| **K2 Begriffe und Anzeige** | B3 bis B7, A7, A9, A11 bis A13 | Eine Person ohne Einweisung trägt Fehltage ein und sieht, wie viel in den nächsten Sprint passt | gemergt (#36); Reste siehe Tabellen A und B |
| **K3 Datenordner und Sync** | Abschnitt D inklusive Umfang „Alltags-Git ohne Terminal“ (mehrere PRs) | Zwei Personen arbeiten parallel, einschließlich absichtlicher Konflikte, ohne Terminal und ohne Datenverlust; alle Alltagsvorgänge und Fehlerfälle funktionieren in der App; nach jedem Zusammenführen läuft die Gesamtvalidierung | gemergt (#38, #39, #40, #42, #44, #45, #48, #53); Reste siehe Abschnitt D |

Die übrigen Punkte (A14, A15, B8, B9) sind nebenbei umgesetzt; B10 ist in der Kommandozeile umgesetzt, in der Weboberfläche steht es aus.
