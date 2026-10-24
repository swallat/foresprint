package app

import (
	"errors"
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func (a *API) loadRepoTeam(key string) (*storage.Repository, *storage.TeamData, error) {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(key)
	return repo, data, err
}

func round6(v float64) float64 { return math.Round(v*1e6) / 1e6 }

// sprintStart is the start of a recorded sprint or of one the calendar generates up to a year
// ahead.
func sprintStart(data *storage.TeamData, id string) (time.Time, bool) {
	s, err := forecast.FindSprint(data, id, 52)
	if err != nil || s == nil {
		return time.Time{}, false
	}
	return s.Start, true
}

// effectiveUnit is the unit valid today and the sprint it applies from ("" = from the start):
// the latest switch whose sprint has begun.
func effectiveUnit(data *storage.TeamData, now time.Time) (model.Unit, string) {
	unit, from := data.Team.Unit, ""
	var latest time.Time
	for _, c := range data.Team.Estimation.Changes {
		if start, ok := sprintStart(data, c.From); ok && !start.After(now) && !start.Before(latest) {
			unit, from, latest = c.Unit, c.From, start
		}
	}
	return unit, from
}

// TeamSettings returns the settings of Settings > Team.
func (a *API) TeamSettings(team string) (TeamSettings, error) {
	_, data, err := a.loadRepoTeam(team)
	if err != nil {
		return TeamSettings{}, err
	}
	t := data.Team
	unit, from := effectiveUnit(data, time.Now())
	basis := "plan"
	if t.Forecast.ProductBasis == model.BasisRoadmap {
		basis = "share"
	}
	out := TeamSettings{
		Name:     t.Name,
		Unit:     string(unit),
		UnitFrom: from,
		Factor:   t.Estimation.Factor,
		Forecast: ForecastSettings{
			Window:            t.Forecast.Window,
			Trend:             string(t.Forecast.TrendMode),
			ReferenceCapacity: t.Forecast.ReferenceCapacity,
			PlannableShare:    round6(t.Forecast.RoadmapShare * 100),
			Rounding:          t.Forecast.Rounding,
			Horizon:           t.Forecast.Horizon,
			Basis:             basis,
		},
		LengthDays:    t.Sprint.LengthDays,
		Products:      t.Features.Products,
		PO:            t.Features.PO,
		Production:    t.Features.Production,
		ProductionCap: t.Capacity.ProductionCap,
		Projects:      t.Features.Projects,
		ProForma:      append([]string{}, t.Sprint.ProForma...),
		UnitChanges:   []UnitChangeInfo{},
		Country:       t.Capacity.Country,
	}
	if t.Capacity.Region != nil {
		out.Region = *t.Capacity.Region
	}
	for _, c := range t.Estimation.Changes {
		out.UnitChanges = append(out.UnitChanges, UnitChangeInfo{From: c.From, Unit: string(c.Unit)})
	}
	return out, nil
}

func bad(text string, kv ...any) error { return errors.New(i18n.T(text, kv...)) }

// SaveTeamSettings checks and writes the settings to team.yaml. Whether the data is shared is
// the business of Save in the top bar. The unit applies from UnitFrom on if it differs from the
// unit valid now; the first sprint needs no sprint.
func (a *API) SaveTeamSettings(team string, in TeamSettings) error {
	repo, data, err := a.loadRepoTeam(team)
	if err != nil {
		return err
	}
	t := data.Team
	f := in.Forecast
	switch {
	case f.Window < 1 || f.Window > 52:
		return bad("The window must be between 1 and 52 sprints.")
	case f.Trend != string(model.TrendFlat) && f.Trend != string(model.TrendLinear) && f.Trend != string(model.TrendClassic):
		return bad("Unknown trend: {value}", "value", f.Trend)
	case !(f.ReferenceCapacity > 0) || math.IsInf(f.ReferenceCapacity, 0):
		return bad("The reference capacity must be greater than 0.")
	case !(f.PlannableShare >= 0 && f.PlannableShare <= 100):
		return bad("The plannable share must be between 0 and 100 percent.")
	case f.Rounding < 0 || f.Rounding > 3:
		return bad("Rounding means 0 to 3 decimals.")
	case f.Horizon < 1 || f.Horizon > 26:
		return bad("The horizon must be between 1 and 26 sprints.")
	case f.Basis != "plan" && f.Basis != "share":
		return bad("Unknown budget basis: {value}", "value", f.Basis)
	case in.LengthDays < 1 || in.LengthDays > 60:
		return bad("The sprint length must be between 1 and 60 working days.")
	case !(in.ProductionCap >= 0 && in.ProductionCap <= 100):
		return bad("The cap of the production time must be between 0 and 100 percent.")
	case in.Factor != nil && !(*in.Factor > 0):
		return bad("The factor must be greater than 0.")
	case in.Unit != string(model.UnitSP) && in.Unit != string(model.UnitPT):
		return bad("Unknown estimation unit: {value}", "value", in.Unit)
	}
	proForma, err := cleanNames(in.ProForma)
	if err != nil {
		return err
	}
	if !knownCountry(in.Country) {
		return bad("Unknown country: {country}", "country", in.Country)
	}
	if in.Region != "" && !slices.Contains(holidays.Subdivisions(in.Country), in.Region) {
		return bad("Unknown region: {region}", "region", in.Region)
	}

	t.Forecast.Window = f.Window
	t.Forecast.TrendMode = model.TrendMode(f.Trend)
	t.Forecast.ReferenceCapacity = f.ReferenceCapacity
	t.Forecast.RoadmapShare = round6(f.PlannableShare / 100)
	t.Forecast.Rounding = f.Rounding
	t.Forecast.Horizon = f.Horizon
	t.Forecast.ProductBasis = model.BasisPlan
	if f.Basis == "share" {
		t.Forecast.ProductBasis = model.BasisRoadmap
	}
	t.Sprint.LengthDays = in.LengthDays
	t.Sprint.ProForma = proForma
	t.Features.Products, t.Features.PO = in.Products, in.PO
	t.Features.Production, t.Features.Projects = in.Production, in.Projects
	t.Features.Explicit = true
	t.Capacity.ProductionCap = round6(in.ProductionCap)
	t.Capacity.Country = in.Country
	t.Capacity.Region = nil
	if in.Region != "" {
		r := in.Region
		t.Capacity.Region = &r
	}
	t.Estimation.Factor = in.Factor

	if current, _ := effectiveUnit(data, time.Now()); string(current) != in.Unit {
		unit := model.Unit(in.Unit)
		switch {
		case in.UnitFrom != "":
			if _, ok := sprintStart(data, in.UnitFrom); !ok {
				return bad("The sprint {id} is not known.", "id", in.UnitFrom)
			}
			t.Estimation.Changes = append(withoutChange(t.Estimation.Changes, in.UnitFrom), model.UnitChange{From: in.UnitFrom, Unit: unit})
			sort.SliceStable(t.Estimation.Changes, func(i, j int) bool {
				a, _ := sprintStart(data, t.Estimation.Changes[i].From)
				b, _ := sprintStart(data, t.Estimation.Changes[j].From)
				return a.Before(b)
			})
		case len(data.Sprints) == 0 && len(t.Estimation.Changes) == 0:
			t.Unit = unit // no sprint recorded yet: valid from the start
		default:
			return bad("Choose the sprint the new unit applies from.")
		}
	}
	if _, err := repo.SaveTeam(t); err != nil {
		return err
	}
	storage.ClearTeamCache()
	return nil
}

func withoutChange(list []model.UnitChange, from string) []model.UnitChange {
	out := make([]model.UnitChange, 0, len(list)+1)
	for _, c := range list {
		if c.From != from {
			out = append(out, c)
		}
	}
	return out
}

// cleanNames trims the names, drops empty ones and refuses duplicates (case-insensitive).
func cleanNames(names []string) ([]string, error) {
	var out []string
	seen := map[string]bool{}
	for _, n := range names {
		n = strings.TrimSpace(n)
		if n == "" {
			continue
		}
		if seen[strings.ToLower(n)] {
			return nil, bad("{name} is listed twice.", "name", n)
		}
		seen[strings.ToLower(n)] = true
		out = append(out, n)
	}
	return out, nil
}

// TeamFeatures returns the optional parts the team uses; the window hides the rest.
func (a *API) TeamFeatures(team string) (Features, error) {
	_, data, err := a.loadRepoTeam(team)
	if err != nil {
		return Features{}, err
	}
	f := data.Team.Features
	return Features{
		Source:     string(data.Team.Source()),
		Products:   f.Products,
		PO:         f.PO,
		Production: f.Production,
		Projects:   f.Projects || f.Tickets,
	}, nil
}
