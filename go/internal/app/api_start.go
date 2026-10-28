package app

import (
	"fmt"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
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
		if s.StartedOn != nil {
			startedOn = s.StartedOn.Format(isoDay)
		}
	case phase == model.PhaseOpen:
		due = !s.Start.After(today)
	}
	return startedOn, due
}

// StartSprint starts a sprint officially: from then on it is the running sprint (and stays so
// until its Review is closed), whatever its dates say. The sprint counts as started from the
// day given (YYYY-MM-DD; "" = its planned first day), so starting late does not shorten it. The
// day lies between the planned first day and today. Called again for a running sprint it moves
// the start day.
func (a *API) StartSprint(team, sprintID, day string) (SprintStart, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, today())
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
	if fc.Phase(*found) == model.PhasePast {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("Sprint {id} is finished; it cannot be started.", "id", sprintID))
	}
	if found.Start.After(fc.Today) {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("The first day of sprint {id} has not come yet.", "id", sprintID))
	}
	from := found.Start
	if day != "" {
		if from, err = time.Parse(isoDay, day); err != nil {
			return SprintStart{}, fmt.Errorf("%s", i18n.T("Enter the start day as YYYY-MM-DD."))
		}
	}
	if from.Before(found.Start) || from.After(fc.Today) {
		return SprintStart{}, fmt.Errorf("%s", i18n.T("The start day must lie between the first day of the sprint and today."))
	}
	s := found.Clone()
	s.StartedOn, s.StartPending = &from, false
	if _, err := repo.SaveSprint(team, &s); err != nil {
		return SprintStart{}, err
	}
	storage.ClearTeamCache()
	return a.startState(team, sprintID)
}

// WithdrawSprintStart takes the start back (it was a mistake): the sprint is open again and
// waits for the next start. Only the running sprint can be taken back, and only while its Review
// is not closed.
func (a *API) WithdrawSprintStart(team, sprintID string) (SprintStart, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return SprintStart{}, err
	}
	fc, err := forecast.Build(data, today())
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
	if _, err := repo.SaveSprint(team, &s); err != nil {
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
	fc, err := forecast.Build(data, today())
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
