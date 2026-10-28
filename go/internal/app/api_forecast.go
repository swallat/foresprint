package app

import (
	"errors"
	"slices"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/storage"
)

// simulationRuns and simulationSeed make "when is it done?" repeatable: the same data gives the
// same answer.
const (
	simulationRuns = 10000
	simulationSeed = 42
	// forecastEarliest is the probability from which a sprint counts as the earliest possible.
	forecastEarliest = 0.15
)

func (a *API) forecastOf(team string) (*storage.TeamData, *forecast.Forecast, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, nil, err
	}
	fc, err := forecast.Build(data, todayOf(data))
	if err != nil {
		return nil, nil, err
	}
	return data, fc, nil
}

func forecastRow(fc *forecast.Forecast, e *forecast.TimelineEntry, band bool) ForecastRow {
	r := e.Result
	s := e.Sprint
	state := "future"
	switch fc.Phase(s) {
	case model.PhasePast:
		state = "past"
	case model.PhaseRunning:
		state = "current"
	}
	out := ForecastRow{
		ID:                 s.ID,
		Start:              s.Start.Format("2006-01-02"),
		End:                s.End.Format("2006-01-02"),
		State:              state,
		Recorded:           e.Recorded,
		Capacity:           r.Capacity.Value,
		Commitment:         r.Commitment.Value,
		Velocity:           r.Velocity.Value,
		NormalizedVelocity: r.NormalizedVelocity.Value,
		Average:            r.NormalizedVelocity.Average,
		Trend:              r.NormalizedVelocity.Trend,
		Fulfillment:        r.Fulfillment.Value,
		Plan:               r.Plan,
		Plannable:          r.Roadmap,
		Small:              r.SmallStuff,
	}
	if state != "past" {
		out.Capacity = r.PlanCapacity
		if r.PlanCapacitySource != nil {
			out.CapacitySource = string(*r.PlanCapacitySource)
			out.Unsure = r.PlanCapacitySource.Unsure()
		}
	} else if r.Input.CapacitySource != nil {
		out.CapacitySource = string(*r.Input.CapacitySource)
	}
	if r.PlanSource != nil {
		switch *r.PlanSource {
		case engine.PlanActual:
			out.PlanSource = "actual"
		case engine.PlanStart:
			out.PlanSource = "start"
		default:
			out.PlanSource = "projection"
		}
	}
	if state != "past" && r.Plan != nil {
		sprints := make([]model.Sprint, len(fc.Entries))
		for i := range fc.Entries {
			sprints[i] = fc.Entries[i].Sprint
		}
		carry := planning.CarryInto(sprints, s.ID, "")
		split := planning.SplitPlan(*r.Plan, carry.Rest, fc.Data.Team.Forecast.RoadmapShare, fc.Data.Team.Forecast.Rounding)
		out.Plannable, out.Small = &split.Plannable, &split.SmallStuff
		out.CarryIn, out.CarryAssumed, out.Overbooked = carry.Rest, carry.Assumed, split.Overbooked
	}
	if band {
		if b, ok := analysis.BandOf(fc, e); ok {
			out.Low, out.High = &b.Low, &b.High
		}
	}
	return out
}

// Forecast returns the history and the coming sprints of a team with the plan, the range and
// the settings the calculation used.
func (a *API) Forecast(team string) (ForecastView, error) {
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return ForecastView{}, err
	}
	s := data.Team.Forecast
	v := ForecastView{
		Team:              team,
		Today:             fc.Today.Format("2006-01-02"),
		ReferenceCapacity: s.ReferenceCapacity,
		Window:            s.Window,
		RoadmapShare:      s.RoadmapShare,
		TrendMode:         string(s.TrendMode),
		Horizon:           s.Horizon,
		Rounding:          s.Rounding,
		Products:          forecastProductCount(data),
		Samples:           analysis.SampleCount(fc),
		FewSamples:        analysis.FewSamples(fc),
		Past:              []ForecastRow{},
		Upcoming:          []ForecastRow{},
	}
	for _, e := range fc.History() {
		v.Past = append(v.Past, forecastRow(fc, e, false))
	}
	for _, e := range fc.Upcoming() {
		v.Upcoming = append(v.Upcoming, forecastRow(fc, e, true))
	}
	v.Running, v.Next = forecastRunning(fc)
	if cur := fc.Current(); cur != nil {
		v.RunningCommitment = cur.Sprint.Commitment
	}
	for _, r := range v.Upcoming {
		if r.Trend != nil && s.ReferenceCapacity > 0 {
			rate := *r.Trend / s.ReferenceCapacity
			v.Rate = &rate
			if f := forecastFactor(&data.Team, fc, r.ID); f != nil {
				v.Rate, v.RateFixed = f, true
			}
			break
		}
	}
	return v, nil
}

