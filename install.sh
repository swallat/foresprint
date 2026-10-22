#!/bin/sh
# Installs foresprint (command line and window in one program) on Linux and macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/install.sh | sh
#
# Running it again updates. The program also updates itself (foresprint update).
#   FORESPRINT_VERSION=1.0.0      install this version instead of the newest one
#   FORESPRINT_BIN=~/.local/bin   folder for the program (default: ~/.local/bin)
#   FORESPRINT_NO_SHORTCUT=1      do not create a launcher
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
    version=$(fetch_text "https://api.github.com/repos/$REPO/releases/latest" |
        sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -n 1)
    [ -n "$version" ] || fail "could not find the newest version"
fi
version="${version#v}"
name="foresprint_${version}_${os}_${arch}.tar.gz"
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

if [ -z "${FORESPRINT_NO_SHORTCUT:-}" ]; then
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
