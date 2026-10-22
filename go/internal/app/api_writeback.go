package app

import (
	"errors"
	"slices"
	"sync"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/sprintwrite"
	"github.com/swallat/foresprint/internal/ticketimport"
)

// The optional write-back of the planned sprint to the tracker (story 285, decision 10): it
// moves tickets between tracker sprints and nothing else. It is off unless the team switched it
// on, and it changes the tracker only through PlanWriteApply or PlanWriteUndo, which the page
// calls on an explicit action of the person after the preview.

// trackerWriter is the tracker as the write-back needs it; tests replace openTrackerWriter by a
// fake, so that no test talks to a real Jira.
type trackerWriter interface {
	sprintwrite.Mover
	Fetch() ([]sources.RawTicket, error)
	KnownSprints() []sources.SprintValue
	EnableSprintWrite()
	Close()
}

var openTrackerWriter = func(t model.TrackerSettings) (trackerWriter, error) {
	src, err := sources.Open(ticketimport.SourceSettings(t), "", "", nil)
	if err != nil {
		return nil, err
	}
	jira, ok := src.(*sources.JiraSource)
	if !ok {
		return nil, errors.New(i18n.T("Writing the sprint back works with Jira only."))
	}
	return jira, nil
}

// written remembers, per team and sprint, the moves that went through, so that they can be taken
// back. It lives as long as the program does.
var (
	writtenMu sync.Mutex
	written   = map[string][]sprintwrite.Move{}
)

func (a *API) writtenKey(team, sprintID string) string {
	return a.DataDir() + "\x00" + team + "\x00" + sprintID
}

func (a *API) writtenMoves(team, sprintID string) []sprintwrite.Move {
	writtenMu.Lock()
	defer writtenMu.Unlock()
	return slices.Clone(written[a.writtenKey(team, sprintID)])
}

func (a *API) setWrittenMoves(team, sprintID string, moves []sprintwrite.Move) {
	writtenMu.Lock()
	defer writtenMu.Unlock()
	if len(moves) == 0 {
		delete(written, a.writtenKey(team, sprintID))
		return
	}
	written[a.writtenKey(team, sprintID)] = moves
}

func refName(r *sprintwrite.Ref) string {
	if r == nil {
		return ""
	}
	return r.Name
}

func writeMoves(moves []sprintwrite.Move) []WriteMove {
	out := make([]WriteMove, 0, len(moves))
	for _, m := range moves {
		out = append(out, WriteMove{
			Key: m.Key, Title: m.Title, Reason: string(m.Reason),
			From: refName(m.From), To: refName(m.To), FromKnown: m.FromKnown,
		})
	}
	return out
}

// writeEnabled reports whether the team switched write-back on and has a tracker to write to.
func (c *planCtx) writeEnabled() bool {
	t := c.data.Team.Tracker
	return c.tickets() && c.data.Team.Source() == model.SourceTracker && t.WriteSprint && t.Kind == "jira"
}

// writePlan builds the plan of the sprint against the live sprints of the tracker (read only).
func (c *planCtx) writePlan(w trackerWriter) (sprintwrite.Plan, sprintwrite.Directory, error) {
	if _, err := w.Fetch(); err != nil {
		return sprintwrite.Plan{}, sprintwrite.Directory{}, err
	}
	tracker := c.data.Team.Tracker
	dir := sprintwrite.NewDirectory(w.KnownSprints(), tracker)
	var next string
	if n, err := calendar.NewChain(&c.data.Team, c.data.Sprints).After(&c.sprint); err == nil {
		next = n.ID
	}
	plan := sprintwrite.Build(sprintwrite.Input{
		SprintID:     c.sprint.ID,
		Committed:    c.sprint.CommittedTickets,
		TakenOut:     c.sprint.Removed,
		Tickets:      c.data.Tickets,
		Tracker:      tracker,
		Dir:          dir,
		ProForma:     c.data.Team.Sprint.ProForma,
		NextSprintID: next,
	})
	return plan, dir, nil
}

// writeReady checks that the sprint can be written: the plan is frozen and the sprint has not
// started.
func (c *planCtx) writeReady() error {
	switch c.stage() {
	case "past", "current":
		return errors.New(i18n.T("The sprint {id} has started; its plan cannot be written to the tracker any more.", "id", c.sprint.ID))
	case "open":
		return errors.New(i18n.T("Freeze the plan first; only the agreed tickets are written to the tracker."))
	}
	return nil
}

