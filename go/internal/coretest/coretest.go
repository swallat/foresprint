// Package coretest loads the team folders of the golden cases into the types of the calculation
// packages, for their tests. It reads only what the calculation needs and trusts the files (the
// complete reader with validation is the storage of the port).
package coretest

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/golden"
)

type yamlDate string

func (d *yamlDate) UnmarshalYAML(n *yaml.Node) error {
	*d = yamlDate(n.Value)
	return nil
}

func (d yamlDate) date(tb testing.TB) *time.Time {
	tb.Helper()
	if d == "" || d == "null" || d == "~" {
		return nil
	}
	t, err := coretypes.ParseDate(string(d))
	if err != nil {
		tb.Fatalf("date %q: %v", d, err)
	}
	return &t
}

type teamFile struct {
	Name   string `yaml:"name"`
	Unit   string `yaml:"unit"`
	Sprint struct {
		LengthDays *int   `yaml:"length_days"`
		Numbering  string `yaml:"numbering"`
		First      struct {
			ID    *string  `yaml:"id"`
			Start yamlDate `yaml:"start"`
		} `yaml:"first"`
	} `yaml:"sprint"`
	Forecast struct {
		ReferenceCapacity *float64 `yaml:"reference_capacity"`
		Window            *int     `yaml:"window"`
		RoadmapShare      *float64 `yaml:"roadmap_share"`
		Rounding          *int     `yaml:"rounding"`
		TrendMode         string   `yaml:"trend_mode"`
		Horizon           *int     `yaml:"horizon"`
		ProductBasis      string   `yaml:"product_basis"`
	} `yaml:"forecast"`
	Capacity struct {
		OverheadShare  *float64 `yaml:"overhead_share"`
		OverheadDays   *float64 `yaml:"overhead_days"`
		Country        string   `yaml:"country"`
		Region         string   `yaml:"region"`
		Workweek       string   `yaml:"workweek"`
		Rounding       *int     `yaml:"rounding"`
		AbsenceHistory *int     `yaml:"absence_history"`
	} `yaml:"capacity"`
}

type peopleFile struct {
	People []struct {
		ID               string `yaml:"id"`
		Name             string `yaml:"name"`
		Region           string `yaml:"region"`
		Country          string `yaml:"country"`
		Workweek         string `yaml:"workweek"`
		ProductionAccess bool   `yaml:"production_access"`
		Memberships      []struct {
			From yamlDate `yaml:"from"`
			To   yamlDate `yaml:"to"`
			FTE  *float64 `yaml:"fte"`
		} `yaml:"memberships"`
	} `yaml:"people"`
}

type sprintFile struct {
	ID               string             `yaml:"id"`
	Start            yamlDate           `yaml:"start"`
	End              yamlDate           `yaml:"end"`
	Absences         map[string]float64 `yaml:"absences"`
	Capacity         *float64           `yaml:"capacity"`
	ForecastIst      *float64           `yaml:"forecast_ist"`
	Velocity         *float64           `yaml:"velocity"`
	ScopeCreep       *float64           `yaml:"scope_creep"`
	ForecastPlan     *float64           `yaml:"forecast_plan"`
	AbsenceState     string             `yaml:"absence_state"`
	AbsencesConfirm  bool               `yaml:"absences_confirmed"`
	ExpectedAbsences map[string]float64 `yaml:"expected_absences"`
	Planning         *struct {
		Carryover   float64   `yaml:"carryover"`
		Backlog     float64   `yaml:"backlog"`
		Corrections []float64 `yaml:"corrections"`
	} `yaml:"planning"`
}

func readYAML(tb testing.TB, path string, out any) bool {
	tb.Helper()
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return false
	}
	if err != nil {
		tb.Fatal(err)
	}
	if err := yaml.Unmarshal(raw, out); err != nil {
		tb.Fatalf("%s: %v", path, err)
	}
	return true
}

func orInt(p *int, def int) int {
	if p == nil {
		return def
	}
	return *p
}

func orFloat(p *float64, def float64) float64 {
	if p == nil {
		return def
	}
	return *p
}

