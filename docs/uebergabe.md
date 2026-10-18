# Übergabe: Stand der autonomen Nacht (18.10.2026)

Dieses Dokument fasst zusammen, was in der Nacht vom 17. auf den 18.10.2026 im Repository
`swallat/sprint-forecast` geschehen ist, was bewusst nicht getan wurde, welche Befunde offen sind,
was manuell zu prüfen ist, in welcher Reihenfolge die offenen Pull-Requests zu prüfen und zu mergen
sind und was als Nächstes ansteht. Stand: Übergabe um 08:00 Uhr (Berlin).

Grundsätze dieser Nacht: Jeder Pull-Request hat genau ein Thema, wurde vor dem Push mit
`ruff check`, `ruff format` und `pytest -q` geprüft und von einem unabhängigen Review
(Reviewer je Blickwinkel, Skeptiker widerlegen jeden Befund) geprüft; bestätigte Befunde wurden mit
Test und Mutationsprobe behoben. Gemergt wurde nur bei grüner CI und abgearbeitetem Review
(Erlaubnis aus dem Auftrag: „autonom mergen, solange ein Review von Claude oder Codex vorliegt und
vollständig bearbeitet wurde“). Alle von mir gemergten PRs stehen unter 1.

## 1. Pull-Requests

Stand: kurz vor der Übergabe. Den genauen Stand der CI und der Entwürfe zeigt GitHub; die
Spalte „Stand“ nennt, was ich zuletzt festgestellt habe.

**Offene Pull-Requests (alle Entwurf, nichts davon vom Owner gemergt):**

