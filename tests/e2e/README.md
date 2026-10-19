# Browser tests (Playwright)

These tests really start the web UI (`sprintforecast web --no-browser`, own port, copy of the
demo data, fixed as-of date 2026-10-15, own settings folder) and drive it in a browser. They
check what `AppTest` cannot see: measured heights and widths, text in the data grid, real
clicking and typing, two apps against one shared Git repository.

The normal suite (`uv run pytest`) does **not** run them (marker `e2e`, excluded in
`pyproject.toml`). To run them:

```bash
uv sync --all-extras
uv run playwright install chromium          # once; on Linux add --with-deps
uv run pytest -m e2e                        # all browser tests
uv run pytest -m e2e tests/e2e/test_stepbar.py -k 1400
```

Environment variables:

| Variable | Effect |
|---|---|
| `E2E_CHANNEL` | use an installed browser, e.g. `msedge` or `chrome` (Windows) |
| `E2E_EXECUTABLE` | path to a Chromium (instead of the one downloaded by Playwright) |
| `E2E_HEADED=1` | visible window, to watch |
| `E2E_ARTIFACTS` | folder for screenshots and server logs of failed tests (default `test-results/e2e`) |

## Layout

- `harness.py`: start/stop app instances (the process tree is terminated cleanly), prepare Git
  repositories, helpers for reading Streamlit pages (data grids through their accessible
  table, keyboard input into the grid, "Save and share").
- `conftest.py`: browser, pages, apps (`app` and `app_without_products` read-only, `make_app`
  and `clones` per test).
- Tests: `test_smoke` (every page without errors, also a team without products), `test_start`,
  `test_sprint_choice`, `test_language`, `test_stepbar` (same height at every width),
  `test_tables` (no "None" cells, nothing cut off), `test_server_mask`, `test_two_clones`
  (Alice and Bob: changes, value conflict, restart in conflict, tags).

## Troubleshooting

If a test fails, the folder `test-results/e2e/` (in CI the artifact `e2e-screenshots`) holds a
screenshot per opened page (`<Test>.png`, with several `<Test>-1.png` …) and the log of every
app involved (`<Test>-<App>.log`). Both are captured while pages and servers are still running.
An app that does not start is stopped again immediately; its log is in the error message.

## No flakiness

No fixed waits. We wait for states: `expect(...)` with automatic waiting (time limit 20 s, see
`conftest.py`), the server's health check and, after input, the result in the page content.
`settle()` is only valid after loading a page; after a click it may still see the state
*before* the run (see `rerun_finished`). Streamlit loads data grids and charts only after the
script has finished: `wait_until_stable` waits for that.

Deliberately not tested: two tabs or users in the same checkout (never happens in practice).
