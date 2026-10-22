package app

import (
	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/i18n"
)

// Storage states of the status chip in the top bar (flows.md section 5).
const (
	StorageSaved    = "saved"    // nothing to save, nothing new on the server
	StorageDirty    = "dirty"    // unsaved changes on this machine
	StorageIncoming = "incoming" // new changes from others, "Refresh" takes them
	StorageConflict = "conflict" // the same value was changed by two people
	StorageDecided  = "decided"  // all conflicts decided, Save finishes
	StorageOffline  = "offline"  // no connection: saved locally only
	StorageMR       = "mr"       // waits for review on the server
	StoragePending  = "pending"  // saved on this machine, not shared yet
	StorageLocal    = "local"    // no server set up: saved on this machine only
	StorageProblem  = "problem"  // the storage cannot be used
	StorageReadOnly = "readonly" // no write access
	StorageLocked   = "locked"   // locked by someone else
)

// Status is what the top bar shows on every page.
type Status struct {
	Storage  string        `json:"storage"`        // one of the Storage constants
	Detail   string        `json:"detail"`         // text for the chip, e.g. "2 new changes from Anna"; "" = default text
	Link     string        `json:"link,omitempty"` // review address while the chip says "mr"
	Incoming int           `json:"incoming"`       // number of changes from others
	Findings int           `json:"findings"`       // number of findings of the data check (badge)
	Tracker  TrackerStatus `json:"tracker"`
	// Data is the full state of the storage for the Data area.
	Data datasvc.Status `json:"data"`
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
	// Outcome is the outcome of Save and Refresh (datasvc.Outcome*), "" for other actions.
	Outcome string `json:"outcome,omitempty"`
	// Findings are the data errors that stop Save; the window offers "save anyway".
	Findings []string `json:"findings,omitempty"`
	// Link leads to the review while the changes wait for it.
	Link string `json:"link,omitempty"`
	// Conflicts is how many files wait for a decision.
	Conflicts int `json:"conflicts,omitempty"`
	// Taken lists what came from others.
	Taken []datasvc.Change `json:"taken,omitempty"`
	// Notes are hints for the person, already translated.
	Notes []string `json:"notes,omitempty"`
	// Problem is set when the storage failed in a way the person can act on.
	Problem *datasvc.Problem `json:"problem,omitempty"`
}

var chipStorage = map[string]string{
	datasvc.ChipOK:               StorageSaved,
	datasvc.ChipUnsaved:          StorageDirty,
	datasvc.ChipIncoming:         StorageIncoming,
	datasvc.ChipConflict:         StorageConflict,
	datasvc.ChipDecided:          StorageDecided,
	datasvc.ChipOffline:          StorageOffline,
	datasvc.ChipWaitingForReview: StorageMR,
	datasvc.ChipPending:          StoragePending,
	datasvc.ChipLocal:            StorageLocal,
	datasvc.ChipProblem:          StorageProblem,
}

// statusOf maps the state of the storage to the chip of the top bar.
func statusOf(d datasvc.Status) Status {
	state, ok := chipStorage[d.Chip.State]
	if !ok {
		state = StorageSaved
	}
	if !d.Writable && d.Problem == nil && d.Configured {
		state = StorageReadOnly
	}
	return Status{Storage: state, Detail: d.Chip.Text, Link: d.Chip.Link, Incoming: d.Incoming, Data: d}
}

// Status returns the current state of storage and tracker. It also starts the check for changes
// of others in the background when one is due (at start and every 30 minutes); the answer of that
// check shows with a later call.
//
// The tracker part is a placeholder until the area "Tickets and tracker" fills it.
func (a *API) Status() Status {
	a.data.StartBackgroundCheck()
	return statusOf(a.data.Status())
}

// Save saves the changes and shares them (commit, merge at key level, upload).
func (a *API) Save() (Result, error) { return a.save(false), nil }

// SaveAnyway saves although the check of the changed data found errors.
func (a *API) SaveAnyway() (Result, error) {
	return a.save(true), nil
}

// save runs Save with the tags the Review asked for; they are dropped once a save went through.
func (a *API) save(anyway bool) Result {
	tags := a.pendingTags()
	r := a.data.Save(datasvc.SaveOptions{SaveAnyway: anyway, Tags: tags})
	if r.Outcome == datasvc.OutcomeSaved {
		a.dropTags(tags)
	}
	return resultOf(r, false)
}

// Refresh fetches the changes of others.
func (a *API) Refresh() (Result, error) { return resultOf(a.data.Refresh(), true), nil }

// SyncTracker fetches the tickets from the tracker now.
//
// Placeholder, see Status.
func (a *API) SyncTracker() (Result, error) {
	return Result{OK: true, Message: i18n.T("Tracker synced.")}, nil
}

// resultOf turns the result of the storage into the short answer of the top bar. refresh says
// the action was Refresh, which changes the words for "nothing to do".
func resultOf(r datasvc.Result, refresh bool) Result {
	out := Result{Outcome: r.Outcome, Findings: r.Findings, Link: r.Link, Conflicts: r.Conflicts,
		Taken: r.Taken, Notes: r.Notes, Problem: r.Problem}
	taken := len(r.Taken)
	switch r.Outcome {
	case datasvc.OutcomeSaved:
		out.OK = true
		out.Message = i18n.T("Saved.")
		if refresh {
			out.Message = i18n.T("Up to date.")
		}
		if taken == 1 {
			out.Message = i18n.T("Done. Took over 1 change from others.")
		} else if taken > 1 {
			out.Message = i18n.T("Done. Took over {count} changes from others.", "count", taken)
		}
	case datasvc.OutcomeNothing:
		out.OK = true
		out.Message = i18n.T("Nothing to save.")
		if refresh {
			out.Message = i18n.T("Up to date.")
		}
	case datasvc.OutcomeFindings:
		out.Message = i18n.T("The data has errors. Fix them or save anyway.")
	case datasvc.OutcomeConflict:
		out.Message = i18n.T("{count} files need your decision.", "count", r.Conflicts)
		if r.Conflicts == 1 {
			out.Message = i18n.T("1 file needs your decision.")
		}
	case datasvc.OutcomeOffline:
		out.OK = true
		out.Message = i18n.T("Saved on this computer. It is shared when the connection is back.")
		if refresh {
			out.OK = false
			out.Message = i18n.T("No connection. You keep working with the last state.")
		}
	case datasvc.OutcomeWaitingForReview:
		out.OK = true
		out.Message = i18n.T("Saved. Your changes wait for approval.")
	case datasvc.OutcomeDecided:
		out.OK = true
		out.Message = i18n.T("All decided. Save finishes the merge.")
	case datasvc.OutcomeReadOnly:
		out.Message = i18n.T("You may not write to this storage.")
		if r.Problem != nil && r.Problem.Message != "" {
			out.Message = r.Problem.Message
		}
	default:
		out.Message = i18n.T("Saving did not work.")
		if r.Problem != nil && r.Problem.Message != "" {
			out.Message = r.Problem.Message
		}
	}
	return out
}
