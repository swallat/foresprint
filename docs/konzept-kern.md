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

### Tests

- Eigenschaftstests ergänzen: konstante Velocity ergibt konstanten Forecast; der Plan liegt in der
  Bandbreite; ein Feiertagssprint hat weniger Kapazität als ein Normalsprint; Randfall „genau
  `window` Sprints“.
- Rückblickende Prüfung: Prognosen mit damals verfügbaren Daten gegen einen einfachen konstanten
  Forecast vergleichen; Trefferquote behaupteter Wahrscheinlichkeiten prüfen.
- Bestehende Konsistenztests behalten (Stärke), aber nicht mit Fachlichkeit verwechseln.

## B. Bedienung und Begriffe

| # | Punkt | Priorität | Empfehlung |
|---|---|---|---|
| B1 | „Forecast PLAN“ bedeutet je nach Seite die aktuelle Berechnung oder den eingefrorenen Stand. | kritisch | überall „Prognose aktuell“, „Prognose beim Planning“ und die Differenz zeigen |
| B2 | „Weiter ohne Eintrag“ im Planning setzt Fehltage stillschweigend auf „niemand fehlt“; unbekannt und 0 sind zu leicht verwechselbar. | kritisch | expliziter Zustand je Sprint (unbekannt / voraussichtlich / bestätigt) statt der Dateiheuristik; ausdrückliche Bestätigung „niemand fehlt“ |
| B3 | „Forecast IST“ ist die Zusage zu Sprintbeginn, kein Ergebnis. „Roadmap“ bezeichnet einen reservierten Anteil. „erwartete“ und „voraussichtliche“ Fehltage sind zwei Mechanismen mit fast gleichem Namen. | wichtig | z. B. „Zusage“; „Roadmap“-Anteil umbenennen; die beiden Fehltage-Begriffe unterscheidbar machen |
| B4 | 15 bis 16 Seiten mit konkurrierenden Wegen (Produktwerte auf „Produktverteilung“ und auf allen Boards; Sprintauswahl uneinheitlich). | wichtig | Einstieg über Aufgaben („Sprint vorbereiten“, „Planning“, „Sprint abschließen“); Produktverteilung als Auswertung; Stammdaten unter „Team verwalten“ |
| B5 | Unsicherheit steht abseits der Entscheidung (Seite „Analyse“). | wichtig | Spanne, Stichprobengröße und Kapazitätsquelle direkt an der Kachel |
| B6 | Die Formelansicht zeigt nicht die eingesetzten Zahlen; die Formeln der Trend-Modi sind für Nichtfachleute schwer lesbar. | wichtig | kurze Erklärung in Alltagssprache, ausklappbar die eingesetzten Werte und Quellen |
| B7 | Der Einstieg verlangt ein Git-Repository und 6+ Reviews, bevor ein Forecast erscheint. | wichtig | Forecast schon ab 2 bis 3 Sprints (`flat`) mit Hinweis „Historie dünn“ |
| B8 | Das Was-wäre-wenn-Panel gibt es zweimal mit leicht anderem Text; die Prognosen-Historie ist ein Audit-Log mit 8 Spalten. | nice-to-have | eine Stelle; letzte Prognose und Abweichung im Review genügen |
| B9 | Sprintkalender-Texte behaupten Mo–Fr trotz konfigurierter Arbeitswoche; Fehltage in „Tagen“ (Halbtagskraft) sind missverständlich. | nice-to-have | Texte anpassen; Spaltenhilfe ergänzen |
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
- Alternativ nennt der Pilot einen erreichbaren Git-Ansprechpartner. Die Abnahme erfolgt mit
  zwei gleichzeitig arbeitenden Personen und absichtlich erzeugten Konflikten.
- Die Beobachtung der Prüfung: „ein Sprint pro Datei“ hält Konflikte nur dann selten, wenn je
  Sprint eine Person schreibt.

## E. Phasen (Kern)

| Phase | Inhalt | Abnahmekriterium |
|---|---|---|
| **K1 Berechnung** | A1 bis A5 samt Eigenschaftstests; B1 und B2 | Eigenschaftstests grün; der Plan liegt in der Bandbreite; unbekannte und bestätigte Fehltage sind unterscheidbar |
| **K2 Begriffe und Anzeige** | B3 bis B7, A6 bis A13 | Eine Person ohne Einweisung trägt Fehltage ein und sieht, wie viel in den nächsten Sprint passt |
| **K3 Datenordner und Sync** | Abschnitt D | Zwei Personen arbeiten parallel, einschließlich absichtlicher Konflikte, ohne Terminal und ohne Datenverlust |

Die übrigen Punkte (A14, A15, B8 bis B10) können nebenbei oder später folgen.
