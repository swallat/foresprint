#!/usr/bin/env bash
# Hook der Claude-Code-Sitzung: meldet dem Läufer, ob die Sitzung gerade still ist.
#   hook.sh idle   nach jeder abgeschlossenen Antwort (Stop)   -> Marke IDLE anlegen
#   hook.sh aktiv  bei jeder neuen Eingabe (UserPromptSubmit)  -> Marke IDLE löschen
# Der Läufer beendet die Sitzung, wenn IDLE lange genug unverändert besteht.
d="${SPRINTFORECAST_LAUF_DIR:-}"
[ -n "$d" ] || exit 0
case "${1:-}" in
    idle) date +%s >"$d/IDLE" ;;
    aktiv) rm -f "$d/IDLE" ;;
esac
exit 0