// forecastRunning is the running sprint and the one after it; "" if none runs or none follows.
func forecastRunning(fc *forecast.Forecast) (running, next string) {
	cur := fc.Current()
	if cur == nil {
		return "", ""
	}
	for i := range fc.Entries {
		if fc.Entries[i].Sprint.ID == cur.Sprint.ID && i+1 < len(fc.Entries) {
			return cur.Sprint.ID, fc.Entries[i+1].Sprint.ID
		}
	}
	return cur.Sprint.ID, ""
}

// forecastAssumed builds the forecast again under the expectation for the running sprint; without
// one, or without a running sprint, it is the forecast itself.
func forecastAssumed(data *storage.TeamData, fc *forecast.Forecast, as ForecastAssumption) (*forecast.Forecast, error) {
	running, _ := forecastRunning(fc)
	if as.ExpectedVelocity == nil || running == "" {
		return fc, nil
	}
	return forecast.WhatIf(data, fc.Today, running, model.Prognosis{ExpectedDone: as.ExpectedVelocity})
}

func forecastCheck(as ForecastAssumption) error {
	if as.ExtraAbsenceDays < 0 || as.FocusPercent < 0 || (as.ExpectedVelocity != nil && *as.ExpectedVelocity < 0) {
		return errors.New(i18n.T("Absence days, focus and velocity must not be negative."))
	}
	return nil
}

// forecastRows calculates the coming sprints under the assumption: the running sprint ends with
// the expected velocity, fewer person days (ExtraAbsenceDays per sprint, in addition to the known
// absences) and a changed share of the capacity that turns into points (FocusPercent, 100 = as
// measured). Only the chosen sprint, or all coming ones if none is chosen.
func forecastRows(data *storage.TeamData, fc, fc2 *forecast.Forecast, as ForecastAssumption) []WhatIfRow {
	ref := data.Team.Forecast.ReferenceCapacity
	out := []WhatIfRow{}
	for _, e := range fc.Upcoming() {
		if as.Sprint != "" && e.Sprint.ID != as.Sprint {
			continue
		}
		r := e.Result
		// the running sprint with an expected velocity has a result of its own and no projection
		// any more; its row keeps the trend it had
		trend := r.NormalizedVelocity.Trend
		if e2 := fc2.Entry(e.Sprint.ID); e2 != nil && e2.Result.NormalizedVelocity.Trend != nil {
			trend = e2.Result.NormalizedVelocity.Trend
		}
		fromStart := r.PlanSource != nil && *r.PlanSource == engine.PlanStart
		if r.Plan == nil || r.PlanCapacity == nil || (trend == nil && !fromStart) {
			continue
		}
		capacity := max(0, *r.PlanCapacity-as.ExtraAbsenceDays)
		rate := 0.0
		if fromStart {
			rate = data.Team.Forecast.StartRate // no history yet: the start rate is the rate
		} else {
			rate = *trend / ref
		}
		value := engine.RoundDown(rate*capacity*as.FocusPercent/100, data.Team.Forecast.Rounding)
		out = append(out, WhatIfRow{ID: e.Sprint.ID, Capacity: capacity, Forecast: value, Base: *r.Plan, Delta: value - *r.Plan})
	}
	return out
}

// ForecastWhatIf calculates the coming sprints again under an assumption. Nothing is saved.
func (a *API) ForecastWhatIf(team string, as ForecastAssumption) ([]WhatIfRow, error) {
	if err := forecastCheck(as); err != nil {
		return nil, err
	}
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return nil, err
	}
	fc2, err := forecastAssumed(data, fc, as)
	if err != nil {
		return nil, err
	}
	return forecastRows(data, fc, fc2, as), nil
}

