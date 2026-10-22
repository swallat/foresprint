# Foresprint 1.0: Plan und Vorgehen

Entwurf vom 21.10.2026 zur Abstimmung mit dem Maintainer. Stand: Branch `v1` angelegt, Runde 1 der Grundlage läuft.

## 1. Ziel und Rahmen

Für die Version 1.0 entsteht eine neue Oberfläche mit deutlich besserer Bedienung und Geschwindigkeit, ausgeliefert als ein einzelnes Programm. Die Version 0.8.0 bleibt unverändert auf `main`. Die Entwicklung läuft bis zum Release auf dem Branch `v1`.

**Muss in 1.0:**

- Jira-artiges Backlog mit Sortieren und Ziehen, Sofortfilter, Einordnen in Sprints
- Automatischer Hintergrund-Abruf von Jira (standardmäßig nur lesend per PAT; optional schreibbar: Label `planned_for_<sprint>` und, je Team einschaltbar, die Sprintzuordnung des geplanten Sprints) und von Git
- Die heutigen Abläufe: Sprint vorbereiten, Planung, Review, Forecast, Teamverwaltung, Git-Teilen
- Hell und Dunkel, Deutsch und Englisch, flache Icons, keine Emojis
- Ein Programm für Windows ohne Adminrechte (macOS und Linux unterstützt)

**Nicht Ziel von 1.0:** neue Tracker-Anbindungen (GitHub, GitLab), Fileserver- oder SharePoint-Ordner als Speicher, Epic-Roadmap mit Monte-Carlo, Rückschreiben des Einordnens nach Jira (offene Frage 4).

## 2. Technischer Weg (Arbeitsstand, im Prototyp zu prüfen)

- **Kern: vollständige Portierung nach Go** (entschieden 21.10.). Feiertage als eingebettete Datendatei, erzeugt aus der Python-Bibliothek `holidays`. YAML-Dateien bleiben byte-gleich. Kommandozeile als Unterbefehle desselben Programms. Plugins entfallen in 1.0 (Ersatz für den Excel-Import: ein Skill, der einem Agenten erklärt, wie er beliebige Excel-Tabellen in Foresprint-Dateien umsetzt). Die Portierung läuft parallel im Faden "Go-Kern Phase 0", zunächst nur für Teile, die von den neuen Abläufen unabhängig sind.
- **Neue Web-Oberfläche** (HTML, CSS, TypeScript) mit Ziehen, Sofortfilter und virtueller Liste.
- **Fensterhülle: Wails** (entschieden 21.10.). Kern und Oberfläche sind ein Go-Programm; die Oberfläche spricht über Wails-Bindings mit dem Kern.
- **Paket:** ein einziges Programm je Plattform, verteilt über GitHub-Releases statt PyPI. Größe und Startzeit sind Messgrößen.
- **Plattform-Voraussetzungen:** Windows: WebView2-Laufzeit (in Windows 11 enthalten, wird vorausgesetzt). macOS: eingebautes WebKit, nichts zu installieren. Linux: WebKitGTK (bei den meisten Desktops vorhanden).
- Die 0.8 (Python, Streamlit) bleibt bis zur Gleichwertigkeit nutzbar; die Datenformate (YAML) ändern sich nicht.
- **Sprachen:** Deutsch und Englisch umgesetzt, weitere Sprachen technisch möglich (Übersetzungsdateien), aber nicht Teil von 1.0.

## 3. Phasen

| Phase | Ergebnis | Dauer (Kalendertage, Schätzung) | Abnahme durch den Maintainer |
| --- | --- | --- | --- |
| 0 Organisation | Branch `v1`, Meilenstein `v1.0`, Issue-Vorlage, Labels, Aktion zum Schließen von Issues beim Merge nach `v1` | 0,5 | Vorlage und Ablauf ok |
| 1 Grundlage | `PRODUCT.md`, `DESIGN.md`, Inventur der Seiten und Abläufe | 1 | Zielgruppe, Ton, Farben, Schrift |
| 2 Kernabläufe | Klickbare Mocks: Backlog, Sprint-Planung, Forecast; mit impeccable geprüft | 2 bis 3 | Bedienung der drei Abläufe |
| 3 Übrige Bereiche | Start, Abwesenheiten, Team und Produkte, Jira-Anbindung und Sync-Status, Git-Teilen, Einstellungen | 1 bis 2 | Mocks und Abläufe |
| 4 Spezifikation | Zusammenhängendes Dokument (Navigation, Abläufe, Zustände, Tastatur, Fehler), User Stories als Issues mit Akzeptanzkriterien, Architekturentscheidungen | 1 bis 2 | Freigabe der Spezifikation |
| Spur T (parallel zu 1 bis 4) | Kern-Schnittstelle, Hintergrund-Abruf, Prototyp der Hülle mit Windows-Messung (Größe, Start, Ziehen) | 3 bis 4 | Windows-Test |
| 5 Entwicklung | Meilensteine M1 Backlog, M2 Planung und Forecast, M3 übrige Bereiche, M4 Paketierung und Signatur, M5 Beta mit einem Pilotteam | 8 bis 12 | je Meilenstein ein Test durch den Maintainer |
| 6 Release 1.0 | Release-Notiz (Seiten-URLs, Plugin-Schnittstelle, Umbenennung), Tag durch den Maintainer | 1 | Tag |

Gesamtschätzung bis 1.0: 17 bis 25 Kalendertage mit parallelen Fäden. Der kritische Pfad ist die Abnahme durch den Maintainer und der Windows-Test, nicht das Schreiben.

