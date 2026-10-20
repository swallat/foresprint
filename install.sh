#!/bin/sh
# Installs sprintforecast (including the web UI and the extras excel and jira) on Linux and
# macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/install.sh | sh
#
# Running it again updates. The script asks for plugins and remembers the choice.
# Without prompting:
#   SPRINTFORECAST_WITH="owner/repo; name @ git+https://…"  plugins (empty = none)
#   SPRINTFORECAST_REF=…                                       branch or tag instead of main
#   SPRINTFORECAST_NO_SHORTCUT=1                               do not create a launcher
set -eu

REF="${SPRINTFORECAST_REF:-main}"
KIND=heads
case "$REF" in v[0-9]*) KIND=tags ;; esac
CORE="sprintforecast[web,excel,jira] @ https://github.com/swallat/foresprint/archive/refs/${KIND}/${REF}.zip"
PLUGIN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/sprintforecast/plugins"

say() { printf '%s\n' "$*"; }
trim() { printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

# "owner/repo" -> git+https://github.com/owner/repo; everything else unchanged
expand() {
    case "$1" in
        *[!A-Za-z0-9_./-]* | */*/* | /* | */ | '') printf '%s' "$1" ;;
        */*) printf 'git+https://github.com/%s' "$1" ;;
        *) printf '%s' "$1" ;;
    esac
}

interactive() { [ -t 1 ] && (exec </dev/tty) 2>/dev/null; }

if ! command -v uv >/dev/null 2>&1; then
    say "==> installing uv (https://docs.astral.sh/uv/)"
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
        say "Install plugins? Separate several with ';', e.g.:"
        say "  owner/repo   or   name @ git+https://…"
        if [ -n "$saved" ]; then
            printf 'Plugins [Enter = keep: %s | - = none]: ' "$saved"
        else
            printf 'Plugins [Enter = none]: '
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
        say "Plugins from Git repositories require Git (e.g. 'brew install git' or 'sudo apt install git')." >&2
        exit 1
    fi
    say "==> with plugins: $specs"
    # The core's source comes from the plugin ([tool.uv.sources]); otherwise "conflicting URLs".
    set -- "$@" "sprintforecast[web,excel,jira]"
else
    set -- "$@" "$CORE"
fi

say "==> installing sprintforecast with the extras web, excel and jira (Python 3.14 is downloaded if needed)"
uv tool install "$@"
uv tool update-shell >/dev/null 2>&1 || true

# Remember the choice for the next update
if [ -n "$specs" ]; then
    mkdir -p "$(dirname "$PLUGIN_FILE")"
    printf '%s\n' "$specs" >"$PLUGIN_FILE"
else
    rm -f "$PLUGIN_FILE"
fi

# Double-click launcher (disable with SPRINTFORECAST_NO_SHORTCUT=1)
if [ -z "${SPRINTFORECAST_NO_SHORTCUT:-}" ]; then
    "$(uv tool dir --bin)/sprintforecast" shortcut || say "Note: launcher not created."
fi

# Git is optional for the installation, but needed to save, share and view the history of data
if ! command -v git >/dev/null 2>&1; then
    say ""
    say "Note: Git was not found. The app runs without it, but committing, sharing with the team,"
    say "the history and cloning the data repository need Git (no administrator rights required;"
    say "see the Git section in docs/installation.md)."
fi

say ""
say "Done: sprintforecast $("$(uv tool dir --bin)/sprintforecast" --version)"
say "Start by double-clicking \"Foresprint\" or, in a new terminal, e.g.:"
say "  cd ~/sprint-daten && sprintforecast web"
