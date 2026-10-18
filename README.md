# sprintforecast

Velocity- und Kapazitäts-Forecast für Scrum-Teams. Beantwortet vor allem eine Frage: **Wie viel kann das Team im nächsten
Sprint einplanen?** – auch mitten im laufenden Sprint, für die Planung der POs.

- **Git ist die Datenbank:** YAML-Dateien, ein Sprint pro Datei, gut diff- und mergebar.
- **Geführte Eingabe:** Assistenten für Planning, Review und Fehltage, mit Erklärung zu
  jedem Feld und Plausibilitätsprüfung. Das Planning folgt dem Ablauf am Termin:
  Fehltage → Forecast PLAN & Einplanung → Commitment.
- **Mehrere Produkte:** Standardverteilung, PO-Vorplanung, Planning und Erledigt je Produkt,
  mit Diagrammen und Saldo; die Produktliste kann sich über die Zeit ändern.
- **Aktualisiert sich selbst:** prüft täglich auf eine neue Version und installiert sie nach
  dem Beenden (abschaltbar).
- **Kapazität aus einer Personenliste:** Personen mit Zugehörigkeitszeitraum und FTE,
  planbare Fehltage je Sprint, Feiertage und Arbeitswoche je Land und Region (weltweit, über die
  Bibliothek `holidays`).
- **Nachvollziehbare Rechenlogik:** normierte Velocity, gleitender Durchschnitt und Trend,
  konfigurierbar je Team.
- **Erweiterbar:** Plugins können Befehle und Seiten ergänzen, z. B. Importe.
- **SP/PT-neutral:** Die Schätzeinheit ist eine Team-Einstellung.
- **Deutsch und Englisch:** Oberfläche, Kommandozeile und Bericht in beiden Sprachen; die
  YAML-Dateien sind immer englisch (Schlüssel und Kommentare).

## Installation

