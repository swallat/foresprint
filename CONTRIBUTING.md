# Contributing

Thank you for helping with sprintforecast. This page covers the local setup, the checks every
change has to pass and how pull requests are reviewed.

## Setup

[mise](https://mise.jdx.dev) installs the pinned Python and uv versions from `mise.toml`:

```bash
mise install
uv sync --all-extras
uv run sprintforecast --data examples/teams web   # run the web UI from source
```

`uv sync --all-extras` also installs the development group (pytest, ruff, Playwright, the Excel
libraries).

## Tests

```bash
uv run pytest                      # the fast suite
uv run pytest tests/test_cli.py    # one file
```

Browser tests (Playwright, Chromium) live in `tests/e2e/`, carry the marker `e2e` and are
excluded from the default run. They start the real web UI and need a browser:

```bash
uv run playwright install chromium   # once; on Linux add --with-deps
uv run pytest -m e2e
```

See [tests/e2e/README.md](tests/e2e/README.md) for the harness, the environment variables and
how to run a single browser test.

## Lint and format

```bash
uv run ruff check
uv run ruff format --check         # or `uv run ruff format` to apply
```

Line length is 100. CI runs both checks, so run them before pushing.

## Translations

Every user-facing text is written once, in the source language, and wrapped in `t("...")`.
Every new `t("...")` text needs an entry in `src/sprintforecast/locale_en.py` with the same
placeholders. `tests/test_i18n.py` walks the source tree, collects every literal `t("...")`
call and the static texts, and fails when an entry is missing or the placeholders differ, so a
missing translation never reaches `main`. Texts that are only data (YAML keys, file names,
command names) are not translated.

## Pull requests

- Keep pull requests small and about one topic; a documentation change and a behaviour change
  go into separate pull requests.
- Write commit messages and pull request titles and descriptions in English.
- Add or adjust tests for behaviour changes; keep `examples/teams` working, because CI runs
  `sprintforecast check` against it.
- Never commit spreadsheets or real team data; CI rejects `*.xlsx` files.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

- **test:** no spreadsheets in the repository, `ruff check`, `ruff format --check`, `pytest`,
  and `sprintforecast check` on the demo data.
- **build:** `uv build`; the wheel and source distribution are stored as the artifact `dist`.
- **e2e:** the browser tests. A pull request that changes only documentation (`docs/` and
  `*.md` files) skips the browser run; the job still reports success so that the required check
  is satisfied. On `main` and for every other change the tests run.

Pull requests also get an automated review by Claude (`.github/workflows/claude-code-review.yml`).
Its comments are suggestions; the code owner decides.

## Review

The code owners in `.github/CODEOWNERS` are requested as reviewers automatically. A pull request
is merged after the CI is green and a code owner has approved it.

## License

Contributions are licensed under the [EUPL-1.2](LICENSE), like the rest of the project.
