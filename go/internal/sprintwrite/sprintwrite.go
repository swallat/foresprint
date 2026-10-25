// Package sprintwrite plans and carries out the optional write-back of the planned sprint to
// the tracker (decision 10 of the design). It moves tickets between tracker sprints and nothing
// else: order, estimate, status and texts stay untouched, and tracker sprints are never
// created, started or closed. A plan is always shown first (preview), each move can be left
// out, and what was done can be undone. New in 1.0, there is no Python original.
package sprintwrite

import (
	"errors"
	"math"
	"sort"
	"strconv"
	"strings"

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
	d.Add(known)
	return d
}

// SprintNumber reads the numeric tracker id of a sprint. It accepts what a tracker may hand out
// for the same number: "12", " 12 " and "12.0".
func SprintNumber(id string) (int, bool) {
	id = strings.TrimSpace(id)
	if n, err := strconv.Atoi(id); err == nil && n > 0 {
		return n, true
	}
	if f, err := strconv.ParseFloat(id, 64); err == nil && f == math.Trunc(f) && f >= 0 && f < 1<<31 {
		return int(f), true
	}
	return 0, false
}

// Add makes further tracker sprints known, for example the sprints of a board that hold no ticket
// yet (JiraSource.ListBoardSprints). A sprint already known is kept as it is, except that a
// missing or non-numeric id is replaced by the numeric id of a sprint of the same name.
func (d *Directory) Add(known []sources.SprintValue) {
	for _, s := range known {
		_, numeric := SprintNumber(s.ID)
		merged := false
		for i := range d.sprints {
			r := &d.sprints[i]
			if r.ID == s.ID && s.ID != "" {
				merged = true
				break
			}
			if r.Name == s.Name {
				if _, have := SprintNumber(r.ID); !have && numeric {
					r.ID = s.ID
				}
				if r.State == "" {
					r.State = s.State
				}
				merged = true
				break
			}
		}
		if !merged {
			d.sprints = append(d.sprints, Ref{ID: s.ID, Name: s.Name, State: s.State})
		}
	}
}

