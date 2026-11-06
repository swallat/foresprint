// Package sharedfolder holds the building blocks of the shared-folder storage: a folder on a file
// server or in a sync service (Dropbox, Nextcloud, OneDrive ...) that a team keeps its data in.
//
// Layout inside the shared folder (next to the team folders, never inside them):
//
//	.foresprint/storage.yaml            kind and format version, written when the folder is set up
//	.foresprint/lock                    the short save lock (owner, host, time, expiry)
//	.foresprint/journal/<person>.jsonl  one line per save: who, when, files, before/after checksums
//	.foresprint/snapshots/<day>/        files changed that day (copies of the state before the save)
//	.foresprint/snapshots/<day>-full/   a complete copy, once a week
//
// The package only does file work; merging and the window's wording live in datasvc.
package sharedfolder

// Dir is the name of the folder with the storage's own files.
const Dir = ".foresprint"
