# Jira import

The ticket pre-planning ([design](design/ticket-planning.md), `features.tickets`) can read its
tickets straight from **Jira Data Center** instead of from a CSV export. The import is
**read-only**: the tool sends only `GET` requests and never changes anything in Jira.

## Setup

1. **Install the extra `[jira]`.** The installer does it; otherwise
   `uv tool install --force "sprintforecast[web,excel,jira]"` (see
   [installation.md](installation.md)). Without it the CSV import still works.
2. **Configure the tracker** in `team.yaml` (details: [data-format.md](data-format.md)):

   ```yaml
   features:
     tickets: true
   tracker:
     kind: jira
     base_url: https://jira.example.org
     query: 'project = ABC AND resolution = Unresolved ORDER BY Rank'
     fields:
       estimate: Story Points
       remaining: Remaining Points
       epic: Epic Link
   ```

3. **Create a personal access token** in Jira: profile > *Personal Access Tokens* > *Create
   token*. The token carries your own permissions (it sees what you see) and expires when Jira
   says so; the tool only ever uses it to read.
4. **Give the tool the token.** Either set the environment variable

   ```bash
   export SPRINTFORECAST_JIRA_TOKEN=...        # PowerShell: $env:SPRINTFORECAST_JIRA_TOKEN = "..."
   ```

   or store it in the operating system keychain (hidden input, nothing is echoed):

   ```bash
   sprintforecast tickets TEAM --set-token
   ```

   The keychain needs the optional package `keyring`
   (`uv tool install --force "sprintforecast[web,excel,jira]" --with keyring`); it is looked up
   under the service `sprintforecast-jira` and the host of `base_url`. The environment variable
   comes first when both exist.
5. **Test the connection.** Shows the account the token belongs to and the fields found in the
   instance; writes nothing:

   ```bash
   sprintforecast tickets TEAM --test-connection
   ```

## Reading tickets

```bash
sprintforecast tickets TEAM --fetch            # preview: what would change, nothing is written
sprintforecast tickets TEAM --fetch --apply    # write tickets.yaml (and preplan.yaml if needed)
sprintforecast tickets TEAM --fetch --apply --commit
```

The preview is the same as for the CSV import (new, changed, done, to be assigned, refined status
unclear ...) and starts with the Jira host and the number of tickets read.
`--import FILE` (CSV export) stays available as an offline fallback, also for Jira teams;
`--fetch` and `--import` cannot be combined.

**An empty answer never counts as "no work".** If the query returns no tickets while
`tickets.yaml` holds tickets, nothing is written (also with `--apply`) and the command fails with a
hint to check the JQL and the permissions of the token.

## What is read

Only `GET` requests, to these endpoints:

| Request | Purpose |
|---|---|
| `/rest/api/2/myself` | connection test: the display name of the account |
| `/rest/api/2/field` | resolves the field names from `tracker.fields` to `customfield_…` ids; finds the sprint, rank and epic link fields by their schema |
| `/rest/api/2/search` | the tickets of `tracker.query`, 100 per page, with `fields=` limited to what is needed (summary, status, issue type, labels, components, resolution, issue links, parent, estimate, remaining, epic, sprint, rank) |

Authentication is the header `Authorization: Bearer <token>`; the certificate is always verified
and every request has a 30 second timeout. Proxy settings of the environment (`HTTPS_PROXY`,
`NO_PROXY`) are respected.

## What is never stored

- The token is never written to a file of the data folder, to the Git repository, to a log, or
  into an error message. A `token`, `password` or `secret` key in the `tracker` section of
  `team.yaml` is an error.
- The answers of Jira are not kept; `tickets.yaml` holds only the fields listed above, in the
  form described in [data-format.md](data-format.md).
- Error messages say what went wrong (token rejected, no permission, address wrong, invalid JQL
  with Jira's own error text) but never contain ticket data.

## Problems

| Message | What to do |
|---|---|
| Jira rejects the token (401) | The token is wrong or has expired: create a new one and store it again. |
| Jira denies access (403) | The account may not read this data; after repeated failed logins Jira can also block the account for a while. |
| Jira not found at ... (404) | Check `base_url`; a context path such as `/jira` belongs to it. |
| ... redirects | `base_url` is not the final address (e.g. `http` instead of `https`): use the address it redirects to. |
| The TLS check of the certificate failed | The check is **never** switched off. If your company CA signs the certificate, point the environment variable `SSL_CERT_FILE` (or `SSL_CERT_DIR`) to the CA bundle, then retry. |
| Not reachable / no answer within 30 seconds | VPN, proxy or firewall; the host must be reachable from this computer on the HTTPS port. |
| Jira rejects the query (400) | The text after it is Jira's own message about the JQL. |
| The field "..." does not exist / is ambiguous | Use the display name exactly as in Jira, or the field id (`customfield_10016`) if two fields share a name; the message lists the ids. |
| No Jira token found | Set `SPRINTFORECAST_JIRA_TOKEN` or run `--set-token`. |

## Manual test against a real instance

The test suite never touches the network. One test is deselected by default and runs against a
real instance when you ask for it:

```bash
SPRINTFORECAST_JIRA_URL=https://jira.example.org \
SPRINTFORECAST_JIRA_TOKEN=... \
SPRINTFORECAST_JIRA_JQL='project = ABC AND sprint in openSprints()' \
uv run --extra jira pytest -m jira_live
```

Optionally `SPRINTFORECAST_JIRA_ESTIMATE`, `_REMAINING` and `_EPIC` name the fields. The test
prints only counts.
