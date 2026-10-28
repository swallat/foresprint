package app

import (
	"fmt"
	"math"
	"sort"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// Sprint workspace: absences (Prepare, later also Team > People), the readiness list and the
// figures of the sprint overview. Edits are written to the sprint file at once; "Save" in the
// top bar shares them. Absences are days per person and sprint, never a reason.

// editMu serializes edits: Wails runs bound calls at the same time, and every edit loads the
// sprint file, changes it and writes it back.
var editMu sync.Mutex

// sprintWindow returns count consecutive sprints from the sprint with the id from (recorded or
// generated from the calendar). An empty from starts at the running sprint, or the next one.
func sprintWindow(data *storage.TeamData, fc *forecast.Forecast, from string, count int) ([]model.Sprint, error) {
	if count < 1 {
		count = 1
	}
	if from == "" {
		e := fc.Current()
		if e == nil {
			var err error
			if e, err = fc.DefaultEntry(forecast.PurposeNext); err != nil {
				return nil, err
			}
		}
		if e == nil {
			return nil, nil
		}
		from = e.Sprint.ID
	}
	first, err := fc.LookupSprint(from, forecast.DefaultLookupAhead)
	if err != nil {
		return nil, err
	}
	if first == nil {
		return nil, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", from))
	}
	out := []model.Sprint{first.Clone()}
	chain := calendar.NewChain(&data.Team, data.Sprints)
	for len(out) < count {
		next, err := chain.After(&out[len(out)-1])
		if err != nil {
			return nil, err
		}
		if stored := data.SprintByID(next.ID); stored != nil {
			next = stored.Clone()
		}
		out = append(out, next)
	}
	return out, nil
}

func absenceState(s model.Sprint) string {
	switch s.AbsenceStatus() {
	case model.AbsencesConfirmed:
		return AbsenceConfirmed
	case model.AbsencesExpected:
		return AbsenceAnnounced
	}
	return AbsenceUnknown
}

// allAbsences are the absence days of a sprint as the grid shows them, per person: confirmed
// cells and announced ones (confirmed wins).
func allAbsences(s model.Sprint) map[string]float64 {
	out := map[string]float64{}
	for k, v := range s.ExpectedAbsences {
		out[k] = v
	}
	for k, v := range s.Absences {
		out[k] = v
	}
	return out
}

// cellState maps the model's cell state to the one of the window.
func cellState(s model.Sprint, person string) string {
	if s.CellDays(person) == 0 && s.AbsenceStatus() != model.AbsencesConfirmed {
		return CellEmpty
	}
	if s.CellState(person) == model.AbsencesConfirmed {
		return CellConfirmed
	}
	return CellAnnounced
}

// displayName is the name of a sprint: the manual one, else the naming rule of the team, else
// the id.
func displayName(data *storage.TeamData, fc *forecast.Forecast, s model.Sprint) string {
	sprints := make([]model.Sprint, len(fc.Entries), len(fc.Entries)+1)
	known := false
	for i := range fc.Entries {
		sprints[i] = fc.Entries[i].Sprint
		known = known || sprints[i].ID == s.ID
	}
	if !known { // beyond the forecast horizon
		sprints = append(sprints, s)
	}
	return model.SprintDisplayName(&data.Team, sprints, s.ID)
}

// planSpan is the range of the Forecast PLAN of the sprint, nil without one.
func planSpan(fc *forecast.Forecast, id string) (low, high *float64) {
	for i := range fc.Entries {
		if fc.Entries[i].Sprint.ID != id {
			continue
		}
		if span, ok := fc.PlanSpanOf(i); ok {
			return &span.Low, &span.High
		}
	}
	return nil, nil
}

func column(data *storage.TeamData, fc *forecast.Forecast, stored model.Sprint) AbsenceColumn {
	// The column shows what the forecast counts: typed days plus the days of the planned periods.
	s := forecast.EffectiveSprint(data, stored)
	col := AbsenceColumn{
		ID:       s.ID,
		Name:     displayName(data, fc, s),
		Start:    s.Start.Format("2006-01-02"),
		End:      s.End.Add(-24 * time.Hour).Format("2006-01-02"), // the stored end is exclusive
		State:    absenceState(s),
		Workdays: len(calendar.TeamWorkdays(&data.Team, s.Start, s.End)),
		Past:     fc.Phase(s) == model.PhasePast,
	}
	for _, d := range allAbsences(s) {
		if d > 0 {
			col.Entries++
			col.Absent += d
		}
	}
	if e := fc.Entry(s.ID); e != nil {
		if e.Result.Input.Capacity != nil {
			col.Capacity = *e.Result.Input.Capacity
		}
		if !col.Past {
			col.Plan = e.Result.Plan
			col.PlanLow, col.PlanHigh = planSpan(fc, s.ID)
		}
	} else if s.AbsenceStatus() == model.AbsencesConfirmed {
		col.Capacity = capacity.Sprint(&data.Team, data.People, s, 0).Capacity
	} else {
		col.Capacity = capacity.WithOpenAbsences(&data.Team, data.People, s)
	}
	return col
}

func halves(v float64) float64 { return math.Round(v*2) / 2 }

// AbsenceGrid returns the absences of count sprints from the sprint from ("" = the running or
// next sprint).
func (a *API) AbsenceGrid(team, from string, count int) (AbsenceGrid, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return AbsenceGrid{}, err
	}
	return absenceGrid(data, from, count)
}

