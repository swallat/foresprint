# Contributing

Thank you for helping with Foresprint. This page covers the local setup, the checks every change
has to pass and how pull requests are reviewed. The 1.0 line (branch `v1`) is a Go core with a
[Wails](https://wails.io) window and a Svelte frontend. The Python 0.x line
lives on `main` and only gets bug fixes. Pull requests for 1.0 target `v1`.

## Setup

[mise](https://mise.jdx.dev) installs the pinned Go and Node versions from `mise.toml` (and uv,
which runs `scripts/gen_holidays.py` for the public holiday data):

```bash
mise install
mise tasks           # list the tasks
```

Building the window needs cgo and a C compiler. On Linux also
`sudo apt install libgtk-3-dev libwebkit2gtk-4.1-dev`. Go stays below 1.25 because Wails v2.12
does not build with newer versions. Without mise, install Go and Node yourself and run
`node scripts/build.mjs <task>`; the mise tasks are thin wrappers around it.

## Build and run

```bash
mise run dev     # frontend in the browser with demo data, no Go needed
mise run app     # frontend + program with the window into dist/
mise run cli     # program without the window (no cgo)
```

The layout of the window code and how to add a page are in
[go/internal/desktop/README.md](go/internal/desktop/README.md).

## Tests and checks

```bash
mise run test    # go vet + go test; needs neither Node, cgo nor a web view
mise run check   # frontend: svelte-check, translations, vitest
mise run all     # everything plus the build of the window
```

CI additionally runs `gofmt`, `golangci-lint`, a build of the window on Windows, Linux and macOS,
and the installer scripts. Format your Go code with `gofmt` before
pushing. Behaviour changes need tests; new methods that return lists must return empty lists, not
`nil`, and belong in `go/internal/app/nilslice_test.go`.

## Translations

Every user-facing text has an English source and a German translation.

- Frontend: `t('English source text', { name })`; the German text goes to
  `go/internal/i18n/data/de.ui.<area>.json`. `npm run check` (or `mise run check`) fails when a
  text is missing, unused or in two files.
- Go: messages of the core use the catalogs in `go/internal/i18n/data/de.<area>.json`. Generated
  files such as `de.json` (from `scripts/gen_locales.py`) are not edited by hand.

Never build a sentence from pieces; use placeholders. YAML keys, file names and command names are
not translated.

## Pull requests

- Keep pull requests small and about one topic; a documentation change and a behaviour change go
  into separate pull requests.
- Write commit messages and pull request titles and descriptions in English.
- Never commit spreadsheets or real team data; CI rejects `*.xlsx` files. Examples and screenshots
  use the invented demo team.
- Changes to `.github/workflows/` need the maintainer's explicit approval.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests, on pushes to `main` and on manual dispatch. The jobs are `hygiene` (no
spreadsheets in the repository), `go` (format, vet, lint, tests), `desktop` (frontend checks and
the window on all three platforms) and `installers`. Pull requests also get an
automated review by Claude (`.github/workflows/claude-code-review.yml`); its comments are
suggestions, the code owner decides.

## Review

The code owners in `.github/CODEOWNERS` are requested as reviewers automatically. A pull request is
merged after the CI is green and a code owner has approved it.

## License

Contributions are licensed under the [EUPL-1.2](LICENSE), like the rest of the project.
