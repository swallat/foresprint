package app

import (
	"errors"
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
	fc, err := forecast.Build(data, today())
	if err != nil {
		return nil, nil, err
	}
	return data, fc, nil
}

func today() time.Time {
	y, m, d := time.Now().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

func forecastRow(fc *forecast.Forecast, e *forecast.TimelineEntry, band bool) ForecastRow {
	r := e.Result
	s := e.Sprint
	state := "future"
	switch {
	case !s.End.After(fc.Today):
		state = "past"
	case !s.Start.After(fc.Today):
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
		out.PlanSource = "projection"
		if *r.PlanSource == engine.PlanActual {
			out.PlanSource = "actual"
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
	for _, r := range v.Upcoming {
		if r.Trend != nil && s.ReferenceCapacity > 0 {
			rate := *r.Trend / s.ReferenceCapacity
			v.Rate = &rate
			break
		}
	}
	return v, nil
}

// ForecastWhatIf calculates the coming sprints again with fewer person days (extraAbsenceDays
// per sprint, in addition to the known absences) and a changed share of the capacity that turns
// into points (focusPercent, 100 = as measured). Nothing is saved.
func (a *API) ForecastWhatIf(team string, extraAbsenceDays, focusPercent float64) ([]WhatIfRow, error) {
	if extraAbsenceDays < 0 || focusPercent < 0 {
		return nil, errors.New(i18n.T("Absence days and focus must not be negative."))
	}
	data, fc, err := a.forecastOf(team)
	if err != nil {
		return nil, err
	}
	s := data.Team.Forecast
	out := []WhatIfRow{}
	for _, e := range fc.Upcoming() {
		r := e.Result
		if r.Plan == nil || r.PlanCapacity == nil || r.NormalizedVelocity.Trend == nil {
			continue
		}
		capacity := max(0, *r.PlanCapacity-extraAbsenceDays)
		forecastValue := engine.RoundDown(*r.NormalizedVelocity.Trend/s.ReferenceCapacity*capacity*focusPercent/100, s.Rounding)
		out = append(out, WhatIfRow{ID: e.Sprint.ID, Capacity: capacity, Forecast: forecastValue, Base: *r.Plan, Delta: forecastValue - *r.Plan})
	}
	return out, nil
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
	c, err := analysis.Simulate(data, today(), remaining, sharePercent/100, analysis.DefaultMaxSprints, simulationRuns, simulationSeed)
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
	fc, err := analysis.HorizonForecast(data, today(), analysis.DefaultMaxSprints)
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