// PlanWritePreview shows what writing the frozen plan back would change. It reads from the
// tracker (to know its sprints) and changes nothing.
func (a *API) PlanWritePreview(team, sprintID string) (*WritePreview, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	out := &WritePreview{Moves: []WriteMove{}, Problems: []string{}, RemovedTarget: c.data.Team.Tracker.RemovedTarget}
	if out.RemovedTarget == "" {
		out.RemovedTarget = "backlog"
	}
	out.CanUndo = len(a.writtenMoves(team, sprintID)) > 0
	if !c.writeEnabled() {
		return out, nil
	}
	out.Enabled = true
	if err := c.writeReady(); err != nil {
		out.Problems = append(out.Problems, err.Error())
		return out, nil
	}
	w, err := openTrackerWriter(c.data.Team.Tracker)
	if err != nil {
		return nil, err
	}
	defer w.Close()
	plan, dir, err := c.writePlan(w)
	if err != nil {
		return nil, err
	}
	if ref, ok := dir.ForSprint(sprintID); ok {
		out.Sprint = ref.Name
	}
	out.Moves = writeMoves(plan.Moves)
	out.Problems = append(out.Problems, plan.Problems...)
	return out, nil
}

// PlanWriteApply carries the preview out after the person asked for it; skip are the tickets
// they left out. The plan is built again from the tracker's current state, so a ticket that
// moved meanwhile is not moved twice. What went through can be taken back with PlanWriteUndo.
func (a *API) PlanWriteApply(team, sprintID string, skip []string) (*WriteResult, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	if !c.writeEnabled() {
		return nil, errors.New(i18n.T("Writing the sprint back to the tracker is not switched on."))
	}
	if err := c.writeReady(); err != nil {
		return nil, err
	}
	w, err := openTrackerWriter(c.data.Team.Tracker)
	if err != nil {
		return nil, err
	}
	defer w.Close()
	plan, _, err := c.writePlan(w)
	if err != nil {
		return nil, err
	}
	for i := range plan.Moves {
		plan.Moves[i].Skip = slices.Contains(skip, plan.Moves[i].Key)
	}
	w.EnableSprintWrite()
	res := sprintwrite.Apply(plan, w)
	a.setWrittenMoves(team, sprintID, append(a.writtenMoves(team, sprintID), res.Done...))
	out := &WriteResult{Done: writeMoves(res.Done), Failed: writeMoves(res.Failed), CanUndo: len(a.writtenMoves(team, sprintID)) > 0}
	if res.Err != nil {
		out.Error = res.Err.Error()
	}
	return out, nil
}

// PlanWriteUndo puts the tickets that PlanWriteApply moved back where they were.
func (a *API) PlanWriteUndo(team, sprintID string) (*WriteResult, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	done := a.writtenMoves(team, sprintID)
	if len(done) == 0 {
		return nil, errors.New(i18n.T("There is nothing to take back."))
	}
	if !c.writeEnabled() {
		return nil, errors.New(i18n.T("Writing the sprint back to the tracker is not switched on."))
	}
	w, err := openTrackerWriter(c.data.Team.Tracker)
	if err != nil {
		return nil, err
	}
	defer w.Close()
	w.EnableSprintWrite()
	plan := sprintwrite.UndoPlan(done)
	res := sprintwrite.Apply(plan, w)
	back := map[string]bool{}
	for _, m := range res.Done {
		back[m.Key] = true
	}
	// What is taken back leaves the list; what could not go back (or failed) stays.
	var rest []sprintwrite.Move
	for _, m := range done {
		if !back[m.Key] {
			rest = append(rest, m)
		}
	}
	a.setWrittenMoves(team, sprintID, rest)
	out := &WriteResult{Done: writeMoves(res.Done), Failed: writeMoves(res.Failed), CanUndo: len(rest) > 0}
	if res.Err != nil {
		out.Error = res.Err.Error()
	}
	for _, p := range plan.Problems {
		if out.Error == "" {
			out.Error = p
		}
	}
	return out, nil
}
