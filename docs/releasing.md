# Releasing and publishing on PyPI

A pushed version tag (`v*`) starts the *Release* workflow (`.github/workflows/release.yml`):
tests and lint, tag and version comparison, `uv build`, release page on GitHub, and then the job
`publish-pypi`, which uploads the same files to [PyPI](https://pypi.org/project/foresprint/) via
Trusted Publishing (OpenID Connect). No API token is stored in the repository or in GitHub.

Users then install with `pipx install "foresprint[web,excel,jira]"` or
`uv tool install "foresprint[web,excel,jira]"`, and update with `uv tool upgrade foresprint`.

## One-time setup (maintainer)

1. Create an account on <https://pypi.org> and enable two-factor authentication.
2. Open *Your account, Publishing* (<https://pypi.org/manage/account/publishing/>) and add a
   **pending publisher** (this reserves the name `foresprint` before the first upload):
   - PyPI project name: `foresprint`
   - Owner: `swallat`
   - Repository name: `foresprint`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. On GitHub, *Settings, Environments, New environment* named `pypi`. Recommended: under
   *Deployment protection rules* require yourself as reviewer, so every upload needs one click.
4. Optional dry run: the same steps on <https://test.pypi.org> with an environment `testpypi`.

The first tag after the setup creates the project on PyPI; afterwards the pending publisher
becomes a normal trusted publisher.

## Per release

1. Raise the version in `pyproject.toml`, the package `__init__.py` and `uv.lock`, merge via pull
   request.
2. Tag the merge commit and push: `git tag -a vX.Y.Z -m "Version X.Y.Z" && git push origin vX.Y.Z`.
3. Approve the `pypi` deployment if a reviewer is required. PyPI never accepts a version twice;
   after a faulty upload raise the version (a yanked release cannot be replaced).

For an existing tag, the release can be repeated under *Actions, Release, Run workflow*. The normal
CI also builds the packages on every push and stores them as the artifact `dist`.

## The program (GitHub release files)

The same tag starts the workflow *Release app* (`.github/workflows/release-app.yml`). It builds the
program with the window on Windows, macOS (Apple silicon and Intel) and Linux (amd64 and arm64)
with `-tags desktop,production` (Linux also `webkit2_41`), puts the newest holiday data in, and
attaches to the release page:

- `foresprint_<version>_<os>_<arch>.tar.gz` (`.zip` on Windows) with the program at the top level
  (the names are what the self-update looks for),
- `checksums.txt` (SHA-256), which the self-update and the install scripts check,
- `checksums.txt.bundle`, the cosign signature of `checksums.txt` (keyless, no key to manage),
- a GitHub build attestation for every archive.

There is no code signing certificate: Windows and macOS warn once, see
[installation.md](installation.md#not-signed-smartscreen-and-gatekeeper). A tag with a suffix
(`v1.0.0-beta.1`) becomes a pre-release, which the self-update ignores. The Windows file is linked
for the GUI subsystem so that a double click opens no console window; the program attaches to
the console of the caller (`cmd/foresprint/console_windows.go`).

"Run workflow" builds the commit it is started on (choose the branch or tag under "Use workflow from") and names the
release after the input `tag`; a tag that does not exist yet is created at that commit by the release page. For an
existing tag it repeats the build and replaces the files.

A run started by hand that creates the tag does not start the workflow *Release* (events caused by the workflow's own token start no other workflow). To publish the wheel and the source distribution (and PyPI) for such a tag, start *Actions, Release, Run workflow* with that tag afterwards; its check needs the version in `pyproject.toml` at that commit to match the tag. The name must look like `v1.0.0` or `v1.0.0-beta.1`, and for an existing tag the run must be started from that tag.