| PR | Thema | Stand |
|---|---|---|
| [#81](https://github.com/swallat/sprint-forecast/pull/81) | Git-Fehler richtig zuordnen (Adresse, Rechte, Ordner, Fingerabdruck), Hinweis „Zurück auf den Branch“ | Entwurf; Review hat 36 Befunde (rund 12 verschiedene) bestätigt, die Themen A bis H sind behoben (u. a. `not_writable` auf Dateisystem-Schreibfehler eingegrenzt, `_folder_access`, `safe.directory`-Rat entfernt, Laufwerksprüfung), I teilweise; lokal 1607 Tests grün, CI läuft; **ein zweites unabhängiges Review der Korrekturen fehlt noch** — erst danach mergen |
| [#82](https://github.com/swallat/sprint-forecast/pull/82) | „Speichern und teilen“: Meldung geht bei einem zweiten Durchlauf nicht mehr verloren (Ursache des flackernden e2e-Tests) | Entwurf; CI grün, aber das Review fand Fehler in der Sperre (prozessweit, unbegrenztes Warten); **nicht mergen**, Überarbeitung im PR-Text beschrieben |
| [#62](https://github.com/swallat/sprint-forecast/pull/62) | `docs/konzept-kern.md`: Umsetzungsstand | Entwurf; „Stand“-Zellen nach den Merges aktualisieren (A3, A10, B5, D-Abschnitte, Phasentabelle) |
| dieser PR | `docs/uebergabe.md` | Entwurf |

**Gemergt in der Nacht (von mir, ohne Review des Owners; jeweils CI grün und unabhängiges Review
abgearbeitet):**

- [#60](https://github.com/swallat/sprint-forecast/pull/60) Browsertests (Playwright, e2e)
- [#63](https://github.com/swallat/sprint-forecast/pull/63) Schreib-/Lesefehler der Datendateien als Meldung (`FileAccessError`)
- [#64](https://github.com/swallat/sprint-forecast/pull/64) YAML-Aufbaufehler als `DataError` mit Dateiname
- [#65](https://github.com/swallat/sprint-forecast/pull/65) Konfliktmarker nicht committen oder teilen
- [#66](https://github.com/swallat/sprint-forecast/pull/66) Spanne und Stichprobe an Planning, Fehltage, Vorplanung, Kommandozeile, Bericht (9 Befunde behoben)
- [#67](https://github.com/swallat/sprint-forecast/pull/67) Kapazitätstexte: Kalender und Personen statt „Trend“
- [#68](https://github.com/swallat/sprint-forecast/pull/68) Hinweis nach dem Speichern und Hilfe-Einleitung kennen das Teilen
- [#69](https://github.com/swallat/sprint-forecast/pull/69) README/Hilfe: Namen, Pfade, Befehle, Git-Aussagen
- [#70](https://github.com/swallat/sprint-forecast/pull/70) `nan`/`inf`/`1e999` ablehnen
- [#71](https://github.com/swallat/sprint-forecast/pull/71) Ungültiger Stichtag: Meldung statt Traceback
- [#72](https://github.com/swallat/sprint-forecast/pull/72) Teamkürzel beim Anlegen prüfen
- [#73](https://github.com/swallat/sprint-forecast/pull/73) Prognose: Meldung statt `ValueError` (kein erster Sprint, ID passt nicht zur Nummerierung)
- [#74](https://github.com/swallat/sprint-forecast/pull/74) Datenordner: Pfad- und Klonfehler als Meldung
- [#75](https://github.com/swallat/sprint-forecast/pull/75) Kommandozeile: Git-Fehler mit Überschrift und nächstem Schritt
- [#77](https://github.com/swallat/sprint-forecast/pull/77) Analyse: Warnung bei wenig Daten auch in der Kommandozeile
- [#78](https://github.com/swallat/sprint-forecast/pull/78) Produktbilanz in Kommandozeile und Bericht: fehlende Werte ausweisen
- [#79](https://github.com/swallat/sprint-forecast/pull/79) Datenrepository: `*.tmp` ignorieren, `.gitattributes` (YAML und Berichte mit LF) im Datenordner neuer Repositories
- [#80](https://github.com/swallat/sprint-forecast/pull/80) Kommandozeile: Namen und Pfade aus den Daten nicht als Rich-Markup auswerten (`_plain`, `_plain_end`, Hinweis `[web]`); zwei Review-Runden, offen nur niedrige Testlücken (im PR-Text)
- [#76](https://github.com/swallat/sprint-forecast/pull/76) Texte anderer (Commit-Autor/-Betreff, Tags, Branches, Dateipfade, rohe Git-Ausgabe) in der Weboberfläche als Code statt Markdown; Absturz bei leerem Betreff; Geister-Tags durch `splitlines` — zwei Review-Runden, offen nur niedrige Punkte (Teil 3)

Früher gemergt (Aufgaben 1 bis 6 des Auftrags): [#55](https://github.com/swallat/sprint-forecast/pull/55) (UI aufräumen), [#56](https://github.com/swallat/sprint-forecast/pull/56) (`web` öffnet
standardmäßig ein App-Fenster), [#57](https://github.com/swallat/sprint-forecast/pull/57) (Windows-Testskript), [#58](https://github.com/swallat/sprint-forecast/pull/58) (Forecast: Spanne als Zeile),
[#59](https://github.com/swallat/sprint-forecast/pull/59) (Konfliktmarker CRLF und kleine Schuld), [#61](https://github.com/swallat/sprint-forecast/pull/61) (Schrittleiste sofort aktuell).

Auf `main` nach allen Merges (bis #76 und #80): ruff sauber, 1615 Tests grün (lokal, ohne e2e); e2e in der CI bis auf den
bekannten Aussetzer grün.


## 2. Bewusst nicht getan (und warum)

Aus dem Auftrag („BEWUSST NICHT TUN“): keine Anmeldung/SSH-Schlüsselerstellung/`credential.helper`
in der App, kein B10, kein Ticketsystem/Jira, keine Änderungen an `launcher.py` und `proctree.py`,
keine Sperre für gleichzeitiges `config.update`, keine Pfade über 260 Zeichen und keine
Dateinamen ohne UTF-8, keine weitere `resolve()`-Bereinigung, `requires-python` unverändert.

Fachlich unklare oder das Verhalten ändernde Punkte (Zahlen, Berechnung, Speicherformat) habe ich
nicht umgesetzt, sondern mit Optionen und Empfehlung festgehalten. Die Empfehlung steht jeweils
zuerst:

| Thema (Konzept-Kennung) | Frage | Optionen | Empfehlung |
|---|---|---|---|
| A1: Plan in der Bandbreite | Der Sprint zählt bis zu seinem Ende als laufend; zwischen Review und Sprintende rechnet der Plan mit dem erfassten Review-Wert, Spanne, Stichprobenzahl und Monte Carlo aber ohne ihn. Der Plan kann außerhalb der Spanne liegen. (ändert Zahlen) | (a) lassen; (b) `normalized_history` und `sample_count` (damit `band`, `completion`) auf dieselbe Wertemenge wie die Engine umstellen | (b), kleiner PR mit Eigenschaftstest „laufender Sprint mit Velocity, Plan in Spanne“; Spanne und Stichprobenzahl ändern sich nur zwischen Review und Sprintende |
| A1: Bestandsteams mit `trend_mode: classic` | Bleiben auf dem Modus, der Rauschen fortschreibt; es gibt nur die Warnung | (a) lassen; (b) Knopf „Auf konstant umstellen“; (c) still umstellen | (b); (c) nicht empfohlen (ändert Zahlen unbemerkt) |
| A5: Altdateien ohne erfasste Fehltage | Zählen als „bestätigt, niemand fehlte“ und ziehen die Quote gegen 0; die Kapazität künftiger Sprints wird zu hoch geschätzt | (a) lassen; (b) Quote als unsicher kennzeichnen (keine Zahlenänderung); (c) abgeleitete Stände nicht zählen oder migrieren (ändert Zahlen) | (b), kleiner PR in `capacity.absence_history` |
| B3: Name für „Roadmap“ | Das Konzept sagt „umbenennen“, nennt aber keinen Namen; offen auch, ob der YAML-Schlüssel wechselt | (1) belassen und erklären; (2) nur Anzeigename ändern, Schlüssel `roadmap_share` bleibt; (3) Schlüssel mit Migration umbenennen (Speicherformat) | (2), sobald ein Name gewählt ist; bis dahin (1) |
| C: Einrichtungsassistent | Das Konzept nennt ihn „mögliches späteres Ziel“ ohne Entscheidung | (a) nichts; (b) leichte Checkliste „Einrichtung“ auf der Startseite, verlinkt auf vorhandene Seiten; (c) vollständiger Assistent | (b), nach K2 |
| D1b: Serverstand nur auf Klick | „Offline“ und „neu von anderen“ sind nach dem Start erst nach einem Klick bekannt (Netzwerk nur auf Klick) | (A) so lassen; (B) einmal je Sitzung im Hintergrund abfragen (kurzes Timeout, kein Anmeldefenster); (C) zyklisch per Fragment | (A); wünscht der Owner mehr, (B) als eigener PR |
| D4b: Listen ohne `id` (Prognosen) | Zwei Personen hängen gleichzeitig eine Prognose an denselben Sprint: Wertkonflikt über die ganze Liste, eine Seite geht verloren | (A) lassen (in `yamlmerge` dokumentiert); (B) `prognoses` über `at` vereinigen (nur anhängen); (C) je Zeitpunkt eigene Dateien | (B), kleiner PR in `yamlmerge._keyed` mit Test |
| D: Git-Identität global | Die App schreibt Name und E-Mail in die globale Git-Konfiguration; Konzept und README sagen an anderer Stelle das Gegenteil | (A) nur lokal im Daten-Repository; (B) global lassen, Sätze in Konzept und README präzisieren; (C) in den App-Einstellungen speichern | (B), nur Text |
| Robust: stille Annahmen | Leere Werte und doppelte Schlüssel werden still zu 0, `None` bzw. „letzter gewinnt“ | (A) Hinweise in der Prüfung (Warnung), Duplikat-Erkennung, Berechnung unverändert; (B) überall `DataError` (strenger); (C) nur dokumentieren | (A); bei (B) würden bisher ladbare Dateien abgelehnt |
| Doku: Abnahme Phase P | Browser-Stoppuhr-Abnahme: Konzept F verzichtet auf weitere Messungen, `performance.md` führt sie als ausstehend | (A) Phase P als abgeschlossen mit benanntem Rest führen; (B) Messung nachholen | (A) |

Ebenfalls nicht umgesetzt, weil das Verhalten ändernd: aus dem Review von #74 die Frage, ob die
App bei bestehenden Daten-Repositories eine `.gitattributes` im Datenordner anbieten soll (siehe
#79; Risiko: CRLF-Dateien im Index gelten danach als geändert); aus #77 die Fragen, ob die Stichprobe
der Simulation durch `window` gedeckelt sein soll und ob der Mindestwert der Simulation (derzeit
ab zwei Werten) angehoben werden soll; aus #78 die Frage nach einer Fußnote zur Spalte „ohne Wert“
in Kommandozeile und Bericht.


## 3. Offene Befunde und bekannte Fehler

Bekannte Fehler und offene Befunde, jeweils mit dem Ort, an dem sie behandelt werden:

- **Flackernder e2e-Test** (`tests/e2e/test_two_clones.py::test_absences_of_different_people_merge_without_conflict`):
  Ursache war ein Fehler im Produktcode (Meldung nach „Speichern und teilen“ ging bei einem zweiten
  Durchlauf verloren), Behebung in PR **#82**. Bis #82 gemergt ist, kann dieser Test in der CI
  sporadisch rot sein (ein Lauf rot, der zweite des gleichen Commits grün). Gemergt wurde nur bei
  einem vollständig grünen Lauf.
- **Nicht abfangbar** (#82): Ein Klick, der verloren geht, weil die zweite Anforderung des Browsers
  vor dem Rückruf selbst eintrifft (Millisekundenfenster).
- **#76 (gemergt, Rest offen, niedrig):** Die Hinweise zu Konfliktmarkierungen (`refuse_conflict_markers` in `git.py`) nennen
  Dateinamen aus dem Repository ungeschützt (Markdown); Tests für Tooltip und Sicherungspfad, für
  `split_record` mit `\x1f` im Betreff fehlen; der `pre-receive`-Hook im Test hat keinen Windows-Skip. Eigene
  `GitError`-Texte ohne Hinweis mit eingesetzten Namen (z. B. „Den Tag {name} gibt es auf diesem Rechner
  nicht.“) bleiben Fließtext.
- **#80 (gemergt, Rest offen):** Emoji-Kürzel wie `:smile:` in Namen werden von Rich zu Emojis (kosmetisch). Die
  `escape(...)`-Aufrufe um ganze Meldungen aus #74/#75 behandeln genau einen abschließenden
  Backslash (kosmetisch).
- **#79:** Die `.gitignore` liegt im Stamm des Repositories und wird von der App nie committet
  (bestand schon vorher). Bestehende Daten-Repositories und Klone ohne `.gitattributes` bleiben
  ungeschützt (siehe Entscheidungen). Die Windows-Prüfung „Zeilenenden“ prüft jetzt den
  geschützten Zustand (neues Repository mit `.gitattributes`), nicht mehr den ungeschützten.
- **#81 offen:** (1) Ein Schreibfehler beim automatischen Zusammenführen (`resolve_conflicts`, `gitsync.py`)
  bleibt Art `locked` und bekommt den `index.lock`-Absatz, der dort nicht passt (braucht einen eigenen Hinweistext
  für Dateien; unter Windows ist es oft wirklich eine gehaltene Datei, der Bestandstest erwartet `locked`).
  (2) `GIT_HELP` in `guide.py` und `docs/konzept-kern.md` erwähnen die neuen Fälle (unsicherer Ordner, nicht
  beschreibbar, Fingerabdruck, verwaiste `index.lock`, offene Änderungen beim Zurück auf den Branch) noch nicht;
  englische Fassungen in `locale_en.py` nötig. (3) Für den Owner offen: „Zurück auf den Branch“ sichert offene
  Änderungen nicht vorher auf dem Rettungsbranch (Option A im PR-Text); ein nacktes „Could not read from remote
  repository“ bleibt `offline`; ein Einhängepunkt auf Linux, der bei fehlendem Laufwerk als leerer Ordner
  bestehen bleibt, gilt weiter als „nicht gefunden“.
- **Übersetzungen:** `tests/test_i18n.py` prüft nur fehlende, nie überzählige Schlüssel. Das Review von #77
  fand rund 47 scheinbar ungenutzte Einträge in `locale_en.py` (nicht einzeln geprüft, einige
  vermutlich falsch positiv). Zwei sicher tote Schlüssel habe ich entfernt.
- **Doppelter Text** „Wenig Daten: bisher nur {samples} Sprints …“ in Bericht und Forecast-Seite (#77).
- **Umgebung der Nacht** (kein Fehler im Code): `/dev/null` im Cloud-Container wurde zu einer
  normalen Datei (vermutlich durch `git config --global` mit `GIT_CONFIG_GLOBAL=/dev/null` als root);
  die Reparatur wurde vom Berechtigungssystem verweigert und nicht umgangen; die e2e-Harness nutzt
  deshalb eine eigene leere Git-Konfiguration. Außerdem fiel in der Nacht kurz der Signierdienst der
  Umgebung aus („too many open files“); ein Teil-Agent hat daraufhin einen Commit mit
  `commit.gpgsign=false` auf den Branch von #76 gepusht (nicht freigegeben). Der Commit wurde nach
  der Erholung des Dienstes neu signiert (Force-Push mit Lease auf den eigenen Branch), alle Commits der
  offenen Branches tragen eine Signatur.
- **Committer-Adresse:** Die Commits tragen die im Auftrag verlangte Adresse
  `873008+swallat@users.noreply.github.com`. GitHub zeigt sie als „Unverified“, weil die Signatur zur
  Identität `noreply@anthropic.com` gehört. Soll das anders sein, muss die Identität festgelegt werden.
- **Reihenfolge der Merges in der Nacht:** #66 und #72 wurden gemergt, bevor deren e2e-Lauf fertig war
  (test/build/claude-review grün). Die Läufe auf `main` waren danach grün (einmal nach Neustart des
  Auftrags, wegen des genannten Aussetzers). Seitdem wurde auf e2e gewartet.


## 4. Manuell zu prüfen (nur Optik und Verständlichkeit)

Der Owner prüft nur Optik und Verständlichkeit sowie die Ergebnisse des Windows-Skripts.

- #55: Forecast-Kacheln (Spanne/Quelle), Schrittleiste (Höhen, vier Schritte, Haken, Flagge), „–“
  statt `None` in Zellen, Kapazität ohne Abschneiden, Anmelde-Hinweis, Server-Maske-Schaltflächen
- #56: `sprintforecast web` öffnet ein App-Fenster; `--no-browser` öffnet nichts
- #57: **Windows-Skript ausführen und den Bericht zurückgeben** (`scripts/windows-tests.ps1`,
  Anleitung in `docs/windows-tests.md`); dieses Ergebnis steht noch aus
- #58: Forecast: Zeile „Spanne a–b“ mit Beschriftung „Spanne aus den letzten N Sprints“
- #59: Umbenennen-Meldung mit Backticks
- #61: Schrittleiste springt nach dem Speichern sofort auf „erledigt“ (Vorplanung, Planning, Review)
- #63: rote Meldung bei schreibgeschützter Sprintdatei
- #64: Meldung bei fehlerhaftem Aufbau (`sprint: foo` in `team.yaml`)
- #65: Meldung „Konflikt beim Zusammenführen“ bei Markierungen ohne Merge
- #66: Planning Schritt 2, Fehltage, PO-Vorplanung: Zeile „Spanne … aus den letzten N Sprints“ an
  sinnvoller Stelle; Planning: die Kapazität nennt darunter die Quelle; Terminal:
  `sprintforecast forecast demo` mit Spalte „Spanne“ (in 80 Spalten enger)
- #67: Forecast-Seite, Tooltip „Kapazität (PT)“ und Rechenweg; „Fehltage zurücksetzen“
- #68: Hinweis nach dem Speichern (Datenordner mit Server, Git ohne Server, ohne Git) passt zu den
  Knöpfen; Hilfe-Seite, erster Absatz
- #69: Hilfe-Seite (Reiter Befehle, Zusammenarbeit): Namen stimmen mit der Seitenleiste überein
- #70: Planning, Korrekturfeld: `nan` eintragen gibt „bitte endliche Zahlen …“
- #71: `SPRINTFORECAST_STICHTAG=morgen sprintforecast web` gibt eine verständliche Fehlermeldung
- #72: „Neues Team“ mit Kürzel `a/b` oder `con`: Meldung verständlich
- #73: Daten ohne ersten Sprint bzw. mit Sprintdatei `2026.22b.yaml`: Meldung statt Fehlerseite;
  Seite „Prüfung“ und `pruefen`
- #74: Seite „Datenordner“: `~keinbenutzer/x`, „Anlegen“ auf eine Datei, Klonen (nicht erreichbar,
  Anmeldung, nicht leerer Ordner), leeres Pfadfeld
- #75: Terminal: Git-Fehler mit Überschrift „Kein Git-Repository“ statt roher Meldung
- #77: Seite „Analyse“ mit 2 bis 4 Sprints: gelbe Warnung; Terminal `analyse --rest`
- #78: Terminal `produkte … --verlauf` mit fehlendem Wert: Spalte „ohne Wert“
- #79: Seite „Datenordner“, „Neues Daten-Repository anlegen“: erweiterter Hilfetext; nach dem Anlegen
  liegt `teams/.gitattributes` neben den Teams und gilt bis zum ersten „Speichern und teilen“ als
  offene Änderung
- #62: Stand-Angaben in `docs/konzept-kern.md` stimmen mit dem Eindruck überein

Pull-Requests, die erst spät in der Nacht gemergt wurden bzw. noch offen sind (nach dem Mergen prüfen):

- #76: Seitenleiste „Neu von anderen“, Reiter Tags, Konfliktseite, Verwerfen-Liste: Autor, Betreff,
  Tag-Namen, Dateipfade als Code gut lesbar (auch in der schmalen Seitenleiste)?
- #80: Terminal mit Namen wie „Eva [x]“ oder Produkt `[/x]`: Ausgabe unverändert lesbar
- #81: Boxen „Repository nicht gefunden“, „Ordner gehört einem anderen Benutzer“, Meldung zum
  Rettungsbranch nach „Zurück auf den Branch“
- Fix „Speichern und teilen“ (Meldung geht bei zweitem Durchlauf nicht mehr verloren): nach
  „Fehltage speichern“ sofort „Speichern und teilen“ klicken; die Meldung („… übernommen“,
  „Hochgeladen“) erscheint immer


## 5. Empfohlene Reihenfolge für Review und Merge

1. **[#80](https://github.com/swallat/sprint-forecast/pull/80)** ist gemergt (nur `cli.py` und ein Testmodul).
2. **[#76](https://github.com/swallat/sprint-forecast/pull/76)** ist gemergt.
3. **[#81](https://github.com/swallat/sprint-forecast/pull/81)** (nach dem Merge von [#76](https://github.com/swallat/sprint-forecast/pull/76)): berührt dieselben Dateien (`git.py`, `ui.py`, `cli.py`), Konflikte beim
   Einmergen von `main` sind zu erwarten. Die Befunde zu `not_writable` und `_folder_access` sind behoben; vor dem
   Mergen ein zweites unabhängiges Review der Korrekturen, `main` einmergen, CI abwarten.
4. **[#82](https://github.com/swallat/sprint-forecast/pull/82)** nach der Überarbeitung der Sperre (Abschnitt 3, Befunde im PR-Text); berührt `web/ui.py` und
   `web/app.py`. Erst danach ist der e2e-Aussetzer in der CI weg.
5. **[#62](https://github.com/swallat/sprint-forecast/pull/62)** zuletzt: die „Stand“-Zellen in `docs/konzept-kern.md` erst nach den Merges aktualisieren.
6. **Dieser PR** (Übergabe) jederzeit; er enthält nur Dokumentation.

Abhängigkeiten in Kurzform: [#81](https://github.com/swallat/sprint-forecast/pull/81) baut auf [#74](https://github.com/swallat/sprint-forecast/pull/74) (gemergt) und kollidiert mit [#76](https://github.com/swallat/sprint-forecast/pull/76); [#82](https://github.com/swallat/sprint-forecast/pull/82) ist
unabhängig, löst aber den e2e-Aussetzer, den jeder PR in der CI sehen kann; [#62](https://github.com/swallat/sprint-forecast/pull/62) hängt von allen
anderen ab.


## 6. Backlog der nächsten Aufgaben

Reihenfolge nach Nutzen und Risiko; kleine Pull-Requests mit je einem Thema:

1. **Entscheidungen des Owners** (Abschnitt 2) und daraus je ein kleiner PR: A1 „Plan in der
   Bandbreite“ (ändert Zahlen), D4b Prognosen über `at` vereinigen, A5 Quote als unsicher
   kennzeichnen, Git-Identität (nur Text), Phase P als abgeschlossen führen.
2. **Übersetzungen aufräumen:** Test auf verwaiste englische Schlüssel (Schlüssel, die nirgends in
   `src/` als `t()`-Literal vorkommen) und Entfernen der ungenutzten Einträge.
3. **#81-Nachtrag:** `_folder_access` auch für die Art `not_writable`; Hinweistexte zu Anmelde-Hilfe
   (D6) ohne Anmeldung in der App.
4. **Robustheit aus dem Audit der Nacht** (Stand zu Beginn der Nacht „offen“, nicht erneut geprüft):
   Updater-Status (ausdrückliches `--auto` wird als gespeichert gemeldet, obwohl das Schreiben
   scheiterte), Protokolldatei des App-Starters nicht abgesichert, Feldtypen in `settings.json`,
   Wertebereiche von CLI-Optionen, unterschiedliches Verhalten von CLI und Weboberfläche bei
   ungültigen Eingaben (CLI schreibt und meldet nachträglich), `OSError` beim Schreiben in
   `resolve_conflicts`, stille Annahmen (Entscheidung nötig).
5. **Doku:** Stand-Angaben in `docs/konzept-kern.md` nach den Merges aktualisieren (PR #62),
   README-Hinweise (FTE, Produktanteil, Einstellungen, Vorplanung, Begriffe im Rechenweg),
   Abnahmetests zur Doku (D-Abnahme).
6. **e2e:** Nach #82 prüfen, ob die CI stabil ist; weitere Browsertests nur gezielt.
7. **Windows:** `scripts/windows-tests.ps1` ausführen und den Bericht zurückgeben (liegt beim Owner);
   danach Befunde daraus abarbeiten.

## 7. Übergabe-Prompt für die lokale Windows-Sitzung

Der folgende Text ist der vollständige Auftrag für die lokale Sitzung; er ist wie der ursprüngliche
Auftrag aufgebaut.

````text
Du bist ein Claude-Code-Agent in einer lokalen Windows-Sitzung (PowerShell) und übernimmst die Arbeit
am Repository swallat/sprint-forecast (Python 3.14, uv, Streamlit-Oberfläche und Typer-Kommandozeile,
YAML-Daten, pytest, ruff mit Zeilenlänge 100) von einer autonomen Cloud-Sitzung der Nacht auf den
18.10.2026. Lies zuerst `docs/uebergabe.md` (Branch `claude/uebergabe`, Pull-Request #83; falls noch nicht
gemergt: `git fetch origin claude/uebergabe` und die Datei von dort lesen). Dort stehen der Stand jedes
Pull-Requests, die offenen Entscheidungen des Owners, die offenen Befunde, die manuell zu prüfenden
Änderungen, die empfohlene Reihenfolge und das Backlog.

REGELN
- Antworte, kommentiere und schreibe Commit- und PR-Texte auf Deutsch. Commit-E-Mail:
  873008+swallat@users.noreply.github.com.
- KEINE Attributionszeilen in Commits und PR-Beschreibungen (kein Co-Authored-By, keine Session-Zeile,
  keine „Generated with“-Fußzeile; falls ein Werkzeug sie automatisch anhängt, danach entfernen).
- Mergen: Der Owner mergt. Du darfst nur dann selbst mergen, wenn die CI auf dem aktuellen Kopf vollständig
  grün ist UND ein unabhängiges Review (Claude oder Codex) vorliegt und vollständig bearbeitet wurde.
  Nenne jeden eigenen Merge im Bericht. Entwürfe können nicht gemergt werden (zuerst „bereit“ setzen).
- Vor jedem Push: `uv run ruff check .`, `uv run ruff format .`, `uv run pytest -q` (ohne e2e; die
  Windows-Tests laufen hier mit, anders als in der Cloud).
- Jeder neue `t("...")`-Text braucht einen Eintrag in `src/sprintforecast/locale_en.py`
  (`tests/test_i18n.py` prüft das).
- Nicht anfassen: `requires-python`, das Ticketsystem/Jira, das Daten-Repository, `launcher.py`,
  `proctree.py`.
- Immer von aktuellem `origin/main` (git fetch) auf einem eigenen Branch arbeiten; Pull-Requests klein,
  deutsch, ein Thema je PR. Unabhängiges Review vor dem Mergen: Reviewer je Blickwinkel plus Skeptiker, die
  jeden Befund zu widerlegen versuchen; dem Reviewer nicht die eigene Einschätzung mitgeben; Befunde mit
  Datei:Zeile und Ablauf, bestätigte Befunde beheben (mit Test und Mutationsprobe).
- AppTest-Hinweis: Bei Formularen `set_value` und den Submit-Knopf direkt klicken, kein `.run()` dazwischen.
- BEWUSST NICHT TUN: keine Anmeldung, SSH-Schlüsselerstellung oder `credential.helper` in der App, kein B10,
  keine Sperre für gleichzeitiges `config.update`, keine Pfade über 260 Zeichen oder Dateinamen ohne UTF-8,
  keine weitere `resolve()`-Bereinigung. Fachlich unklare oder das Verhalten ändernde Punkte (Zahlen,
  Berechnung, Speicherformat) nur mit Optionen und Empfehlung festhalten bzw. dem Owner vorlegen, nicht
  umsetzen.
- Die Commits dürfen nicht unsigniert gepusht werden, wenn dein Git Signatur verlangt; umgehe eine
  Signierpflicht nicht.

AUFGABEN, IN DIESER REIHENFOLGE
1. Windows-Skript: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-tests.ps1`
   (Anleitung `docs/windows-tests.md`). Bericht auswerten und dem Owner geben. Danach die drei
   Windows-Tests laufen lassen (`test_windows_paths_scoop_and_choco`, `test_mac_bundle_and_alias`, der
   Symlink-Rechtetest) und alle Fehler prüfen, die es nur unter Windows gibt (Pfade mit `/` in
   `tests/test_cli_markup.py`, CRLF im `pre-push`-Hook des e2e-Tests aus #82). Windows-Befunde als eigene
   kleine Pull-Requests beheben.
2. Offene Pull-Requests abarbeiten, Reihenfolge und Abhängigkeiten stehen in Teil 5 der Übergabe: #80
   (gemergt), #76 (gemergt), #81 (zweites Review der Korrekturen, offene Punkte aus Teil 3), #82 (Sperre je Sitzung, Zeitgrenze, Rückmeldung für verworfene Klicks),
   zuletzt #62 (Stand-Zellen in `docs/konzept-kern.md`).
3. Entscheidungen des Owners einholen (Teil 2 der Übergabe), nicht selbst treffen; danach je Entscheidung
   ein kleiner PR (Empfehlungen stehen dort).
4. Backlog (Teil 6 der Übergabe): Übersetzungen aufräumen, Robustheit, Doku.

BERICHT: PR-Links, was geprüft wurde, was offen bleibt, die Liste der manuell zu prüfenden Änderungen
(der Owner prüft nur Optik und Verständlichkeit sowie die Ergebnisse des Windows-Skripts).
````
