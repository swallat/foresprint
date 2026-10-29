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

// writebackTracker is the tracker as the write-back needs it; tests replace writebackOpen by a
// fake, so that no test talks to a real Jira.
type writebackTracker interface {
	sprintwrite.Mover
	Fetch() ([]sources.RawTicket, error)
	KnownSprints() []sources.SprintValue
	ListBoardSprints(boardID int) ([]sources.SprintValue, error)
	EnableSprintWrite()
	Close()
}

var writebackOpen = func(t model.TrackerSettings) (writebackTracker, error) {
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
	// writebackLock lets one Apply or Undo run at a time, so the list below stays consistent.
	writebackLock   sync.Mutex
	writebackListMu sync.Mutex
	writebackList   = map[string][]sprintwrite.Move{}
)

func (a *API) writebackKey(team, sprintID string) string {
	return a.DataDir() + "\x00" + team + "\x00" + sprintID
}

func (a *API) writebackMoved(team, sprintID string) []sprintwrite.Move {
	writebackListMu.Lock()
	defer writebackListMu.Unlock()
	return slices.Clone(writebackList[a.writebackKey(team, sprintID)])
}

func (a *API) writebackSetMoved(team, sprintID string, moves []sprintwrite.Move) {
	writebackListMu.Lock()
	defer writebackListMu.Unlock()
	if len(moves) == 0 {
		delete(writebackList, a.writebackKey(team, sprintID))
		return
	}
	writebackList[a.writebackKey(team, sprintID)] = moves
}

func writebackRefName(r *sprintwrite.Ref) string {
	if r == nil {
		return ""
	}
	return r.Name
}

func writebackMoves(moves []sprintwrite.Move) []WriteMove {
	out := make([]WriteMove, 0, len(moves))
	for _, m := range moves {
		out = append(out, WriteMove{
			Key: m.Key, Title: m.Title, Reason: string(m.Reason),
			From: writebackRefName(m.From), To: writebackRefName(m.To), FromKnown: m.FromKnown,
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
func (c *planCtx) writePlan(w writebackTracker) (sprintwrite.Plan, sprintwrite.Directory, error) {
	raws, err := w.Fetch()
	if err != nil {
		return sprintwrite.Plan{}, sprintwrite.Directory{}, err
	}
	if len(raws) == 0 {
		return sprintwrite.Plan{}, sprintwrite.Directory{}, errors.New(i18n.T("The tracker returned no tickets; nothing is written. Check the query and the permissions of the token."))
	}
	// The plan follows the tracker as it is now, not the last import, so a ticket moved
	// meanwhile (by hand or by an earlier write-back) is seen where it really is.
	fresh := ticketimport.PlanImport(ticketimport.Env{
		Tracker: c.data.Team.Tracker, Projects: c.data.Projects, Products: c.data.Products,
		Tickets: c.data.Tickets, Preplan: c.data.Preplan, Sprints: ticketimport.ForecastSprints{Forecast: c.fc}, Today: c.today,
	}, raws, nil, false)
	tracker := c.data.Team.Tracker
	dir, err := sprintwrite.LoadDirectory(w.KnownSprints(), w, tracker)
	if err != nil {
		return sprintwrite.Plan{}, sprintwrite.Directory{}, err
	}
	var next string
	if n, err := calendar.NewChain(&c.data.Team, c.data.Sprints).After(&c.sprint); err == nil {
		next = n.ID
	}
	plan := sprintwrite.Build(sprintwrite.Input{
		SprintID:     c.sprint.ID,
		Committed:    c.sprint.CommittedTickets,
		TakenOut:     c.sprint.Removed,
		Tickets:      fresh.Tickets,
		Tracker:      tracker,
		Dir:          dir,
		ProForma:     c.data.Team.Sprint.ProForma,
		NextSprintID: next,
	})
	return plan, dir, nil
}

// writeReady checks that the sprint can be written: the plan is agreed (starting the sprint on
// the Plan page agrees it) and the sprint is not finished.
func (c *planCtx) writeReady() error {
	switch c.stage() {
	case "past":
		return errors.New(i18n.T("The sprint {id} has started; its plan cannot be written to the tracker any more.", "id", c.sprint.ID))
	case "open":
		return errors.New(i18n.T("Start the sprint first; only the agreed tickets are written to the tracker."))
	case "current":
		if c.sprint.CommittedTickets == nil {
			return errors.New(i18n.T("This sprint was started without an agreed plan; take the start back and start it on the Plan page."))
		}
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
	out.CanUndo = len(a.writebackMoved(team, sprintID)) > 0
	if !c.writeEnabled() {
		return out, nil
	}
	out.Enabled = true
	if err := c.writeReady(); err != nil {
		out.Problems = append(out.Problems, err.Error())
		return out, nil
	}
	w, err := writebackOpen(c.data.Team.Tracker)
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
	out.Moves = writebackMoves(plan.Moves)
	out.Problems = append(out.Problems, plan.Problems...)
	return out, nil
}

// PlanWriteApply carries the preview out after the person asked for it; approved are the keys
// of the tickets they saw and left ticked. The plan is built again from the tracker's current
// state and only moves of approved tickets are written, so a ticket that moved meanwhile is not
// moved twice and nothing the person did not see is written. What went through can be taken
// back with PlanWriteUndo.
func (a *API) PlanWriteApply(team, sprintID string, approved []string) (*WriteResult, error) {
	writebackLock.Lock()
	defer writebackLock.Unlock()
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
	w, err := writebackOpen(c.data.Team.Tracker)
	if err != nil {
		return nil, err
	}
	defer w.Close()
	plan, _, err := c.writePlan(w)
	if err != nil {
		return nil, err
	}
	for i := range plan.Moves {
		plan.Moves[i].Skip = !slices.Contains(approved, plan.Moves[i].Key)
	}
	w.EnableSprintWrite()
	res := sprintwrite.Apply(plan, w)
	a.writebackSetMoved(team, sprintID, append(a.writebackMoved(team, sprintID), res.Done...))
	out := &WriteResult{Done: writebackMoves(res.Done), Failed: writebackMoves(res.Failed), CanUndo: len(a.writebackMoved(team, sprintID)) > 0}
	if res.Err != nil {
		out.Error = res.Err.Error()
	}
	return out, nil
}

// PlanWriteUndo puts the tickets that PlanWriteApply moved back where they were.
func (a *API) PlanWriteUndo(team, sprintID string) (*WriteResult, error) {
	writebackLock.Lock()
	defer writebackLock.Unlock()
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	if c.stage() == "past" {
		return nil, errors.New(i18n.T("The sprint {id} has started; its plan cannot be written to the tracker any more.", "id", sprintID))
	}
	done := a.writebackMoved(team, sprintID)
	if len(done) == 0 {
		return nil, errors.New(i18n.T("There is nothing to take back."))
	}
	if !c.writeEnabled() {
		return nil, errors.New(i18n.T("Writing the sprint back to the tracker is not switched on."))
	}
	w, err := writebackOpen(c.data.Team.Tracker)
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
	// What is taken back leaves the list, and so does what can never go back (its earlier place
	// is unknown or closed: the problems below say so); only what failed stays for another try.
	retry := map[string]bool{}
	for _, m := range res.Failed {
		retry[m.Key] = true
	}
	var rest []sprintwrite.Move
	for _, m := range done {
		if !back[m.Key] && retry[m.Key] {
			rest = append(rest, m)
		}
	}
	a.writebackSetMoved(team, sprintID, rest)
	out := &WriteResult{Done: writebackMoves(res.Done), Failed: writebackMoves(res.Failed), CanUndo: len(rest) > 0}
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
