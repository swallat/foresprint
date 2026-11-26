# Automated maintenance

Dependencies and security fixes are looked after without anyone watching.
This page says what runs, what is merged on its own and what always waits
for a person.

## Renovate

Configuration: [`renovate.json`](../renovate.json).

- Updates are raised on weekday nights (00:00 to 06:00, Europe/Berlin), at
  most 5 PRs open at once. A release must be 3 days old first. Security fixes
  are raised at once and skip that wait.
- Go modules, frontend packages and GitHub Actions are grouped. Lock file
  maintenance runs on Monday night.
- Renovate merges a PR itself once every check on it is green.
- **Merged on their own:** patch and minor updates, pins and digests, lock
  file maintenance, and security fixes of packages that are not listed below.
- **Never merged on their own** (label `needs-review`):
  - every major update (label `major`);
  - minor updates of `0.x` packages;
  - the Go, Node and uv versions (`go.mod`, `mise.toml`, workflows);
  - core libraries: `github.com/wailsapp/wails/v2`,
    `github.com/xuri/excelize/v2`;
  - the actions of the release chain (`actions/upload-artifact`,
    `actions/download-artifact`, `actions/attest-build-provenance`,
    `sigstore/cosign-installer`) and `anthropics/claude-code-action`.

## Vulnerability scan

[`vulnerability-scan.yml`](../.github/workflows/vulnerability-scan.yml) runs
`govulncheck` (also for Windows with the window code) and `npm audit` (high
and above) every Sunday night. One open issue labelled `vulnerability` lists
the findings; a clean run closes it. It is not a required check.

## Weekly Claude task

Every Monday morning a scheduled Claude task in the cloud
(`Softwarepflege foresprint`):

1. Looks at open PRs by `renovate[bot]`, at open issues labelled
   `vulnerability` or `security-release`, and at security fixes that are
   merged but not released. If there is nothing, it ends at once.
2. Repairs red checks on those PRs.
3. Merges non-major updates after an independent review and green CI.
4. Prepares major updates, but does not merge them, and lists them in its
   report.
5. Decides on a security release, see below.

It touches no other PRs, never force-pushes and changes no settings. CI can
be started by hand with the `workflow_dispatch` trigger of `ci.yml`.

## Security releases

When pull requests labelled `security` were merged after the latest stable
release, the weekly task decides whether to publish them:

- It releases only when the fixed dependency is part of the shipped program
  (not a build, test or CI tool), and when everything on `main` since the
  latest release is dependency updates, holiday data, maintenance and bug
  fixes.
- It then starts [`release-app.yml`](../.github/workflows/release-app.yml) on
  `main` with the next patch version as `tag` (`v1.3.0` becomes `v1.3.1`),
  with `main` green. The workflow creates the tag and publishes as for any
  other release ([releasing.md](releasing.md)).
- It checks afterwards that the release is published with all its files.
- In any other case, or when in doubt, it publishes nothing and opens an
  issue `Security release needs a decision` (label `security-release`).

At most one security release per run. Every other release stays a decision
of the maintainer. Routine dependency updates alone no longer cause a
release.

## Deviations from the standard

None.
