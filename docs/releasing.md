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