func absenceGrid(data *storage.TeamData, from string, count int) (AbsenceGrid, error) {
	fc, err := forecast.Build(data, today())
	if err != nil {
		return AbsenceGrid{}, err
	}
	sprints, err := sprintWindow(data, fc, from, count)
	if err != nil {
		return AbsenceGrid{}, err
	}
	grid := AbsenceGrid{Columns: []AbsenceColumn{}, Rows: []AbsenceRow{}}
	for _, s := range sprints {
		grid.Columns = append(grid.Columns, column(data, fc, s))
	}
	for _, p := range data.People {
		row := AbsenceRow{Person: p.ID, Name: p.Name, FTE: p.FTEOn(today()), Cells: []AbsenceCell{}}
		if row.FTE == 0 && len(p.Memberships) > 0 {
			row.FTE = p.Memberships[len(p.Memberships)-1].FTE
		}
		any := false
		for _, stored := range sprints {
			s := forecast.EffectiveSprint(data, stored)
			cell := AbsenceCell{Days: s.CellDays(p.ID), State: cellState(s, p.ID), FromPeriod: stored.CellState(p.ID) == model.AbsencesUnknown && s.CellDays(p.ID) > 0}
			if pc, ok := capacity.PersonOf(&data.Team, p, s, 0); ok {
				cell.Active = true
				cell.Max = float64(pc.Workdays - pc.Holidays)
			}
			any = any || cell.Active || cell.Days > 0
			row.Cells = append(row.Cells, cell)
		}
		if any {
			grid.Rows = append(grid.Rows, row)
		}
	}
	return grid, nil
}

// editSprint loads the team, applies change to the sprint (a copy of the stored one, or the
// generated one) and writes the sprint file. It returns the updated column.
func (a *API) editSprint(team, sprintID string, change func(data *storage.TeamData, s *model.Sprint) error) (AbsenceColumn, error) {
	editMu.Lock()
	defer editMu.Unlock()
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return AbsenceColumn{}, err
	}
	fc, err := forecast.Build(data, today())
	if err != nil {
		return AbsenceColumn{}, err
	}
	found, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return AbsenceColumn{}, err
	}
	if found == nil {
		return AbsenceColumn{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	}
	if fc.Phase(*found) == model.PhasePast {
		return AbsenceColumn{}, fmt.Errorf("%s", i18n.T("Sprint {id} is finished; its absences cannot be changed.", "id", sprintID))
	}
	s := found.Clone()
	if err := change(data, &s); err != nil {
		return AbsenceColumn{}, err
	}
	if _, err := repo.SaveSprint(team, &s); err != nil {
		return AbsenceColumn{}, err
	}
	data, err = repo.Load(team)
	if err != nil {
		return AbsenceColumn{}, err
	}
	if fc, err = forecast.Build(data, today()); err != nil {
		return AbsenceColumn{}, err
	}
	saved := data.SprintByID(sprintID)
	if saved == nil {
		saved = &s
	}
	return column(data, fc, *saved), nil
}

