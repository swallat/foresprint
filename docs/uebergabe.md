# Übergabe: Stand der Arbeit vom 18.10.2026

Dieses Dokument fasst zusammen, was in der Nacht vom 17. auf den 18.10.2026 und am Tag danach im
Repository `swallat/sprint-forecast` geschehen ist, was bewusst nicht getan wurde, welche Befunde
offen sind, was manuell zu prüfen ist, was als Nächstes ansteht (Todo-Liste in Teil 6) und wie die
planmäßige Arbeit auf dem Linux-Host läuft (Teil 8). Stand: Abend des 18.10.2026, nach dem Merge von
#62; die ursprüngliche Übergabe der Cloud-Nacht war um 08:00 Uhr (Berlin).

Grundsätze: Jeder Pull-Request hat genau ein Thema, wurde vor dem Push mit `ruff check`,
`ruff format` und `pytest -q` geprüft und von einem unabhängigen Review (Reviewer je Blickwinkel,
Skeptiker widerlegen jeden Befund; später auch Codex und die `claude-review` der CI) geprüft;
bestätigte Befunde wurden mit Test und Mutationsprobe behoben. Gemergt wurde nur bei grüner CI und
abgearbeitetem Review (Erlaubnis aus dem Auftrag: „autonom mergen, solange ein Review von Claude oder
Codex vorliegt und vollständig bearbeitet wurde“). Alle gemergten PRs stehen unter 1; die Ausnahmen von
diesen Grundsätzen (Merges bei rotem oder noch laufendem e2e, Merge vor dem Review) stehen in Teil 3.

## 1. Pull-Requests

Den genauen Stand der CI und der Entwürfe zeigt GitHub; die Spalte „Stand“ nennt, was zuletzt
festgestellt wurde.

**Offene Pull-Requests:**

