#!/usr/bin/env bash
# Planmäßige Aufgabe für sprint-forecast. Startet eine interaktive Claude-Code-Sitzung mit
# Remote Control in einem eigenen tmux-Server und wartet, bis sie fertig ist. So kann der Owner
# den Lauf in claude.ai/code oder in der App ansehen und eingreifen.
#
# Läuft als gehärtete systemd-Benutzereinheit (siehe sprintforecast-lauf.service): ohne sudo, mit
# schreibgeschütztem Home. Dieser Ordner (Skripte, Auftragstext) ist für die Sitzung nur lesbar;
# beschreibbar sind nur der Klon, zustand/ und die Arbeitsordner von Claude und uv.
#
# Bedienung (Ordner = ~/sprintforecast-lauf):
#   touch zustand/PAUSE                                   anhalten (Datei löschen: fortsetzen)
#   tmux -S zustand/tmux.sock attach -t lauf              im Terminal zuschauen (lösen: Strg-b d)
#   Protokolle: zustand/<Zeit>.log, Zusammenfassungen: zustand/berichte/
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO="${SPRINTFORECAST_REPO:-$HOME/devel/sprint-forecast}"
PROMPT="${SPRINTFORECAST_PROMPT:-$DIR/prompt.md}"
LEERLAUF="${SPRINTFORECAST_LEERLAUF:-600}"           # so lange nach der letzten Antwort warten
HARTE_GRENZE="${SPRINTFORECAST_HARTE_GRENZE:-10200}" # 170 Minuten
Z="$DIR/zustand"                                      # der einzige beschreibbare Ordner hier
SOCK="$Z/tmux.sock"
SITZUNG=lauf

mkdir -p "$Z/berichte" "$Z/lauf"
exec 9>"$Z/lauf.lock"
if ! flock -n 9; then
    echo "$(date -Is) übersprungen: ein Lauf ist noch aktiv" >>"$Z/uebersprungen.txt"
    exit 0
fi
if [ -e "$Z/PAUSE" ]; then
    echo "$(date -Is) übersprungen: PAUSE gesetzt" >>"$Z/uebersprungen.txt"
    exit 0
fi

cd "$REPO" || exit 1
# Nach einem Neustart ist das Netz oft noch nicht da: dreimal versuchen.
HOLEN=1
for _ in 1 2 3; do
    if git fetch origin --prune --quiet; then HOLEN=0; break; fi
    sleep 30
done
if [ "$HOLEN" -ne 0 ]; then
    echo "$(date -Is) übersprungen: git fetch fehlgeschlagen (Netz oder Anmeldung)" >>"$Z/uebersprungen.txt"
    exit 0
fi
if tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null; then
    echo "$(date -Is) übersprungen: die tmux-Sitzung existiert noch (vom Owner geöffnet?)" >>"$Z/uebersprungen.txt"
    exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
LOG="$Z/$TS.log"
NAME="sprint-forecast-$TS"
BERICHT="$Z/berichte/$TS.md"
SETTINGS="$Z/lauf/settings-$TS.json"
rm -f "$Z/IDLE" "$SOCK"

# Einstellungen nur für diese Sitzung: keine Attributionszeilen in Commits und PR-Texten (auch nicht die
# Zeile „Claude-Session: …“ aus Remote-Control-Sitzungen: sessionUrl), und Hooks.
# „Stop“ meldet das Ende einer Antwort (Leerlauf), „UserPromptSubmit“ eine neue Eingabe.
cat >"$SETTINGS" <<EOF
{"attribution":{"commit":"","pr":"","sessionUrl":false},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"$DIR/hook.sh idle"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"$DIR/hook.sh aktiv"}]}]}}
EOF

echo "== Start $(date -Is), Sitzung $NAME" >"$LOG"
tmux -S "$SOCK" -f "$DIR/tmux.conf" new-session -d -s "$SITZUNG" -x 200 -y 50 -c "$REPO" \
    "$DIR/sitzung.sh" "$DIR" "$REPO" "$NAME" "$BERICHT" "$SETTINGS" "$PROMPT" >>"$LOG" 2>&1 || {
    echo "== tmux-Start fehlgeschlagen" >>"$LOG"
    exit 0
}

START="$(date +%s)"
ENDE="Sitzung beendet"
while tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null; do
    JETZT="$(date +%s)"
    if [ -e "$Z/IDLE" ] && [ $((JETZT - $(stat -c %Y "$Z/IDLE"))) -ge "$LEERLAUF" ]; then
        ENDE="Leerlauf von $LEERLAUF s"
        break
    fi
    if [ $((JETZT - START)) -ge "$HARTE_GRENZE" ]; then
        ENDE="Zeitgrenze von $HARTE_GRENZE s"
        break
    fi
    sleep 20
done

if tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null; then
    {
        echo "== Bildschirm am Ende ($ENDE):"
        tmux -S "$SOCK" capture-pane -p -J -S -400 -t "$SITZUNG"
    } >>"$LOG" 2>&1
    tmux -S "$SOCK" send-keys -t "$SITZUNG" "/exit" Enter
    for _ in 1 2 3 4 5 6; do
        sleep 5
        tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null || break
    done
    tmux -S "$SOCK" kill-server 2>/dev/null
fi
echo "== Ende $(date -Is): $ENDE" >>"$LOG"
rm -f "$Z/IDLE" "$SETTINGS" "$SOCK"

# Alte Protokolle und Zusammenfassungen nach 30 Tagen löschen.
find "$Z" -maxdepth 2 \( -name '2*.log' -o -path '*/berichte/*.md' \) -mtime +30 -delete 2>/dev/null
exit 0
