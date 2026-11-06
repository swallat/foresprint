# Shared folder as storage

Besides Git, a team can keep its data in a **shared folder**: a file server share (SMB), or a folder that
Dropbox, Nextcloud, OneDrive or SharePoint keeps in sync. Nothing runs on a server; the data stays
readable YAML.

## How it works

- You work on a **local copy** (the data folder of the window). The shared folder holds the team's state.
- **Save** takes a short lock (Refresh does too, so nobody saves in between), merges your changes with what others saved (by key, as with Git: only a value
  changed by two people at once is a conflict), writes each file in one step and adds a line to your journal.
- **Refresh** takes over what others saved. The window also asks when it gets focus.
- Without a connection you can keep editing; saving waits.
- A file you changed and nobody else did is simply written; a file nobody changed is left alone.

## What the shared folder contains

```
shared/
├─ team-a/ ...                       the data, same layout as in a Git data repository
└─ .foresprint/
   ├─ storage.yaml                   marks the folder as a Foresprint storage
   ├─ lock                           present only while somebody saves (expires after 60 s)
   ├─ journal/<person>.jsonl         one line per save: who, when, files, checksums before and after
   └─ snapshots/<day>/               state of each file before the first save of a day that changed it
      snapshots/<day>-full/          once a week a full copy
```

Daily snapshots are kept for 30 days, full copies for 12 weeks. History comes from the journals.
**Restore** brings back a file as it was at the start of the day of a save. **Take back** (revert) works
for a file where nothing was saved since, you have no unsaved changes in it, and the state before that save is
still a snapshot (the first save of a day); otherwise it says so instead of overwriting later work.
What Discard, Restore or a decision replaces and was not saved is kept in `.foresprint-local/trash` in your local copy.

## Sync services

Sync services deliver changes with a delay, so the lock can not protect you there. What protects the data is
the version check: Save compares each file with the state of the last sync and merges when someone else
changed it. If a sync service still makes a conflict copy (`... (conflicted copy ...)`,
`....sync-conflict-...`, `..._conflict-...`), Foresprint finds it and lists it among the conflicts: keep the
file as it is (the copy is deleted) or take the content of the copy.

OneDrive and SharePoint add the computer name to the copy; that cannot be told from other file names and is
not detected.

## Setting up

A folder becomes the team's storage only when a person says "create" (it then gets `.foresprint/storage.yaml`);
for everybody else the folder must already have that marker. If the local copy was set up for another shared
folder before, its record of the last sync is reset, so nothing is mistaken for a deletion by others.

The setup checks the folder first (can we write, does the exclusive create of the lock file work, can a file
be replaced in one step, do the clocks agree within 5 s, do umlauts in names work). It only writes a temporary
subfolder and removes it again. The local copy and the shared folder must be different folders, neither
inside the other.

## Safety rules

- A file that cannot be read (another program has it open, a network error) stops the operation; it is never
  treated as deleted.
- Before a file in the shared folder is replaced it is checked against what the scan saw; if it changed since,
  the save stops ("A file changed meanwhile") and nothing of the other person is overwritten.
- The base of the merge is written from exactly the bytes that were merged or copied.
- A folder counts as reachable only if it contains `.foresprint/storage.yaml`; an unmounted mount point or a
  sync folder that is not filled yet is treated as offline.
- Names from the journal are checked before use (no `..`, no absolute paths).

## Limits

- People with read-only access can refresh (without the lock) but not save.
- Needs the shared folder to be reachable as a path; there is no login to cloud APIs.
- The clocks of the team members should agree within a few seconds (the lock expiry relies on it).
- Git-only features (branches, labels) are not available; the window hides them.
- File names that differ only in case, or that are invalid on Windows (`aux.yaml`, `a:b.yaml`), are not handled;
  avoid them in team data.
- The data check before saving (errors in the merged data) is not run yet.
