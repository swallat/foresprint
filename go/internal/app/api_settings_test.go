package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/model"
)

// copyDemo copies the demo team to a temporary data folder, so that tests may write.
func copyDemoTeam(t *testing.T) (*API, string) {
	t.Helper()
	src := demoDir(t)
	dst := t.TempDir()
	err := filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, path)
		if info.IsDir() {
			return os.MkdirAll(filepath.Join(dst, rel), 0o755)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(dst, rel), b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	api := newAPI(t, dst)
	teams := api.Teams()
	if len(teams) == 0 {
		t.Fatal("no demo team")
	}
	return api, teams[0].Key
}

func TestTeamSettingsRoundTrip(t *testing.T) {
	api, team := copyDemoTeam(t)
	s, err := api.TeamSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	s.Forecast.Window = 6
	s.Forecast.PlannableShare = 70
	s.Forecast.Trend = "linear"
	s.Production = true
	s.ProductionCap = 60
	s.ProForma = []string{" Refinement ", "", "Parkplatz"}
	if err := api.SaveTeamSettings(team, s); err != nil {
		t.Fatal(err)
	}
	got, err := api.TeamSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	if got.Forecast.Window != 6 || got.Forecast.PlannableShare != 70 || got.Forecast.Trend != "linear" {
		t.Errorf("forecast = %+v", got.Forecast)
	}
	if !got.Production || got.ProductionCap != 60 {
		t.Errorf("production = %v cap %v", got.Production, got.ProductionCap)
	}
	if strings.Join(got.ProForma, "|") != "Refinement|Parkplatz" {
		t.Errorf("pro forma = %q", got.ProForma)
	}
}

