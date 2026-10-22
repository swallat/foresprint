// Package sprintwrite plans and carries out the optional write-back of the planned sprint to
// the tracker (decision 10 of the design). It moves tickets between tracker sprints and nothing
// else: order, estimate, status and texts stay untouched, and tracker sprints are never
// created, started or closed. A plan is always shown first (preview), each move can be left
// out, and what was done can be undone. New in 1.0, there is no Python original.
package sprintwrite

import (
	"fmt"
	"sort"
	"strconv"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

// Ref is a sprint of the tracker.
type Ref struct {
	// ID is the id in the tracker (Jira: the number).
	ID    string
	Name  string
	State string // ACTIVE, FUTURE or CLOSED; "" = unknown
}

// Closed reports whether the tracker refuses to put tickets into the sprint.
func (r Ref) Closed() bool { return r.State == "CLOSED" }

// Directory knows the tracker sprints and how they map to the tool's sprint ids.
type Directory struct {
	sprints     []Ref
	sprintNames model.OrderedMap[string]
}

// NewDirectory builds the directory from the sprints met while reading the tickets.
func NewDirectory(known []sources.SprintValue, tracker model.TrackerSettings) Directory {
	d := Directory{sprintNames: tracker.SprintNames}
	for _, s := range known {
		d.sprints = append(d.sprints, Ref{ID: s.ID, Name: s.Name, State: s.State})
	}
	return d
}

// ByName finds a tracker sprint by its name.
func (d Directory) ByName(name string) (Ref, bool) {
	for _, r := range d.sprints {
		if r.Name == name {
			return r, true
		}
	}
	return Ref{}, false
}

// ForSprint finds the tracker sprint of a sprint id of the tool: tracker sprints are matched by
// sprint id, either because the tracker sprint is named like the id or through
// tracker.sprint_names.
func (d Directory) ForSprint(toolID string) (Ref, bool) {
	for _, r := range d.sprints {
		if r.Name == toolID {
			return r, true
		}
		if id, ok := d.sprintNames.Get(r.Name); ok && id == toolID {
			return r, true
		}
	}
	return Ref{}, false
}

// Reason says why a ticket is moved.
type Reason string

// The reasons of a move.
const (
	// Committed: the ticket is on the agreed list but not (yet) in the tracker's sprint.
	Committed Reason = "committed"
	// TakenOut: the ticket is in the tracker's sprint but was taken out during planning.
	TakenOut Reason = "taken_out"
	// Undo: the move reverses an earlier one.
	Undo Reason = "undo"
)

// Move puts one ticket into a tracker sprint (To) or, with To nil, back to the backlog.
type Move struct {
	Key    string
	Title  string
	Reason Reason
	// From is where the ticket is now (nil = backlog or unknown).
	From *Ref
	To   *Ref
	// Skip leaves the move out (the per-ticket opt-out of the preview).
	Skip bool
}

// Plan is the preview of a write-back.
type Plan struct {
	Moves []Move
	// Problems are texts for things that keep part of the plan from being carried out.
	Problems []string
}

// Input is what the plan needs.
type Input struct {
	// SprintID is the sprint of the tool that is written.
	SprintID string
	// Committed is the list frozen at Planning; nil = not frozen (nothing is taken out then).
	Committed []string
	Tickets   []model.Ticket
	Tracker   model.TrackerSettings
	Dir       Directory
	// ProForma are the names of the pro-forma sprints; NextSprintID is the sprint after SprintID.
	ProForma     []string
	NextSprintID string
}

// Build plans the moves: committed tickets that are not in the tracker's sprint go in, tickets
// that are in it but were taken out go to tracker.removed_target.
func Build(in Input) Plan {
	var plan Plan
	target, ok := in.Dir.ForSprint(in.SprintID)
	switch {
	case !ok:
		plan.Problems = append(plan.Problems, fmt.Sprintf("sprint %s: no sprint of the tracker belongs to it", in.SprintID))
		return plan
	case target.Closed():
		plan.Problems = append(plan.Problems, fmt.Sprintf("sprint %s: the tracker's sprint %q is closed", in.SprintID, target.Name))
		return plan
	}
	byKey := map[string]model.Ticket{}
	for _, t := range in.Tickets {
		byKey[t.Key] = t
	}
	from := func(t model.Ticket) *Ref {
		if t.SprintName == nil {
			return nil
		}
		if r, ok := in.Dir.ByName(*t.SprintName); ok {
			return &r
		}
		return nil
	}
	committed := map[string]bool{}
	for _, key := range in.Committed {
		committed[key] = true
		t, known := byKey[key]
		switch {
		case !known:
			plan.Problems = append(plan.Problems, fmt.Sprintf("%s: not in the ticket list, cannot be moved", key))
		case t.Done || (t.InSprint != nil && *t.InSprint == in.SprintID):
		default:
			plan.Moves = append(plan.Moves, Move{Key: key, Title: t.Title, Reason: Committed, From: from(t), To: &target})
		}
	}
	if in.Committed != nil {
		removed, problem := removedTarget(in)
		if problem != "" {
			plan.Problems = append(plan.Problems, problem)
		}
		for _, t := range in.Tickets {
			if t.InSprint == nil || *t.InSprint != in.SprintID || committed[t.Key] || t.Done {
				continue
			}
			if problem != "" {
				continue
			}
			plan.Moves = append(plan.Moves, Move{Key: t.Key, Title: t.Title, Reason: TakenOut, From: from(t), To: removed})
		}
	}
	sort.SliceStable(plan.Moves, func(i, j int) bool { return plan.Moves[i].Key < plan.Moves[j].Key })
	return plan
}

// removedTarget is the tracker sprint for a ticket taken out (nil = backlog) or a problem text.
func removedTarget(in Input) (*Ref, string) {
	switch in.Tracker.RemovedTarget {
	case "next":
		if r, ok := in.Dir.ForSprint(in.NextSprintID); ok && !r.Closed() {
			return &r, ""
		}
		return nil, fmt.Sprintf("sprint %s: the next sprint does not exist in the tracker, taken-out tickets stay where they are", in.NextSprintID)
	case "pro_forma":
		for _, name := range in.ProForma {
			if r, ok := in.Dir.ByName(name); ok && !r.Closed() {
				return &r, ""
			}
		}
		return nil, "no pro-forma sprint exists in the tracker, taken-out tickets stay where they are"
	}
	return nil, ""
}

// Mover is what the tracker offers for the write.
type Mover interface {
	MoveToSprint(sprintID int, keys []string) error
	MoveToBacklog(keys []string) error
}

// Result says what a carried-out plan did.
type Result struct {
	// Done are the moves that went through, in the order they were carried out.
	Done []Move
	// Failed is the move group that failed and its error; later groups were not tried.
	Failed []Move
	Err    error
}

// Apply carries out the moves that are not skipped, one request per target. It stops at the first
// error; what went through is in Done (and can be undone), the rest in Failed.
func Apply(plan Plan, mover Mover) Result {
	type group struct {
		to    *Ref
		moves []Move
	}
	var groups []*group
	index := map[string]*group{}
	for _, m := range plan.Moves {
		if m.Skip {
			continue
		}
		id := "backlog"
		if m.To != nil {
			id = m.To.ID
		}
		g := index[id]
		if g == nil {
			g = &group{to: m.To}
			index[id] = g
			groups = append(groups, g)
		}
		g.moves = append(g.moves, m)
	}
	var res Result
	for i, g := range groups {
		keys := make([]string, len(g.moves))
		for k, m := range g.moves {
			keys[k] = m.Key
		}
		var err error
		if g.to == nil {
			err = mover.MoveToBacklog(keys)
		} else if id, convErr := strconv.Atoi(g.to.ID); convErr != nil {
			err = fmt.Errorf("sprint %q has no usable id", g.to.Name)
		} else {
			err = mover.MoveToSprint(id, keys)
		}
		if err != nil {
			res.Err = err
			for _, rest := range groups[i:] {
				res.Failed = append(res.Failed, rest.moves...)
			}
			return res
		}
		res.Done = append(res.Done, g.moves...)
	}
	return res
}

// UndoPlan reverses moves that went through: every ticket goes back to where it was.
func UndoPlan(done []Move) Plan {
	var plan Plan
	for i := len(done) - 1; i >= 0; i-- {
		m := done[i]
		plan.Moves = append(plan.Moves, Move{Key: m.Key, Title: m.Title, Reason: Undo, From: m.To, To: m.From})
	}
	return plan
}
