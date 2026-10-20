#!/bin/sh
# Removes the installation left over from the old name "sprintforecast" (Linux and macOS):
# the uv tool, the launchers and the browser profile cache. User data is never deleted.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/uninstall-old.sh | sh
#   sh uninstall-old.sh --dry-run        only list what would happen
#   sh uninstall-old.sh --yes            no confirmation
#
# Options:
#   --dry-run, -n          change nothing, only list
#   --yes, -y              do not ask
#   --remove-old-config    also remove the old settings folder after copying (files that exist in
#                          the new folder are not overwritten, the old ones are deleted)
#                          (default: keep it)
#   --help, -h
#
# Never touched: the team data folder, the Jira token in the keychain, Git credentials, the
# new foresprint installation. The settings (data folder, plugin selection) are copied from
# ~/.config/sprintforecast to ~/.config/foresprint unless the file exists there already.
# Running it again is harmless.
set -eu

say() { printf '%s\n' "$*"; }

OLD=sprintforecast
OLD_APP="Sprint-Forecast"
NEW=foresprint
dry=0
yes=0
rm_config=0
for arg in "$@"; do
    case "$arg" in
        --dry-run | -n) dry=1 ;;
        --yes | -y) yes=1 ;;
        --remove-old-config) rm_config=1 ;;
        --help | -h)
            say "Usage: sh uninstall-old.sh [--dry-run|-n] [--yes|-y] [--remove-old-config]"
            say "Removes the installation under the old name sprintforecast (uv tool, launchers,"
            say "browser profile cache) and copies the settings to ~/.config/foresprint."
            say "Never deletes the team data folder, the keychain or Git credentials."
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

# 1. uv tool (removes the commands sprintforecast and sprintforecast-app with it)
if ! command -v uv >/dev/null 2>&1 && [ -x "$home/.local/bin/uv" ]; then
    PATH="$home/.local/bin:$PATH"
    export PATH
fi
if command -v uv >/dev/null 2>&1; then
    if uv tool list 2>/dev/null | grep -q "^$OLD "; then add tool "$OLD"; fi
elif [ -e "$home/.local/bin/$OLD" ]; then
    say "Warning: uv not found, so the commands in ~/.local/bin cannot be removed; install uv or run 'uv tool uninstall $OLD'."
fi

# 2. launchers; a .desktop file only if it really starts the old program
for f in "$data_home/applications/$OLD.desktop" "$home/Desktop/$OLD.desktop"; do
    if [ -f "$f" ] && grep -q "^Exec=.*$OLD" "$f"; then add file "$f"; fi
done
for f in "$home/Applications/$OLD_APP.app" "$home/Desktop/$OLD_APP.app"; do
    # only if it starts the old program (or is a dangling alias)
    if grep -qs "$OLD-app" "$f/Contents/MacOS/$OLD_APP" || { [ -L "$f" ] && [ ! -e "$f" ]; }; then
        add file "$f"
    fi
done

# 3. cache: browser profile of the app window and the logo (recreated on demand)
case "$(uname -s)" in
    Darwin) cache_dir="$home/Library/Application Support/$OLD" ;;
    *) cache_dir="$cache_home/$OLD" ;;
esac
if [ -d "$cache_dir" ]; then add dir "$cache_dir"; fi

# 4. settings: copy to the new folder, remove the old one only on request
old_config="$config_home/$OLD"
new_config="$config_home/$NEW"
if [ -d "$old_config" ]; then
    for name in settings.json plugins plugins.txt; do
        if [ -f "$old_config/$name" ] && [ ! -e "$new_config/$name" ]; then
            add copy "$old_config/$name"
        fi
    done
    if [ "$rm_config" = 1 ]; then add dir "$old_config"; fi
fi

if [ -z "$actions" ]; then
    say "Nothing to remove: no installation under the old name '$OLD' found."
    exit 0
fi

say "Found under the old name '$OLD':"
printf '%s' "$actions" | while IFS='|' read -r kind path; do
    [ -z "$kind" ] && continue
    case "$kind" in
        tool) say "  uv tool        $path (uv tool uninstall)" ;;
        file) say "  remove         $path" ;;
        dir) say "  remove folder  $path" ;;
        copy) say "  copy settings  $path -> $new_config/" ;;
    esac
done
say "Kept: team data folder, Jira token in the keychain, Git credentials."
if [ "$rm_config" != 1 ] && [ -d "$old_config" ]; then
    say "Kept: $old_config (add --remove-old-config to remove it after copying)."
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

# Copy first so that a removal of the old folder never loses settings.
printf '%s' "$actions" | grep '^copy|' | while IFS='|' read -r _ path; do
    mkdir -p "$new_config"
    cp -p "$path" "$new_config/"
    say "copied $path -> $new_config/"
done
printf '%s' "$actions" | grep -v '^copy|' | while IFS='|' read -r kind path; do
    [ -z "$kind" ] && continue
    case "$kind" in
        tool)
            uv tool uninstall "$path" </dev/null || {
                say "uv tool uninstall failed (is the app still running?); close it and run again." >&2
                exit 1
            }
            say "uv tool $path removed"
            ;;
        file) rm -rf -- "$path" && say "removed $path" ;;
        dir) rm -rf -- "$path" && say "removed $path" ;;
    esac
done
say "Done."