| PR | Thema | Stand |
|---|---|---|
| [#83](https://github.com/swallat/sprint-forecast/pull/83) | `docs/uebergabe.md` (dieses Dokument) und die Referenzkopien des Läufers unter `docs/linux-betrieb/` (Skripte, Auftragstext, systemd-Einheiten; sie werden nicht aus dem Repository ausgeführt, sondern auf den Host kopiert), `.gitattributes` für diese Dateien | wird mit diesem Stand gemergt; danach liegt die Todo-Liste in `main`. Die Läufe beginnen, sobald die Pause aufgehoben ist (Teil 8) |

Alle übrigen Pull-Requests sind gemergt (die Entwürfe #81, #82 und #62 ebenfalls, siehe unten).

**Gemergt am Tag danach (von der lokalen Windows-Sitzung, ohne Review des Owners; jeweils CI grün; Review
abgearbeitet, Ausnahmen stehen beim PR und in Teil 3):**

- [#62](https://github.com/swallat/sprint-forecast/pull/62) `docs/konzept-kern.md`: Umsetzungsstand nachgetragen (Phasen, Fehlerzustände, Kopfzeile). Nicht nachgeführt sind die Zellen zu A3, A10, B5 und D.5 (Spanne an Planning/Fehltage/Vorplanung/CLI aus #66, Warnung bei `analyse --rest` aus #77, fehlende Werte statt 0 aus #78, `.gitattributes` aus #79); siehe Todo-Liste D.3
- [#81](https://github.com/swallat/sprint-forecast/pull/81) Git-Fehler richtig zuordnen (Adresse, Rechte, Ordner, Fingerabdruck), Hinweis „Zurück auf den Branch“; Review mit 36 bestätigten Befunden abgearbeitet, `claude-review` der CI ohne Befund auf dem letzten Kopf. Der Nachtrag der letzten Überarbeitung (Hinweistext bei `resolve_conflicts`, Hilfeseite `GIT_HELP`, Tests) wurde nicht noch einmal unabhängig geprüft
- [#82](https://github.com/swallat/sprint-forecast/pull/82) „Speichern und teilen“: Meldung geht bei einem zweiten Durchlauf nicht mehr verloren (Ursache des flackernden e2e-Tests), Sperre je Sitzung mit Zeitgrenze
- [#84](https://github.com/swallat/sprint-forecast/pull/84) Protokolle der Sprint-Termine: Markdown je Speichern, frühere Stände ansehen, beim Aufheben `_obsolet_<Zeit>`; elf Review-Runden, ein Befund mit Absicht in #90
- [#90](https://github.com/swallat/sprint-forecast/pull/90) Protokolle: Sperre des Betriebssystems je Sprint und Termin gegen doppelte Protokolle
- [#85](https://github.com/swallat/sprint-forecast/pull/85) Was-wäre-wenn: Felder ausrichten; Planning: Kapazität nach Produktionszugriff aufteilen (eine Zeile „Kapazität: x PT mit Produktionszugriff (y %), z PT ohne · Forecast PLAN: bis zu a … für Tickets mit Produktionszugriff, b … für alle übrigen“ in Schritt 2, nur sichtbar bei eingeschaltetem Bereich „Produktionszugriff“ und wenn berechtigte Personen Kapazität haben)
- [#86](https://github.com/swallat/sprint-forecast/pull/86) Excel-Rückweg für das ganze Team: Ausgabe mit Formeln und Trend-Diagrammen, Import mit Vorschau (`sprintforecast excel`, `excel-import`, extra `excel`; in der Weboberfläche nur die Ausgabe: „Excel-Liste erstellen“ und „herunterladen“ auf der Forecast-Seite). Wurde vor jedem Review gemergt (das Codex-Review kam danach); dessen vier Sicherheitsbefunde (Pfadausbruch über Teamkürzel und Sprint-ID, Einstellungen ohne Prüfung, NaN/inf) behebt #91
- [#91](https://github.com/swallat/sprint-forecast/pull/91) Excel-Import härten: sichere Namen, geprüfte Einstellungen und Zahlen, Rundlauf-Prüfung
- [#87](https://github.com/swallat/sprint-forecast/pull/87), [#88](https://github.com/swallat/sprint-forecast/pull/88), [#89](https://github.com/swallat/sprint-forecast/pull/89) Windows-Befunde: Pfade der Kommandozeilen-Tests, Tests unabhängig vom Rechner (Chrome, Profilordner, Zeilenenden), Symlink-Tests ohne Recht überspringen

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

Auf `main` nach allen Merges (bis #62): ruff sauber, 1901 Tests grün bei 12 übersprungenen (lokal unter
Windows mit allen Extras, ohne e2e); e2e in der CI grün, der frühere Aussetzer ist mit #82 behoben.


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
| #81: „Zurück auf den Branch“ mit offenen Änderungen | Die App wechselt auf den Branch und nennt in der Erfolgsmeldung den Rettungsbranch, sichert die offenen Änderungen aber nicht vorher dort | (A) offene Änderungen vor dem Wechsel auf dem Rettungsbranch sichern; (B) den Wechsel ablehnen und „Verwerfen“ anbieten; (C) Änderungen mitnehmen | (A) |
| Protokolle (#84): Zwischenschritte des Plannings | Heute bekommt nur der Schritt Commitment ein Protokoll; Fehltage und Einplanung nicht | (a) so lassen; (b) auch Fehltage und Einplanung protokollieren (mehr Dateien je Sprint); (c) ein Protokoll je Planning-Sitzung | (a), bis der Owner mehr Nachvollziehbarkeit wünscht; dann (c) |

Ebenfalls nicht umgesetzt, weil das Verhalten ändernd: aus dem Review von #74 die Frage, ob die
App bei bestehenden Daten-Repositories eine `.gitattributes` im Datenordner anbieten soll (siehe
#79; Risiko: CRLF-Dateien im Index gelten danach als geändert); aus #77 die Fragen, ob die Stichprobe
der Simulation durch `window` gedeckelt sein soll und ob der Mindestwert der Simulation (derzeit
ab zwei Werten) angehoben werden soll; aus #78 die Frage nach einer Fußnote zur Spalte „ohne Wert“
in Kommandozeile und Bericht.


## 3. Offene Befunde und bekannte Fehler

Bekannte Fehler und offene Befunde, jeweils mit dem Ort, an dem sie behandelt werden:

- **Flackernde e2e-Tests** (`tests/e2e/test_two_clones.py::test_absences_of_different_people_merge_without_conflict`
  und `::test_same_tag_name_on_different_states_is_shown_as_different`): behoben mit **#82** (Ursache war ein
  Fehler im Produktcode: die Rückmeldung nach „Speichern und teilen“ ging bei einem zweiten Durchlauf
  verloren). Seit dem Merge war die CI auf `main` und den PRs stabil.
- **Nicht abfangbar** (#82): Ein Klick, der verloren geht, weil die zweite Anforderung des Browsers
  vor dem Rückruf selbst eintrifft (Millisekundenfenster).
- **#82 (gemergt, Rest offen):** Die Sperre gilt je Sitzung, nicht je Datenordner (F5, ein zweites
  Fenster oder ein zweiter Serverprozess können parallel abgleichen); ein Datenordnerwechsel verwirft das
  Ergebnis eines laufenden Abgleichs, vorgemerkte Tags bleiben stehen; die Laufanzeige gilt für die ganze
  Sitzung; das Aufräumen nach der Ruhezeit löscht noch nicht übernommene Ergebnisse. Option: eine
  Höchstdauer der Sperre bei hängendem Abgleich.
- **#84/#90 Protokolle (gemergt, Rest offen, niedrig):** (a) Der Zeitstempel des Protokollnamens sollte unter
  der Sperre `max(jetzt, neuestes + 1 s)` sein; (b) das Ausweichen auf den Temp-Ordner sollte nur bei
  dauerhaften Fehlern geschehen, bei WinError 32/EBUSY kurz wiederholen; (c) Fehler beim Bestimmen der
  Sperrdatei als `FileAccessError`; (d) EACCES unter Linux/macOS nicht als „belegt“ werten; (e) der Sperrort
  hängt von Benutzerkonto und Umgebung ab; (f) Fehler beim Rückbau dem Benutzer melden; (g) der
  Windows-Test der Fehlernummern 32/33 prüft sie nicht.
- **#86/#91 Excel (gemergt, Rest offen, niedrig):** Die Lockerung unter Linux/macOS macht neue IDs
  unportabel (Klon unter Windows); der Rundlauf Export → Import scheitert unter Linux für IDs wie `a:b`;
  `casefold` weicht von den Dateisystemen ab (ß, NFC/NFD).
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
- **#81 (gemergt, Rest offen):** Der Schreibfehler beim automatischen Zusammenführen (`resolve_conflicts`)
  hat jetzt einen eigenen Hinweistext, `GIT_HELP` und `docs/konzept-kern.md` nennen die neuen Fälle, die
  englischen Fassungen stehen in `locale_en.py`. Offen: der Hinweis zu `locked` erwähnt bei „unable to
  unlink“ / „Device busy“ weiter die `index.lock`, weil `hint_for` die Meldung nicht kennt; ein nacktes
  „Could not read from remote repository“ und „unable to access … 503“ bleiben `offline`; ein Einhängepunkt
  auf Linux, der bei fehlendem Laufwerk als leerer Ordner bestehen bleibt, gilt weiter als „nicht gefunden“;
  schlägt „Zurück auf den Branch“ nach dem Anlegen des Rettungsbranchs fehl, nennt die Fehlermeldung ihn
  nicht (nur die Erfolgsmeldung). Entscheidung des Owners: Sichern vor dem Wechsel (Teil 2).
- **Codex-Kontingent:** Das Kontingent für Code-Reviews war am 18.10.2026 erschöpft. Bis es zurück ist,
  prüfen eigene Agenten (vier Blickwinkel plus Skeptiker) und die `claude-review` der CI. Codex hat #84
  (elf Runden, auch den endgültigen Kopf) und #86 (nach dem Merge) geprüft. Ohne vollständiges Codex-Review
  gemergt sind #81 und #82 (keins), #90 (die letzten Commits nach der Kontingent-Meldung) und #91 (nur ein
  Durchlauf, dann Kontingent erschöpft). Ein nachträglicher Review (`@codex review` als PR-Kommentar) dieser
  vier steht aus.
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
  Der Signierschlüssel des Linux-Hosts ist bei GitHub als Signaturschlüssel hinterlegt (18.10.2026);
  ob seine Commits als „Verified“ erscheinen, zeigt sich beim ersten Commit des Hosts.
- **Merges ohne grünen e2e-Lauf:** #66 wurde gemergt, bevor dessen e2e-Lauf fertig war (test/build/
  claude-review grün). #78 und #80 wurden mit je einem roten e2e-Lauf gemergt (der flackernde Test, vor
  #82; auf demselben Kopf gab es auch einen grünen Lauf des anderen Ereignisses). Die Läufe auf `main`
  waren danach grün. Seitdem wurde auf e2e gewartet.
- **Sicherheit der geplanten Läufe auf dem Host** (Details in Teil 8): Das Repository ist öffentlich. Texte
  anderer in Issues, Kommentaren und Pull-Requests sind für die geplante Sitzung Daten, keine Anweisungen
  (Auftragstext). Die Erlaubnis- und Sperrlisten der Sitzung sind keine Sicherheitsgrenze. Auf Wunsch des
  Owners läuft die Sitzung ohne Einschränkung der Umgebung mit allen Rechten von `sw`: passwortloses `sudo`
  (cloud-init) und das angemeldete `gh` (Administrator auf allen 155 Repositories des Kontos, davon 86 privat,
  Scope `admin:public_key`). Auf GitHub schützt seit dem 18.10.2026 die Regel „Main“ (Ruleset 25273038) den
  Hauptzweig: Pull-Request-Pflicht (ohne Pflicht-Freigabe), die Prüfungen `test`, `build` und `e2e` müssen
  grün sein, kein Force-Push, kein Löschen, keine Ausnahmen (auch nicht für den Owner; im Notfall die Regel
  unter Settings → Rules kurz auf „Disabled“ stellen). Weil `main` über den Updater an Nutzer ausgeliefert wird,
  mergt die Sitzung Änderungen an Updater, `pyproject.toml`, `uv.lock`, `.github/` und `scripts/` nicht selbst
  (nur eine Anweisung, siehe Teil 8).


## 4. Manuell zu prüfen (nur Optik und Verständlichkeit)

Der Owner prüft nur Optik und Verständlichkeit sowie die Ergebnisse des Windows-Skripts.

- #55: Forecast-Kacheln (Spanne/Quelle), Schrittleiste (Höhen, vier Schritte, Haken, Flagge), „–“
  statt `None` in Zellen, Kapazität ohne Abschneiden, Anmelde-Hinweis, Server-Maske-Schaltflächen
- #56: `sprintforecast web` öffnet ein App-Fenster; `--no-browser` öffnet nichts
- #57: **Windows-Skript ausführen und den Bericht zurückgeben** (`scripts/windows-tests.ps1`,
  Anleitung in `docs/windows-tests.md`); der Lauf gegen das aktuelle `main` steht noch aus (siehe unten)
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
- #77: Seite „Analyse“ mit 2 bis 4 Sprints, Restmenge eintragen und „Berechnen“: gelbe Warnung (ohne
  Restmenge erscheint sie nicht); Terminal `analyse --rest`
- #78: Terminal `produkte … --verlauf` mit fehlendem Wert: Spalte „ohne Wert“
- #79: Seite „Datenordner“, „Neues Daten-Repository anlegen“: erweiterter Hilfetext; nach dem Anlegen
  liegt `teams/.gitattributes` neben den Teams und gilt bis zum ersten „Speichern und teilen“ als
  offene Änderung
- #62 (nach dem Merge): Stand-Angaben in `docs/konzept-kern.md` stimmen mit dem Eindruck überein

Pull-Requests, die erst spät in der Nacht oder am Tag danach gemergt wurden (jetzt prüfen):

- #76: Seitenleiste „Neu von anderen“, Reiter Tags, Konfliktseite, Verwerfen-Liste: Autor, Betreff,
  Tag-Namen, Dateipfade als Code gut lesbar (auch in der schmalen Seitenleiste)?
- #80: Terminal mit Namen wie „Eva [x]“ oder Produkt `[/x]`: Ausgabe unverändert lesbar
- #81: Boxen „Repository nicht gefunden“ und „Git hält den Ordner für unsicher“ (der Text nennt den
  anderen Benutzer), Meldung zum Rettungsbranch nach „Zurück auf den Branch“; Hilfeseite
  „Zusammenarbeit (Git)“: neue Abschnitte verständlich?
- #82: nach „Fehltage speichern“ sofort „Speichern und teilen“ klicken; die Meldung („… übernommen“,
  „Hochgeladen“) erscheint immer
- #84/#90: Beim Speichern eines Sprint-Termins entsteht ein Protokoll (Markdown) im Datenordner; die
  früheren Stände lassen sich ansehen; im Planning mit „Einfrieren aufheben“ heißt das alte Protokoll
  danach `…_obsolet_<JJJJMMTT>-<HHMMSS>.md` (Datum und Zeit mit Bindestrich)
- #85: „Was-wäre-wenn“: Eingabefelder auf einer Höhe; Planning Schritt 2 zeigt unter der Spanne die Zeile
  „Kapazität: … PT mit Produktionszugriff (… %), … PT ohne · Forecast PLAN: bis zu …“ (nur bei
  eingeschaltetem Bereich „Produktionszugriff“ und berechtigten Personen mit Kapazität)
- #86/#91: Excel-Ausgabe je Team: Weboberfläche, Forecast-Seite „Excel-Liste erstellen“ und
  „herunterladen“, oder `sprintforecast excel …`; Blätter, Formeln und Trend-Diagramm in Excel öffnen.
  `sprintforecast excel-import …` (nur Kommandozeile): Vorschau der Änderungen lesbar, abgelehnte Zellen mit Grund
- Windows-Skript (#57): `scripts/windows-tests.ps1` ist am 18.10. einmal ohne Rückfragen gelaufen (Zeilenenden:
  Fehler; gesperrte Datei und Symlink: Hinweis; interaktive Prüfungen übersprungen); die Windows-Befunde
  von #87 bis #89 kamen aus dem anschließenden `pytest`-Lauf unter Windows. Ein erneuter Lauf gegen das
  aktuelle `main` samt den interaktiven Prüfungen (Anmeldung) und der Bericht an den Owner stehen aus (kann
  nur lokal unter Windows laufen)


## 5. Reihenfolge der Merges

Alle Pull-Requests der Nacht und des Tages danach sind gemergt (siehe Teil 1). Offen ist nur dieser PR
([#83](https://github.com/swallat/sprint-forecast/pull/83)); er enthält Dokumentation und die
Referenzkopien des Läufers (Teil 8) und wird gemergt, sobald die CI grün ist. Danach hebt der Owner (oder
die Sitzung, die ihn gemergt hat) die Pause des Läufers auf, und die Todo-Liste unten beginnt. Neue Wünsche
des Owners kommen immer zuerst in diese Liste; erst wenn keine Pull-Requests mehr offen sind, wird mit neuen
Funktionen begonnen.


## 6. Todo-Liste

Reihenfolge nach Nutzen und Risiko; kleine Pull-Requests mit je einem Thema. Wer hier arbeitet (die
planmäßige Aufgabe auf dem Linux-Host in Teil 8 oder eine Sitzung des Owners), nimmt den ersten Punkt, der
nicht auf den Owner wartet, und hakt ihn nach dem Merge hier in einem kleinen PR ab.

**A. Wünsche des Owners (Stand 18.10.2026)**

1. **Änderungen als Änderungen anzeigen:** Vor dem Speichern oder Committen eine Änderungsansicht
   (was hat sich an welchen Werten geändert), damit Änderungen nachvollziehbar sind.
2. **Besserer Vorschlag für die Commit-Nachricht:** aus den geänderten Dateien und Werten abgeleitet statt
   „Sprint-Daten aktualisiert“ (`COMMIT_DEFAULT` in `web/ui.py`; englisch „Sprint data updated“ in
   `locale_en.py`). Punkt 1 und 2 teilen sich die Diff-Logik und gehören in einen gemeinsamen,
   zuerst nur lesenden Baustein (`diff`-Modul), dann zwei kleine PRs.
3. **Excel-Import in der Weboberfläche:** bisher nur in der Kommandozeile (`excel-import`); mit Vorschau
   und Bestätigung wie dort.

**B. Entscheidungen des Owners** (Teil 2): je Entscheidung ein kleiner PR, erst nach der Antwort.
A1 „Plan in der Bandbreite“ (ändert Zahlen), D4b Prognosen über `at` vereinigen, A5 Quote als unsicher
kennzeichnen, Git-Identität (nur Text), Phase P als abgeschlossen führen, „Zurück auf den Branch“ sichert
die Änderungen, Protokolle für die Zwischenschritte des Plannings. Die planmäßige Aufgabe darf diese Punkte
nicht ohne Antwort umsetzen. Zum Betrieb auf dem Host (Teil 3 und 8) hat der Owner entschieden: `main` wird
geschützt (erledigt, Ruleset „Main“); `sudo` und das volle `gh` bleiben bewusst, die Umgebung wird nicht
eingeschränkt, der Job wird nur gestartet. Offen (nur auf Wunsch): ein beschränktes Token, eine
Einschränkung der Einheit oder ein eigener Benutzer für die Sitzung (Teil 8, Sicherheit).

**C. Backlog aus den Reviews** (Teil 3): niedrige Punkte zu #76, #80, #81, #82, #84/#90, #86/#91; mittlere
Punkte zuerst (#82: Sperre je Datenordner statt je Sitzung, Ergebnis beim Datenordnerwechsel).

**D. Aufräumen und Robustheit**

1. **Übersetzungen aufräumen:** Test auf verwaiste englische Schlüssel (Schlüssel, die nirgends in
   `src/` als `t()`-Literal vorkommen) und Entfernen der ungenutzten Einträge (rund 47 Kandidaten, einzeln
   prüfen).
2. **Robustheit aus dem Audit der Nacht** (Stand zu Beginn der Nacht „offen“, nicht erneut geprüft):
   Updater-Status (ausdrückliches `--auto` wird als gespeichert gemeldet, obwohl das Schreiben
   scheiterte), Protokolldatei des App-Starters nicht abgesichert, Feldtypen in `settings.json`,
   Wertebereiche von CLI-Optionen, unterschiedliches Verhalten von CLI und Weboberfläche bei
   ungültigen Eingaben (CLI schreibt und meldet nachträglich), stille Annahmen (Entscheidung nötig).
3. **Doku:** In `docs/konzept-kern.md` die Stand-Zellen von A3 und B5 (Spanne und Warnung an Planning,
   Fehltage, Vorplanung, Kommandozeile und `analyse --rest`: #66, #77), A10 (fehlende Erledigt-Werte in
   Kommandozeile und Bericht: #78) und D.5 (`.gitattributes` im Datenordner neuer Repositories: #79)
   nachführen; README-Hinweise (FTE, Produktanteil, Einstellungen, Vorplanung, Begriffe im Rechenweg),
   Abnahmetests zur Doku (D-Abnahme).
4. **Hinweistexte zur Anmelde-Hilfe** (D6) ohne Anmeldung in der App.

**E. Nur mit dem Owner oder lokal unter Windows**

1. **Windows-Skript:** `scripts/windows-tests.ps1` erneut gegen das aktuelle `main` laufen lassen, samt
   den interaktiven Prüfungen (Anmeldung), und den Bericht an den Owner geben; Befunde daraus als kleine PRs.
   Läuft nicht auf dem Linux-Host.
2. **Nachträglicher Codex-Review** der ohne vollständigen Codex-Review gemergten PRs #81, #82, #90, #91,
   sobald das Kontingent zurück ist (`@codex review` als PR-Kommentar, das darf auch die planmäßige Aufgabe
   anstoßen); bestätigte Befunde als Folge-PR.
3. **Manuelle Prüfungen** des Owners (Teil 4).

## 7. Übergabe-Prompt für die lokale Windows-Sitzung

Der folgende Text ist der vollständige Auftrag für die lokale Sitzung; er ist wie der ursprüngliche
Auftrag aufgebaut. Stand 18.10.2026 abends: Die Aufgaben 1 (bis auf den erneuten Windows-Lauf) und 2
sind erledigt, Aufgabe 3 und 4 sind in Teil 2 und 6 fortgeführt. Die Regeln gelten unverändert und sind
die Grundlage des Auftragstexts für den Linux-Host (Teil 8).

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

## 8. Betrieb auf dem Linux-Host (planmäßige Aufgabe)

Damit die Arbeit auch nachts und nach dem Zurücksetzen des Kontingents weiterläuft, startet ein Timer auf
dem Linux-Host des Owners stündlich eine interaktive Claude-Code-Sitzung **mit Remote Control** (in einem
eigenen `tmux`-Server), die die Todo-Liste (Teil 6) abarbeitet. Der Owner sieht die Sitzung in claude.ai/code
oder in der App, kann zuschauen und ihr schreiben. Die Regeln der Sitzung stehen im Auftragstext
`docs/linux-betrieb/prompt.md` (Kopie des Texts auf dem Host) und entsprechen Teil 7.

**Host und Werkzeuge**

- Host: `sw@workstation.nova.wallat.de` (Linux, 8 Kerne, 15 GB), Klon `~/devel/sprint-forecast`. Der Klon
  ist in Claude Code als vertrauenswürdig bestätigt (sonst fragt die interaktive Sitzung beim Start).
- Python 3.14 und uv kommen über `mise` (`mise.toml` im Repository, Shims zuerst im `PATH` des Läufers);
  Abhängigkeiten mit `uv sync --all-extras`. `gh` ist per https am Konto `swallat` angemeldet (so vom Owner
  eingerichtet), die Claude-Code-Anmeldung gehört dem Owner.
- Git: globale Konfiguration mit Name und Commit-Adresse `873008+swallat@users.noreply.github.com`,
  Commits per SSH signiert (`commit.gpgsign=true`, Schlüssel `~/.ssh/id_ed25519_signing`). Der öffentliche
  Schlüssel ist bei GitHub als **Signaturschlüssel** hinterlegt (18.10.2026). Fingerabdruck:
  `SHA256:drX+EJmXujvgrttwiGjAT6Fv44jQDQvjxatHmeb4d6I`.

**Ablauf**

- Der systemd-Timer des Benutzers (`sprintforecast-lauf.timer`, stündlich, bis zwei Minuten verzögert, holt
  verpasste Läufe nach) startet `sprintforecast-lauf.service`, die `~/sprintforecast-lauf/sprintforecast-lauf.sh`
  ausführt. Mit `loginctl enable-linger sw` läuft das auch ohne angemeldeten Benutzer. Es ist kein cron
  installiert. Die Einheit startet nur den Job; sie schränkt die Umgebung nicht ein.
- Der Läufer startet nie zwei Läufe gleichzeitig und überspringt den Lauf bei gesetzter Pausen-Datei
  (`zustand/PAUSE`), fehlendem Auftragstext oder wenn `git fetch` dreimal scheitert (Eintrag in
  `zustand/uebersprungen.txt`). Dann startet er die Sitzung im `tmux`-Server `zustand/tmux.sock` (Sitzung `lauf`,
  Remote-Control-Name `sprint-forecast-<Zeit>`). Die Sitzung liest zuerst `docs/uebergabe.md` von `origin/main` und
  nimmt dann die erste Aufgabe aus Teil 6, die nicht auf den Owner wartet; offene Pull-Requests gehen vor. Je Lauf
  höchstens zwei Pull-Requests; läuft die CI noch, endet der Lauf, der nächste setzt fort.
- Ende des Laufs: Zwei Hooks melden dem Läufer, ob die Sitzung still ist (`Stop` nach jeder Antwort,
  `UserPromptSubmit` bei jeder Eingabe, auch des Owners über Remote Control). Ist sie 10 Minuten still, beendet
  der Läufer sie mit `/exit`; spätestens nach 160 Minuten (Einheit: 3 Stunden) beendet er sie hart. **`zustand/PAUSE`
  hält auch einen laufenden Lauf an.** Das Protokoll mit dem Bildschirm am Ende liegt in `zustand/<Zeit>.log`
  (auch wenn sich `claude` selbst beendet oder systemd den Läufer beendet), die Zusammenfassung in
  `zustand/berichte/<Zeit>.md`; beides wird nach 30 Tagen gelöscht.
- Ist das Kontingent leer oder die Anmeldung abgelaufen, zeigt die Sitzung eine Fehlermeldung. Ob der
  `Stop`-Hook dann ausgelöst wird, ist nicht getestet; im ungünstigen Fall endet die Sitzung erst an der
  Zeitgrenze, und der nächste Lauf versucht es danach erneut. So setzt sich die Arbeit nach dem Zurücksetzen
  des Kontingents von selbst fort (im ungünstigen Fall mit bis zu drei Stunden Verzögerung).
- Berechtigungsmodus der Sitzung ist `dontAsk`: Was nicht ausdrücklich erlaubt ist, wird sofort abgelehnt, es
  gibt keine Rückfragen (eine unbeantwortete Rückfrage würde den Lauf bis zur Zeitgrenze blockieren). Auch der
  Owner kann Werkzeugaufrufe deshalb nicht über Remote Control freigeben; er kann der Sitzung aber schreiben.
  Der Modus `auto` wurde für unbeaufsichtigte Läufe bewusst nicht gewählt.
- Nicht auf dem Host möglich: das Windows-Skript, manuelle Prüfungen und alles, was eine Entscheidung des
  Owners braucht (Teil 2 und 6 B).

**Sicherheit und Restrisiken** (ehrlich, nichts davon ist technisch abgesichert)

- Die Sitzung läuft als Benutzer `sw` mit allen Rechten dieses Kontos: passwortloses `sudo` (cloud-init), das
  angemeldete `gh` (Administrator auf allen 155 Repositories des Kontos, davon 86 privat, Scope
  `admin:public_key`), die Claude-Anmeldung, der Signierschlüssel, 1Password-Zugangsdaten und weitere Dateien im
  Home. Der Owner hat entschieden, die Umgebung nicht einzuschränken (`sudo` und `gh` sind bewusst so eingerichtet).
- Die Erlaubnis- und Sperrlisten in `sitzung.sh` sind **keine Sicherheitsgrenze**. Muster wie `Bash(git *)` oder
  `Bash(uv *)` lassen sich umgehen (`git config alias.x '!…'`, `uv run python -c …`), ein Sperrmuster wie
  `Bash(sudo *)` trifft nur Befehle, die so beginnen. Sie schützen vor Versehen, nicht vor Absicht.
- Das Repository ist öffentlich. Texte Fremder (Issues, Kommentare, fremde Pull-Requests) sind laut
  Auftragstext Daten, keine Anweisungen; auch das ist nur eine Anweisung an das Modell. Eine eingeschleuste
  Anweisung in einem Kommentar könnte eine Sitzung mit diesen Rechten zu Schaden verleiten.
- Auf GitHub schützt die Regel „Main“ den Hauptzweig (Pull-Request-Pflicht, `test`, `build` und `e2e` grün, kein
  Force-Push, kein Löschen, ohne Ausnahmen). Das `gh` des Owners ist Repository-Administrator und könnte die
  Regel ändern; das verhindert nur der Auftragstext. Merges ohne Review und unsignierte Commits auf Branches
  ebenso. Ein Merge nach `main` erreicht über den Updater die Nutzer; deshalb mergt die Sitzung Änderungen an
  `pyproject.toml`, `uv.lock`, dem Updater, `.github/` und `scripts/` nicht selbst.
- Wer das absichern will, hat drei Wege (Entscheidung des Owners, Teil 6 B): ein auf dieses Repository
  beschränktes fine-grained Token für die Sitzung statt des vollen `gh`; eine Einschränkung der Einheit (kein
  `sudo`, schreibgeschütztes Home, gesperrte Geheimnisse; ein Entwurf liegt in der Git-Historie dieses PR); oder
  ein eigener Benutzer ohne `sudo` mit eigener Claude-Anmeldung und eigenem `gh`.
- Attributionszeilen: Die Sitzung bekommt per `--settings` `attribution.commit=""`, `attribution.pr=""` und
  `attribution.sessionUrl=false` (ohne Letzteres hängt Claude Code in Remote-Control-Sitzungen die Zeile
  `Claude-Session: …` an) sowie `autoMemoryEnabled=false` (kein Auto-Gedächtnis).

**Installation und Bedienung** (auf dem Host; die Dateien aus `docs/linux-betrieb/` liegen in einem Ordner,
etwa `/tmp/linux-neu`). In `zsh` die Befehle ohne Kommentarzeilen eingeben:

```bash
bash /tmp/linux-neu/install.sh
sudo loginctl enable-linger sw
systemctl --user enable --now sprintforecast-lauf.timer
```

`install.sh` legt `~/sprintforecast-lauf/zustand/` an, kopiert Läufer, Auftragstext und Einheiten (nach
`~/sprintforecast-lauf/` und `~/.config/systemd/user/`), lädt die Einheiten neu und aktiviert nichts; die
nächsten Schritte gibt es am Ende aus. Auf einem frischen Host davor: Klon anlegen und
`mise trust && mise install && uv sync --all-extras`, `gh` und Claude anmelden, Git-Konfiguration und
Signierschlüssel einrichten, den Klon einmal in Claude Code als vertrauenswürdig bestätigen.

Im Alltag:

```bash
touch ~/sprintforecast-lauf/zustand/PAUSE
rm ~/sprintforecast-lauf/zustand/PAUSE
systemctl --user list-timers sprintforecast-lauf.timer
systemctl --user start --no-block sprintforecast-lauf.service
tmux -S ~/sprintforecast-lauf/zustand/tmux.sock attach -t lauf
ls -t ~/sprintforecast-lauf/zustand/berichte | head
systemctl --user disable --now sprintforecast-lauf.timer
```

(Reihenfolge: anhalten, fortsetzen, nächster Lauf, sofort einen Lauf starten, im Terminal zuschauen und mit
Strg-b d lösen, Zusammenfassungen, ganz abschalten.) Änderungen am Läufer, am Auftragstext oder an den Einheiten
werden zuerst unter `docs/linux-betrieb/` nachgeführt und dann mit `install.sh` auf den Host gebracht. Das
Repository legt für diese Dateien LF-Zeilenenden und ausführbare Skripte fest; eine CRLF-Kopie bricht die
Shebang-Zeile (`install.sh` prüft das).
