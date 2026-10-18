#!/usr/bin/env bash
# Installiert den Läufer auf dem Linux-Host (Benutzer sw). Aufruf aus diesem Ordner: bash install.sh
# Es aktiviert nichts und braucht kein sudo; die nächsten Schritte werden am Ende ausgegeben.
set -eu

QUELLE="$(cd "$(dirname "$0")" && pwd)"
ZIEL="$HOME/sprintforecast-lauf"

mkdir -p "$ZIEL/zustand" "$HOME/.config/systemd/user"
for datei in sprintforecast-lauf.sh sitzung.sh hook.sh prompt.md tmux.conf; do
    install -m 0644 "$QUELLE/$datei" "$ZIEL/$datei"
done
chmod 0755 "$ZIEL/sprintforecast-lauf.sh" "$ZIEL/sitzung.sh" "$ZIEL/hook.sh"
for datei in sprintforecast-lauf.service sprintforecast-lauf.timer; do
    install -m 0644 "$QUELLE/$datei" "$HOME/.config/systemd/user/$datei"
done
if grep -q $'\r' "$ZIEL/sprintforecast-lauf.sh"; then
    echo "FEHLER: die Skripte haben CRLF-Zeilenenden (Shebang bricht); mit LF neu kopieren." >&2
    exit 1
fi

systemctl --user daemon-reload
echo "Installiert nach $ZIEL und ~/.config/systemd/user/."
cat <<'EOT'

Noch zu tun (einmalig):
  1. sudo loginctl enable-linger sw
  2. systemctl --user enable --now sprintforecast-lauf.timer
  3. Pause aufheben: rm ~/sprintforecast-lauf/zustand/PAUSE   (der Läufer pausiert, solange die Datei existiert)
EOT
