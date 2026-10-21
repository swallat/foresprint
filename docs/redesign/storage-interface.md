# Storage interface

Decided 21.10.2026: **Git is the storage of 1.0** (history, data integrity). A **shared folder** (file server, later SharePoint) is supported after 1.0. Both sit behind one interface so the UI and the flows in [flows.md](flows.md) (D1 to D6) stay the same when the folder arrives. Data stays readable YAML in both. In the table, the Folder column is the design for after 1.0; only the Git column is built for 1.0.

## Operations

| Operation | Returns | Folder | Git |
| --- | --- | --- | --- |
| `status()` | kind, location, writable, connected, pending saves, lock holder, changes from others (count, who) | checksums vs. disk, `.lock` | fetch, ahead/behind |
| `load(scope)` | files with a version token each | checksum per file | blob id per file |
| `save(changes, base_versions, message)` | `saved`, `merged` (auto by key), `conflict(entries)`, `read_only(reason)`, `waiting_for_review(link)` | short lock (owner, host, time, 30 s expiry), version check, key merge (`yamlmerge.py`), temp file + atomic replace, retry on Windows sharing violation, journal entry | commit, pull with key merge, push; protected branch: push own branch with push options, return link |
| `refresh()` | changed files and who changed them | compare checksums, read journal | pull |
| `conflicts()` / `resolve(decisions)` | entries with mine, theirs, base | from failed version check | from merge |
| `history(scope)` | entries: who, when, files, summary | journal `.journal/<person>.jsonl` | log |
| `restore(entry or snapshot)` | files as unsaved changes | daily snapshot folder, last 30 | checkout of an earlier state |
| `revert(entry)` | inverse change as unsaved changes | from journal before/after values | git revert as changes |
| `capabilities()` | flags the UI uses to show or hide features | `offline_write: false`, `snapshots`, `tags: false` | `offline_write: true`, `tags`, `branches` |

## Rules

- The UI only talks to this interface; Git words appear only in Settings > Storage.
- Every save is atomic per file and recorded (journal or commit) with person and time.
- A conflict is only raised when the same key got different values; everything else merges.
- Smaller files (one per project instead of one ticket file) reduce conflicts; the file layout is part of the 1.0 data-format review.
- The interface is defined independently of the core language (Python or Go, decision pending).

## Open (folder, after 1.0)

- Behaviour on the real SMB share (lock, rename, clock skew): test script `share-test.py` from the storage pre-study, result pending.
- Working without connection to the shared folder: read only from cache (proposal), clarification pending.
- SharePoint folder after the file-server test, with detection of conflict copies.
