package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// copyDemo copies the demo team to a temporary data folder, so that tests may write.
func copyDemo(t *testing.T) (*API, string) {
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
	api, team := copyDemo(t)
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
	api, team := copyDemo(t)
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
	api, team := copyDemo(t)
	s, _ := api.TeamSettings(team)
	orig, other := s.Unit, "SP"
	if s.Unit == "SP" {
		other = "PT"
	}
	s.Unit, s.UnitFrom = other, "2099.1"
	if err := api.SaveTeamSettings(team, s); err != nil {
		t.Fatal(err)
	}
	got, _ := api.TeamSettings(team)
	if got.Unit != other || got.UnitFrom != "2099.1" || len(got.UnitChanges) != 1 {
		t.Fatalf("after change: %+v", got)
	}
	got.Unit = orig // back again: needs a sprint
	got.UnitFrom = ""
	if err := api.SaveTeamSettings(team, got); err == nil {
		t.Error("a second switch without a sprint must be refused")
	}
}

func TestTrackerSettingsRoundTrip(t *testing.T) {
	api, team := copyDemo(t)
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
	api, team := copyDemo(t)
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
	api, team := copyDemo(t)
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

func TestCheckRule(t *testing.T) {
	api, _ := copyDemo(t)
	if c := api.CheckRule(`label = "a"  OR  component IN (b, c)`, nil); !c.OK || c.Text == "" {
		t.Errorf("good rule: %+v", c)
	}
	if c := api.CheckRule("team = x", nil); c.OK || c.Message == "" {
		t.Errorf("unknown source must fail: %+v", c)
	}
	if c := api.CheckRule("team = x", []string{"team"}); !c.OK {
		t.Errorf("registered source must pass: %+v", c)
	}
	if c := api.CheckRule("  ", nil); !c.OK || c.Text != "" {
		t.Errorf("empty rule is no rule: %+v", c)
	}
}

func TestPersonalChoices(t *testing.T) {
	api := newAPI(t, "")
	if err := api.SetDensity("roomy"); err != nil {
		t.Fatal(err)
	}
	if err := api.SetCalcMode("inline"); err != nil {
		t.Fatal(err)
	}
	p := api.Prefs()
	if p.Density != "roomy" || p.CalcMode != "inline" {
		t.Fatalf("prefs = %+v", p)
	}
	if api.SetDensity("huge") == nil || api.SetCalcMode("loud") == nil {
		t.Error("unknown values must be refused")
	}
}

func TestTokenStateNeverHoldsTheToken(t *testing.T) {
	api, team := copyDemo(t)
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
