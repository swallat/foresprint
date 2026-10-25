#!/bin/sh
# Uninstalls Foresprint (Linux and macOS), including the installation under the old name
# "sprintforecast". Your data is never deleted.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/uninstall.sh | sh
#   sh uninstall.sh --dry-run        only list what would happen
#   sh uninstall.sh --yes            no confirmation
#
# Removed, under both names (foresprint and sprintforecast):
#   - the program of install.sh (~/.local/bin/foresprint)
#   - the uv tool of an old (Python) installation with its commands (foresprint, sprintforecast, ...)
#   - the launchers (.desktop files, macOS app bundle and desktop alias)
#   - the cache folder with the browser profile of the app window
# Kept: the team data folder, the Jira token in the keychain, Git credentials and the settings
# folder (~/.config/foresprint and ~/.config/sprintforecast: data folder, plugin selection).
# A later installation finds the settings again.
#
# Options:
#   --dry-run, -n     change nothing, only list
#   --yes, -y         do not ask
#   --remove-config   also remove the settings folders (data folder choice, plugin selection)
#   --help, -h
#
# Running it again is harmless.
set -eu

say() { printf '%s\n' "$*"; }

NAMES="foresprint sprintforecast"
dry=0
yes=0
rm_config=0
for arg in "$@"; do
    case "$arg" in
        --dry-run | -n) dry=1 ;;
        --yes | -y) yes=1 ;;
        --remove-config) rm_config=1 ;;
        --help | -h)
            say "Usage: sh uninstall.sh [--dry-run|-n] [--yes|-y] [--remove-config]"
            say "Uninstalls Foresprint and the old installation sprintforecast (uv tool, launchers,"
            say "browser profile cache). Keeps the team data, the keychain, Git credentials and,"
            say "unless --remove-config is given, the settings."
            exit 0
            ;;
        *)
            printf 'Unknown option: %s (see --help)\n' "$arg" >&2
            exit 2
            ;;
    esac
done

home="${HOME:?HOME is not set}"
config_home="${XDG_CONFIG_HOME:-$home/.config}"
data_home="${XDG_DATA_HOME:-$home/.local/share}"
cache_home="${XDG_CACHE_HOME:-$home/.cache}"

actions=""    # one line per step: kind|path
add() { actions="${actions}$1|$2
"; }

# 1. uv tool (removes its commands with it)
if ! command -v uv >/dev/null 2>&1 && [ -x "$home/.local/bin/uv" ]; then
    PATH="$home/.local/bin:$PATH"
    export PATH
fi
if command -v uv >/dev/null 2>&1; then
    tools=$(uv tool list 2>/dev/null || true)
    for name in $NAMES; do
        if printf '%s\n' "$tools" | grep -q "^$name "; then add tool "$name"; fi
    done
elif [ -e "$home/.local/bin/sprintforecast" ] || [ -e "$home/.local/bin/foresprint" ]; then
    say "Warning: uv not found, so the commands in ~/.local/bin cannot be removed; install uv or run 'uv tool uninstall foresprint'."
fi

# 1b. the program of the installer (a plain file, not the link of a uv tool)
bin="${FORESPRINT_BIN:-$home/.local/bin}/foresprint"
if [ -f "$bin" ] && [ ! -L "$bin" ]; then add file "$bin"; fi

# 2. launchers; only if they really start one of our programs
for f in "$data_home/applications/foresprint.desktop" "$data_home/applications/sprintforecast.desktop" \
    "$home/Desktop/foresprint.desktop" "$home/Desktop/sprintforecast.desktop"; do
    if [ -f "$f" ] && grep -Eq '^Exec=.*(foresprint|sprintforecast)' "$f"; then add file "$f"; fi
done
for app in Foresprint Sprint-Forecast; do
    for f in "$home/Applications/$app.app" "$home/Desktop/$app.app"; do
        # also dangling aliases
        if grep -Eqs '(foresprint|sprintforecast)' "$f/Contents/MacOS/$app" ||
            { [ -L "$f" ] && [ ! -e "$f" ]; }; then
            add file "$f"
        fi
    done
done

# 3. cache: browser profile of the app window and the logo (recreated on demand)
for name in $NAMES; do
    case "$(uname -s)" in
        Darwin) cache_dir="$home/Library/Application Support/$name" ;;
        *) cache_dir="$cache_home/$name" ;;
    esac
    if [ -d "$cache_dir" ]; then add dir "$cache_dir"; fi
done

# 4. settings: only on request
if [ "$rm_config" = 1 ]; then
    for name in $NAMES; do
        if [ -d "$config_home/$name" ]; then add dir "$config_home/$name"; fi
    done
fi

if [ -z "$actions" ]; then
    say "Nothing to remove: no installation of foresprint or sprintforecast found."
    exit 0
fi

say "Found:"
printf '%s' "$actions" | while IFS='|' read -r kind path; do
    [ -z "$kind" ] && continue
    case "$kind" in
        tool) say "  uv tool        $path (uv tool uninstall)" ;;
        file) say "  remove         $path" ;;
        dir) say "  remove folder  $path" ;;
    esac
done
say "Kept: team data folder, Jira token in the keychain, Git credentials."
if [ "$rm_config" != 1 ]; then
    say "Kept: settings folders (add --remove-config to remove them)."
fi

if [ "$dry" = 1 ]; then
    say "Dry run: nothing changed."
    exit 0
fi

if [ "$yes" != 1 ]; then
    if [ -t 0 ]; then
        printf 'Proceed? [y/N] '
        read -r answer || answer=""
    elif (exec </dev/tty) 2>/dev/null; then
        printf 'Proceed? [y/N] ' >/dev/tty
        read -r answer </dev/tty || answer=""
    else
        say "No terminal for the confirmation; use --yes or --dry-run." >&2
        exit 1
    fi
    case "$answer" in
        [yYjJ] | [yY][eE][sS] | [jJ][aA]) ;;
        *) say "Cancelled."; exit 0 ;;
    esac
fi

printf '%s' "$actions" | while IFS='|' read -r kind path; do
    [ -z "$kind" ] && continue
    case "$kind" in
        tool)
            uv tool uninstall "$path" </dev/null || {
                say "uv tool uninstall failed (is the app still running?); close it and run again." >&2
                exit 1
            }
            say "uv tool $path removed"
            ;;
        *) rm -rf -- "$path" && say "removed $path" ;;
    esac
done
say "Done."
