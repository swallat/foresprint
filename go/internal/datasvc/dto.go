// Package datasvc is the "Data" area of the window: Save, Refresh, the status chip, conflicts,
// history and Settings > Storage, written against flows D1 to D6 and the storage interface
// (docs/redesign/storage-interface.md).
//
// The window talks to this package only. It speaks the neutral words of the design (save, refresh,
// history); the words of the storage kind (branch, merge request, token) appear only in the
// storage settings. The methods of Store take plain values and return plain structs with JSON
// names, no context and no error types, so that Wails can bind them as they are: expected
// problems (offline, denied, conflict ...) come back as Problem in the result, an error is only
// returned for what the person cannot act on.
package datasvc

import (
	"github.com/swallat/foresprint/internal/git"
)

// Chip states, in the order they win when several apply.
const (
	ChipConflict         = "conflict"           // red: the same value was changed by two people
	ChipProblem          = "problem"            // the storage cannot be used (no Git, no folder ...)
	ChipOffline          = "offline"            // the server is not reachable; saving works locally
	ChipIncoming         = "incoming"           // others changed something; Refresh takes it over
	ChipWaitingForReview = "waiting_for_review" // a merge request waits on the server
	ChipUnsaved          = "unsaved"            // own changes not saved yet
	ChipPending          = "pending"            // saved, not shared yet
	ChipLocal            = "local"              // no server set up: saved on this computer only
	ChipOK               = "ok"
)

// Outcomes of Save and Refresh.
const (
	OutcomeSaved            = "saved"
	OutcomeNothing          = "nothing"            // nothing to save
	OutcomeFindings         = "findings"           // errors in the merged data: fix or save anyway
	OutcomeConflict         = "conflict"           // see Conflicts
	OutcomeOffline          = "offline"            // saved locally, shared with the next Refresh
	OutcomeWaitingForReview = "waiting_for_review" // saved on the server's own branch, see Link
	OutcomeReadOnly         = "read_only"          // the person may not write
	OutcomeProblem          = "problem"
)

// Problem is a failure with a heading, the message and the next step, in the language of the
// person. Kind is stable for the window to branch on (for example "auth" opens the sign-in).
type Problem struct {
	Kind    string `json:"kind"`
	Title   string `json:"title"`
	Message string `json:"message"`
	Hint    string `json:"hint,omitempty"`
}

func problemOf(err error) *Problem {
	if err == nil {
		return nil
	}
	e := git.As(err)
	if e == nil {
		return &Problem{Kind: "error", Message: err.Error()}
	}
	return &Problem{Kind: e.Kind, Title: git.TitleFor(e.Kind), Message: e.Error(), Hint: e.Hint()}
}

// Chip is the status chip of the top bar.
type Chip struct {
	State string `json:"state"`
	// Text is the short line ("2 new changes from Anna").
	Text string `json:"text"`
	// Link is set when the chip leads somewhere outside (the merge request).
	Link string `json:"link,omitempty"`
}

// Capabilities are the flags the window uses to show or hide features.
type Capabilities struct {
	OfflineWrite bool `json:"offlineWrite"`
	Tags         bool `json:"tags"`
	Branches     bool `json:"branches"`
	Snapshots    bool `json:"snapshots"`
}

// Status is the state of the storage as the top bar and the Data area show it.
type Status struct {
	Kind string `json:"kind"` // "git" (a shared folder follows after 1.0)
	// Location is the address of the server without credentials, "" = none set up.
	Location     string       `json:"location"`
	Configured   bool         `json:"configured"` // a server is set up
	Writable     bool         `json:"writable"`
	Connected    bool         `json:"connected"`
	Unsaved      int          `json:"unsaved"`  // changed files not saved yet
	Pending      int          `json:"pending"`  // saves not shared yet
	Incoming     int          `json:"incoming"` // changes from others, as of the last check
	IncomingFrom []string     `json:"incomingFrom"`
	Conflicts    int          `json:"conflicts"` // files waiting for a decision
	Link         string       `json:"link,omitempty"`
	Chip         Chip         `json:"chip"`
	Capabilities Capabilities `json:"capabilities"`
	Problem      *Problem     `json:"problem,omitempty"`
}