func (d Directory) byID(id string) (Ref, bool) {
	for _, r := range d.sprints {
		if r.ID == id {
			return r, true
		}
	}
	return Ref{}, false
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
	// From is where the ticket is now: nil with FromKnown = the backlog; FromKnown false = a
	// place the directory does not know (an undo cannot go back there).
	From      *Ref
	FromKnown bool
	To        *Ref
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
	// Committed is the list frozen at Planning; nil = not frozen (nothing is put in then).
	Committed []string
	// TakenOut are the tickets that were in the tracker's sprint but taken out in planning (the
	// list "adjust in Jira"). Tickets pulled in after the freeze are drift, never taken out.
	TakenOut []string
	Tickets  []model.Ticket
	Tracker  model.TrackerSettings
	Dir      Directory
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
		plan.Problems = append(plan.Problems, sources.T("Sprint {sprint}: no sprint of the tracker belongs to it", "sprint", in.SprintID))
		return plan
	case target.Closed():
		plan.Problems = append(plan.Problems, sources.T("Sprint {sprint}: the tracker's sprint “{name}” is closed", "sprint", in.SprintID, "name", target.Name))
		return plan
	}
	byKey := map[string]model.Ticket{}
	for _, t := range in.Tickets {
		byKey[t.Key] = t
	}
	from := func(t model.Ticket) (*Ref, bool) {
		if t.SprintName == nil || *t.SprintName == "" {
			return nil, true
		}
		if r, ok := in.Dir.ByName(*t.SprintName); ok {
			return &r, true
		}
		return nil, false
	}
	// The tracker's sprint decides, not the tool's sprint id (that is cleared once the sprint
	// of the tool has ended).
	inTarget := func(t model.Ticket) bool {
		return t.SprintName != nil && *t.SprintName == target.Name ||
			t.InSprint != nil && *t.InSprint == in.SprintID
	}
	seenKey := map[string]bool{}
	for _, key := range in.Committed {
		if seenKey[key] {
			continue
		}
		seenKey[key] = true
		t, known := byKey[key]
		switch {
		case !known:
			plan.Problems = append(plan.Problems, sources.T("{key}: not in the ticket list, cannot be moved", "key", key))
		case t.Done || inTarget(t):
		default:
			ref, ok := from(t)
			plan.Moves = append(plan.Moves, Move{Key: key, Title: t.Title, Reason: Committed, From: ref, FromKnown: ok, To: &target})
		}
	}
	if len(in.TakenOut) > 0 {
		removed, problem := removedTarget(in)
		if problem != "" {
			plan.Problems = append(plan.Problems, problem)
		}
		seenOut := map[string]bool{}
		for _, key := range in.TakenOut {
			t, known := byKey[key]
			if seenOut[key] || problem != "" || !known || t.Done || !inTarget(t) || seenKey[key] {
				continue
			}
			seenOut[key] = true
			ref, ok := from(t)
			plan.Moves = append(plan.Moves, Move{Key: key, Title: t.Title, Reason: TakenOut, From: ref, FromKnown: ok, To: removed})
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
		return nil, sources.T("Sprint {sprint}: the next sprint does not exist in the tracker, taken-out tickets stay where they are", "sprint", in.NextSprintID)
	case "pro_forma":
		for _, name := range in.ProForma {
			if r, ok := in.Dir.ByName(name); ok && !r.Closed() {
				return &r, ""
			}
		}
		return nil, sources.T("No pro-forma sprint exists in the tracker, taken-out tickets stay where they are")
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
		for start := 0; start < len(g.moves); start += sources.MaxMoveBatch {
			batch := g.moves[start:min(start+sources.MaxMoveBatch, len(g.moves))]
			keys := make([]string, len(batch))
			for k, m := range batch {
				keys[k] = m.Key
			}
			var err error
			if g.to == nil {
				err = mover.MoveToBacklog(keys)
			} else if id, ok := SprintNumber(g.to.ID); !ok {
				err = errors.New(sources.T("Sprint “{name}” has no usable number (read: “{id}”)", "name", g.to.Name, "id", g.to.ID))
			} else {
				err = mover.MoveToSprint(id, keys)
			}
			if err != nil {
				// What went through stays in Done (and can be undone); the rest failed.
				res.Err = err
				res.Failed = append(res.Failed, g.moves[start:]...)
				for _, rest := range groups[i+1:] {
					res.Failed = append(res.Failed, rest.moves...)
				}
				return res
			}
			res.Done = append(res.Done, batch...)
		}
	}
	return res
}

// UndoPlan reverses moves that went through: every ticket goes back to where it was. A ticket
// whose earlier place is unknown or a closed sprint cannot go back; it is named in Problems.
func UndoPlan(done []Move) Plan {
	var plan Plan
	for i := len(done) - 1; i >= 0; i-- {
		m := done[i]
		switch {
		case !m.FromKnown:
			plan.Problems = append(plan.Problems, sources.T("{key}: its earlier place is unknown, it stays where it is", "key", m.Key))
		case m.From != nil && m.From.Closed():
			plan.Problems = append(plan.Problems, sources.T("{key}: its earlier sprint “{name}” is closed, it stays where it is", "key", m.Key, "name", m.From.Name))
		default:
			plan.Moves = append(plan.Moves, Move{Key: m.Key, Title: m.Title, Reason: Undo, From: m.To, FromKnown: true, To: m.From})
		}
	}
	return plan
}

// BoardLister reads the open and future sprints of a Jira board (JiraSource.ListBoardSprints).
type BoardLister interface {
	ListBoardSprints(boardID int) ([]sources.SprintValue, error)
}

// LoadDirectory builds the directory from the sprints met in the fetched tickets and, when
// tracker.board_id is set, the sprints of that board, so that a future sprint without any
// ticket is found too.
func LoadDirectory(known []sources.SprintValue, board BoardLister, tracker model.TrackerSettings) (Directory, error) {
	d := NewDirectory(known, tracker)
	if tracker.BoardID == nil || board == nil {
		return d, nil
	}
	more, err := board.ListBoardSprints(*tracker.BoardID)
	if err != nil {
		return d, err
	}
	d.Add(more)
	return d, nil
}
