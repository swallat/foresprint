#!/usr/bin/env bash
# Planmäßige Aufgabe für sprint-forecast: startet Claude Code ohne Terminal (claude -p) und
# arbeitet die Todo-Liste aus docs/uebergabe.md ab. Wird vom systemd-Timer stündlich gerufen.
#
# Anhalten:   touch ~/sprintforecast-lauf/PAUSE   (Fortsetzen: Datei löschen)
# Protokolle: ~/sprintforecast-lauf/<Zeitstempel>.log
set -u

export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin"
REPO="$HOME/devel/sprint-forecast"
DIR="$HOME/sprintforecast-lauf"
PROMPT="$DIR/prompt.md"
mkdir -p "$DIR"

# Nie zwei Läufe gleichzeitig: ein früherer Lauf kann länger als eine Stunde dauern.
exec 9>"$DIR/lauf.lock"
if ! flock -n 9; then
    echo "$(date -Is) übersprungen: ein Lauf ist noch aktiv" >>"$DIR/uebersprungen.log"
    exit 0
fi

if [ -e "$DIR/PAUSE" ]; then
    echo "$(date -Is) übersprungen: PAUSE gesetzt" >>"$DIR/uebersprungen.log"
    exit 0
fi

cd "$REPO" || exit 1
git fetch origin --prune --quiet || {
    echo "$(date -Is) übersprungen: git fetch fehlgeschlagen (Netz oder Anmeldung)" >>"$DIR/uebersprungen.log"
    exit 0
}

LOG="$DIR/$(date +%Y%m%d-%H%M%S).log"
{
    echo "== Start $(date -Is)"
    # Erlaubt ist, was die Arbeit an Pull-Requests braucht; sudo und Löschen außerhalb des Klons
    # bleiben verboten. Was nicht erlaubt ist, wird im Lauf abgelehnt (kein Nachfragen).
    timeout --signal=TERM --kill-after=60 170m claude -p "$(cat "$PROMPT")" \
        --permission-mode acceptEdits \
        --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "Agent" \
            "Bash(git *)" "Bash(gh *)" "Bash(uv *)" "Bash(mise *)" "Bash(ls *)" "Bash(cat *)" \
            "Bash(grep *)" "Bash(rg *)" "Bash(sed *)" "Bash(head *)" "Bash(tail *)" "Bash(wc *)" \
            "Bash(sort *)" "Bash(diff *)" "Bash(mkdir *)" "Bash(cp *)" "Bash(mv *)" \
            "Bash(python *)" "Bash(python3 *)" "Bash(date *)" "Bash(sleep *)" "Bash(touch *)" \
        --disallowedTools "Bash(sudo *)" "Bash(rm -rf /*)" "Bash(rm -rf ~*)" \
        --max-turns 400 \
        --output-format text
    echo "== Ende $(date -Is) (Rückgabewert $?)"
} >"$LOG" 2>&1

# Alte Protokolle nach 30 Tagen löschen.
find "$DIR" -maxdepth 1 -name '*.log' -mtime +30 -delete 2>/dev/null
exit 0
