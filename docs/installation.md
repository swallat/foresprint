# Installation and updates

Foresprint is one program: the window and the command line are the same file
(`foresprint` / `foresprint.exe`). Nothing else has to be installed; Git is needed only if you
keep your team data in a Git repository.

## Install

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/foresprint/main/install.ps1 | iex"
```

**Linux / macOS:**

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/install.sh | sh
```

The script downloads the archive for your system from the newest GitHub release, checks its
SHA-256 sum against `checksums.txt`, puts the program in place and creates a launcher. Running
it again updates. Settings through environment variables:

| Variable | Effect |
|---|---|
| `FORESPRINT_VERSION` | install this version (`1.0.0`) instead of the newest |
| `FORESPRINT_BIN` | folder for the program (default `~/.local/bin`, on Windows `%LOCALAPPDATA%\Programs\foresprint`) |
| `FORESPRINT_NO_SHORTCUT` | do not create a launcher |

Without the script: download `foresprint_<version>_<os>_<arch>` (`.zip` on Windows, `.tar.gz`
elsewhere) from the [releases](https://github.com/swallat/foresprint/releases), unpack it and
copy the program wherever you like. Platforms: Windows (amd64), macOS (Apple silicon and Intel),
Linux (amd64 and arm64; needs GTK 3 and WebKitGTK 4.1 for the window).

## Not signed: SmartScreen and Gatekeeper

The program is not signed with a code signing certificate. The operating systems therefore warn
once on the first start of a downloaded copy. The installer scripts avoid most of it, a copy
downloaded in a browser does not.

- **Windows (SmartScreen):** "Windows protected your PC" appears. Choose **More info**, then
  **Run anyway**.
- **macOS (Gatekeeper):** "cannot be opened because the developer cannot be verified" appears.
  Open **System Settings > Privacy & Security**, scroll to the message about foresprint and
  choose **Open Anyway**. Or in a terminal: `xattr -d com.apple.quarantine /path/to/foresprint`.

## Verify a download

Every release page has `checksums.txt` with the SHA-256 sums of all archives:

```bash
sha256sum -c --ignore-missing checksums.txt
```

`checksums.txt` is signed with [cosign](https://docs.sigstore.dev/) (keyless, by the release
workflow of this repository) and every archive carries a GitHub build attestation:

```bash
cosign verify-blob --bundle checksums.txt.bundle \
  --certificate-identity-regexp '^https://github.com/swallat/foresprint/.github/workflows/release-app.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com checksums.txt
gh attestation verify foresprint_<version>_<os>_<arch>.tar.gz --repo swallat/foresprint
```

`install.sh` runs the cosign check by itself when `cosign` is installed.

## Desktop launcher

The installer creates a launcher **"Foresprint"**: on Windows on the desktop and in the Start
menu, on macOS in `~/Applications` (plus an alias on the desktop), on Linux as an application
entry and on the desktop. Create it again with `foresprint shortcut`. A double click starts the
window; on Windows no console window opens, and the program still prints to the terminal when
you call it from one (`foresprint --help`). Note that `cmd.exe` and PowerShell do not wait for a
Windows program of this kind: in scripts use `Start-Process -Wait` or `start /wait`.

## Tab completion

Tab completes commands, options, team names and sprint IDs in bash, zsh, fish and PowerShell.
Print the script for your shell with `foresprint completion bash|zsh|fish|powershell` and load it
from your shell profile, for example `eval "$(foresprint completion bash)"` in `~/.bashrc`.

## Updating

The program checks at most once a day, in the background, whether a newer release exists. What
happens then is a setting:

| Command / variable | Effect |
|---|---|
| `foresprint update` | check and update now (`--check`: check only, `--force`: reinstall) |
| `foresprint update --auto on` | install new versions by itself (default) |
| `foresprint update --auto notice` | only point out new versions |
| `foresprint update --auto off` | never check |
| `FORESPRINT_AUTOUPDATE=on\|notice\|off` | like `--auto`, takes precedence (for managed machines) |

The new file is checked against `checksums.txt` before it replaces the program; a failed check
leaves the old program in place. Pre-releases (`1.0.0-beta.1`) are not offered.

## Uninstalling

`uninstall.sh` / `uninstall.ps1` remove the program, the launchers and the cache; they also
clean up a Python-era installation (including the old name `sprintforecast`). Your data, the
keychain entries and Git credentials stay; the settings stay unless you add `--remove-config`
(`-RemoveConfig`). The script lists what it would do and asks first (`--dry-run` / `-DryRun`
only lists, `--yes` / `-Force` skips the question). Close the app first, Windows locks running
programs. The `PATH` entry added by `install.ps1` stays.

```bash
curl -LsSf https://raw.githubusercontent.com/swallat/foresprint/main/uninstall.sh | sh -s -- --dry-run
```

```powershell
powershell -ExecutionPolicy ByPass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/swallat/foresprint/main/uninstall.ps1))) -DryRun"
```