// Change is a change that came from someone else.
type Change struct {
	Who     string `json:"who"`
	Day     string `json:"day"`
	Summary string `json:"summary"`
}

// SaveOptions are the choices of Save.
type SaveOptions struct {
	// Message describes the save; empty = a default.
	Message string `json:"message"`
	// SaveAnyway shares even if the merged data has errors (the list of D2).
	SaveAnyway bool `json:"saveAnyway"`
}

// Result is the result of Save and Refresh.
type Result struct {
	Outcome string `json:"outcome"`
	// Taken lists what came from others.
	Taken []Change `json:"taken"`
	// Findings are the new data errors (Outcome findings).
	Findings []string `json:"findings,omitempty"`
	// Link leads to the merge request (Outcome waiting_for_review).
	Link  string   `json:"link,omitempty"`
	Notes []string `json:"notes,omitempty"`
	// Conflicts is how many files wait for a decision (Outcome conflict).
	Conflicts int      `json:"conflicts"`
	Problem   *Problem `json:"problem,omitempty"`
	Status    Status   `json:"status"`
}

// Decision values of a conflict.
const (
	Mine   = "ours"
	Theirs = "theirs"
)

// Conflict is one value (or one file) that two people changed.
type Conflict struct {
	// File is the file, relative to the data folder.
	File string `json:"file"`
	// Entries are the values to decide; empty with Whole set.
	Entries []ConflictEntry `json:"entries"`
	// Whole: the file can only be decided as a whole (mine or theirs).
	Whole         bool `json:"whole"`
	MineDeleted   bool `json:"mineDeleted"`
	TheirsDeleted bool `json:"theirsDeleted"`
}

// ConflictEntry is one conflicting value. Mine, Theirs and Before are shown as text; Missing
// values are empty with the matching flag set.
type ConflictEntry struct {
	Path          []string `json:"path"`
	Label         string   `json:"label"`
	Mine          string   `json:"mine"`
	Theirs        string   `json:"theirs"`
	MineMissing   bool     `json:"mineMissing"`
	TheirsMissing bool     `json:"theirsMissing"`
	// Before is the common state both changed; HasBefore is false when the value is new.
	Before    string `json:"before"`
	HasBefore bool   `json:"hasBefore"`
}

// Decision is the choice for one entry or, with an empty Path, for a whole file.
type Decision struct {
	File   string   `json:"file"`
	Path   []string `json:"path"`
	Choice string   `json:"choice"` // Mine or Theirs
}

// Version is one entry of the history.
type Version struct {
	ID      string   `json:"id"`
	Short   string   `json:"short"`
	Who     string   `json:"who"`
	Day     string   `json:"day"`
	Summary string   `json:"summary"`
	Files   []string `json:"files"`
	// Merge entries cannot be taken back.
	Merge bool `json:"merge"`
	// Tags name the entry (Git tags), empty = none.
	Tags []string `json:"tags"`
}

// Label is a name on a state of the data (a Git tag).
type Label struct {
	Name     string `json:"name"`
	Target   string `json:"target"`
	Day      string `json:"day"`
	Summary  string `json:"summary"`
	OnServer *bool  `json:"onServer,omitempty"`
	// Differs: on the server the name points to a different state.
	Differs bool `json:"differs"`
}

// Done is the result of an action that changes unsaved data: restore or take back.
type Done struct {
	// Version is the short id of the resulting state.
	Version string   `json:"version"`
	Warning string   `json:"warning,omitempty"`
	Problem *Problem `json:"problem,omitempty"`
	Status  Status   `json:"status"`
}
