#!/bin/sh
# Installiert sprintforecast (inkl. Weboberfläche) für Linux und macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.sh | sh
#
# Erneut ausführen = aktualisieren. Das Skript fragt nach Plugins und merkt sich die Auswahl.
# Ohne Rückfrage:
#   SPRINTFORECAST_WITH="besitzer/repo; name @ git+https://…"  Plugins (leer = keine)
#   SPRINTFORECAST_REF=…                                       Branch oder Tag statt main
#   SPRINTFORECAST_NO_SHORTCUT=1                               keinen Starter anlegen
set -eu

REF="${SPRINTFORECAST_REF:-main}"
KIND=heads
case "$REF" in v[0-9]*) KIND=tags ;; esac
CORE="sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/${KIND}/${REF}.zip"
PLUGIN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/sprintforecast/plugins"

say() { printf '%s\n' "$*"; }
trim() { printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

# „besitzer/repo“ → git+https://github.com/besitzer/repo; alles andere unverändert
expand() {
    case "$1" in
        *[!A-Za-z0-9_./-]* | */*/* | /* | */ | '') printf '%s' "$1" ;;
        */*) printf 'git+https://github.com/%s' "$1" ;;
        *) printf '%s' "$1" ;;
    esac
}

interactive() { [ -t 1 ] && (exec </dev/tty) 2>/dev/null; }

if ! command -v uv >/dev/null 2>&1; then
    say "==> uv wird installiert (https://docs.astral.sh/uv/)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

saved=""
[ -f "$PLUGIN_FILE" ] && saved=$(trim "$(cat "$PLUGIN_FILE")")
if [ -n "${SPRINTFORECAST_WITH+x}" ]; then
    plugins="$SPRINTFORECAST_WITH"
elif interactive; then
    {
        say ""
        say "Plugins installieren? Mehrere mit ';' trennen, z. B.:"
        say "  besitzer/repo   oder   name @ git+https://…"
        if [ -n "$saved" ]; then
            printf 'Plugins [Enter = beibehalten: %s | - = keine]: ' "$saved"
        else
            printf 'Plugins [Enter = keine]: '
        fi
    } >/dev/tty
    answer=""
    read -r answer </dev/tty || answer=""
    answer=$(trim "$answer")
    case "$answer" in
        "") plugins="$saved" ;;
        -) plugins="" ;;
        *) plugins="$answer" ;;
    esac
else
    plugins="$saved"
fi

set -- --force --reinstall --python 3.14
specs=""
OLD_IFS=$IFS
IFS=';'
for item in $plugins; do
    IFS=$OLD_IFS
    item=$(trim "$item")
    [ -z "$item" ] && continue
    spec=$(expand "$item")
    set -- "$@" --with "$spec"
    specs="${specs:+$specs; }$item"
done
IFS=$OLD_IFS

if [ -n "$specs" ]; then
    if ! command -v git >/dev/null 2>&1; then
        say "Für Plugins aus Git-Repositories wird Git benötigt (z. B. 'brew install git' bzw. 'sudo apt install git')." >&2
        exit 1
    fi
    say "==> mit Plugins: $specs"
    # Die Quelle des Kerns kommt aus dem Plugin ([tool.uv.sources]) – sonst „conflicting URLs“.
    set -- "$@" "sprintforecast[web]"
else
    set -- "$@" "$CORE"
fi

say "==> sprintforecast wird installiert (Python 3.14 wird bei Bedarf geladen)"
uv tool install "$@"
uv tool update-shell >/dev/null 2>&1 || true

# Auswahl für das nächste Aktualisieren merken
if [ -n "$specs" ]; then
    mkdir -p "$(dirname "$PLUGIN_FILE")"
    printf '%s\n' "$specs" >"$PLUGIN_FILE"
else
    rm -f "$PLUGIN_FILE"
fi

# Starter zum Doppelklicken (abschaltbar mit SPRINTFORECAST_NO_SHORTCUT=1)
if [ -z "${SPRINTFORECAST_NO_SHORTCUT:-}" ]; then
    "$(uv tool dir --bin)/sprintforecast" verknuepfung || say "Hinweis: Starter nicht angelegt."
fi

say ""
say "Fertig: sprintforecast $("$(uv tool dir --bin)/sprintforecast" --version)"
say "Start per Doppelklick auf „Sprint-Forecast“ – oder im neuen Terminal z. B.:"
say "  cd ~/sprint-daten && sprintforecast web"
