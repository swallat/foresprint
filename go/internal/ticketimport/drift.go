package ticketimport

import (
	"sort"

	"github.com/swallat/foresprint/internal/model"
)

// Drift compares the list frozen at Planning with the tracker's sprint (decision 15a): tickets
// pulled in after the freeze and tickets that left the sprint.
type Drift struct {
	// PulledIn are tickets in the tracker's sprint that are not on the frozen list.
	PulledIn []string
	// Dropped are frozen tickets that are no longer in the tracker's sprint (and not done).
	Dropped []string
	// Unknown are frozen tickets the last import did not return at all (for example finished
	// ones, if the query leaves them out): nothing is known about them.
	Unknown []string
}

// DetectDrift compares the frozen list of the sprint with the tickets of the last import.
// frozen nil (not frozen yet) has no drift. A ticket that is done counts as still in the sprint.
func DetectDrift(frozen []string, tickets []model.Ticket, sprintID string) Drift {
	var d Drift
	if frozen == nil {
		return d
	}
	onList := map[string]bool{}
	for _, k := range frozen {
		onList[k] = true
	}
	inSprint := map[string]bool{}
	known := map[string]model.Ticket{}
	for _, t := range tickets {
		known[t.Key] = t
		if t.InSprint != nil && *t.InSprint == sprintID {
			inSprint[t.Key] = true
			if !onList[t.Key] {
				d.PulledIn = append(d.PulledIn, t.Key)
			}
		}
	}
	listed := map[string]bool{}
	for _, k := range frozen {
		if listed[k] {
			continue
		}
		listed[k] = true
		t, ok := known[k]
		switch {
		case !ok:
			d.Unknown = append(d.Unknown, k)
		case inSprint[k] || t.Done:
		default:
			d.Dropped = append(d.Dropped, k)
		}
	}
	sort.Strings(d.PulledIn)
	sort.Strings(d.Dropped)
	sort.Strings(d.Unknown)
	return d
}
