# Data repository

The code repository (`swallat/foresprint`) contains **only code and demo data**. Real team
data lives in a separate data repository inside your company's domain (`*.xlsx` and `/teams/`
are excluded from the code repository through `.gitignore`).

## Why Git is the database

- YAML files, one sprint per file, easy to diff and merge.
- Parallel maintenance by POs and Scrum Masters works because every sprint is its own file;
  different values in the same file are merged automatically (see [The window](window.md) for the
  details and the conflict resolution).
- Every change has an author, a time and a history; an earlier state can be restored.
- Closed sprints are marked with the tag `TEAM/SPRINT`.
- No server component: the window runs locally on the clone, and the hosted Git service
  (GitHub, GitLab, ...) handles sharing and access control.

## Template

The template [`templates/daten-repo/`](../templates/daten-repo) is the starting point for a new
data repository (the first-start guide of the window creates a repository with `.gitignore` and a
`teams` folder with `.gitattributes` through "Create new data repository"; the task file and the
workflow come from the template):

```
data-repo/
├─ mise.toml                      # data directory + task `mise run sf -- ...`
├─ .gitignore, .gitattributes     # no spreadsheets and *.tmp; YAML and reports always with LF
├─ .github/workflows/forecast.yml # checks changes, updates FORECAST.md (GitLab: analogous)
└─ teams/
   ├─ team-a/
   │  ├─ team.yaml
   │  ├─ people.yaml
   │  ├─ products.yaml            # optional
   │  ├─ FORECAST.md              # generated
   │  └─ sprints/2026.20.yaml ...
   └─ team-b/ ...
```

- `mise.toml` defines the task `mise run sf -- forecast team-a`, which runs the `foresprint`
  program (install it first, see [Installation](installation.md)), and points the data directory
  at `teams` for the repository.
- `.gitattributes` forces LF line endings for `*.yaml`, `*.yml` and `*.md` even with
  `core.autocrlf` on Windows; otherwise the first save would rewrite every line ending and add
  noise to the history.
  An existing repository without it gets an offer: in **Settings > Storage**, the
  section "Set line endings" shows the lines to be added (an existing `.gitattributes` is
  extended, never rewritten) and the tracked files that are stored with CRLF and would be
  converted to LF. Nothing is written before you click "Create `.gitattributes`", and the
  button does not commit: the change appears among the open changes and is saved and shared
  like any other, as a merge request if the repository is set up that way. The offer disappears
  once Git applies `eol=lf` to those files, also through a `.gitattributes` elsewhere.
- `.gitignore` keeps spreadsheets out of the repository: they can contain real team data, and
  the app refuses to commit them anyway.
- `forecast.yml` installs the command line variant of a pinned release (raise the version in
  the workflow when you update) and runs `check` on every change under `teams/`, and on pushes to `main` and on a
  weekday schedule regenerates `FORECAST.md` and commits it.

The file formats are described in [Data format](data-format.md).