// ForecastSaveWhatIf keeps the assumption for the sprint after the running one as a prognosis
// ("Prognose") with the label: the running sprint's file holds it, the review compares it with
// the result. Only that one sprint can be saved, the one the planning uses.
func (a *API) ForecastSaveWhatIf(team string, as ForecastAssumption) error {
	if err := forecastCheck(as); err != nil {
		return err
	}
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return err
	}
	running, next := forecastRunning(fc)
	if running == "" || next == "" || as.Sprint != next {
		return errors.New(i18n.T("Only the sprint after the running one can be saved as a prognosis."))
	}
	fc2, err := forecastAssumed(data, fc, as)
	if err != nil {
		return err
	}
	rows := forecastRows(data, fc, fc2, as)
	if len(rows) != 1 {
		return errors.New(i18n.T("There is no forecast for {id} yet.", "id", next))
	}
	cur := fc.Entry(running).Sprint.Clone()
	if as.ExpectedVelocity == nil && cur.Commitment == nil {
		return errors.New(i18n.T("Enter the velocity you expect for {id} to save the prognosis.", "id", running))
	}
	// The expectation is stored the way the plan page does: commitment, and what is not done or
	// gained on top. A velocity that is not entered means the commitment is met.
	expected := floatOr(as.ExpectedVelocity, floatOr(cur.Commitment, 0))
	commitment := floatOr(cur.Commitment, expected)
	label := as.Label
	if label == "" {
		label = forecastFreeLabel(cur.Prognoses, next)
	}
	n := nowOf(data)
	plan := rows[0].Forecast
	p := model.Prognosis{At: time.Date(n.Year(), n.Month(), n.Day(), n.Hour(), n.Minute(), n.Second(), 0, time.UTC),
		Target: &next, Plan: &plan, Label: &label, Commitment: &commitment, ExpectedDone: &expected}
	if as.FocusPercent != 100 {
		p.FocusPercent = model.Ptr(as.FocusPercent)
	}
	if as.ExtraAbsenceDays > 0 {
		p.ExtraAbsenceDays = model.Ptr(as.ExtraAbsenceDays)
	}
	if expected < commitment {
		p.NotDone = model.Ptr(commitment - expected)
	} else if expected > commitment {
		p.AdditionalDone = model.Ptr(expected - commitment)
	}
	// what the newest prognosis says about the carry-over stays: readers take the newest one
	if old := newestPrognosis(&cur, next, ""); old != nil {
		p.Carry = slices.Clone(old.Carry)
		p.RestNext = old.RestNext
		p.Preplanned = old.Preplanned
	}
	kept := make([]model.Prognosis, 0, len(cur.Prognoses)+1)
	for _, old := range cur.Prognoses {
		if str(old.Target) != next || labelOf(old) != label {
			kept = append(kept, old)
		}
	}
	kept = append(kept, p)
	cur.Prognoses = kept
	_, err = storage.NewRepository(a.DataDir()).SaveSprint(team, &cur)
	storage.ClearTeamCache()
	return err
}

// forecastOpenScope is the open scope of a project in the unit of the team: the sizes of its
// open tickets, or, without any, the scope entered by hand; nil if neither exists.
func forecastOpenScope(data *storage.TeamData, p model.Project) (*float64, int) {
	sum, open := 0.0, 0
	for _, t := range data.Tickets {
		if t.Done || effectiveProject(data, t) != p.ID {
			continue
		}
		open++
		size := t.Estimate
		if data.Team.Tracker.PlanningUses == model.UsesRemaining && t.Remaining != nil {
			size = t.Remaining
		}
		if size != nil {
			sum += *size
		}
	}
	if sum > 0 {
		return &sum, open
	}
	return p.OpenScope, open
}

// ForecastWhenProjects lists the open projects for the analysis "When is it done?" with their
// open scope, so that the page can fill the form.
func (a *API) ForecastWhenProjects(team string) ([]WhenProject, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, err
	}
	out := []WhenProject{}
	if !data.Team.Features.Tickets && !data.Team.Features.Projects {
		return out, nil
	}
	for _, p := range data.Projects {
		if p.Closed() {
			continue
		}
		scope, open := forecastOpenScope(data, p)
		end := p.End
		if end == nil {
			end = p.Target
		}
		out = append(out, WhenProject{ID: p.ID, Name: p.Name, End: day(end), OpenScope: scope, Open: open})
	}
	return out, nil
}

