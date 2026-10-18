#!/usr/bin/env bash
# Planmäßige Aufgabe für sprint-forecast. Startet eine interaktive Claude-Code-Sitzung mit
# Remote Control in einem eigenen tmux-Server und wartet, bis sie fertig ist. So kann der Owner
# den Lauf in claude.ai/code oder in der App ansehen und eingreifen.
#
# Läuft als systemd-Benutzereinheit (sprintforecast-lauf.service) mit den Rechten des Benutzers; die Einheit
# schränkt die Umgebung bewusst nicht ein (Entscheidung des Owners).
#
# Bedienung (Ordner = ~/sprintforecast-lauf):
#   touch zustand/PAUSE                                   anhalten, auch einen laufenden Lauf (Datei löschen: fortsetzen)
#   (zustand/ liegt neben diesem Skript; dort liegen auch Sperre, tmux-Socket und Protokolle)
#   tmux -S zustand/tmux.sock attach -t lauf              im Terminal zuschauen (lösen: Strg-b d)
#   Protokolle: zustand/<Zeit>.log, Zusammenfassungen: zustand/berichte/, Übersprungenes: zustand/uebersprungen.txt
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO="${SPRINTFORECAST_REPO:-$HOME/devel/sprint-forecast}"
PROMPT="${SPRINTFORECAST_PROMPT:-$DIR/prompt.md}"
LEERLAUF="${SPRINTFORECAST_LEERLAUF:-600}"          # so lange nach der letzten Antwort warten
HARTE_GRENZE="${SPRINTFORECAST_HARTE_GRENZE:-9600}" # 160 Minuten; TimeoutStartSec der Einheit ist 3 Stunden
Z="$DIR/zustand"                                      # Sperre, Pause, Protokolle, Zusammenfassungen
SOCK="$Z/tmux.sock"
SITZUNG=lauf

mkdir -p "$Z/berichte" "$Z/lauf"
uebersprungen() { echo "$(date -Is) übersprungen: $1" >>"$Z/uebersprungen.txt"; exit 0; }

exec 9>"$Z/lauf.lock"
flock -n 9 || uebersprungen "ein Lauf ist noch aktiv"
[ -e "$Z/PAUSE" ] && uebersprungen "PAUSE gesetzt"
[ -r "$PROMPT" ] || uebersprungen "Auftragstext $PROMPT fehlt"

# Die Sitzung nutzt das angemeldete gh des Benutzers (Entscheidung des Owners).
export GH_PROMPT_DISABLED=1 GIT_TERMINAL_PROMPT=0 GH_NO_UPDATE_NOTIFIER=1 DISABLE_AUTOUPDATER=1

cd "$REPO" || uebersprungen "Klon $REPO fehlt"
# Nach einem Neustart ist das Netz oft noch nicht da: dreimal versuchen, jeder Versuch mit Zeitlimit.
HOLEN=1
for _ in 1 2 3; do
    if timeout 120 git fetch origin --prune --quiet; then HOLEN=0; break; fi
    sleep 30
done
[ "$HOLEN" -eq 0 ] || uebersprungen "git fetch fehlgeschlagen (Netz oder Anmeldung)"
tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null && uebersprungen "die tmux-Sitzung existiert noch (vom Owner geöffnet?)"

TS="$(date +%Y%m%d-%H%M%S)"
LOG="$Z/$TS.log"
NAME="sprint-forecast-$TS"
BERICHT="$Z/berichte/$TS.md"
SETTINGS="$Z/lauf/settings-$TS.json"
ENDE="unbekannt"
rm -f "$Z/IDLE" "$SOCK"

# Einstellungen nur für diese Sitzung: keine Attributionszeilen in Commits und PR-Texten (auch nicht die Zeile
# „Claude-Session: …“ aus Remote-Control-Sitzungen: sessionUrl), kein Auto-Gedächtnis (die Sitzung soll keine
# Erinnerungen für spätere Sitzungen ablegen oder fremde lesen) und Hooks. „Stop“ meldet das Ende einer Antwort
# (Leerlauf), „UserPromptSubmit“ eine neue Eingabe.
cat >"$SETTINGS" <<EOF
{"attribution":{"commit":"","pr":"","sessionUrl":false},"autoMemoryEnabled":false,"hooks":{"Stop":[{"hooks":[{"type":"command","command":"$DIR/hook.sh idle"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"$DIR/hook.sh aktiv"}]}]}}
EOF

# Beendet die Sitzung (zuerst höflich mit /exit), sichert den Bildschirm und räumt auf. Läuft bei jedem Ende,
# auch bei SIGTERM von systemd (Zeitgrenze der Einheit, systemctl stop).
KLAR=0
aufraeumen() {
    [ "$KLAR" -eq 0 ] || return
    KLAR=1
    if tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null; then
        {
            echo "== Bildschirm am Ende ($ENDE):"
            tmux -S "$SOCK" capture-pane -p -J -S -400 -t "$SITZUNG"
        } >>"$LOG" 2>&1
        tmux -S "$SOCK" send-keys -t "$SITZUNG" "/exit" Enter 2>/dev/null
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
}
trap 'ENDE="Signal von systemd oder Benutzer"; exit 0' TERM INT
trap aufraeumen EXIT

echo "== Start $(date -Is), Sitzung $NAME" >"$LOG"
tmux -S "$SOCK" -f "$DIR/tmux.conf" new-session -d -s "$SITZUNG" -x 200 -y 50 -c "$REPO" \
    "$DIR/sitzung.sh" "$DIR" "$REPO" "$NAME" "$BERICHT" "$SETTINGS" "$PROMPT" >>"$LOG" 2>&1 || {
    ENDE="tmux-Start fehlgeschlagen"
    exit 0
}

START="$(date +%s)"
while :; do
    JETZT="$(date +%s)"
    if ! tmux -S "$SOCK" has-session -t "$SITZUNG" 2>/dev/null; then
        ENDE="Sitzung beendet"; break
    fi
    # remain-on-exit hält das Fenster nach einem Ende von claude offen, damit der Bildschirm gesichert wird.
    if [ "$(tmux -S "$SOCK" list-panes -t "$SITZUNG" -F '#{pane_dead}' 2>/dev/null | head -n 1)" = "1" ]; then
        ENDE="claude hat sich beendet"; break
    fi
    if [ -e "$Z/PAUSE" ]; then
        ENDE="Pause gesetzt"; break
    fi
    IDLE_ZEIT="$(stat -c %Y "$Z/IDLE" 2>/dev/null || true)"
    if [ -n "$IDLE_ZEIT" ] && [ $((JETZT - IDLE_ZEIT)) -ge "$LEERLAUF" ]; then
        ENDE="Leerlauf von $LEERLAUF s"; break
    fi
    if [ $((JETZT - START)) -ge "$HARTE_GRENZE" ]; then
        ENDE="Zeitgrenze von $HARTE_GRENZE s"; break
    fi
    sleep 20 &
    wait $!
done
exit 0
