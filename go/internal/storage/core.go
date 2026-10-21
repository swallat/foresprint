package storage

import (
	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/model"
)

func orEmpty(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func copyDays(m map[string]float64) map[string]float64 {
	out := make(map[string]float64, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// CoreTeam gives the calculation packages the settings of a team they work with.
func CoreTeam(t model.Team) *coretypes.Team {
	return &coretypes.Team{
		Key:  t.Key,
		Name: t.Name,
		Unit: coretypes.Unit(t.Unit),
		Sprint: coretypes.SprintSettings{
			LengthDays: t.Sprint.LengthDays,
			Numbering:  coretypes.Numbering(t.Sprint.Numbering),
			FirstID:    orEmpty(t.Sprint.FirstID),
			FirstStart: t.Sprint.FirstStart,
		},
		Forecast: coretypes.ForecastSettings{
			ReferenceCapacity: t.Forecast.ReferenceCapacity,
			Window:            t.Forecast.Window,
			RoadmapShare:      t.Forecast.RoadmapShare,
			Rounding:          t.Forecast.Rounding,
			TrendMode:         coretypes.TrendMode(t.Forecast.TrendMode),
			Horizon:           t.Forecast.Horizon,
			ProductBasis:      coretypes.ProductBasis(t.Forecast.ProductBasis),
		},
		Capacity: coretypes.CapacitySettings{
			OverheadShare:  t.Capacity.OverheadShare,
			OverheadDays:   t.Capacity.OverheadDays,
			Country:        t.Capacity.Country,
			Region:         orEmpty(t.Capacity.Region),
			Workweek:       t.Capacity.Workweek,
			Rounding:       t.Capacity.Rounding,
			AbsenceHistory: t.Capacity.AbsenceHistory,
		},
	}
}

// CorePerson is the person as the calculation packages see them.
func CorePerson(p model.Person) coretypes.Person {
	out := coretypes.Person{
		ID:               p.ID,
		Name:             p.Name,
		Region:           orEmpty(p.Region),
		ProductionAccess: p.ProductionAccess,
		Country:          orEmpty(p.Country),
		Workweek:         orEmpty(p.Workweek),
	}
	for _, m := range p.Memberships {
		out.Memberships = append(out.Memberships, coretypes.Membership{Start: m.Start, End: m.End, FTE: m.FTE})
	}
	return out
}

// CoreSprint is the sprint as the calculation packages see it; nothing is shared with s.
func CoreSprint(s model.Sprint) coretypes.Sprint {
	out := coretypes.Sprint{
		ID:               s.ID,
		Start:            s.Start,
		End:              s.End,
		Absences:         copyDays(s.Absences),
		Capacity:         s.Capacity,
		Commitment:       s.Commitment,
		Velocity:         s.Velocity,
		ScopeCreep:       s.ScopeCreep,
		ForecastPlan:     s.ForecastPlan,
		ExpectedAbsences: copyDays(s.ExpectedAbsences),
	}
	if s.Planning != nil {
		out.Planning = &coretypes.Planning{
			Carryover:   s.Planning.Carryover,
			Backlog:     s.Planning.Backlog,
			Corrections: append([]float64(nil), s.Planning.Corrections...),
		}
	}
	if s.AbsenceState != nil {
		state := coretypes.AbsenceState(*s.AbsenceState)
		out.AbsenceState = &state
	}
	return out
}

// Core returns the part of the team's data that the forecast, capacity and analysis packages
// calculate with. The result shares nothing mutable with d.
func (d *TeamData) Core() *coretypes.TeamData {
	out := &coretypes.TeamData{Team: CoreTeam(d.Team)}
	for _, p := range d.People {
		out.People = append(out.People, CorePerson(p))
	}
	for _, s := range d.Sprints {
		out.Sprints = append(out.Sprints, CoreSprint(s))
	}
	return out
}
