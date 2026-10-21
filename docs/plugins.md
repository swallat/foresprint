# Plugins

Plugins are separate Python packages that hook in through the entry point
`foresprint.plugins` (the former group `sprintforecast.plugins` is still loaded) (see `src/foresprint/plugins.py`). They can add commands to the
command line and pages to the web UI, for example an import of the history from a previous tool.
They are installed next to the tool:

```bash
uv tool install "foresprint[web,excel,jira] @ git+https://github.com/swallat/foresprint" \
  --with "my-plugin @ git+https://..."
```

If the plugin pins the source of the core itself (`[tool.uv.sources]`), give the core without an
address, otherwise uv reports "conflicting URLs":
`uv tool install "foresprint[web,excel,jira]" --with "my-plugin @ git+https://..."`.

A format-neutral helper for imports: `foresprint.storage.import_sprints`.

## Plugins with the installer

The [install scripts](installation.md) ask whether plugins should be installed as well: several
separated by `;`, as the short form `owner/repo` (expands to `git+https://github.com/owner/repo`)
or in full as `name @ git+https://...`. The selection is remembered (Windows:
`%APPDATA%\foresprint\plugins.txt`, otherwise `~/.config/foresprint/plugins`); when
updating, Enter keeps it and `-` removes all plugins. Plugins from Git repositories need Git,
private ones additionally a login. A plugin must pin the source of the core in
`[tool.uv.sources]`.

Without the prompt (set the environment variables before the call):

| Variable | Effect |
|---|---|
| `FORESPRINT_WITH="owner/repo; ..."` | install these plugins (empty = none) |
| `FORESPRINT_REF=v1.0` | install a particular tag or branch instead of `main` |
| `FORESPRINT_NO_SHORTCUT=1` | do not create a desktop launcher |

Plugins and the Python version are kept across [automatic updates](installation.md#updating).
While a merge is open in the data repository, plugin pages are replaced by the conflict
resolution like every other team page (see [Web UI](web-ui.md)).