Ein Befehl – installiert bei Bedarf [uv](https://docs.astral.sh/uv/), lädt Python 3.14 und
installiert sprintforecast mit Weboberfläche. Git wird für Plugins aus Git-Repositories sowie zum
Anlegen, Committen, Teilen, Verlauf und Klonen der Daten benötigt (auch `sprintforecast datenordner
PFAD` verlangt ein Git-Repository). Ohne Git läuft die App mit einem Datenordner ohne Repository
(`--daten`, `SPRINTFORECAST_DATEN` oder „Ohne Git verwenden“ auf der Seite Datenordner), aber ohne
diese Funktionen.

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.sh | sh
```

Danach ein neues Terminal öffnen.

**Start per Doppelklick:** Das Skript legt einen Starter **„Sprint-Forecast“** an – unter
Windows auf dem Desktop und im Startmenü, unter macOS in `~/Applications` (plus Alias auf dem
Schreibtisch), unter Linux als Programmeintrag und auf dem Desktop. Er startet die
Weboberfläche als App-Fenster (unter Windows ohne Konsolenfenster); beim ersten Start führt
die Oberfläche durch die Einrichtung des Datenordners. Neu anlegen: `sprintforecast
verknuepfung`; Protokoll: `app.log` neben der Plugin-Auswahl.

**Aktualisieren** – automatisch, ähnlich wie bei Claude Code: Beim Start eines Befehls prüft
sprintforecast höchstens einmal am Tag im Hintergrund, ob es eine neuere Version gibt (Feld
`version` in `pyproject.toml` des installierten Branches). Ist eine da, wird sie **nach dem
Beenden** des Befehls mit `uv tool upgrade --reinstall sprintforecast` installiert und gilt ab
dem nächsten Start; Plugins und Python-Version bleiben erhalten. Unter Windows wartet die
Aktualisierung, bis das Programm geschlossen ist (laufende Programme sind dort gesperrt).

| Befehl / Variable | Wirkung |
|---|---|
| `sprintforecast aktualisieren` | sofort prüfen und aktualisieren (`--pruefen`: nur prüfen, `--erzwingen`: neu installieren) |
| `sprintforecast aktualisieren --auto hinweis` | nur auf neue Versionen hinweisen; `--auto aus` schaltet ab, `--auto an` wieder ein |
| `SPRINTFORECAST_AUTOUPDATE=an\|hinweis\|aus` | wie `--auto`, hat Vorrang (z. B. für verwaltete Rechner) |

**In der Weboberfläche:** Beim Start wird im Hintergrund geprüft; ist eine neue Version da,
erscheint sie in der Seitenleiste (beim nächsten Seitenaufbau nach der Prüfung, die Oberfläche
wartet nicht darauf). Sie wird beim Schließen installiert – oder sofort mit
**Jetzt aktualisieren und neu starten**: Die App beendet sich, aktualisiert und öffnet sich
neu (gleiches Datenverzeichnis, gleiche Optionen).

Protokoll und Stand liegen neben der Plugin-Auswahl (`update.log`, `update.json`). Auf einen
Tag festgelegte Installationen (`SPRINTFORECAST_REF=v…`) werden nicht automatisch
aktualisiert. Das Installationsskript erneut auszuführen geht weiterhin.

> Für Maintainer: Eine neue Version wird nur erkannt, wenn `version` in `pyproject.toml`
> (und `__version__`) erhöht wird.

**Plugins:** Das Skript fragt, ob Plugins mitinstalliert werden sollen – mehrere mit `;`
getrennt, als Kurzform `besitzer/repo` (wird zu `git+https://github.com/besitzer/repo`) oder
vollständig `name @ git+https://…`. Die Auswahl wird gemerkt (Windows:
`%APPDATA%\sprintforecast\plugins.txt`, sonst `~/.config/sprintforecast/plugins`); beim
Aktualisieren genügt Enter, `-` entfernt alle Plugins. Plugins aus Git-Repositories brauchen Git,
private zusätzlich eine Anmeldung. Ein Plugin muss die Quelle des Kerns in `[tool.uv.sources]`
festlegen.

Ohne Rückfrage (Umgebungsvariablen vor dem Aufruf setzen):

| Variable | Wirkung |
|---|---|
| `SPRINTFORECAST_WITH="besitzer/repo; …"` | diese Plugins installieren (leer = keine) |
| `SPRINTFORECAST_REF=v1.0` | bestimmten Tag oder Branch statt `main` installieren |
| `SPRINTFORECAST_NO_SHORTCUT=1` | keinen Starter zum Doppelklicken anlegen |

Entfernen: `uv tool uninstall sprintforecast`.

Manuell ohne Skript:

```bash
uv tool install "sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/heads/main.zip"
```

## Sprache / Language

Deutsch ist Standard. Umschalten in der Seitenleiste der Weboberfläche (**Sprache / Language**)
oder mit `sprintforecast sprache en` (bzw. `sprintforecast language de`); die Wahl wird
gemerkt. `SPRINTFORECAST_LANG=en` hat Vorrang. Alle Befehle und wichtigen Optionen haben
englische Namen, z. B. `sprintforecast absences TEAM`, `forecast TEAM --explain SPRINT`,
`--data PATH` – die deutschen Namen funktionieren immer. Die YAML-Dateien sind unabhängig von
der Sprache englisch; nur der Bericht `FORECAST.md` folgt der eingestellten Sprache.

## Schnellstart

```bash
cd sprint-daten                    # Datenverzeichnis: je Team ein Unterordner
sprintforecast web                 # Weboberfläche
sprintforecast hilfe               # Was ist wann zu tun?
sprintforecast forecast team-a     # Prognose auf der Kommandozeile
```

**Datenverzeichnis:** `--daten PFAD`, sonst die Umgebungsvariable `SPRINTFORECAST_DATEN`,
sonst das **aktuelle Verzeichnis**, falls es Teams enthält, sonst der **gemerkte
Datenordner** (Weboberfläche: Seite *Datenordner*, Kommandozeile: `sprintforecast
datenordner PFAD`). Teams sind Unterordner mit einer `team.yaml`; enthält ein Verzeichnis
keine, aber einen Unterordner `teams` mit Teams, wird dieser genommen.

Findet die Weboberfläche keinen Datenordner (keine Teams, kein Git-Repository), führt sie
durch die Einrichtung: vorhandenen Ordner wählen (Git empfohlen, aber nicht Pflicht: ohne Git gibt es keinen Commit; nach „Ohne Git verwenden“ geht es mit **Neues Team** weiter; die Entscheidung wird je Ordner in
den Benutzereinstellungen gemerkt und gilt auch nach dem Neuladen oder in einem neuen Tab), neues
Daten-Repository anlegen (`git init`, `.gitignore`, Ordner `teams` mit `.gitattributes`) oder das gemeinsame
Daten-Repository des Teams klonen.

**Windows PowerShell:**

```powershell
cd "$HOME\sprint-daten"
sprintforecast web
```

Demo ausprobieren (im Ordner dieses Repositorys):

```bash
sprintforecast --daten examples/teams --stichtag 2026-10-15 forecast demo
```

## Weboberfläche

```bash
sprintforecast web                         # im Datenverzeichnis
sprintforecast --daten ../daten-repo web   # oder mit Pfad
```

**Als App (Standard):** `sprintforecast web` öffnet die Oberfläche in einem eigenen Fenster ohne
Adressleiste; Schließen des Fensters beendet auch den Server. `--app` ist weiterhin erlaubt
(Starter und Verknüpfungen verwenden es). Mit `--no-app` öffnet sich stattdessen ein normaler
Browser-Tab und der Server läuft bis Strg+C; mit `--no-browser` öffnet sich nirgends ein
Fenster und der Server beendet sich auch nicht von selbst (z. B. für Tests oder Fernzugriff per
Port-Weiterleitung). Gesucht wird in dieser
Reihenfolge – im PATH (inkl. Scoop-/Chocolatey-Shims) und in den üblichen
Installationsorten (Windows inkl. Scoop- und Chocolatey-Verzeichnissen):

1. App-Modus: Edge, Chrome, Comet, Chromium, Brave, Vivaldi
2. Firefox (kein App-Modus mehr) in einem neuen Fenster
3. Standardbrowser des Systems
4. nichts gefunden → Adresse wird angezeigt, der Server läuft weiter

Einen bestimmten Browser erzwingt `--browser PFAD` bzw. die Umgebungsvariable
`SPRINTFORECAST_BROWSER`. Ist Port 8501 belegt, wird automatisch ein freier gewählt.

Startet eine lokale Weboberfläche unter <http://localhost:8501>. Sie ist nur auf dem
eigenen Rechner erreichbar und braucht kein Hosting; die Daten bleiben im lokalen
Git-Klon. Die Oberfläche liest und schreibt **dieselben YAML-Dateien** wie die
Kommandozeile und prüft vor jedem Speichern:

| Bereich | Seite | Inhalt |
|---|---|---|
| Aufgaben (in zeitlicher Reihenfolge) | Start | drei Aufgaben-Kacheln („Sprint vorbereiten“, „Planning“, „Sprint abschließen“); jede führt je nach Stand des Sprints zur nächsten sinnvollen Seite (z. B. Fehltage unbekannt oder nur angekündigt → Fehltage) |
| | Sprint vorbereiten: Fehltage | Tabelle Person × Sprint mit Live-Vorschau von Kapazität und Forecast; Stand je Sprint, „Niemand fehlt“ ausdrücklich bestätigen |
| | PO-Vorplanung | je Produkt vorsehen, was in den Sprint soll – im Vergleich zum Standard, Summe je PO; angekündigte Fehltage |
| | Planning | geführter Ablauf: 1. Fehltage, 2. Forecast PLAN & Einplanung je Produkt, 3. Commitment |
| | Sprint abschließen (Review) | Velocity, Scope Creep, Erledigt je Produkt, nicht erledigt/zusätzlich erledigt; verfügbare Personentage werden eingefroren |
| Auswertung | Forecast | Prognose für laufenden + kommende Sprints (mit Spanne), Verlauf, Diagramm, Bericht schreiben |
| | Analyse | ergänzend: Bandbreite, Fokusfaktor, Puffer-Empfehlung, „Wann ist es fertig?“ |
| | Produktverteilung | reine Auswertung: Standard, PO-Vorplanung, Planning, Erledigt je Produkt; Diagramme, Verlauf, Saldo; geändert werden die Werte nur auf den Boards (Links auf der Seite) |
| Team verwalten | Sprintkalender | kommende Sprints mit Start, letztem Tag und Arbeitstagen; anlegen, Länge anpassen |
| | Personen | eine Tabelle (Zeile je Zeitraum, FTE); IDs automatisch; Ehemalige ausblendbar |
| | Produkte | Produktliste mit PO und Zeitraum (ab/bis); Ehemalige ausblendbar |
| | Einstellungen | alle Team-Einstellungen; Änderungen werden vor dem Speichern angezeigt |
| | Neues Team | Team anlegen |
| Daten & Hilfe | Datenordner | Datenordner wählen, neu anlegen oder klonen (Git-Repository); Server (Remote) eintragen, prüfen und ändern |
| | Änderungen und Verlauf | Offene Änderungen verwerfen, Verlauf je Team/Sprint/Datei, früheren Stand wiederherstellen, Tags verwalten |
| | Prüfung | Befunde aller Teams |
| | Hilfe | Reiter Ablauf, Begriffe, Eingabefelder, Team-Einstellungen, Zusammenarbeit (Git) und Kommandozeile |

Die Startseite bietet die drei Aufgaben **Sprint vorbereiten**, **Planning** und **Sprint abschließen**; der **Forecast** („Wie viel passt in den nächsten Sprint?“) steht unter **Auswertung**. Die Sprintauswahl ist auf allen Seiten gleich (Beschriftung „Sprint“, gleiche Reihenfolge, Vorgabe: laufender Sprint) und gilt seitenübergreifend. Produktwerte (PO-Vorplanung, Planning, Erledigt) werden ausschließlich auf den Boards erfasst; die Seite **Produktverteilung** ist nur Auswertung. Ohne offenen Sprint verweisen „Sprint vorbereiten“ und „Planning“ auf den Sprintkalender.

Auf den Aufgabenseiten **Sprint vorbereiten: Fehltage**, **PO-Vorplanung**, **Planning** und **Sprint abschließen (Review)** (Reihenfolge wie in der Seitenleiste) zeigt oben eine Schrittleiste den Stand des gewählten Sprints und wechselt mit einem Klick zwischen den vier Schritten; der aktive Schritt ist blau hinterlegt. Erledigte Schritte tragen ein grünes Haken-Symbol hinter dem Namen (offene Schritte kein Zeichen); der Tooltip sagt „erfasst für Sprint …“ bzw. „noch offen für Sprint …“. Der Haken kommt aus den Sprintdaten: bei den Fehltagen nur für den Stand „bestätigt“ (eingetragen oder ausdrücklich „niemand fehlt“; „angekündigt“ und „unbekannt“ bekommen keinen Haken, und die Aufgabe „Sprint vorbereiten“ der Startseite führt dann ebenfalls zu den Fehltagen), bei PO-Vorplanung eine erfasste Vorplanung je Produkt, bei Planning das Commitment, beim Review die Velocity. Teams ohne den Funktionsbereich Produkte haben nur die drei Schritte ohne PO-Vorplanung.

**Speichern, Committen und Teilen:** Jede Seite speichert in die YAML-Dateien. Die Seitenleiste
zeigt unter **Git** den Stand gegenüber dem Server (noch nicht geteilt, neu von anderen, offline,
wann zuletzt geprüft) und die offenen Änderungen im Datenverzeichnis.

- **Speichern und teilen** sichert zuerst die eigenen Änderungen (Commit, nach einem Review
  optional mit Tag `TEAM/SPRINT`), holt dann den Stand der anderen, führt beides zusammen und lädt
  es hoch. Danach steht in der Seitenleiste, was von anderen übernommen wurde (wer, wann, welche
  Dateien). Bei einem Wettlauf (jemand lädt zwischendurch hoch) wird erneut geholt und
  hochgeladen. Hat der Server eine ganz andere Historie (meist das falsche Repository, z. B. ein
  Code-Repository), wird nichts zusammengeführt oder hochgeladen, sondern mit Hinweis abgebrochen;
  nur nach ausdrücklicher Bestätigung in der Seitenleiste (Kästchen „Ja, beide Historien
  zusammenführen“, Vorgabe ist Abbrechen; die Meldung nennt Server und Branch) wird trotzdem
  zusammengeführt. Hinweise trotz Erfolg (z. B. ein Tag, der auf einen anderen Stand zeigt) stehen
  unter dem Ergebnis. Ein Tag, den es lokal schon
  gibt, bricht das Speichern ab, bevor etwas committet wird. Verschiedene Werte derselben Datei (z. B. Fehltage von Anna und von Ben im selben
  Sprint, zwei verschiedene Personen in `people.yaml`) werden automatisch vereinigt. Nur wenn beide
  denselben Wert unterschiedlich geändert haben, ist die Bearbeitung gesperrt, und die Seite
  **Konflikte lösen** fragt je Eintrag „Meine Änderung“ oder „Andere Änderung“ (Dateien, die auf
  einer Seite gelöscht wurden, werden als Ganzes entschieden). Das Zusammenführen kann dort auch
  abgebrochen werden; nichts geht verloren, der eigene Commit bleibt erhalten. Ein offenes
  Zusammenführen übersteht einen Neustart der App.
- **Gesamtvalidierung:** Nach jedem Zusammenführen läuft die Datenprüfung. Ein technisch sauberer
  Merge kann fachlich ungültig sein (zwei Personen ändern verschiedene Produktanteile, zusammen
  120 %): Neue Fehler halten das Hochladen an, die Liste zeigt sie; nach der Korrektur genügt
  „Speichern und teilen“, oder bewusst **Trotzdem teilen**.
- **Veraltete Formulare:** Ändern sich die Dateien, während eine Seite offen ist (Teilen, anderes
  Programm), werden nicht gespeicherte Eingaben mit Hinweis verworfen und neu geladen, statt fremde
  Änderungen zu überschreiben. Konfliktmarkierungen in einer Datei (`<<<<<<<`) werden erkannt,
  bevor die YAML geladen wird; die Seite bietet dann die Wiederherstellung an.
- **Stabile Dateien:** Gespeichert wird immer mit LF-Zeilenenden, nur bei geändertem Inhalt und
  über eine Zwischendatei; Fehltage, erledigte Produkte usw. stehen alphabetisch sortiert, damit
  gleichzeitige Ergänzungen selten kollidieren.
- **Stand prüfen** fragt den Server, ob es Neues gibt, und ändert nichts. Der Serverstand wird
  nur dabei und beim Teilen abgefragt.
- **Änderungen committen** sichert nur lokal, ohne zu teilen.
- Fehlerfälle erklärt die App verständlich mit nächstem Schritt: Server nicht erreichbar,
  Repository nicht gefunden (Adresse prüfen), nicht anerkanntes Zertifikat, Hochladen abgelehnt
  (inzwischen Neues da bzw. vom Server verboten), fehlende Anmeldung (https-Zugangstoken bzw.
  SSH-Schlüssel, Credential Manager; bei SSH auch der unbekannte Server-Fingerabdruck), Git nicht
  installiert, gesperrte Datei, nicht beschreibbarer oder von Git als unsicher abgelehnter Ordner,
  fehlender Name/E-Mail (wird abgefragt), unvollständiges Zusammenführen (Abbrechen) und detached
  HEAD (zurück auf den Branch). Git fragt nie im Hintergrund nach einem Kennwort; die Anmeldung des
  Rechners (Credential Manager, SSH-Agent) wird genutzt.
- **Server (Remote) eintragen:** Hat ein Datenordner noch keinen Server, verweist die Seitenleiste
  („Server einrichten“) auf die Seite **Datenordner**; dort steht der Abschnitt **Server
  (Remote)** auch zum Ändern der Adresse. Die Adresse wird sofort geprüft (erlaubt sind
  `https://…`, `ssh://…`, `git@server:pfad` und vollständige Ordnerpfade; `http://` nur nach
  ausdrücklicher Bestätigung), **Verbindung prüfen** fragt den Server nach seinen Branches und
  ändert nichts, **Speichern** prüft erneut und speichert nur bei bestandener Prüfung. Ist der
  Server nachweislich nicht erreichbar (Netzwerkfehler, Zeitüberschreitung) oder fehlt ihm der
  lokale Branch, lässt sich die Adresse nur mit ausdrücklicher Bestätigung trotzdem speichern;
  ein nicht gefundenes Repository (Tippfehler im Projektnamen), eine abgelehnte Anmeldung oder
  ein nicht anerkanntes Zertifikat werden nie gespeichert. Hat der neue Ordner noch keine Daten,
  der Server aber schon, warnt die Maske und verweist auf **Repository klonen**.
  Zugangsdaten (Benutzername, Kennwort, Token) in
  der Adresse werden abgelehnt, nie gespeichert und nie angezeigt; die Anmeldung übernimmt wie
  immer der Anmeldedienst des Rechners, fehlt sie, erklärt die App den nächsten Schritt. Die App
  legt keine SSH-Schlüssel an und ändert die globale Git-Konfiguration nur auf Wunsch und nur für
  Name und E-Mail der Commits. Mehrere Adressen oder eine eigene Upload-Adresse (`pushurl`) sowie
  ein offenes Zusammenführen sperren das Speichern. Wer einem bestehenden Team beitritt, wählt
  besser **Repository klonen**.

- **Datenordner wechseln:** Die Seitenleiste zeigt Datenordner (mit übergeordnetem Ordner, z. B.
  `daten/teams`) und Branch dauerhaft; die Liste der zuletzt benutzten Ordner (bis zu 8, in den
  Benutzereinstellungen gemerkt) dient als Umschalter in der Seitenleiste und auf der Seite
  **Datenordner** (dort auch „Entfernen“ aus der Liste). Der Datenordner gilt je Browser-Fenster:
  Wechselt ein Fenster, arbeiten andere offene Fenster in ihrem Ordner weiter; neu geöffnete
  Fenster starten im zuletzt gewählten. Beim Wechsel werden nicht gespeicherte Formulareingaben
  und alle Zwischenspeicher (Teams, Git-Stand) des alten Ordners verworfen; vorgemerkte Tags, die
  Commit-Nachricht und offene Änderungen im alten Ordner bleiben dort erhalten und sind beim
  Zurückwechseln wieder da.
- **Offenes Zusammenführen sperrt das Schreiben:** Solange ein Zusammenführen oder Rebase offen
  ist, sind alle Teamseiten, **Neues Team** und Plugin-Seiten durch die Konfliktlösung ersetzt; auf
  der Seite **Änderungen und Verlauf** sind Wiederherstellen, Zurücknehmen, Verwerfen und Tags
  deaktiviert.
- **Änderungen und Verlauf** (eigene Seite): *Verwerfen* einzelner Dateien oder aller offenen
  Änderungen mit Anzeige, was verloren geht, und Bestätigung (eine Kopie landet im Papierkorb unter
  `.git/sprintforecast-verworfen`). *Verlauf* je Team, Sprint oder Datei (wer, wann, was);
  *Wiederherstellen* eines früheren Stands ist selbst ein Commit und mit „Diese Änderung
  zurücknehmen“ rückgängig zu machen (Zusammenführungen lassen sich so nicht zurücknehmen). *Tags*
  anzeigen, nachträglich an einen beliebigen Stand setzen und löschen, jeweils auch auf dem Server
  (scheitert das, bleibt der Tag lokal und die App sagt es). „Mit dem Server abgleichen“ (Netzwerk,
  nur auf Klick) zeigt je Tag, ob er nur lokal, nur auf dem Server oder unterschiedlich ist; nur
  lokale Tags lassen sich mit „Zum Server übertragen“ nachholen, auch Tags, die es nur auf dem
  Server gibt, lassen sich löschen. Beim Verwerfen erscheinen Umbenennungen als „umbenannt: alt →
  neu“. Lassen sich die Benutzereinstellungen nicht speichern (Ordner nicht beschreibbar), zeigt die
  App die Meldung mit dem nächsten Schritt, und der Wechsel bzw. die Änderung unterbleibt.

Committet wird nur das Datenverzeichnis, Tabellenkalkulationen (`*.xlsx` …) werden abgelehnt. Das
Modell ist „ein Branch, immer synchron halten“; Branches, Rebase, Force-Push und Stash gehören
bewusst nicht zur App. Der Git-Stand wird kurz (5 Sekunden) zwischengespeichert; Änderungen
außerhalb der App (Editor, Terminal) erscheinen daher mit kleiner Verzögerung, eigene
Speicherungen sofort.

## Ablauf im Sprint

| Wann | Befehl | Was passiert |
|---|---|---|
| Sprints vorab anlegen | `sprintforecast sprints team-a --anlegen` | Kommende Sprints (Start, letzter Tag, Arbeitstage) anzeigen und Dateien anlegen; `--ende 2026.25=2027-01-12` verlängert einen Sprint, die folgenden verschieben sich. |
| Urlaub o. Ä. wird bekannt | `sprintforecast fehltage team-a [SPRINT]` | Fehltage je Person erfassen (Standard: nächster Sprint). Zeigt Kapazität und Prognose. |
| Team ändert sich | `sprintforecast personen team-a` | Person hinzufügen, FTE ändern, Austritt eintragen. |
| Einstellungen ändern | `sprintforecast einstellungen team-a` | Bundesland, Referenzkapazität, Trend-Modus usw. geführt ändern; zeigt die Änderungen vor dem Speichern. |
| Produkte ändern sich | `sprintforecast produktliste team-a` | Produkt anlegen, PO ändern, Produkt abgeben (mit Enddatum). |
| PO-Vorplanung | `sprintforecast produkte team-a --vorplanung` | POs tragen je Produkt ein, was sie vorsehen; Vergleich mit dem Standard. |
| Sprint Planning | `sprintforecast planning team-a` | Geführt: 1. Fehltage, 2. Forecast PLAN und Planning je Produkt, 3. Commitment (+ optional Kontrollrechnung). Friert den Forecast PLAN ein. Standard: nächster noch nicht geplanter Sprint. |
| Sprint Review | `sprintforecast review team-a --commit` | Erfasst Velocity, Scope Creep und Erledigt je Produkt, friert die verfügbaren Personentage ein, committet und setzt Tag `team-a/<sprint>`. |
| PO-Planung | `sprintforecast forecast team-a` | Prognose für laufenden + nächste Sprints. |
| Produktauswertung | `sprintforecast produkte team-a [SPRINT]` | Verteilung je Produkt und Saldo der letzten Sprints. |
| Bericht | `sprintforecast bericht [team-a]` | Schreibt `teams/team-a/FORECAST.md` (Tabelle + Mermaid-Diagramm). |
| Excel | `sprintforecast excel team-a [-o datei.xlsx]` | Schreibt eine Excel-Liste (Rückweg für alle, die mit Excel weiterarbeiten): Sprintwerte als Eingaben (gelb), n. Velocity, Durchschnitt, Trend, Forecast PLAN, Roadmap und Kleinkram als echte Formeln, Aufteilung nach Produktionszugriff und je Produkt, zwei Trend-Diagramme. Braucht den Zusatz `[excel]` (`uv tool install "sprintforecast[web,excel] …"`); nicht im Datenordner ablegen (`*.xlsx` wird nicht committet). In der Weboberfläche: Seite Forecast → „Excel-Liste erstellen“. Die Mappe enthält das ganze Team (Einstellungen, Personen, Produkte, alle Sprints mit Fehltagen, Produktwerten und Prognosen). |
| Excel-Import | `sprintforecast excel-import team-a datei.xlsx [--uebernehmen]` | Liest eine solche Mappe zurück (nur die gelben Eingabezellen, nach fester Spaltenposition) und zeigt zuerst je Datei und Wert, was sich ändert; mit `--uebernehmen` werden nur die geänderten Dateien geschrieben. Sprintdateien, die in der Mappe fehlen, bleiben unverändert. Unabhängig vom früheren Import-Plugin, das weiter die ursprüngliche Excel-Liste einliest. |
| Vor dem Commit / CI | `sprintforecast pruefen` | Fehler und Plausibilität aller Teams prüfen. Meldet auch stille Annahmen beim Laden als Hinweis mit Datei, Zeile und Schlüsselpfad: doppelte Schlüssel in einer Datei (es zählt nur der letzte Eintrag) und leere Zahlenfelder, die als 0 gelesen werden (z. B. `fte:` ohne Zahl, leere Fehltage). Geladen und gerechnet wird unverändert. Gleiches zeigt die Seite „Prüfung“ der Weboberfläche. |

### PO-Vorplanung und Planning

- **Angekündigte Fehltage:** Auf dem Board *PO-Vorplanung* lassen sich schon vor dem Planning
  Fehltage je Person als **Prognose** eintragen. Sie wirken auf Kapazität (Quelle „angekündigte
  Fehltage“) und Forecast PLAN, gelten aber nicht als bestätigt. Im *Planning* (Schritt 1) sind sie
  vorbelegt; erst „Fehltage speichern und weiter“ bestätigt sie. Bestätigte Fehltage haben immer Vorrang.
- **Stand der Fehltage je Sprint** (unbekannt / angekündigt / bestätigt) ist überall sichtbar
  (Forecast, Fehltage, Planning). „Weiter ohne Bestätigung“ im Planning bestätigt **nichts**: Wer wirklich
  keine Fehltage hat, bestätigt das ausdrücklich („Niemand fehlt – bestätigen und weiter“ bzw. Spalte
  *Niemand fehlt* auf der Seite *Sprint vorbereiten: Fehltage*). Das Speichern von Planning-Werten (Commitment, Einplanung)
  ändert den Stand der Fehltage nicht. Das Datum, an dem ein Sprint geplant wurde, ist kein Beleg mehr.
- **Einplanung aus der Vorplanung:** Im Planning (Schritt 2) ist die Einplanung je Produkt mit der
  letzten PO-Vorplanung vorbelegt (bitte prüfen und speichern).
- **Einfrieren aufheben:** Der beim Planning eingefrorene Forecast PLAN lässt sich auf dem Planning-Board
  nur nach Bestätigung einer Fehlerkorrektur freigeben. Tickets, die nach dem Planning hinzugezogen oder
  herausgenommen werden, gehören nicht nachträglich ins Planning, sondern fließen im *Review* ein
  (Davon nicht erledigt / Zusätzlich erledigt).

### Längere oder kürzere Sprints (z. B. über Weihnachten)

Einzelne Sprints lassen sich verlängern oder verkürzen, indem man ihren **letzten Tag** ändert:

- **Weboberfläche:** Seite *Sprintkalender* → in der Zeile des Sprints den **Letzten Tag** ändern →
  *Sprints anlegen bzw. speichern*. Die Spalte *Arbeitstage* zählt die Arbeitstage der konfigurierten Arbeitswoche des Teams (Standard Mo–Fr) mit.
- **Kommandozeile:** `sprintforecast sprints team-a --ende 2026.25=2027-01-12` (Form `SPRINT=letzter Tag`, mehrfach möglich).
- **Folgesprints:** Jeder folgende Sprint beginnt am Tag nach dem letzten Tag des vorherigen und behält seine
  bisherige Länge; noch nicht angelegte Sprints bekommen neue IDs. Die Standard-Sprintlänge (Einstellung
  *Sprintlänge*) gilt nur für neu erzeugte Sprints.
- **Forecast:** Die Kapazität zählt die tatsächlichen Arbeitstage des Sprints (abzüglich Feiertage und Fehltage), die
  Velocity ist auf die Kapazität normiert. Ein Sprint mit doppelt so vielen Arbeitstagen erhält daher etwa den
  doppelten Forecast PLAN, und die Normierung bleibt mit den kürzeren Sprints vergleichbar.
- **Brückentage:** Amtliche Feiertage der eingestellten Region werden automatisch abgezogen; Brückentage sowie
  24. und 31. Dezember trägt man als **Fehltage** je Person ein.
- **Review:** Wie bei jedem Sprint Velocity eintragen; die Kapazität wird eingefroren. Für einen bereits erfassten
  Sprint ändert man das Ende nachträglich über denselben Weg; die Sprintdatei behält ihre Daten.

Alle Assistenten erklären jedes Feld (was, woher, Beispiel). Nachschlagen:
`sprintforecast hilfe begriffe`, `… hilfe felder`, `… hilfe team`.

## Code- und Daten-Repository trennen

Dieses Repository enthält **nur Code und Demo-Daten**. Echte Team-Daten liegen in einem
eigenen Daten-Repository innerhalb der Unternehmensdomäne (`*.xlsx` und `/teams/` sind
hier per `.gitignore` ausgeschlossen). Vorlage: [`templates/daten-repo/`](templates/daten-repo):

```
daten-repo/
├─ mise.toml                      # Tool-Versionen + Task `mise run sf -- …`
├─ .gitignore, .gitattributes     # keine Tabellenkalkulationen und *.tmp; YAML und Berichte immer mit LF
├─ .github/workflows/forecast.yml # prüft Änderungen, aktualisiert FORECAST.md (auf GitLab analog)
└─ teams/
   ├─ team-a/
   │  ├─ team.yaml
   │  ├─ people.yaml
   │  ├─ products.yaml            # optional
   │  ├─ FORECAST.md              # erzeugt
   │  └─ sprints/2026.20.yaml …
   └─ team-b/ …
```

Parallele Pflege durch POs und Scrum Master funktioniert, weil jeder Sprint eine eigene
Datei ist. Abgeschlossene Sprints werden per Tag `TEAM/SPRINT` markiert.

## Dateiformate

**Funktionsbereiche:** Nicht jedes Team braucht alles. Drei Bereiche sind unabhängig voneinander
zuschaltbar (Einstellungen bzw. Abschnitt `features` in `team.yaml`) und bei **neuen Teams aus**:

| Bereich (`features.…`) | Wirkung, wenn an | Wenn aus |
|---|---|---|
| `products` – Produktverteilung | Produktliste, PO-Vorplanung, Planning und Erledigt je Produkt, Standardverteilung, Saldo | diese Seiten und Eingaben entfallen |
| `po` – Zuordnung PO | Spalte PO je Produkt, Summen je PO (sinnvoll nur mit `products`) | keine PO-Spalte, keine Summen je PO |
| `production` – Produktionszugriff | Personen als berechtigt markieren, Menge mit Produktionszugriff im Planning/Review (je Produkt, ohne Produktverteilung je Sprint), Engpass-Hinweis | keine Markierung, keine Eingaben, kein Hinweis |

Ausgeschaltete Bereiche löschen nichts: Bereits erfasste Werte bleiben in den Dateien und
erscheinen wieder, sobald der Bereich eingeschaltet wird. **Ältere `team.yaml` ohne `features`**
bleiben wie bisher nutzbar: Beim Laden gilt `products` an, wenn Produkte erfasst sind, `po`, wenn
ein Produkt einen PO hat, und `production`, wenn eine Person als berechtigt markiert ist; beim
nächsten Speichern der Einstellungen wird der Abschnitt geschrieben.

**`team.yaml`** – Einstellungen (alle optional außer `name`; geführt änderbar mit `einstellungen`):

```yaml
name: Team A
unit: PT                    # PT oder SP (Kapazität ist immer PT)
features:                   # optionale Bereiche, bei neuen Teams alle false
  products: false           # Produktverteilung
  po: false                 # Zuordnung PO
  production: false         # Produktionszugriff
sprint:
  length_days: 14
  numbering: yearly         # 2026.1, 2026.2 … | sequential: 1, 2, 3 …
  first: {id: '2026.20', start: 2026-10-14}   # nur nötig, solange keine Sprintdatei existiert
forecast:
  reference_capacity: 67    # Bezug der normierten Velocity
  window: 5                 # gleitender Durchschnitt
  roadmap_share: 0.8
  rounding: 1               # Forecast PLAN wird abgerundet (Kapazität: intern ungerundet)
  trend_mode: flat        # flat (Standard) | classic | linear – die beiden letzten schreiben Rauschen fort
  horizon: 3                # künftige Sprints in der Prognose
  product_basis: plan       # Standard je Produkt aus: plan (Forecast PLAN) | roadmap
capacity:
  overhead_share: 0.0       # pauschaler Abzug für Scrum-Termine
  overhead_days: 1          # optional: fester Abzug in PT je Person und Sprint (× FTE); ersetzt
                            # overhead_share (derselbe Abzug in zwei Einheiten, nicht addiert)
  absence_history: 4        # Standard 4: Kapazität von Sprints mit unbekannten Fehltagen um die
                            # Ø Fehltage der letzten 4 Sprints mit bestätigten Fehltagen mindern
                            # (0 = keine Schätzung, dann ohne Abzug)
  country: DE               # optional (Standard DE): ISO-Ländercode für Feiertage und Wochenende
  region: NW                # Region im Land (Bundesland, Staat, Provinz), z. B. NW, CA, ON
  workweek: auto            # optional: auto (wie im Land) | mon-fri | sun-thu | mon-sat
  rounding: 1               # optional: Stellen der angezeigten und im Review eingefrorenen
                            # Kapazität (kaufmännisch gerundet); die Prognose rechnet ungerundet
```

**`people.yaml`** – Personen werden nie gelöscht, nur Zugehörigkeiten beendet:

```yaml
people:
- id: ben
  name: Ben
  region: BY                # optional, sonst Team-Region
  country: AT               # optional: abweichendes Land der Person (Feiertage, Wochenende)
  workweek: mon,tue,wed,thu # optional: eigene Arbeitswoche, z. B. 4-Tage-Woche (sonst Land/Team)
  production_access: true   # optional: darf Tickets mit Produktionszugriff bearbeiten
  memberships:
  - {from: 2025-01-01, to: 2026-05-31, fte: 1}
  - {from: 2026-06-01, to: null, fte: 0.5}
```

**FTE und Arbeitswoche:** `fte` ist der Anteil an den **Arbeitstagen der Person** (1 = alle ihre
Arbeitstage). Die Arbeitswoche (`workweek`) legt fest, welche Wochentage das sind. Teilzeit bitte nur
**einmal** abbilden, sonst wird doppelt abgezogen. Beispiel mit 10 Arbeitstagen (Mo–Fr) im Sprint:

| Eintrag | Kapazität |
|---|---|
| `workweek: mon-fri` (Standard), `fte: 0.8` | 10 × 0,8 = **8 PT** |
| `workweek: mon,tue,wed,thu`, `fte: 1` | 8 Arbeitstage × 1 = **8 PT** |
| `workweek: mon,tue,wed,thu`, `fte: 0.8` (doppelt!) | 8 × 0,8 = 6,4 PT |
| `workweek: mon-fri`, `fte: 0.5` (halbtags) | **5 PT** |

**`products.yaml`** (optional) – Produkte nie löschen, sondern mit `to:` beenden:

```yaml
products:
- {id: webshop, name: Webshop, po: Alex, from: null, to: null}
- {id: partner, name: Partnerportal, share: 0.1}  # laut Vereinbarung 10 % der Kapazität
- {id: portal, name: Kundenportal, po: Bea, from: 2026-09-02, to: null}
- {id: altsystem, name: Altsystem, po: Bea, from: null, to: 2026-09-15}
```

**`sprints/<id>.yaml`** – leere Felder sind `null` (= keine Angabe):

```yaml
id: '2026.21'               # in Anführungszeichen!
start: 2026-10-14
end: 2026-10-28             # = Start des nächsten Sprints (exklusiv); letzter Tag 27.10.
absences: {ben: 3, cem: 5}  # planbare Fehltage (Arbeitstage), ohne Feiertage
capacity: null              # wird beim Review eingefroren; manuell nur ohne Personenliste
forecast_ist: 10
velocity: null
scope_creep: null           # Anteil, 0.3 = 30 %
planning: {carryover: 0.25, backlog: 9.48, corrections: [1.5]}
forecast_plan: 10.1         # Forecast PLAN beim Planning (eingefroren), optional
absence_state: confirmed   # Stand der Fehltage: unknown | expected | confirmed. „confirmed“ auch ohne
                           # Einträge („niemand fehlt“, ausdrücklich bestätigt); „unknown“: Kapazität
                           # aus Kalender und Personen, Fehltage nach der Historie geschätzt.
                           # Ältere Dateien ohne dieses Feld bleiben lesbar (Stand wird abgeleitet:
                           # Einträge, absences_confirmed: true oder ein schon geplanter bzw.
                           # ausgewerteter Sprint gelten als bestätigt).
absences_confirmed: true   # nur für ältere Programmversionen; wird zusammen mit „confirmed“ geschrieben
expected_absences: {anna: 2}   # PO-Vorplanung: angekündigte Fehltage (Prognose); wirken auf
                           # Kapazität und Forecast PLAN, bis die Fehltage bestätigt sind
not_done: 1.5              # Review, optional: Menge, die nicht fertig wurde
additional_done: 0.5       # Review, optional: zusätzlich zum Commitment erledigt
                           # (Velocity = Commitment − nicht erledigt + zusätzlich erledigt)
prognoses:                 # PO-Vorplanung: Prognosen des Teams für diesen offenen Sprint
- at: 2026-10-16 09:30:00
  comment: Prognose aus dem Daily      # woher die Annahme stammt
  forecast_ist: 10
  not_done: 2
  additional_done: 0.5
  expected_done: 8.5
  target: '2026.22'        # Zielsprint der Vorplanung
  plan: 9.9                # Forecast PLAN des Zielsprints mit dieser Annahme
  preplanned: {webshop: 4}
products:                   # optional, je Produkt-ID
  webshop: {preplanned: 4, planned: 4.5, done: 4, production_planned: 1, production_done: 0.5}
                            # production_*: davon Tickets mit Produktionszugriff (optional)
production_planned: 1       # ohne Produktverteilung (features.products aus): davon im Planning mit
production_done: 0.5        # bzw. im Review erledigt, je Sprint mit Produktionszugriff
```

## Rechenlogik

| Kennzahl | Formel |
|---|---|
| Normierte Velocity | Velocity / Kapazität × Referenzkapazität |
| Ø | Mittel der letzten `window` Sprints **mit Wert**, nur wenn der Sprint selbst einen Wert hat; Sprints ohne Wert (Lücken) zählen nicht mit, das Fenster reicht weiter zurück |
| Trend | Fortschreibung des Ø in die Zukunft (nie negativ) |
| Forecast PLAN | n. Velocity-Trend / Referenz × Kapazität, auf 1 Stelle abgerundet, nie negativ; Vergangenheit: Commitment |
| Roadmap / Kleinkram | Forecast PLAN × 0,8 / Rest |
| Fulfillment | Velocity / Commitment |
| Planning-Delta | Forecast PLAN − (Überkipper + Backlog − Korrekturen) |
| Erledigt | fertige Tickets **plus** im Sprint erledigte Teilanteile offener Tickets (Teampraxis); sollte im Team einheitlich gezählt werden, sonst sind Velocity und Erledigt über eine Umstellung hinweg nicht vergleichbar |
| Standard je Produkt | verfügbar × `share` (fester Anteil, optional) bzw. (verfügbar − Σ feste Anteile) / Anzahl der Produkte ohne `share`; verfügbar = Forecast PLAN (beim Planning eingefroren, sonst aktuell) bzw. dessen Roadmap-Anteil |
| Saldo je Produkt | Σ Erledigt − Σ Standard über die Sprints, in denen für das Produkt Erledigt erfasst ist (fehlt ≠ 0: Sprints ohne Wert zählen nicht); feste Anteile dürfen zusammen nicht über 100 % liegen |

**Neue Teams:** Ein erster Forecast erscheint schon ab **3 Sprints mit Velocity** („Historie dünn“:
Ø aus allen vorhandenen Sprints, konstant fortgeschrieben, mit Warnung „Wenig Daten“); das volle
Fenster (`window`, Standard 5) und die Schwelle von 5 Sprints für belastbare Aussagen kommen später.

**Kapazität eines Sprints** – in dieser Reihenfolge:
1. `capacity` in der Sprintdatei (eingefroren oder manuell) → *erfasst*
2. Mit Personenliste wird die Kapazität **immer aus Kalender und Personen** berechnet
   (Feiertage, Sprintlänge, Arbeitswoche, FTE); geschätzt werden nur die *unbekannten Fehltage*.
   Je nach **Stand der Fehltage** des Sprints (`absence_state`):
   - *bestätigt* (Fehltage eingetragen oder ausdrücklich „niemand fehlt“) → Σ Personen
     (Arbeitstage − Feiertage − Fehltage) × FTE − Abzug → *Personenliste*
   - *angekündigt* (PO-Vorplanung) → dasselbe mit den angekündigten Fehltagen →
     *angekündigte Fehltage*
   - *unbekannt* → Kalender und Personen, gemindert um die Ø Fehltage der letzten
     `absence_history` Sprints **mit bestätigten Fehltagen** (bestätigte Sprints ohne Fehltage
     zählen mit 0 mit; die verwendeten Sprints zeigt die Seite *Sprint vorbereiten: Fehltage*) → *erwartete Fehltage*;
     gibt es noch keine solche Historie, ohne Abzug → *Kalender, Fehltage unbekannt* (⚠️)
3. Nur **ohne Personenliste**: Kapazitäts-Trend → *Trend* (⚠️)

**Abzug für Scrum-Termine** (eine gemeinsame Rechnung für bestätigte, angekündigte und
erwartete Fehltage): erst Feiertage und Fehltage je Person, dann der Abzug. Die Kapazität bleibt
dabei ungerundet (die Prognose rechnet damit weiter); kaufmännisch gerundet (ab ,5 auf) wird sie
erst bei der Anzeige und beim Einfrieren im Review, auf `capacity.rounding` Stellen (Standard 1)
– überall gleich, ein Wert wird nirgends zwei verschieden gezeigt. Die Gleichungen im Rechenweg
zeigen die Zahlen, mit denen gerechnet wird (Kapazität und Trend bis 4 Nachkommastellen, z. B.
`16,8433 / 45 × 25,25`), der Forecast PLAN bleibt abgerundet. Feste PT je Person
(`overhead_days` × FTE, höchstens die Kapazität der Person) **ersetzen** den Prozentabzug
(`overhead_share`); beide sind derselbe Abzug in zwei Einheiten und werden nicht addiert.

**Trend-Modi** (`forecast.trend_mode`):
- `flat` (Standard): letzter Ø bleibt konstant (robust).
- `classic`: 1. Zukunftssprint linear `Ø + (Ø − Ø_vorher)`,
  2. multiplikativ `Ø_vorletzt / Ø_vorvorletzt × Trend_vorher`, danach linear.
- `linear`: durchgehend linear.

Beispiel (Ø zuletzt 44, davor 40, drei Zukunftssprints): `flat` → 44, 44, 44; `linear` → 48, 52, 56;
`classic` → 48, 52,8 (44/40 = +10 % auf 48), 57,6. Den Modus kann man jederzeit wechseln; es gehen
keine Daten verloren, die Prognose wird nur neu berechnet.

⚠️ `classic` und `linear` schreiben auch Rauschen fort: Der Forecast kann steigen oder fallen und
liegt bei längerem Horizont schnell außerhalb der Bandbreite. Sie sind nur ausdrücklich zu wählen
(die Oberfläche warnt dann). Der Forecast ist nie negativ. Reicht die Historie nicht für den
gewählten Modus (z. B. genau `window` Sprints), gilt `flat` mit dem Hinweis „Historie dünn“.

**Unsicherheit:** Die Forecast-Kacheln zeigen die Spanne (niedrigste bis höchste n. Velocity der
letzten Sprints) und warnen bei weniger als 5 Sprints mit Velocity. Aussagen wie „in 85 % der
Simulationen“ sind modellabhängige Häufigkeiten aus der Historie (Stichprobe wird angezeigt),
keine Zusagen.

**Prognose aktuell / beim Planning:** „Prognose aktuell“ ist der heute berechnete Forecast PLAN,
„Prognose beim Planning“ der beim Planning eingefrorene Stand (Basis der Verteilung je Produkt);
wo beide vorkommen, werden sie getrennt mit Differenz gezeigt.

**Rechenweg:** Jede Kennzahl lässt sich mit eingesetzten Zahlen nachvollziehen – in der
Weboberfläche per Tooltip (ⓘ an Kennzahlen und Spaltenköpfen) und im ausklappbaren
**Rechenweg** auf Forecast- und Planning-Seite, auf der Kommandozeile mit
`sprintforecast forecast TEAM --rechenweg SPRINT`.

## Ergänzende Analysen

`sprintforecast analyse TEAM [--rest MENGE] [--gesamt]` bzw. Seite **Analyse** – zusätzlich
zum Forecast, die bisherigen Werte bleiben unverändert:

- **Bandbreite:** Forecast mit der niedrigsten, mittleren und höchsten normierten Velocity
  der letzten Sprints (konservativ / mittel / optimistisch).
- **Fokusfaktor:** Velocity / Kapazität – dieselbe Größe wie die normierte Velocity, nur ohne
  Referenzkapazität (n. Velocity = Fokusfaktor × Referenzkapazität). Er hängt von der
  Schätzeinheit ab (bei Story Points von der Schätzskala des Teams) und ist daher **nicht**
  zwischen Teams vergleichbar, sondern zeigt den Verlauf im eigenen Team.
- **Puffer:** Ø Scope Creep der letzten Sprints im Vergleich zum Kleinkram-Anteil.
- **Wann ist es fertig?** Monte-Carlo-Simulation ab dem nächsten Sprint: in welchem Sprint
  eine Restmenge in 50 % bzw. 85 % der Simulationsläufe erledigt ist (modellabhängige Häufigkeit
  aus den letzten `window` Sprints, keine Zusage; Stichprobe und Warnung bei wenig Daten werden
  angezeigt) – mit dem Roadmap-Anteil oder (`--gesamt`) dem ganzen Forecast, optional nur mit
  einem **Projektanteil** davon (`--anteil 50` = die Hälfte). Teams ohne Personenliste rechnen
  mit der Ø Kapazität.

Der Bericht `FORECAST.md` enthält am Ende einen Abschnitt „Ergänzend: Bandbreite“.

## Erweiterungen (Plugins)

Plugins sind eigene Python-Pakete, die sich über den Entry-Point
`sprintforecast.plugins` einklinken (siehe `src/sprintforecast/plugins.py`). Sie können
Befehle für die Kommandozeile und Seiten für die Weboberfläche ergänzen – etwa einen Import
der Historie aus einem bisherigen Werkzeug. Installiert werden sie neben dem Tool:

```bash
uv tool install "sprintforecast[web] @ git+https://github.com/swallat/sprint-forecast" \
  --with "mein-plugin @ git+https://…"
```

Legt das Plugin die Quelle des Kerns selbst fest (`[tool.uv.sources]`), den Kern ohne
Adresse angeben – sonst meldet uv „conflicting URLs“:
`uv tool install "sprintforecast[web]" --with "mein-plugin @ git+https://…"`.

Formatneutrale Hilfsfunktion für Importe: `sprintforecast.storage.import_sprints`.

## Entwicklung

Voraussetzung: [mise](https://mise.jdx.dev) – Python und uv sind in `mise.toml` festgelegt.

```bash
mise install
uv sync --all-extras
uv run sprintforecast --daten examples/teams web   # aus dem Quellcode starten
uv run pytest
uv run ruff check && uv run ruff format --check
uv run python scripts/measure.py --md      # Messung der Antwortzeiten (siehe docs/performance.md)
```

### Release

1. Version in `pyproject.toml` und `src/sprintforecast/__init__.py` erhöhen, `uv lock` ausführen, per Pull Request nach `main` bringen.
2. Tag auf den Merge-Commit setzen und pushen: `git tag -a v0.4.2 -m "Version 0.4.2" && git push origin v0.4.2`.
3. Der Workflow *Release* (`.github/workflows/release.yml`) prüft Tests und Lint, vergleicht Tag und Version, baut Wheel und Quellpaket (`uv build`) und schreibt die Release-Seite mit den Dateien und automatisch erzeugten Notizen (aus den gemergten Pull Requests seit dem letzten Tag).

Für einen bereits vorhandenen Tag lässt sich das Release unter *Actions → Release → Run workflow* nachholen. Die normale CI baut bei jedem Push ebenfalls die Pakete und legt sie als Artefakt `dist` ab.

## Lizenz

[EUPL-1.2](LICENSE) (European Union Public Licence). Kurz: Nutzung, auch kommerziell und
firmenintern, ist frei. Wer eine veränderte Fassung weitergibt oder öffentlich als Dienst
anbietet, muss die Änderungen unter der EUPL offenlegen.

Alle von der EU-Kommission genehmigten Sprachfassungen sind gleichwertig (Art. 13 EUPL).
`LICENSE` enthält die englische Fassung; die amtliche deutsche Fassung steht im
[Durchführungsbeschluss (EU) 2017/863](https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:32017D0863).
