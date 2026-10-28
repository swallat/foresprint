package model

import "time"

// Phase is where a sprint stands in its life: open (before the official start), running (started,
// the Review not closed yet) or past.
type Phase string

// The phases of a sprint.
const (
	PhaseOpen    Phase = "open"
	PhaseRunning Phase = "running"
	PhasePast    Phase = "past"
)

// frozenPlan reports whether the sprint has a frozen plan or a result.
func (s Sprint) frozenPlan() bool {
	return s.Commitment != nil || s.Planning != nil || s.CommittedTickets != nil || s.Velocity != nil
}

// reviewed reports whether the Review of the sprint is closed on the day. A result counts from
// the last day of the sprint on, so an "as of" date inside a sprint that has a result already
// (demo data, a replay) still sees it running.
func (s Sprint) reviewed(today time.Time) bool {
	return s.Velocity != nil && !s.End.AddDate(0, 0, -1).After(today)
}

// Started reports whether the sprint has been started officially on the day: by "Start sprint"
// (on the day entered, which may be earlier than the day of the click). Files without that mark
// count as started once their plan is frozen and their first day is over, so that sprints of
// earlier versions keep running.
func (s Sprint) Started(today time.Time) bool {
	switch {
	case s.StartedOn != nil:
		return !s.StartedOn.After(today)
	case s.StartPending:
		return false
	}
	return s.Start.Before(today) && s.frozenPlan()
}

// PhaseOf is the phase of a sprint among all (the timeline of the team, in any order). A sprint
// is past once its Review is closed or a later sprint has been started, and a sprint that was
// never started is past when its last day is over. Being started and the end date are
// otherwise independent: a sprint stays running after its last day until the Review closes it.
func PhaseOf(all []Sprint, s Sprint, today time.Time) Phase {
	if s.reviewed(today) {
		return PhasePast
	}
	for _, o := range all {
		if o.ID != s.ID && o.Start.After(s.Start) && (o.reviewed(today) || o.Started(today)) {
			return PhasePast
		}
	}
	switch {
	case s.Started(today):
		return PhaseRunning
	case !s.End.After(today):
		return PhasePast
	}
	return PhaseOpen
}