// SetAbsence sets the absence days of one person in one sprint (half days; 0 removes the
// entry). The days are cut to the person's working days in the sprint. In a frozen sprint the
// entry is confirmed, otherwise announced.
func (a *API) SetAbsence(team, sprintID, person string, days float64) (AbsenceColumn, error) {
	return a.editSprint(team, sprintID, func(data *storage.TeamData, s *model.Sprint) error {
		var p *model.Person
		for i := range data.People {
			if data.People[i].ID == person {
				p = &data.People[i]
			}
		}
		if p == nil {
			return fmt.Errorf("%s", i18n.T("Person {id} does not exist.", "id", person))
		}
		if days < 0 || math.IsNaN(days) {
			return fmt.Errorf("%s", i18n.T("Enter a number of days from 0 to the working days of the sprint."))
		}
		days = halves(days)
		if pc, ok := capacity.PersonOf(&data.Team, *p, *s, 0); ok {
			days = math.Min(days, float64(pc.Workdays-pc.Holidays))
		}
		state := model.AbsencesExpected
		if s.CellState(person) == model.AbsencesConfirmed {
			state = model.AbsencesConfirmed // typing into a confirmed cell keeps it confirmed
		}
		s.SetCell(person, days, state)
		return nil
	})
}

// SetAbsenceConfirmed locks or unlocks one cell: a confirmed cell is final for that person, an
// announced one is still a plan. In a frozen sprint all cells are confirmed and stay so.
func (a *API) SetAbsenceConfirmed(team, sprintID, person string, confirmed bool) (AbsenceColumn, error) {
	return a.editSprint(team, sprintID, func(data *storage.TeamData, s *model.Sprint) error {
		days := forecast.EffectiveSprint(data, *s).CellDays(person) // a day from a period can be locked too
		if days != 0 && s.CellDays(person) == 0 && s.AbsenceStatus() != model.AbsencesConfirmed {
			s.SetCell(person, days, model.AbsencesExpected)
		}
		if days == 0 {
			return nil // an empty cell has no state of its own
		}
		state := model.AbsencesExpected
		if confirmed {
			state = model.AbsencesConfirmed
		}
		s.SetCell(person, days, state)
		return nil
	})
}

// FreezeAbsences confirms the whole allocation of a sprint: all entries count as confirmed and
// every empty cell as 0 days, so "nobody is absent" needs no extra step.
func (a *API) FreezeAbsences(team, sprintID string) (AbsenceColumn, error) {
	return a.editSprint(team, sprintID, func(data *storage.TeamData, s *model.Sprint) error {
		*s = forecast.EffectiveSprint(data, *s) // the days of the planned periods are frozen with it
		s.Freeze()
		return nil
	})
}

// UnfreezeAbsences opens a frozen sprint again: the entries count as announced.
func (a *API) UnfreezeAbsences(team, sprintID string) (AbsenceColumn, error) {
	return a.editSprint(team, sprintID, func(_ *storage.TeamData, s *model.Sprint) error {
		s.Unfreeze()
		return nil
	})
}

// SprintPrepare returns the preview and the readiness list of a sprint.
func (a *API) SprintPrepare(team, sprintID string) (SprintPrepare, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return SprintPrepare{}, err
	}
	fc, err := forecast.Build(data, today())
	if err != nil {
		return SprintPrepare{}, err
	}
	s, err := fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return SprintPrepare{}, err
	}
	if s == nil {
		return SprintPrepare{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	}
	out := SprintPrepare{Sprint: column(data, fc, *s), Unit: settingsUnitAt(data, s.Start), Ready: []ReadyItem{}}
	// The preview compares with the sprint without any absence.
	bare := s.Clone()
	bare.Absences, bare.ExpectedAbsences = nil, nil
	bare.SetAbsencesConfirmed(true)
	out.CapacityBase = capacity.Sprint(&data.Team, data.People, bare, 0).Capacity

	abs := ReadyItem{Kind: "absences", State: ReadyOpen, Count: out.Sprint.Entries, Names: []string{}}
	if out.Sprint.State == AbsenceConfirmed {
		abs.State = ReadyDone
	}
	out.Ready = append(out.Ready, abs)

	if data.Team.Features.Tickets {
		ref := ReadyItem{Kind: "refinement", State: ReadyDone, Names: []string{}}
		for _, em := range data.Preplan.Earmarks {
			if em.Sprint != sprintID {
				continue
			}
			if t := data.TicketByKey(em.Ticket); t != nil && t.EstimateSource != model.EstimateRefined && t.EstimateSource != model.EstimateManual {
				ref.Names = append(ref.Names, t.Key)
			}
		}
		sort.Strings(ref.Names)
		if ref.Count = len(ref.Names); ref.Count > 0 {
			ref.State = ReadyOpen
		}
		out.Ready = append(out.Ready, ref)
	}

	pre := ReadyItem{Kind: "preplan", State: ReadyDone, Names: []string{}}
	for _, p := range data.Products {
		if !p.ActiveBetween(s.Start, s.End) {
			continue
		}
		v := s.Products[p.ID]
		if v.Preplanned == nil {
			pre.Names = append(pre.Names, p.Name)
		} else {
			out.Preplanned += *v.Preplanned
		}
	}
	if pre.Count = len(pre.Names); pre.Count > 0 {
		pre.State = ReadyOpen
	}
	out.Ready = append(out.Ready, pre)

	if e := fc.Entry(sprintID); e != nil && e.Result.Input.Capacity != nil && out.Sprint.Capacity > 0 && out.Sprint.Plan != nil {
		base := *out.Sprint.Plan / out.Sprint.Capacity * out.CapacityBase
		out.PlanBase = &base
	}
	return out, nil
}

