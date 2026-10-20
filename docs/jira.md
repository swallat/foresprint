# Jira import

The ticket pre-planning ([design](design/ticket-planning.md), `features.tickets`) can read its
tickets straight from **Jira Data Center** instead of from a CSV export. The import is
**read-only**: the tool sends only `GET` requests and never changes anything in Jira. The one
exception is the optional [label write-back](#writing-earmarks-as-labels) (`write_labels: true`,
off by default), which adds or removes `planned_for_<sprint>` labels and nothing else.

## Setup

1. **Install the extra `[jira]`.** The installer does it; run it again on an older installation
   (it keeps your plugins). By hand:
   `uv tool install --force "sprintforecast[web,excel,jira] @ https://github.com/swallat/sprint-forecast/archive/refs/heads/main.zip"`
   (give plugins again with `--with`; see [installation.md](installation.md)). Without the extra
   the CSV import still works.
2. **Configure the tracker** in `team.yaml` (details: [data-format.md](data-format.md)):

   ```yaml
   features:
     tickets: true
   tracker:
     kind: jira
     base_url: https://jira.example.org
     query: 'project = ABC AND resolution = Unresolved AND issuetype not in subTaskIssueTypes() ORDER BY Rank'
     fields:
       estimate: Story Points
       remaining: Remaining Points
       epic: Epic Link
   ```

   Exclude sub-tasks in the query (`issuetype not in subTaskIssueTypes()`): a sub-task is read as
   a ticket of its own, so it would be counted twice next to its parent's estimate.

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
   (the install command above with `--with keyring` added); the entry is stored under the
   service `sprintforecast-jira` and the **host** of `base_url` only: one token per Jira host,
   shared by all teams and paths on it. The environment variable comes first when both exist
   (`--set-token` warns about that).
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

## Writing earmarks as labels

With `write_labels: true` in the `tracker` section of `team.yaml`, an earmark of the tool can be
mirrored to Jira as the label `planned_for_<sprint_id>` (for example `planned_for_2026.23`), so
that others see the planned sprint in Jira without being able to put a not yet refined ticket into
the sprint itself.

```bash
sprintforecast tickets TEAM --write-labels            # preview: which label is added or removed where
sprintforecast tickets TEAM --write-labels --apply    # write the labels to Jira
```

- The command reads the tickets fresh from Jira, compares them with the earmarks and lists only
  tickets whose labels differ. Nothing is written without `--apply`; nothing changes when the
  preview is empty.
- Per ticket it adds the label of the earmark and removes any other `planned_for_*` label. A
  released earmark removes its label. Other labels of the ticket are never touched, and done
  tickets are skipped.
- **Precedence:** the sprint field of Jira beats the earmark of the tool, which beats the label.
  A ticket that sits in a real sprint in Jira gets no label and loses a stale one; a deviating
  earmark is dropped by the import as before.
- **Reading:** with `write_labels: true` the import takes `planned_for_<sprint>` labels of tickets
  without sprint and earmark as earmarks (shown as "earmark taken from the label"). A label of an
  unknown or past sprint, or several labels, are reported and not adopted. With `write_labels:
  false` labels are ignored, so a stale label cannot bring back a released earmark.
- Jira labels cannot contain spaces: a sprint id with a space cannot be written and is reported.
- The write needs the permission to edit labels of the ticket (403 otherwise). If a write fails
  the run stops; what was written before stays, and the next run starts from the then current labels.
- Afterwards `--fetch --apply` brings the new labels into `tickets.yaml`.

The only write the tool can perform is `PUT /rest/api/2/issue/<KEY>` with an `update` of
`labels` (`add`/`remove` of `planned_for_*` labels). The request function refuses every other
method, path and body, and a test enforces it.

## What is read

Reading uses only `GET` requests, to these endpoints:

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
| The CA file in `SSL_CERT_FILE` / `SSL_CERT_DIR` cannot be read | The variable points to a missing or invalid file; fix or unset it. |
| The TLS handshake failed | `http` instead of `https`, wrong port, or a proxy that interferes with TLS; not a certificate problem. |
| The TLS check of the certificate failed | The check is **never** switched off. If your company CA signs the certificate, point the environment variable `SSL_CERT_FILE` (or `SSL_CERT_DIR`) to the CA bundle, then retry. |
| Not reachable / no answer within 30 seconds | VPN, proxy or firewall; the host must be reachable from this computer on the HTTPS port. |
| Jira rejects the query (400) | The text after it is Jira's own message about the JQL. |
| The field "..." does not exist / is ambiguous | Use the display name exactly as in Jira, or the field id (`customfield_10016`) if two fields share a name; the message lists the ids. |
| The result changed while reading | Tickets were edited while the pages were read, or Jira returned fewer than announced: nothing is written, just run the command again. |
| The proxy requires authentication (407) | Check `HTTPS_PROXY` and its credentials. |
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