## 4. Arbeitsweise

- **Branches:** Alle PRs für 1.0 gehen gegen `v1`. `main` wird regelmäßig nach `v1` gemerged (Fehlerkorrekturen an 0.8.x). Der stündliche Läufer arbeitet weiter nur auf `main`.
- **Ablage:** Spezifikation und Mocks im Repo unter `docs/redesign/` (Quelle der Wahrheit für das Was). User Stories als GitHub-Issues (Vorlage: Als wer, will ich, damit; Akzeptanzkriterien; Link auf Mock und Spezifikationsabschnitt), Epics mit Unter-Issues, Meilenstein `v1.0`, ein GitHub-Projekt als Tafel obendrauf.
- **Ein Faden pro Issue.** PRs mit `Closes #n`; die Aktion schließt das Issue beim Merge nach `v1`.
- **Review und CI:** Grüne CI, unabhängiges Review durch das höhere Modell, dann Merge nach `v1` durch den Faden. Neue Fäden und Subagents mit Sonnet.
- **Entscheidungen** über den Projektchat als nummerierte Fragen, Fäden arbeiten währenddessen weiter.
- **Design-Regeln:** flache Icons, keine Emojis, keine Textwände (Leitsatz plus Aufklappbereich), Schritte als echte Navigation, Dunkelmodus von Anfang an. Impeccable prüft jede Seite (`audit`, `critique`, `detect`).
- **Leistungsbudget (gemessen, nicht geschätzt):** Eingabe bis sichtbare Antwort unter 100 ms, Sofortfilter unter 50 ms bei 3000 Tickets, Start bis nutzbar unter 3 s, Hintergrund-Abruf blockiert nie die Oberfläche.
- **Definition of Done:** Akzeptanzkriterien erfüllt, Tests grün, Dunkel und Hell geprüft, Tastatur bedienbar, Deutsch und Englisch, Doku und Spezifikation nachgezogen, Messung gegen das Budget.

## 5. Risiken

| Risiko | Gegenmaßnahme |
| --- | --- |
| Langer Branch driftet von `main` weg | Regelmäßiges Zusammenführen von `main` nach `v1`, neue Oberfläche in eigenen Ordnern, gemeinsamer Kern |
| Zu viel Design vor dem ersten Test | Drei Kernabläufe in der Tiefe, der Rest leichter; Prototyp auf Windows früh |
| Fensterhülle verhält sich auf Windows anders (Ziehen, WebView2) | Wails-Prototyp früh auf dem Windows-Rechner des Maintainers; Kern liefert die Oberfläche auch selbst im Browser aus (Rückfallweg) |
| Portierung nach Go verändert Ergebnisse (Feiertage, Monte-Carlo-Zufall) | Vergleichstests gegen die Python-Ergebnisse auf echten Daten vor dem Umstieg |
| Programm zu groß oder zu langsam beim Start | Messen im Wails-Prototyp unter Windows (Größe, Start bis nutzbar unter 3 s) |
| Unsigniertes Programm wird blockiert | Frage 6 (Zertifikat) früh klären |
| Wegfall der Plugins | Excel-Import als Skill für Agenten; Plugin-Schnittstelle erst nach 1.0 neu bewerten |

## 6. Entscheidungen (Stand 21.10.2026)

1. Zielgruppe: beliebige Scrum-Teams, Open Source; keine Interna in Dokumenten, Beispiele mit einem erfundenen Demo-Team. Eine Nutzerart (Scrum Master oder PO).
2. Schrift: Iosevka für Daten, Iosevka Aile für Text und Überschriften (Begründung in `DESIGN.md`, geprüft nach impeccable `typeset`).
3. Hülle und Kern: Wails mit vollständig nach Go portiertem Kern; Verteilung über GitHub-Releases; Plugins entfallen in 1.0.
4. Jira-Rückschreiben: Reihenfolge nein. Label `planned_for_<sprint>` optional; Sprintzuordnung des geplanten Sprints als Team-Option (Standard aus, nur per Knopf mit Vorschau und Rückgängig, Entscheidung 21.10.2026, siehe flows.md Entscheidung 10).
5. WebView2 unter Windows vorausgesetzt (bestätigt); macOS und Linux siehe Abschnitt 2.
6. Code-Signing: der Maintainer klärt ein Zertifikat; bis dahin unsigniert nur zum Testen.
7. Impeccable: direkt aus dem GitHub-Repository (siehe `impeccable.md`).
8. Seitenschicksal: `flows.md` gilt, die Tabelle in `inventory.md` ist überholt.
9. Datenhaltung: Git bleibt in 1.0 der Speicher (Historie, Datenintegrität), mit allen Git-Abläufen inklusive erzwungener Merge Requests. Ein geteilter Ordner (Fileserver, SharePoint) kommt nach 1.0 über dieselbe Schnittstelle (`storage-interface.md`).

10. Reihenfolge: Erst Mockups der Abläufe und Design festlegen (Abnahme durch den Maintainer), parallel nur flow-unabhängige Kern-Portierung.
11. Sprachen: Deutsch und Englisch, weitere möglich, keine weiteren umgesetzt.
12. Geführte Abläufe (22.10.2026): Die Schritt-für-Schritt-Abläufe der Mocks bleiben in 1.0 als Tutorial erhalten (Hilfe > Geführte Abläufe, auf dem Demo-Team, nie auf echten Daten). Siehe flows.md Entscheidung 13.

Offen: GitHub-Projekt als Tafel anlegen (Maintainer).