func TestTeamSettingsRefuseNonsense(t *testing.T) {
	api, team := copyDemoTeam(t)
	base, _ := api.TeamSettings(team)
	for name, mutate := range map[string]func(*TeamSettings){
		"window":    func(s *TeamSettings) { s.Forecast.Window = 0 },
		"trend":     func(s *TeamSettings) { s.Forecast.Trend = "wild" },
		"share":     func(s *TeamSettings) { s.Forecast.PlannableShare = 120 },
		"cap":       func(s *TeamSettings) { s.ProductionCap = -1 },
		"duplicate": func(s *TeamSettings) { s.ProForma = []string{"A", "a"} },
	} {
		s := base
		mutate(&s)
		if err := api.SaveTeamSettings(team, s); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

func TestUnitChangeNeedsASprintOnceRecorded(t *testing.T) {
	api, team := copyDemoTeam(t)
	s, _ := api.TeamSettings(team)
	orig, other := s.Unit, "SP"
	if s.Unit == "SP" {
		other = "PT"
	}
	sprints, _ := api.Sprints(team)
	first, last := sprints[0].ID, sprints[len(sprints)-1].ID
	s.Unit, s.UnitFrom = other, first
	if err := api.SaveTeamSettings(team, s); err != nil {
		t.Fatal(err)
	}
	got, _ := api.TeamSettings(team)
	if got.Unit != other || got.UnitFrom != first || len(got.UnitChanges) != 1 {
		t.Fatalf("after change: %+v", got)
	}
	got.Unit, got.UnitFrom = orig, ""
	if err := api.SaveTeamSettings(team, got); err == nil {
		t.Error("a switch without a sprint must be refused")
	}
	got.UnitFrom = "no-such-sprint"
	if err := api.SaveTeamSettings(team, got); err == nil {
		t.Error("an unknown sprint must be refused")
	}
	if len(sprints) > 1 { // a later switch is kept in order after the earlier one
		got.Unit, got.UnitFrom = orig, last
		if err := api.SaveTeamSettings(team, got); err != nil {
			t.Fatal(err)
		}
		again, _ := api.TeamSettings(team)
		if len(again.UnitChanges) != 2 || again.UnitChanges[0].From != first || again.UnitChanges[1].From != last {
			t.Errorf("changes = %+v", again.UnitChanges)
		}
	}
}

func TestTrackerSettingsRoundTrip(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, err := api.TrackerSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	in.Source, in.Kind = "tracker", "jira"
	in.BaseURL = "https://jira.example.org"
	in.Query = "project = ATL AND resolution = Unresolved"
	in.ProductBy = "field"
	in.Fields.Product = "Component"
	in.RuleFields = []RuleField{{Name: "team", Display: "Team"}}
	in.RefinedRule = `team = "Atlas" and label = refined`
	in.ProductionBy = "rule"
	in.ProdRules = []ProdRule{{Rule: `component = "Ops"`, Percent: 100}}
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	got, err := api.TrackerSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	if got.Source != "tracker" || got.BaseURL != in.BaseURL || got.ProductBy != "field" || got.Fields.Product != "Component" {
		t.Errorf("got %+v", got)
	}
	if got.RefinedRule == "" || len(got.ProdRules) != 1 || got.ProdRules[0].Percent != 100 || got.ProductionBy != "rule" {
		t.Errorf("rules: %+v", got)
	}
	if len(got.RuleFields) != 1 || got.RuleFields[0].Name != "team" {
		t.Errorf("rule fields = %+v", got.RuleFields)
	}

	// A field that a rule uses cannot be removed.
	in = got
	in.RuleFields = nil
	if err := api.SaveTrackerSettings(team, in); err == nil {
		t.Error("removing a rule field that a rule uses must be refused")
	}
	in.RefinedRule = ""
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Errorf("removing an unused rule field: %v", err)
	}
}

func TestTrackerSettingsRefuseNonsense(t *testing.T) {
	api, team := copyDemoTeam(t)
	base, _ := api.TrackerSettings(team)
	base.Source, base.Kind = "tracker", "jira"
	for name, mutate := range map[string]func(*TrackerSettings){
		"address":     func(s *TrackerSettings) { s.BaseURL = "jira.example.org" },
		"credentials": func(s *TrackerSettings) { s.BaseURL = "https://me:secret@jira.example.org" },
		"rule":        func(s *TrackerSettings) { s.RefinedRule = "label ==" },
		"unknown src": func(s *TrackerSettings) { s.RefinedRule = `nope = "x"` },
		"field name":  func(s *TrackerSettings) { s.RuleFields = []RuleField{{Name: "Label", Display: "x"}} },
		"fixed name":  func(s *TrackerSettings) { s.RuleFields = []RuleField{{Name: "label", Display: "x"}} },
		"percent": func(s *TrackerSettings) {
			s.ProductionBy = "rule"
			s.ProdRules = []ProdRule{{Rule: "label = a", Percent: 150}}
		},
		"source": func(s *TrackerSettings) { s.Source = "carrier pigeon" },
	} {
		s := base
		mutate(&s)
		if err := api.SaveTrackerSettings(team, s); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

func TestSourceNoneKeepsTheTrackerSection(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, _ := api.TrackerSettings(team)
	in.Source, in.Kind, in.BaseURL = "tracker", "jira", "https://jira.example.org"
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	in.Source = "none"
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	got, _ := api.TrackerSettings(team)
	if got.Source != "none" || got.BaseURL != "https://jira.example.org" {
		t.Errorf("got %+v", got)
	}
}

func TestPersonalDensity(t *testing.T) {
	api := newAPI(t, "")
	if err := api.SetDensity("roomy"); err != nil {
		t.Fatal(err)
	}
	p := api.Prefs()
	if p.Density != "roomy" {
		t.Fatalf("prefs = %+v", p)
	}
	if api.SetDensity("huge") == nil {
		t.Error("unknown values must be refused")
	}
}

func TestTokenStateNeverHoldsTheToken(t *testing.T) {
	api, team := copyDemoTeam(t)
	t.Setenv("FORESPRINT_JIRA_TOKEN", "secret-value")
	in, _ := api.TrackerSettings(team)
	in.Source, in.Kind, in.BaseURL = "tracker", "jira", "https://jira.example.org"
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	got, _ := api.TrackerSettings(team)
	if !got.Token.FromEnv || got.Token.Host != "jira.example.org" {
		t.Errorf("token state = %+v", got.Token)
	}
}

func TestManualProductionIgnoresHiddenRules(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, _ := api.TrackerSettings(team)
	in.Source, in.Kind = "tracker", "jira"
	in.ProductionBy = "manual"
	in.ProdRules = []ProdRule{{Rule: "", Percent: 100}}
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatalf("hidden rules must not block: %v", err)
	}
	got, _ := api.TrackerSettings(team)
	if got.ProductionBy != "manual" || len(got.ProdRules) != 0 {
		t.Errorf("got %+v", got)
	}
}

func TestCSVTeamHasNoSyncChip(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, _ := api.TrackerSettings(team)
	in.Source, in.Kind = "tracker", "csv"
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	if info := api.TrackerInfo(team); info.Enabled {
		t.Errorf("info = %+v", info)
	}
}

func TestTrackerBoardNumber(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, err := api.TrackerSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	in.Source, in.Kind = "tracker", "jira"
	in.BoardID = 42
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	out, _ := api.TrackerSettings(team)
	if out.BoardID != 42 {
		t.Fatalf("board: %d", out.BoardID)
	}
	in.BoardID = -1
	if err := api.SaveTrackerSettings(team, in); err == nil {
		t.Fatal("a negative board number must be refused")
	}
	in.BoardID = 0
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	if out, _ = api.TrackerSettings(team); out.BoardID != 0 {
		t.Fatalf("board not cleared: %d", out.BoardID)
	}
}

func TestTrackerFetchIntervalAndSprints(t *testing.T) {
	api, team := copyDemoTeam(t)
	in, err := api.TrackerSettings(team)
	if err != nil {
		t.Fatal(err)
	}
	if in.ProForma == nil || in.Sprints == nil || in.FieldHits == nil {
		t.Fatalf("lists must never be null: %+v", in)
	}
	in.Source, in.Kind = "tracker", "jira"
	in.FetchInterval = 15
	in.ProForma = []string{"Refinement", "Ideas"}
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	out, _ := api.TrackerSettings(team)
	if out.FetchInterval != 15 || len(out.ProForma) != 2 {
		t.Fatalf("not kept: %d %v", out.FetchInterval, out.ProForma)
	}
	names := map[string]bool{}
	for _, s := range out.Sprints {
		names[s.Name] = true
	}
	if !names["Refinement"] || !names["Ideas"] {
		t.Errorf("pro-forma names missing in the table: %+v", out.Sprints)
	}
	if info := api.TrackerInfo(team); info.Interval != 15 {
		t.Errorf("status interval %d", info.Interval)
	}
	in.FetchInterval = 7
	if err := api.SaveTrackerSettings(team, in); err == nil {
		t.Error("an unknown interval must be refused")
	}
	in.FetchInterval = 0
	in.ProForma = nil // a caller without the list keeps it
	if err := api.SaveTrackerSettings(team, in); err != nil {
		t.Fatal(err)
	}
	if out, _ = api.TrackerSettings(team); len(out.ProForma) != 2 || out.FetchInterval != 0 {
		t.Errorf("after: %d %v", out.FetchInterval, out.ProForma)
	}
}

func TestTrackerFieldHitsCountFilledValues(t *testing.T) {
	var extra model.OrderedMap[[]string]
	extra.Set("project", []string{"Alpha"})
	var blank model.OrderedMap[[]string]
	blank.Set("project", []string{" "})
	est := 3.0
	hits := trackerFieldHits([]model.Ticket{{Key: "A-1", Estimate: &est, Extra: extra}, {Key: "A-2", Extra: blank}})
	if hits["estimate"] != 1 || hits["project"] != 1 || hits["epic"] != 0 {
		t.Errorf("hits: %v", hits)
	}
}
