# Code signing policy

Foresprint is open-source software under the [EUPL-1.2](../LICENSE). This page
describes how release binaries are built, verified and (where available)
signed.

## Current status

| Platform | Status |
| --- | --- |
| Windows | Not signed yet. Windows SmartScreen may show a warning for new releases. Free signing through the [SignPath Foundation](https://signpath.org/) will be requested once the project qualifies. |
| macOS | Not signed or notarized yet. macOS asks you to approve the app under System Settings > Privacy & Security on first start. |
| Linux | No signature required by the platform. Every release carries a `checksums.txt` (SHA-256). |

Once signing is active, this page is updated and the section "Signed releases"
below applies.

## Verify a download

Compare the SHA-256 hash of the downloaded archive with the entry in
`checksums.txt` of the same release:

```sh
sha256sum -c checksums.txt --ignore-missing      # Linux
shasum -a 256 -c checksums.txt --ignore-missing  # macOS
Get-FileHash .\foresprint_<version>_windows_amd64.zip -Algorithm SHA256   # Windows (PowerShell)
```

## Opening an unsigned build

- **Windows:** in the SmartScreen dialog choose "More info", then "Run anyway".
- **macOS:** open the app once, then go to System Settings > Privacy & Security
  and choose "Open Anyway" next to the Foresprint message.

Only do this for files you downloaded from the
[official releases page](https://github.com/swallat/foresprint/releases) and
whose checksum matches.

## Signed releases (applies once signing is active)

- Free code signing for Windows is provided by the
  [SignPath Foundation](https://signpath.org/); the certificate is issued by
  the SignPath Foundation, which is shown as publisher.
- Only binaries built by the project's GitHub Actions release workflow from the
  public repository are submitted for signing. Nothing is signed from a local
  machine.
- Every signing request needs approval by a project approver before the
  signature is issued.

### Roles

| Role | Who |
| --- | --- |
| Committers and reviewers | Contributors who can merge into the default branch, see the repository's collaborators |
| Approvers | The project maintainer, [@swallat](https://github.com/swallat) |

### What is signed

Only the Foresprint program itself (`foresprint` / `foresprint.exe`) as built
from this repository. Third-party components are not re-signed and keep their
own signatures where they have one.

## Privacy

Foresprint does not send data to the project or to third parties on its own.
The only network access is what you configure: your own Git remote, your own
issue tracker, and the check for new releases on GitHub, which you can turn off
in the update settings. Signing itself does not add any data collection.
