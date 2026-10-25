# Performance (phase P)

This document records the measures from [design/core.md](design/core.md), section E, and how
they were measured.

## Measuring

These measurements are of the Python version 0.8. The measuring script (`scripts/measure.py`)
exists on the branch `main` only; run it there. The Go core of 1.0 has no comparable log yet.

## Measurement log: cloud (Linux x86_64, 4 cores, Python 3.14.6, demo team, 22 sprints)

Before = `main` (78010e5 plus the measurement script), after = `main` with the measures (0.8). Individual rows
vary by about 10 to 20 % from run to run.

| Measurement | before (ms) | after (ms) |
|---|---:|---:|
| import yaml | 14.9 | 14.0 |
| import pandas | 308.9 | 356.8 |
| import altair | 256.3 | 255.2 |
| import streamlit | 258.3 | 246.8 |
| import rich.console | 39.4 | 33.5 |
| import typer | 48.2 | 45.9 |
| import foresprint.storage | 32.4 | 36.2 |
| import foresprint.forecast | 79.9 | 80.2 |
| import foresprint.web.ui | 982.8 | 387.1 |
| import foresprint.cli | 258.0 | 232.7 |
| Load team (no cache) | 19.5 | 4.7 |
| Load team (cache hit) | – | 0.7 |
| build_forecast | 0.3 | 0.3 |
| git status (pending_changes) | 2.5 | 3.0 |
| AppTest start (cold, first run) | 1083.4 | 792.1 |
| AppTest rerun (same page) | 71.2 | 32.8 |
| AppTest page forecast | 63.4 | 32.0 |
| AppTest page absences | 52.8 | 23.6 |
| AppTest page planning | 48.3 | 20.5 |
| AppTest page analysis | 42.8 | 19.1 |
| AppTest page products | 118.8 | 74.6 |
| AppTest page people | 63.4 | 18.1 |
| AppTest page help | 33.5 | 29.3 |

How to read this:

- `import foresprint.web.ui` (everything the UI start-up imports before the first page)
  drops because `pandas` and `altair` are now loaded only by the first page that shows a table
  or a chart. The analysis pages (e.g. the forecast) need both, the "Start" landing page does
  not. This was measured while the forecast was still the landing page: the cold start up to
  the first page dropped by roughly 0.3 s, part of which moves into the first page build.
- Loading a team: libyaml's C loader (`CSafeLoader`) cuts loading a team without the cache
  considerably; with unchanged files the cache returns the team in under a millisecond
  (check the file version, then copy).
- Page switches and reruns in the AppTest drop to about half (team cache, C loader, no waiting
  for the update indicator).
- Git status is fast in the cloud at about 3 ms (small clone, Linux). Measured on Windows the
  median was about 61 ms; that is where the cache helps most.
- `build_forecast` takes 0.3 ms. It is **not** cached: copying the result (the result has to
  stay independent because pages compute previews from it) would be slower than the
  computation. A cache only pays off once the computation becomes noticeable; only the demo
  team (22 sprints) was measured, larger teams were not.

Owner's reference (Windows, before): loading a team about 18 ms (PyYAML `safe_load` about
46 ms in the planning rerun), `build_forecast` 0.25 to 1.3 ms, page switch in the AppTest 35 to
45 ms, `import pandas` 0.4 to 1.0 s, `import streamlit` about 0.5 s, `git status` median about
61 ms.

## Measurement log, Windows (owner, Python 3.14.8, demo team)

Measured on 17 October 2026 with `scripts\measure.py --md` on the owner's workstation.
Before = commit `78010e5` (before PR 1), after = `main` after merging PR 1. Medians in ms.

| Measurement | before | after |
|---|---:|---:|
| import yaml | 23.8 | 24.2 |
| import pandas | 475.1 | 488.8 |
| import altair | 331.6 | 321.3 |
| import streamlit | 480.2 | 433.3 |
| import rich.console | 53.3 | 49.6 |
| import typer | 74.9 | 74.3 |
| import foresprint.storage | 46.5 | 50.1 |
| import foresprint.forecast | 124.9 | 124.4 |
| import foresprint.web.ui | 1364.8 | 730.9 |
| import foresprint.cli | 409.6 | 394.9 |
| Load team (no cache) | 18.4 | 5.0 |
| Load team (cache hit) | – | 1.1 |
| build_forecast | 0.3 | 0.3 |
| git status (pending_changes) | 60.0 | 52.9 |
| AppTest start (cold, first run) | 1165.7 | 1175.4 |
| AppTest rerun (same page) | 99.4 | 23.6 |
| AppTest page forecast | 101.4 | 24.0 |
| AppTest page absences | 94.1 | 18.5 |
| AppTest page planning | 96.5 | 18.8 |
| AppTest page analysis | 90.2 | 17.4 |
| AppTest page products | 122.1 | 46.4 |
| AppTest page people | 91.4 | 16.2 |
| AppTest page help | 80.5 | 23.6 |

Result (Python process only, no browser):

- **Page build and rerun** drop from 80 to 120 ms to 16 to 46 ms (page `produkte`
  122 → 46 ms, all others below 25 ms). Normal input is therefore far below the 200 ms goal in
  the Python part.
- **Loading a team** 18 → 5 ms (C loader), 1.1 ms with unchanged files (cache).
- **Importing the UI** 1365 → 731 ms (without `pandas`/`altair`).
- **Cold start** in the AppTest stays at about 1.2 s: the landing page (forecast) needs
  `pandas` and `altair`, which moves from the import into the first page build. PR 1 gains
  nothing here on this machine.
- **Git status** 60 → 53 ms per query; the cache skips it for inputs within 5 seconds.
- Individual import times vary by 10 to 20 % (ordering, disk cache).

The stopwatch measurement in the browser (start-up to the first page, goal under 3 s; normal
input, goal under 200 ms) is the only open item, see "Goals and acceptance".

## Implemented measures

1. **Update indicator** no longer waits for the background thread (`result()` without `wait`);
   the result appears on the next run.
2. **Git status** is queried at most every 5 seconds (`git.cached_pending_changes`). Every
   write through `Repository`, every commit and switching the data folder invalidate it.
   Changes made outside the app (editor, terminal) show up after at most 5 seconds.
3. **Team cache** (`Repository.load_cached`): the key is data folder and team, the validity is
   the file version (name, modification time in ns and size of `team.yaml`, `people.yaml`,
   `products.yaml` and all sprint files; new and deleted files change it).
   Every caller receives its own copy. Files modified within the last 2 seconds are not cached
   (coarse time resolution of file systems). Saving and switching folders also clear the cache.
   Pages without a forecast (people, products, settings) do not compute one.
4. **YAML** with `CSafeLoader` if PyYAML was built with libyaml; otherwise `SafeLoader`.
5. **Lazy imports:** `pandas` and `altair` are loaded on first access (`web/lazy.py`).
   `rich`, `typer` and the command line are not imported by the UI (guarded by a test).
6. **Fragments:** the calculation path (sprint selection) and the what-if panel of the
   forecast page redraw only themselves on input. Other areas (product editor, absence
   matrix, planning) feed results into the rest of the page and are therefore deliberately not
   fragments; a form would remove the live preview there.

## Goals and acceptance

Goals: start-up under 3 seconds, normal input under 200 ms. These goals are **checked by the
owner with a stopwatch on his machine** (browser and frontend included); the cloud measurement
only covers the share inside the Python process.

Status: phase P is complete. All six measures are implemented and the measurement logs (cloud
and Windows) are in place. The only open item is the stopwatch acceptance in the browser on the
owner's machine (start-up under 3 s, normal input under 200 ms); it will be done on request.