// SprintOverview lists the finished sprints (the last past ones), the running one and the
// coming ones with capacity, Forecast PLAN, commitment and velocity, and the next step of each.
func (a *API) SprintOverview(team string, past int) (SprintOverview, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return SprintOverview{}, err
	}
	fc, err := forecast.Build(data, today())
	if err != nil {
		return SprintOverview{}, err
	}
	out := SprintOverview{Rows: []SprintRow{}, Reference: data.Team.Forecast.ReferenceCapacity, Unit: settingsUnitNow(data), CurrentIndex: -1}
	firstPast := 0
	if n := len(fc.History()); past >= 0 && n > past {
		firstPast = n - past
	}
	pastSeen := 0
	for i := range fc.Entries {
		e := &fc.Entries[i]
		s := e.Sprint
		phase := fc.Phase(s)
		isPast := phase == model.PhasePast
		if isPast {
			pastSeen++
			if pastSeen <= firstPast {
				continue
			}
		}
		row := SprintRow{Factor: forecastFactor(&data.Team, fc, s.ID),
			ID: s.ID, Name: displayName(data, fc, s), Start: s.Start.Format("2006-01-02"),
			End: s.End.Add(-24 * time.Hour).Format("2006-01-02"), Absences: absenceState(s),
			Capacity: e.Result.Input.Capacity, Commitment: e.Result.Commitment.Value, Velocity: e.Result.Velocity.Value,
		}
		if !isPast {
			row.Plan = e.Result.Plan
			row.PlanLow, row.PlanHigh = planSpan(fc, s.ID)
		}
		if row.Velocity != nil && row.Capacity != nil && *row.Capacity > 0 {
			rate := *row.Velocity / *row.Capacity
			row.Rate = &rate
			norm := rate * out.Reference
			row.Normalized = &norm
		}
		switch {
		case isPast:
			row.State = SprintPast
		case phase == model.PhaseRunning:
			row.State = SprintCurrent
		case s.Commitment != nil || s.Planning != nil || len(s.CommittedTickets) > 0:
			row.State = SprintPlanned
		default:
			row.State = SprintFuture
		}
		row.Next = nextStep(data, s, row.State)
		if out.CurrentIndex < 0 && !isPast {
			out.CurrentIndex = len(out.Rows)
		}
		out.Rows = append(out.Rows, row)
	}
	return out, nil
}

// nextStep is what the sprint needs next: the first open item of Prepare, then Plan.
func nextStep(data *storage.TeamData, s model.Sprint, state string) string {
	switch state {
	case SprintPast:
		return NextNone
	case SprintCurrent:
		return NextReview
	case SprintPlanned:
		return NextFrozen
	}
	if s.AbsenceStatus() != model.AbsencesConfirmed {
		return NextAbsences
	}
	for _, p := range data.Products {
		if data.Team.Features.Products && p.ActiveBetween(s.Start, s.End) && s.Products[p.ID].Preplanned == nil {
			return NextPreplan
		}
	}
	return NextPlan
}
