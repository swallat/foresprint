// Package sources reads the tickets of the tracker: the CSV export of Jira and a Jira Data
// Center client. It is the Go port of src/foresprint/sources (Python is the reference, the
// comparison is golden/expected/sources).
//
// A source delivers RawTicket values in a neutral form; the ticket import turns them into the
// tickets of the model. The package depends on nothing but the settings it is given (Settings),
// so that it does not wait for the model.
package sources

import (
	"errors"
	"strings"
)

// LabelPrefix starts the label that marks a ticket as earmarked for a sprint.
const LabelPrefix = "planned_for_"

// PlannedLabel is the label of an earmark for the sprint.
func PlannedLabel(sprintID string) string { return LabelPrefix + sprintID }

// LabelSprints returns the sprint ids of the planned_for_<sprint_id> labels, in order, without
// duplicates.
func LabelSprints(labels []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, label := range labels {
		if !strings.HasPrefix(label, LabelPrefix) || len(label) <= len(LabelPrefix) {
			continue
		}
		id := strings.TrimPrefix(label, LabelPrefix)
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}

// Error means that a source cannot be read (file missing, column missing, value not a number,
// Jira unreachable ...). The text is for the user; it never contains the token.
type Error struct{ Msg string }

func (e *Error) Error() string { return e.Msg }

func errorf(text string, kv ...any) *Error { return &Error{Msg: T(text, kv...)} }

// IsSourceError reports whether err is (or wraps) an Error.
func IsSourceError(err error) bool {
	var e *Error
	return errors.As(err, &e)
}

// RawTicket is a ticket as the source delivers it, before sprint resolution and project
// assignment. Empty strings mean "not set"; a nil number means "no value".
type RawTicket struct {
	Key       string
	Title     string
	Status    string
	IssueType string
	Priority  string
	// Values of the configured rule fields, per rule name.
	Extra     map[string][]string
	Estimate  *float64
	Remaining *float64
	// SprintName is the sprint as the tracker shows it (the import resolves it to a sprint id).
	SprintName string
	Rank       string
	Epic       string
	Labels     []string
	Components []string
	// Parent is the key of the parent ticket when the tracker says this one is a sub-task.
	Parent string
	// BlockedBy lists the keys of tickets that must be finished first (Jira: inward "Blocks").
	BlockedBy []string
	// Resolved is true for a ticket that is done according to the tracker.
	Resolved bool
}

// Source delivers tickets: Kind names the tracker kind ("csv", "jira"), Fetch reads all tickets
// or returns an *Error.
type Source interface {
	Kind() string
	Fetch() ([]RawTicket, error)
}

// Fields are the display names (or ids) of the tracker fields. An empty name is not configured.
type Fields struct {
	Estimate  string
	Remaining string
	Epic      string
}

func (f Fields) get(setting string) string {
	switch setting {
	case "estimate":
		return f.Estimate
	case "remaining":
		return f.Remaining
	default:
		return f.Epic
	}
}

// RuleField is an additional field for assignment rules: the rule name and the display name of
// the field in the tracker (or the header of the CSV column).
type RuleField struct{ Name, Display string }

// Settings is what the sources need of the tracker section of team.yaml.
type Settings struct {
	Kind       string
	BaseURL    string
	Query      string
	Fields     Fields
	RuleFields []RuleField // in the order of team.yaml
	// LinkType is the name of the Jira link type whose inward side means "is blocked by".
	LinkType string
}

// DefaultLinkType is the link type of a tracker section that does not name one.
const DefaultLinkType = "Blocks"
