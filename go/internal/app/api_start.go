package app

import (
	"fmt"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/protocol"
	"github.com/swallat/foresprint/internal/storage"
)

// SprintStart is the official start of a sprint as the pages show it.
type SprintStart struct {
	Sprint string `json:"sprint"`
	// Stage is "open", "planned", "current" or "past", like PlanSprint.Stage.
	Stage string `json:"stage"`
	// StartedOn is the day the sprint counts as started from (YYYY-MM-DD), "" before the start.
	StartedOn string `json:"startedOn"`
}

// startInfo is what a page needs to offer the start of a sprint: whether it was started, from
// which day, and whether its first day has come, so that it can be started now.
func startInfo(s model.Sprint, phase model.Phase, today time.Time) (startedOn string, due bool) {
	switch {
	case phase == model.PhaseRunning || (phase == model.PhasePast && s.Started(today)):
		startedOn = s.Start.Format(isoDay)
		if s.StartedOn != nil && !s.StartedOn.Before(s.Start) { // the calendar may have moved the first day past it
			startedOn = s.StartedOn.Format(isoDay)
		}
	case phase == model.PhaseOpen:
		due = !s.Start.After(today)
	}
	return startedOn, due
}

// startDayOf checks the start day of a sprint: "" = its planned first day, else a day between
// the first day and today. The first day must have come.
func startDayOf(found model.Sprint, day string, today time.Time) (time.Time, error) {
	if found.Start.After(today) {
		return time.Time{}, fmt.Errorf("%s", i18n.T("The first day of sprint {id} has not come yet.", "id", found.ID))
	}
	from := found.Start
	if day != "" {
		var err error
		if from, err = time.Parse(isoDay, day); err != nil {
			return time.Time{}, fmt.Errorf("%s", i18n.T("Enter the start day as YYYY-MM-DD."))
		}
	}
	if from.Before(found.Start) || from.After(today) {
		return time.Time{}, fmt.Errorf("%s", i18n.T("The start day must lie between the first day of the sprint and today."))
	}
	return from, nil
}

// StartSprintWithPlan starts a sprint officially and freezes the agreement of the Planning in
// the same step: from then on it is the running sprint (and stays so until its Review is
// closed), whatever its dates say. The sprint counts as started from the day given (YYYY-MM-DD;
// "" = its planned first day), so starting late does not shorten it; the frozen plan is the one
// of the click. It works from the first day on.
func (a *API) StartSprintWithPlan(team, sprintID, day string, in FreezeInput) (SprintStart, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, todayOf(data))
	if err != nil {
		return SprintStart{}, err
	}
	found, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return SprintStart{}, err
	}
	if found == nil {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	}
	if phase := fc.Phase(*found); phase != model.PhaseOpen {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Sprint {id} cannot be started: it is running or finished.", "id", sprintID))
	}
	from, err := startDayOf(*found, day, fc.Today)
	if err != nil {
		return SprintStart{}, err
	}
	if _, err := a.planFreeze(team, sprintID, in, &from); err != nil {
		return SprintStart{}, err
	}
	return a.startState(team, sprintID)
}

// StartSprint changes the start of a sprint whose plan is frozen already: it starts a sprint
// that was planned before this version (or with the command line), or moves the start day of a
// running sprint. The start day lies between the planned first day and today.
func (a *API) StartSprint(team, sprintID, day string) (SprintStart, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, todayOf(data))
	if err != nil {
		return SprintStart{}, err
	}
	found, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return SprintStart{}, err
	}
	if found == nil {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	}
	phase := fc.Phase(*found)
	if phase == model.PhasePast {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Sprint {id} is finished; it cannot be started.", "id", sprintID))
	}
	if phase == model.PhaseOpen && found.Commitment == nil && found.CommittedTickets == nil {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Plan sprint {id} first: it is started on the Plan page, together with the commitment.", "id", sprintID))
	}
	from, err := startDayOf(*found, day, fc.Today)
	if err != nil {
		return SprintStart{}, err
	}
	s := found.Clone()
	s.StartedOn, s.StartPending = &from, false
	if _, err := repo.SaveSprint(team, &s); err != nil {
		return SprintStart{}, err
	}
	storage.ClearTeamCache()
	return a.startState(team, sprintID)
}

// WithdrawSprintStart takes the start back (it was a mistake): the sprint is open again with its
// plan open, so the team can plan again and start it anew; the planning minutes are marked as
// obsolete. Only the running sprint can be taken back, and only while its last day is not over.
func (a *API) WithdrawSprintStart(team, sprintID string) (SprintStart, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, todayOf(data))
	if err != nil {
		return SprintStart{}, err
	}
	found := data.SprintByID(sprintID)
	if found == nil || fc.Phase(*found) != model.PhaseRunning {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Only the running sprint can be taken back to open."))
	}
	if !found.End.After(fc.Today) {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("The last day of sprint {id} is over; close its Review instead.", "id", sprintID))
	}
	s := found.Clone()
	s.StartedOn, s.StartPending = nil, true
	planUnfreeze(&s)
	store := &protocol.Store{Dir: repo.TeamDir(team)}
	if _, err := store.ObsoleteWithSave(sprintID, protocol.Planning, func() ([]string, error) {
		path, serr := repo.SaveSprint(team, &s)
		return []string{path}, serr
	}); err != nil {
		return SprintStart{}, err
	}
	storage.ClearTeamCache()
	return a.startState(team, sprintID)
}

// startState reads the start state of a sprint from the saved data.
func (a *API) startState(team, sprintID string) (SprintStart, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, todayOf(data))
	if err != nil {
		return SprintStart{}, err
	}
	s, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil || s == nil {
		return SprintStart{}, err
	}
	out := SprintStart{Sprint: sprintID}
	switch phase := fc.Phase(*s); phase {
	case model.PhasePast:
		out.Stage = "past"
	case model.PhaseRunning:
		out.Stage = "current"
	default:
		out.Stage = "open"
		if s.CommittedTickets != nil {
			out.Stage = "planned"
		}
	}
	out.StartedOn, _ = startInfo(*s, fc.Phase(*s), fc.Today)
	return out, nil
}
