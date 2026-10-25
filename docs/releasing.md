# Releasing

Releases are built by the workflow *Release app*
(`.github/workflows/release-app.yml`) when a version tag is pushed. The Python 0.x line (up to
0.8.0, PyPI) is discontinued; its workflow and package files are gone.

Steps per release:

1. Merge everything into `main` and check that the CI is green.
2. Tag the merge commit and push the tag: `git tag -a vX.Y.Z -m "Version X.Y.Z" && git push origin vX.Y.Z`.
3. The workflow builds the archives and writes the release page. A tag with a suffix
   (`v1.0.0-beta.1`) becomes a pre-release.

## The program (GitHub release files)

The workflow builds the
program with the window on Windows, macOS (Apple silicon and Intel) and Linux (amd64 and arm64)
with `-tags desktop,production` (Linux also `webkit2_41`), puts the newest holiday data in, and
attaches to the release page:

- `foresprint_<version>_<os>_<arch>.tar.gz` (`.zip` on Windows) with the program at the top level
  (the names are what the self-update looks for),
- `foresprint-cli_<version>_linux_<arch>.tar.gz`: the same program without the window (built
  without the tag `desktop`, `CGO_ENABLED=0`), which needs no GTK or WebKit; the self-update of that
  variant looks for these names,
- `checksums.txt` (SHA-256), which the self-update and the install scripts check,
- `checksums.txt.bundle`, the cosign signature of `checksums.txt` (keyless, no key to manage),
- a GitHub build attestation for every archive.

There is no code signing certificate: Windows and macOS warn once, see
[installation.md](installation.md#not-signed-smartscreen-and-gatekeeper). A tag with a suffix
(`v1.0.0-beta.1`) becomes a pre-release, which the self-update ignores. The Windows file is a console
program (a terminal waits for it and gets its output); started without arguments from Explorer it
starts itself again without a console (`cmd/foresprint/console_windows.go`).

"Run workflow" builds the commit it is started on (choose the branch or tag under "Use workflow from") and names the
release after the input `tag`; a tag that does not exist yet is created at that commit by the release page. For an
existing tag it repeats the build and replaces the files.

The name must look like `v1.0.0` or `v1.0.0-beta.1`, and for an existing tag the run must be started from that tag.