func orStr(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// Load reads the team folder of a golden case.
func Load(tb testing.TB, c golden.Case) *coretypes.TeamData {
	tb.Helper()
	dir := c.TeamDir(tb)
	var tf teamFile
	if !readYAML(tb, filepath.Join(dir, "team.yaml"), &tf) {
		tb.Fatalf("%s has no team.yaml", dir)
	}
	team := coretypes.NewTeam(c.Team, orStr(tf.Name, c.Team))
	team.Unit = coretypes.Unit(orStr(tf.Unit, "PT"))
	team.Sprint.LengthDays = orInt(tf.Sprint.LengthDays, 14)
	team.Sprint.Numbering = coretypes.Numbering(orStr(tf.Sprint.Numbering, "yearly"))
	if tf.Sprint.First.ID != nil {
		team.Sprint.FirstID = *tf.Sprint.First.ID
	}
	team.Sprint.FirstStart = tf.Sprint.First.Start.date(tb)
	f := &team.Forecast
	f.ReferenceCapacity = orFloat(tf.Forecast.ReferenceCapacity, 67)
	f.Window = orInt(tf.Forecast.Window, 5)
	f.RoadmapShare = orFloat(tf.Forecast.RoadmapShare, 0.8)
	f.Rounding = orInt(tf.Forecast.Rounding, 1)
	mode, ok := coretypes.ParseTrendMode(orStr(tf.Forecast.TrendMode, "flat"))
	if !ok {
		tb.Fatalf("trend mode %q", tf.Forecast.TrendMode)
	}
	f.TrendMode = mode
	f.Horizon = orInt(tf.Forecast.Horizon, 3)
	f.ProductBasis = coretypes.ProductBasis(orStr(tf.Forecast.ProductBasis, "plan"))
	cs := &team.Capacity
	cs.OverheadShare = orFloat(tf.Capacity.OverheadShare, 0)
	cs.OverheadDays = orFloat(tf.Capacity.OverheadDays, 0)
	cs.Country = strings.ToUpper(orStr(tf.Capacity.Country, "DE"))
	cs.Region = tf.Capacity.Region
	cs.Workweek = orStr(tf.Capacity.Workweek, "auto")
	cs.Rounding = orInt(tf.Capacity.Rounding, 1)
	cs.AbsenceHistory = orInt(tf.Capacity.AbsenceHistory, 4)

	data := &coretypes.TeamData{Team: team}
	var pf peopleFile
	readYAML(tb, filepath.Join(dir, "people.yaml"), &pf)
	for _, p := range pf.People {
		person := coretypes.Person{
			ID: p.ID, Name: orStr(p.Name, p.ID), Region: p.Region, Country: strings.ToUpper(p.Country),
			Workweek: p.Workweek, ProductionAccess: p.ProductionAccess,
		}
		for _, m := range p.Memberships {
			start := m.From.date(tb)
			if start == nil {
				tb.Fatalf("person %s: membership without a start", p.ID)
				return nil
			}
			person.Memberships = append(person.Memberships, coretypes.Membership{
				Start: *start, End: m.To.date(tb), FTE: orFloat(m.FTE, 1),
			})
		}
		data.People = append(data.People, person)
	}

	files, err := filepath.Glob(filepath.Join(dir, "sprints", "*.yaml"))
	if err != nil {
		tb.Fatal(err)
	}
	sort.Strings(files)
	for _, file := range files {
		var sf sprintFile
		readYAML(tb, file, &sf)
		s := coretypes.Sprint{
			ID: sf.ID, Start: *sf.Start.date(tb), End: *sf.End.date(tb), Absences: sf.Absences,
			Capacity: sf.Capacity, Commitment: sf.ForecastIst, Velocity: sf.Velocity, ScopeCreep: sf.ScopeCreep,
			ForecastPlan: sf.ForecastPlan, ExpectedAbsences: sf.ExpectedAbsences,
		}
		if s.Absences == nil {
			s.Absences = map[string]float64{}
		}
		if s.ExpectedAbsences == nil {
			s.ExpectedAbsences = map[string]float64{}
		}
		switch {
		case sf.AbsenceState != "":
			st := coretypes.AbsenceState(sf.AbsenceState)
			s.AbsenceState = &st
		case sf.AbsencesConfirm:
			st := coretypes.Confirmed
			s.AbsenceState = &st
		}
		if p := sf.Planning; p != nil {
			s.Planning = &coretypes.Planning{Carryover: p.Carryover, Backlog: p.Backlog, Corrections: append([]float64{}, p.Corrections...)}
		}
		data.Sprints = append(data.Sprints, s)
	}
	sort.SliceStable(data.Sprints, func(i, j int) bool { return data.Sprints[i].Start.Before(data.Sprints[j].Start) })
	return data
}

// Today is the date the case's references were calculated for.
func Today(tb testing.TB, c golden.Case) time.Time {
	tb.Helper()
	d, err := coretypes.ParseDate(c.Today)
	if err != nil {
		tb.Fatal(err)
	}
	return d
}

var dateTime = regexp.MustCompile(`^(\d{4}-\d{2}-\d{2})T00:00:00Z$`)

// emptyIsNull are the keys whose empty text is None in Python.
var emptyIsNull = map[string]bool{"region": true, "country": true, "workweek": true}

// JSON is v as the generic JSON value the golden comparison reads, in the form of the Python
// references: dates as YYYY-MM-DD, empty region, country and workweek as null.
func JSON(tb testing.TB, v any) any {
	tb.Helper()
	out, err := ToAny(v)
	if err != nil {
		tb.Fatal(err)
	}
	return out
}

// ToAny is JSON without a test, for helpers of table tests.
func ToAny(v any) (any, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var out any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&out); err != nil {
		return nil, err
	}
	return normalize("", out), nil
}

func normalize(key string, v any) any {
	switch x := v.(type) {
	case map[string]any:
		for k, e := range x {
			x[k] = normalize(k, e)
		}
	case []any:
		for i, e := range x {
			x[i] = normalize("", e)
		}
	case string:
		if m := dateTime.FindStringSubmatch(x); m != nil {
			return m[1]
		}
		if x == "" && emptyIsNull[key] {
			return nil
		}
	}
	return v
}

// unmodelled are the fields of the Python sprint that the calculation types do not have.
var unmodelled = []string{"products", "note", "production_planned", "production_done", "not_done", "additional_done", "prognoses"}

// Prune removes the keys of the Python sprint that the calculation types do not model from a
// reference, so that it can be compared with a Go result.
func Prune(want any) any {
	switch x := want.(type) {
	case map[string]any:
		for _, k := range unmodelled {
			delete(x, k)
		}
		for k, e := range x {
			x[k] = Prune(e)
		}
	case []any:
		for i, e := range x {
			x[i] = Prune(e)
		}
	}
	return want
}

// German is the code of the German language; its texts come from the catalog of internal/i18n.
func German(tb testing.TB) string {
	tb.Helper()
	return "de"
}
