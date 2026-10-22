package ticketimport

import (
	"errors"
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

// Write-back of the earmarks as Jira labels (spec section 6.6). An earmark of the tool becomes
// the label planned_for_<sprint_id> on the ticket; an old planned_for_* label that does not
// match goes. PlanLabelWrites only compares and writes nothing (the preview); ApplyLabelWrites
// does the one thing the tool ever writes to Jira and only for the changes of the plan.
// Precedence: Jira sprint field > earmark of the tool > label, so a ticket in a real sprint gets
// no label and loses a stale one.

// LabelWrite is the change of the labels of one ticket.
type LabelWrite struct {
	Key    string
	Title  string
	Add    []string
	Remove []string
}

// LabelPlan is the list of label changes.
type LabelPlan struct {
	Writes []LabelWrite
	// Warnings are tickets whose label cannot be written (translated texts).
	Warnings []string
}

// WantedLabel is the label the ticket should carry: its earmark, unless it is done or in a real
// sprint. ok is false when it should carry none.
func WantedLabel(ticket model.Ticket, preplan model.Preplan) (label string, ok bool) {
	if ticket.Done || ticket.InSprint != nil {
		return "", false
	}
	earmark := preplan.EarmarkFor(ticket.Key)
	if earmark == nil {
		return "", false
	}
	return sources.PlannedLabel(earmark.Sprint), true
}

// PlanLabelWrites returns the label changes that make the tracker match the earmarks; only
// changes are listed. Done tickets are left alone.
func PlanLabelWrites(tickets []model.Ticket, preplan model.Preplan) LabelPlan {
	plan := LabelPlan{}
	for _, ticket := range tickets {
		if ticket.Done {
			continue
		}
		wanted, hasWanted := WantedLabel(ticket, preplan)
		if hasWanted && strings.IndexFunc(wanted, sources.IsSpace) >= 0 {
			plan.Warnings = append(plan.Warnings, sources.T(
				"Ticket {key}: the label \"{label}\" contains spaces, which Jira does not allow – "+
					"change the sprint id or plan without a label",
				"key", ticket.Key, "label", wanted))
			continue
		}
		var present []string
		for _, s := range sources.LabelSprints(ticket.Labels) {
			present = append(present, sources.PlannedLabel(s))
		}
		var remove, add []string
		for _, x := range present {
			if !hasWanted || x != wanted {
				remove = append(remove, x)
			}
		}
		if hasWanted && !containsString(present, wanted) {
			add = []string{wanted}
		}
		if len(add) > 0 || len(remove) > 0 {
			plan.Writes = append(plan.Writes, LabelWrite{ticket.Key, ticket.Title, add, remove})
		}
	}
	return plan
}

// LabelSetter changes labels of one ticket (the Jira source).
type LabelSetter interface {
	SetLabels(key string, add, remove []string) error
}

// ApplyLabelWrites sends the planned changes one ticket at a time and returns how many were
// written. The first failure of the source stops the run; what was written before stays, and the
// next run starts from the then current labels.
func ApplyLabelWrites(source LabelSetter, plan LabelPlan) (int, error) {
	done := 0
	for _, write := range plan.Writes {
		if err := source.SetLabels(write.Key, write.Add, write.Remove); err != nil {
			if sources.IsSourceError(err) {
				var se *sources.Error
				_ = errors.As(err, &se)
				return done, &sources.Error{Msg: sources.T("Ticket {key}: {error} – {done} of {total} changes written",
					"key", write.Key, "error", se.Msg, "done", done, "total", len(plan.Writes))}
			}
			return done, err
		}
		done++
	}
	return done, nil
}
