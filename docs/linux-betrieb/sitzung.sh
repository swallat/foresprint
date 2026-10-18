#!/usr/bin/env bash
# Läuft im tmux-Fenster des Läufers: startet die interaktive Claude-Code-Sitzung mit Remote Control.
# Aufruf: sitzung.sh <Skript-Ordner> <Klon> <Name> <Zusammenfassung> <Settings-Datei> <Auftragstext>
set -u

DIR="$1"; REPO="$2"; NAME="$3"; BERICHT="$4"; SETTINGS="$5"; PROMPT="$6"
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export SPRINTFORECAST_LAUF_DIR="$DIR/zustand"
cd "$REPO" || exit 1

AUFTRAG="$(cat "$PROMPT")

LAUFDATEN
- Sitzungsname: $NAME. Der Owner kann sich über Remote Control zuschalten; seine Nachrichten haben Vorrang.
- Schreibe am Ende die Zusammenfassung mit dem Write-Werkzeug nach $BERICHT (Deutsch, kurz: getan, offen,
  blockiert, eigene Merges) und tu danach nichts mehr. Die Sitzung endet von selbst, wenn sie eine Weile still ist."

# Der Auftragstext steht vor den Optionen, damit ihn die Listen von --allowedTools nicht verschlucken.
#
# Die Listen sind Komfort und Schutz vor Versehen, KEINE Sicherheitsgrenze: Muster wie „Bash(git *)“ lassen
# sich umgehen (z. B. git -c …, uv run python -c …). Die eigentliche Grenze setzt die systemd-Einheit
# (kein sudo, Home schreibgeschützt, nur Klon und zustand/ beschreibbar). Im Modus „dontAsk“ wird alles, was
# nicht ausdrücklich erlaubt ist, ohne Rückfrage abgelehnt; eine unbeantwortete Rückfrage würde sonst den
# ganzen Lauf bis zur Zeitgrenze blockieren.
exec claude "$AUFTRAG" \
    --remote-control="$NAME" \
    --permission-mode dontAsk \
    --settings "$SETTINGS" \
    --add-dir "$(dirname "$BERICHT")" \
    --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "Agent" \
        "Bash(git *)" "Bash(gh *)" "Bash(uv *)" "Bash(mise *)" \
        "Bash(echo *)" "Bash(cd *)" "Bash(ls *)" "Bash(cat *)" "Bash(grep *)" "Bash(rg *)" "Bash(head *)" "Bash(tail *)" \
        "Bash(wc *)" "Bash(sort *)" "Bash(diff *)" "Bash(date *)" "Bash(sleep *)" \
    --disallowedTools "Bash(sudo *)" "Bash(su *)" \
        "Bash(git push --force*)" "Bash(git push -f*)" "Bash(git push * --force*)" "Bash(git push * -f*)" \
        "Bash(git push --delete*)" "Bash(git push * --delete*)" "Bash(git push * :*)" \
        "Bash(git -c *)" "Bash(git config --global*)" "Bash(git config --system*)" \
        "Bash(git * --no-gpg-sign*)" "Bash(git * --no-verify*)" \
        "Bash(gh auth token*)" "Bash(gh auth login*)" "Bash(gh auth logout*)" "Bash(gh auth refresh*)" \
        "Bash(gh auth switch*)" "Bash(gh auth setup-git*)" "Bash(gh ssh-key *)" "Bash(gh gpg-key *)" "Bash(gh secret *)" \
        "Bash(gh variable *)" "Bash(gh repo delete*)" "Bash(gh repo edit*)" "Bash(gh ruleset *)" \
        "Bash(gh api * -X DELETE*)" "Bash(gh api -X DELETE*)" "Bash(gh api * --method DELETE*)"
