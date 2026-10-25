#!/bin/sh
# Installs foresprint (command line and window in one program) on Linux and macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/install.sh | sh
#
# Running it again updates. The program also updates itself (foresprint update).
#   FORESPRINT_VERSION=1.0.0      install this version instead of the newest one
#   FORESPRINT_BIN=~/.local/bin   folder for the program (default: ~/.local/bin)
#   FORESPRINT_NO_SHORTCUT=1      do not create a launcher
#   FORESPRINT_VARIANT=cli        Linux only: the command line without the window (needs no GTK or
#                                 WebKit, for servers and CI); "foresprint update" keeps the variant
#   FORESPRINT_DOWNLOAD_BASE=URL  other place for the release files (tests, mirrors)
set -eu

REPO="swallat/foresprint"
BIN="${FORESPRINT_BIN:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" > /dev/null 2>&1 || fail "$1 is needed"; }

need tar
if command -v curl > /dev/null 2>&1; then
    fetch() { curl -fsSL "$1" -o "$2"; }
    fetch_text() { curl -fsSL "$1"; }
elif command -v wget > /dev/null 2>&1; then
    fetch() { wget -q "$1" -O "$2"; }
    fetch_text() { wget -qO- "$1"; }
else
    fail "curl or wget is needed"
fi
if command -v sha256sum > /dev/null 2>&1; then
    sha256() { sha256sum "$1" | cut -d ' ' -f 1; }
elif command -v shasum > /dev/null 2>&1; then
    sha256() { shasum -a 256 "$1" | cut -d ' ' -f 1; }
else
    fail "sha256sum or shasum is needed"
fi

case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) fail "unsupported system $(uname -s); on Windows use install.ps1" ;;
esac
case "$(uname -m)" in
    x86_64 | amd64) arch=amd64 ;;
    arm64 | aarch64) arch=arm64 ;;
    *) fail "unsupported processor $(uname -m)" ;;
esac

version="${FORESPRINT_VERSION:-}"
if [ -z "$version" ]; then
    # releases/latest skips pre-releases and old 0.x tags must be ignored. Take the newest stable
    # release of 1.x or later, else the newest pre-release of 1.x.
    version=$(fetch_text "https://api.github.com/repos/$REPO/releases?per_page=30" |
        awk '/^    "tag_name":/ {match($0, /"v[^"]*"/); t = substr($0, RSTART + 1, RLENGTH - 2)}
             /^    "prerelease":/ {p = ($2 ~ /true/); if (t ~ /^v[1-9]/) {if (!p && !s) s = t; if (!f) f = t} t = ""}
             END {print (s != "" ? s : f)}')
    [ -n "$version" ] || fail "could not find the newest version (GitHub API limit? set FORESPRINT_VERSION, for example 1.0.0)"
fi
version="${version#v}"
prefix=foresprint
case "${FORESPRINT_VARIANT:-}" in
    "") ;;
    cli)
        [ "$os" = linux ] || fail "FORESPRINT_VARIANT=cli exists for Linux only"
        prefix=foresprint-cli
        ;;
    *) fail "unknown FORESPRINT_VARIANT ${FORESPRINT_VARIANT} (only: cli)" ;;
esac
name="${prefix}_${version}_${os}_${arch}.tar.gz"
base="${FORESPRINT_DOWNLOAD_BASE:-https://github.com/$REPO/releases/download}/v$version"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

say "==> downloading foresprint $version ($os/$arch)"
fetch "$base/$name" "$tmp/$name" || fail "download failed: $base/$name"
fetch "$base/checksums.txt" "$tmp/checksums.txt" || fail "download failed: $base/checksums.txt"

# Optional, if cosign is installed: the signature of checksums.txt (GitHub build identity).
if command -v cosign > /dev/null 2>&1 && fetch "$base/checksums.txt.bundle" "$tmp/checksums.txt.bundle" 2> /dev/null; then
    cosign verify-blob --bundle "$tmp/checksums.txt.bundle" \
        --certificate-identity-regexp "^https://github.com/$REPO/.github/workflows/release-app.yml@" \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        "$tmp/checksums.txt" > /dev/null 2>&1 || fail "the signature of checksums.txt does not match"
    say "==> signature of checksums.txt verified (cosign)"
fi

want=$(grep "  $name\$" "$tmp/checksums.txt" | cut -d ' ' -f 1)
[ -n "$want" ] || fail "checksums.txt has no sum for $name"
[ "$(sha256 "$tmp/$name")" = "$want" ] || fail "checksum of $name does not match; not installing"

tar -xzf "$tmp/$name" -C "$tmp" foresprint
mkdir -p "$BIN"
mv -f "$tmp/foresprint" "$BIN/foresprint.new"
chmod 755 "$BIN/foresprint.new"
mv -f "$BIN/foresprint.new" "$BIN/foresprint"
say "==> installed $BIN/foresprint"

if [ "$os" = darwin ]; then
    # Downloaded with curl there is no quarantine flag, but a copy from a browser has one.
    xattr -d com.apple.quarantine "$BIN/foresprint" 2> /dev/null || true
fi

libs_missing=
if [ "$os" = linux ] && [ "$prefix" = foresprint ] && command -v ldd > /dev/null 2>&1; then
    libs_missing=$(ldd "$BIN/foresprint" 2> /dev/null | grep "not found" || true)
fi
if [ -n "$libs_missing" ]; then
    say "Linux: the program needs system libraries that are not installed:"
    say "$libs_missing"
    say "  Debian/Ubuntu: sudo apt install libgtk-3-0 libwebkit2gtk-4.1-0"
    say "  Fedora:        sudo dnf install gtk3 webkit2gtk4.1"
    say "  Arch:          sudo pacman -S gtk3 webkit2gtk-4.1"
    say "Install them, then run: foresprint shortcut"
    say "Without a window (servers, CI): FORESPRINT_VARIANT=cli sh install.sh"
elif [ "$prefix" = foresprint-cli ]; then
    say "(command line variant: no launcher)"
elif [ -z "${FORESPRINT_NO_SHORTCUT:-}" ]; then
    "$BIN/foresprint" shortcut || say "(no launcher created; foresprint shortcut tries again)"
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) say "Add $BIN to your PATH to call foresprint from a terminal." ;;
esac
if [ "$os" = darwin ]; then
    say "macOS: the program is not signed. If Gatekeeper blocks the first start of the launcher,"
    say "open System Settings > Privacy & Security and choose Open Anyway (docs/installation.md)."
fi
say "Done. Start with: foresprint"
