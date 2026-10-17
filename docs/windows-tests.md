# Windows-Prüfung (`scripts/windows-tests.ps1`)

Das Skript prüft, was sich nur auf einem echten Windows-Rechner zeigt, und schreibt einen
Markdown-Bericht, den du an die Entwicklung zurückgibst. Es ändert keine Benutzer-Einstellungen
(kein `git config`, keine dauerhaften Umgebungsvariablen, keine Registry-Schreibzugriffe). Alle
Testdaten liegen in einem Temp-Ordner, der am Ende gelöscht wird.

## Voraussetzungen

- Windows 10 oder 11, Windows PowerShell 5.1 oder PowerShell 7
- `sprintforecast` als uv-Tool installiert (`uv tool install …`), `git` und `uv` im PATH
- für die Anmelde-Prüfung: die https- und/oder SSH-Adresse deines Daten-Repositorys
- **alle sprintforecast-Fenster vorher schließen** (sonst überspringt das Skript die App-Prüfung)

## Starten

Im Ordner dieses Repositorys (nach `git pull`), ohne die Ausführungsrichtlinie dauerhaft zu ändern:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-tests.ps1
```

Wurde die Datei heruntergeladen und meldet Windows, sie sei blockiert, vorher einmalig
`Unblock-File .\scripts\windows-tests.ps1`.

Der Bericht entsteht im **aktuellen Ordner** als `sprintforecast-windows-bericht-JJJJMMTT-HHMM.md`.
Er enthält keine Zugangsdaten (Token und Zugangsdaten in Adressen werden durch `***` ersetzt, der
Profilordner durch `%USERPROFILE%`); lies ihn trotzdem kurz durch, bevor du ihn weitergibst.

Nützliche Parameter:

| Parameter | Wirkung |
|---|---|
| `-Nur Zeilenenden,Symlink` | nur diese Prüfungen (`App`, `Uv`, `Anmeldung`, `Zeilenenden`, `Sperre`, `Symlink`, `Interaktiv`), durch Komma getrennt, ohne Leerzeichen |
| `-HttpsUrl …` / `-SshUrl …` | Adressen für die Anmelde-Prüfung (sonst fragt das Skript; Enter überspringt) |
| `-WartezeitSekunden 30` | Wartezeit nach dem Schließen des App-Fensters (Standard 20) |
| `-OhneRueckfragen` | keine Eingaben; Rückfragen und interaktive Prüfungen entfallen |
| `-MitAutoUpdate` | App im Test mit der eingestellten Selbstaktualisierung starten (Standard: aus, nur für diesen Start) |
| `-Bericht PFAD` | Berichtsdatei woanders ablegen |
| `-PythonExe PFAD` | Python der Installation vorgeben, falls es nicht gefunden wird |

## Was geprüft wird

Dauer ohne Rückfragen etwa 2 bis 3 Minuten; die interaktiven Fragen kommen dazu.

1. **App starten und beenden.** Das Skript startet `sprintforecast-app` mit einem temporären
   Daten-Repository (nur für diesen Start über `SPRINTFORECAST_DATEN`), wartet auf Server und
   Fenster und listet alle Prozesse. Dann schließt es das Fenster wie der Schließen-Knopf
   (`CloseMainWindow`; klappt das nicht, bittet es dich, das Fenster selbst zu schließen), wartet
   20 Sekunden und prüft per `Get-CimInstance Win32_Process`, dass nichts mehr läuft:
   kein `sprintforecast-app.exe`, kein `python(w).exe` mit sprintforecast/streamlit, kein Browser
   mit `--user-data-dir=…\sprintforecast\…`, keine `uv.exe`-Aktualisierung. Bleiben Prozesse, nennt
   der Bericht sie samt Zeitpunkt, zu dem sie später endeten. Zusätzlich zeigt er `app.log` und
   `update.log` aus `%APPDATA%\sprintforecast`. Übrig gebliebene Prozesse beendet das Skript am Ende.
2. **Installation (uv tool).** `uv tool list`; auf Wunsch (Rückfrage j/N, nur bei geschlossener App)
   `uv tool upgrade sprintforecast`.
3. **Anmeldung (Git).** `credential.helper` samt Herkunft, Git Credential Manager, `gh auth status`,
   SSH-Agent und `git ls-remote` gegen deine https- und SSH-Adresse. Adressen mit Zugangsdaten
   werden abgelehnt. Ein Anmeldefenster des Credential Managers kann sich öffnen; Zeitlimit 90 s.
4. **Zeilenenden.** Das Skript legt ein Daten-Repository mit der App-Logik an (Team `demo`, Sprints
   über `sprintforecast sprints`), committiert, klont es dreimal (deine `core.autocrlf`-Einstellung,
   `autocrlf=true`, `autocrlf=false`) und prüft: `git status`/`git diff` leer, `sprintforecast
   pruefen` fehlerfrei, erneutes Speichern ändert nichts.
5. **Gesperrte Datei.** Hält eine YAML-Datei mit exklusiver Sperre (`FileShare.None`) und mit
   Lesesperre (`FileShare.Read`) und speichert über die App-Logik. Erwartet: Datei unverändert, keine
   `*.tmp`-Reste, und eine verständliche Meldung statt eines rohen Systemfehlers
   (`PermissionError` wird als **HINWEIS** gemeldet).
6. **Symlink-Recht.** Legt im Temp-Ordner eine symbolische Verknüpfung an und meldet Administrator
   und Entwicklermodus. Ohne Recht ist das kein Fehler der App; nur ein Test der Entwicklung
   (Symlink) entfällt dann.
7. **Interaktive Prüfungen** (nur mit Eingabe): Netz getrennt, geschützter Branch und die Optik
   (Startseite, Schrittleiste, Tabellen, Server-Maske, Konfliktseite, Was-wäre-wenn/Historie,
   Kalendertexte/Rechenweg, englische Oberfläche). Je Frage `J`, `N` oder Enter (überspringen),
   danach eine Notiz. Dafür öffnest du die App selbst (Verknüpfung) mit deinem echten Repository.

## Ergebniswerte

| Wert | Bedeutung |
|---|---|
| OK | Erwartung erfüllt |
| FEHLER | Erwartung verletzt (Details im Bericht) |
| HINWEIS | Auffällig oder nicht vollständig prüfbar, aber kein harter Fehler |
| ÜBERSPRUNGEN | nicht ausgeführt (Voraussetzung fehlt, ohne Rückfragen, nicht Windows) |

## Was das Skript auf deinem Rechner anlegt oder ändert

- Temp-Ordner `%TEMP%\sprintforecast-wintest-…` (wird am Ende gelöscht; bleibt er stehen, nennt das
  Skript den Pfad)
- die Berichtsdatei im aktuellen Ordner
- durch den Start der App (Prüfung 1): deren übliche Dateien unter `%APPDATA%\sprintforecast`
  (`app.log` wird dabei überschrieben) und das Browserprofil unter `%LOCALAPPDATA%\sprintforecast`
- nur gelesen, nicht geändert: Git-Konfiguration, SSH-Agent, Registry (Entwicklermodus)

## Bekannte Grenzen

- Der Test der gesperrten Datei prüft die Speicherfunktion der App, nicht die Oberfläche darüber;
  ob die Oberfläche eine Meldung zeigt, sagt nur der HINWEIS-Text im Bericht.
- Ein Browser, der das Fenster nicht schließen lässt (z. B. Firefox statt Edge/Chrome), erzwingt das
  manuelle Schließen.
- Das Skript wurde unter Linux mit PowerShell 7 auf Syntax und die plattformunabhängigen Prüfungen
  getestet; die Windows-Teile (Prozessliste, Sperren, Fenster schließen) laufen erstmals bei dir.
