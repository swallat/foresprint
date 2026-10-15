#!/bin/sh
# Installiert sprintforecast (inkl. Weboberfläche) für Linux und macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.sh | sh
#
# Erneut ausführen = aktualisieren. Optional:
#   SPRINTFORECAST_WITH="name @ git+https://…"  zusätzliche Pakete (Plugins), mehrere mit ";"
#                                               getrennt; das Plugin muss die Quelle des Kerns
#                                               in [tool.uv.sources] festlegen (braucht Git)
#   SPRINTFORECAST_REF=…                        Branch oder Tag statt main
set -eu

REF="${SPRINTFORECAST_REF:-main}"
KIND=heads
case "$REF" in v[0-9]*) KIND=tags ;; esac
CORE="sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/${KIND}/${REF}.zip"

say() { printf '%s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
    say "==> uv wird installiert (https://docs.astral.sh/uv/)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

if [ -n "${SPRINTFORECAST_WITH:-}" ]; then
    if ! command -v git >/dev/null 2>&1; then
        say "Für Plugins aus Git-Repositories wird Git benötigt (z. B. 'brew install git' bzw. 'sudo apt install git')." >&2
        exit 1
    fi
    say "==> mit Plugins: ${SPRINTFORECAST_WITH}"
    # Die Quelle des Kerns kommt aus dem Plugin ([tool.uv.sources]) – sonst „conflicting URLs“.
    set -- --force --reinstall --python 3.15 "sprintforecast[web]"
    OLD_IFS=$IFS
    IFS=';'
    for spec in $SPRINTFORECAST_WITH; do
        IFS=$OLD_IFS
        spec=$(printf '%s' "$spec" | sed 's/^ *//; s/ *$//')
        [ -n "$spec" ] && set -- "$@" --with "$spec"
    done
    IFS=$OLD_IFS
else
    set -- --force --reinstall --python 3.15 "$CORE"
fi

say "==> sprintforecast wird installiert (Python 3.15 wird bei Bedarf geladen)"
uv tool install "$@"
uv tool update-shell >/dev/null 2>&1 || true

say ""
say "Fertig: sprintforecast $("$(uv tool dir --bin)/sprintforecast" --version)"
say "Neues Terminal öffnen, dann z. B.:"
say "  cd ~/sprint-daten && sprintforecast web --app"