// ForecastWhenDone simulates in which coming sprint a remaining quantity of points is done.
// sharePercent is the share of the forecast that is available for it (0 to 100). With a project
// the answer also says whether the project end holds: "ok" if the work is done by then in 85 %
// of the runs, "warn" if in half of them, otherwise "bad"; "none" without a project end.
func (a *API) ForecastWhenDone(team string, remaining, sharePercent float64, project string) (WhenDoneView, error) {
	if remaining < 0 || sharePercent < 0 || sharePercent > 100 {
		return WhenDoneView{}, errors.New(i18n.T("Remaining work must not be negative and the share must be between 0 and 100."))
	}
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return WhenDoneView{}, err
	}
	c, err := analysis.Simulate(data, todayOf(data), remaining, sharePercent/100, analysis.DefaultMaxSprints, simulationRuns, simulationSeed)
	if err != nil {
		return WhenDoneView{}, err
	}
	if c == nil {
		return WhenDoneView{Remaining: remaining, Share: sharePercent, Sprints: []string{}, Starts: []string{}, Ends: []string{}, Cumulative: []float64{}, TrendCapacity: []string{}, Light: "none"}, nil
	}
	v := WhenDoneView{
		Remaining: c.Remaining, Share: sharePercent, Runs: c.Runs, Samples: c.Samples,
		Sprints: c.Sprints, Starts: []string{}, Ends: []string{}, Cumulative: c.Cumulative, PerSprint: c.PerSprint,
		TrendCapacity: c.TrendCapacitySprints, Available: true, Light: "none",
	}
	if c.P50 != nil {
		v.P50 = *c.P50
	}
	if c.P85 != nil {
		v.P85 = *c.P85
	}
	for i, p := range c.Cumulative {
		if p >= forecastEarliest {
			v.Earliest = c.Sprints[i]
			break
		}
	}
	fc, err := analysis.HorizonForecast(data, todayOf(data), analysis.DefaultMaxSprints)
	if err != nil {
		return WhenDoneView{}, err
	}
	first, last := map[string]time.Time{}, map[string]time.Time{}
	for _, e := range fc.Entries {
		first[e.Sprint.ID] = e.Sprint.Start
		last[e.Sprint.ID] = e.Sprint.End.AddDate(0, 0, -1)
	}
	for _, id := range c.Sprints {
		s, e := first[id], last[id]
		v.Starts = append(v.Starts, day(&s))
		v.Ends = append(v.Ends, day(&e))
	}
	if project == "" {
		return v, nil
	}
	for _, p := range data.Projects {
		if p.ID != project {
			continue
		}
		v.ProjectName = p.Name
		end := p.End
		if end == nil {
			end = p.Target
		}
		if end == nil {
			break
		}
		v.ProjectEnd = day(end)
		holds := func(id string) bool {
			l, ok := last[id]
			return id != "" && ok && !l.After(*end)
		}
		switch {
		case holds(v.P85):
			v.Light = "ok"
		case holds(v.P50):
			v.Light = "warn"
		default:
			v.Light = "bad"
		}
	}
	return v, nil
}

// productCount is the number of products the team works with; 0 if the feature is off.
func forecastProductCount(data *storage.TeamData) int {
	if !data.Team.Features.Products {
		return 0
	}
	return len(data.Products)
}

// forecastFreeLabel is the first letter that no prognosis for the target carries yet, so that
// saving never replaces an assumption of the plan page.
func forecastFreeLabel(list []model.Prognosis, target string) string {
	used := map[string]bool{}
	for _, p := range list {
		if str(p.Target) == target {
			used[labelOf(p)] = true
		}
	}
	for c := 'A'; c <= 'Z'; c++ {
		if !used[string(c)] {
			return string(c)
		}
	}
	return "Z"
}

// forecastFactor is the fixed points-per-PD factor that applies to a sprint (decision 19), nil
// for a sprint in person days or without a fixed factor: the measured rate is shown then.
func forecastFactor(team *model.Team, fc *forecast.Forecast, id string) *float64 {
	order := make([]string, len(fc.Entries))
	for i, e := range fc.Entries {
		order[i] = e.Sprint.ID
	}
	if planning.UnitAt(team, order, id) != model.UnitSP {
		return nil
	}
	if f := planning.FactorAt(team, order, id); f != nil && *f > 0 {
		return f
	}
	return nil
}
