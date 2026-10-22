package app

import "github.com/swallat/foresprint/internal/i18n"

// Storage states of the status chip in the top bar (flows.md section 5).
const (
	StorageSaved    = "saved"    // nothing to save, nothing new on the server
	StorageDirty    = "dirty"    // unsaved changes on this machine
	StorageIncoming = "incoming" // new changes from others, "Refresh" takes them
	StorageConflict = "conflict" // the same value was changed by two people
	StorageOffline  = "offline"  // no connection: saved locally only
	StorageMR       = "mr"       // waits for a merge request on the server
	StorageReadOnly = "readonly" // no write access
	StorageLocked   = "locked"   // locked by someone else
)

// Status is what the top bar shows on every page.
type Status struct {
	Storage  string        `json:"storage"`  // one of the Storage constants
	Detail   string        `json:"detail"`   // text for the chip, e.g. "2 new changes from Anna"; "" = default text
	Incoming int           `json:"incoming"` // number of changes from others
	Findings int           `json:"findings"` // number of findings of the data check (badge)
	Tracker  TrackerStatus `json:"tracker"`
}

// TrackerStatus is the state of the ticket tracker sync.
type TrackerStatus struct {
	Enabled bool   `json:"enabled"` // the team has a tracker
	Name    string `json:"name"`    // "Jira"
	Last    string `json:"last"`    // time of the last sync (RFC 3339), "" if none
	Syncing bool   `json:"syncing"`
	Failed  string `json:"failed"` // message of the last failure, "" if fine
}

// Result is the answer of an action started from the top bar.
type Result struct {
	OK      bool   `json:"ok"`
	Message string `json:"message"` // shown as a toast
}

// Status returns the current state of storage and tracker.
//
// Placeholder: the area "Data" (storage) and "Tickets and tracker" replace the body with the
// state of gitsync and the sync. The shape of the answer is fixed.
func (a *API) Status() Status { return Status{Storage: StorageSaved} }

// Save saves the changes and shares them (commit, merge at key level, push).
//
// Placeholder, see Status.
func (a *API) Save() (Result, error) {
	return Result{OK: true, Message: i18n.T("Saved.")}, nil
}

// Refresh fetches the changes of others.
//
// Placeholder, see Status.
func (a *API) Refresh() (Result, error) {
	return Result{OK: true, Message: i18n.T("Up to date.")}, nil
}
