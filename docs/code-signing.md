# Code signing policy

Foresprint is open-source software under the [EUPL-1.2](../LICENSE). This page
describes how release binaries are built, verified and (where available)
signed.

## Current status

| Platform | Status |
| --- | --- |
| Windows | Not signed yet. Windows SmartScreen may show a warning for new releases. Free signing through the [SignPath Foundation](https://signpath.org/) will be requested once the project qualifies. |
| macOS | Not signed or notarized yet. macOS asks you to approve the app under System Settings > Privacy & Security on first start. |
| Linux | No signature required by the platform. From the first Go release on, every release carries a `checksums.txt` (SHA-256). The release workflow signs that file with cosign (keyless, `checksums.txt.bundle`) and attaches a GitHub build attestation to every archive, see [installation.md](installation.md#verify-a-download). |

Once signing is active, this page is updated and the section "Signed releases"
below applies.

## Verify a download

From the first Go release on, compare the SHA-256 hash of the downloaded
archive with the entry in `checksums.txt` of the same release:

```sh
sha256sum -c checksums.txt --ignore-missing      # Linux
shasum -a 256 -c checksums.txt --ignore-missing  # macOS
(Get-FileHash .\foresprint_<version>_windows_amd64.zip -Algorithm SHA256).Hash -eq '<hash from checksums.txt>'   # Windows (PowerShell), prints True if equal
```

## Opening an unsigned build

- **Windows:** in the SmartScreen dialog choose "More info", then "Run anyway".
- **macOS:** open the app once, then go to System Settings > Privacy & Security
  and choose "Open Anyway" next to the Foresprint message.

Only do this for files you downloaded from the
[official releases page](https://github.com/swallat/foresprint/releases) and
whose checksum matches.

## Signed releases (applies once signing is active)

- Free code signing provided by [SignPath.io](https://signpath.io/),
  certificate by [SignPath Foundation](https://signpath.org/). The
  SignPath Foundation is shown as publisher on Windows.
- Only binaries built by the project's GitHub Actions release workflow from the
  public repository are submitted for signing. Nothing is signed from a local
  machine.
- Every signing request needs approval by a project approver before the
  signature is issued.

### Roles

| Role | Who |
| --- | --- |
| Committers and reviewers | Contributors with merge rights, listed on the [contributors page](https://github.com/swallat/foresprint/graphs/contributors); changes to the default branch go through pull requests |
| Approvers | The project maintainer, [@swallat](https://github.com/swallat) |

### What is signed

Checksums are additionally signed with cosign. `install.sh` verifies that signature when
`cosign` is installed; the self-update checks the SHA-256 sums in `checksums.txt` (a check of
the signature in the self-update is planned). Only the Foresprint program itself (`foresprint` / `foresprint.exe`) as built
from this repository. Third-party components are not re-signed and keep their
own signatures where they have one.

## Privacy

Foresprint does not send your planning data to the project or to third parties.
The only network access is what you configure (your own Git remote, your own
issue tracker) and the update check: once a day the program asks GitHub for the
latest release. By default it also installs the update by itself. Switch this
to report-only or off with `foresprint update --auto notice` or
`foresprint update --auto off`, or with the environment variable
`FORESPRINT_AUTOUPDATE` (`on`, `notice`, `off`), which takes precedence.
Signing itself does not add any data collection.
