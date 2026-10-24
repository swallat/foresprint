package app

import (
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func nextSprint(t *testing.T, api *API, team string) string {
	t.Helper()
	sprints, err := api.Sprints(team)
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range sprints {
		if s.State == "future" {
			return s.ID
		}
	}
	t.Fatal("no future sprint")
	return ""
}

func TestUseDefaultsPreplansTheStandardAmounts(t *testing.T) {
	api, team := planTeam(t)
	next := nextSprint(t, api, team)
	if err := api.UseDefaults(team, next); err != nil {
		t.Fatal(err)
	}
	v, err := api.PlanSprint(team, next, nil)
	if err != nil {
		t.Fatal(err)
	}
	withDefault := 0
	for _, p := range v.Products {
		if p.Default == nil {
			continue
		}
		withDefault++
		if p.Pre == nil || *p.Pre != *p.Default {
			t.Errorf("%s: pre = %v, default = %v", p.ID, p.Pre, *p.Default)
		}
	}
	if withDefault == 0 {
		t.Fatal("the demo team has no product with a standard amount: the test checks nothing")
	}
	if err := api.UseDefaults(team, "no-such-sprint"); err == nil {
		t.Error("an unknown sprint was accepted")
	}
}

func TestProductionPTIsSetClearedAndRefusedWhenNegative(t *testing.T) {
	api, team := planTeam(t)
	next := nextSprint(t, api, team)
	four := 4.0
	if err := api.SetProductionPT(team, next, &four); err != nil {
		t.Fatal(err)
	}
	read := func() *float64 {
		_, data, err := api.loadRepoTeam(team)
		if err != nil {
			t.Fatal(err)
		}
		for _, s := range data.Sprints {
			if s.ID == next {
				return s.ProductionPlanned
			}
		}
		t.Fatalf("sprint %s not stored", next)
		return nil
	}
	if got := read(); got == nil || *got != 4 {
		t.Fatalf("production = %v", got)
	}
	if err := api.SetProductionPT(team, next, nil); err != nil {
		t.Fatal(err)
	}
	if got := read(); got != nil {
		t.Fatalf("production not cleared: %v", *got)
	}
	neg := -1.0
	if err := api.SetProductionPT(team, next, &neg); err == nil {
		t.Error("a negative amount was accepted")
	}
}

func TestProjectAmountIsSetClearedAndChecked(t *testing.T) {
	api, team := projectDir(t, false) // a team without tickets, where the amounts are typed
	next := nextSprint(t, api, team)
	total := 40.0
	id, err := api.SaveProject(team, ProjectInput{Name: "Self-Service", Products: []string{"portal"}, End: "2027-01-29", Booked: &total})
	if err != nil {
		t.Fatal(err)
	}
	three := 3.0
	if err := api.SetProjectAmount(team, next, id, &three); err != nil {
		t.Fatal(err)
	}
	read := func() (model.ProductValues, bool) {
		_, d, err := api.loadRepoTeam(team)
		if err != nil {
			t.Fatal(err)
		}
		for _, s := range d.Sprints {
			if s.ID == next {
				v, ok := s.Projects[id]
				return v, ok
			}
		}
		return model.ProductValues{}, false
	}
	if v, ok := read(); !ok || v.Preplanned == nil || *v.Preplanned != 3 {
		t.Fatalf("amount = %+v, %v", v, ok)
	}
	if err := api.SetProjectAmount(team, next, id, nil); err != nil {
		t.Fatal(err)
	}
	if _, ok := read(); ok {
		t.Error("a cleared amount must remove the entry")
	}
	if err := api.SetProjectAmount(team, next, "no-such-project", &three); err == nil || !strings.Contains(err.Error(), "does not exist") {
		t.Errorf("unknown project: %v", err)
	}
	neg := -1.0
	if err := api.SetProjectAmount(team, next, id, &neg); err == nil {
		t.Error("a negative amount was accepted")
	}
}

func TestResetOrderGivesTheTrackerRankBack(t *testing.T) {
	api := packagesTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, _ := repo.Load("t")
	data.Team.Tracker.Kind = "jira"
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	r1, r2 := "0|a", "0|b"
	tf := storage.TicketsFile{Tickets: []model.Ticket{
		{Key: "X-1", Title: "One", Rank: &r1, EstimateSource: model.EstimateNone},
		{Key: "X-2", Title: "Two", Rank: &r2, EstimateSource: model.EstimateNone},
	}}
	if _, err := repo.SaveTickets("t", tf); err != nil {
		t.Fatal(err)
	}
	order := func() string {
		view, err := api.Backlog("t")
		if err != nil {
			t.Fatal(err)
		}
		var keys []string
		for _, tk := range view.Tickets {
			keys = append(keys, tk.Key)
		}
		return strings.Join(keys, ",")
	}
	if err := api.MoveWorkPackage("t", "X-2", "X-1", false); err != nil {
		t.Fatal(err)
	}
	if got := order(); got != "X-2,X-1" {
		t.Fatalf("own order = %s", got)
	}
	if err := api.ResetOrder("t"); err != nil {
		t.Fatal(err)
	}
	if got := order(); got != "X-1,X-2" {
		t.Fatalf("order after reset = %s", got)
	}
}

func TestRuleFieldsListTheFieldsOfTheTeam(t *testing.T) {
	api, team := planTeam(t)
	fields, err := api.RuleFields(team)
	if err != nil || len(fields) == 0 {
		t.Fatalf("fields = %v, %v", fields, err)
	}
	if _, err := api.RuleFields("no-such-team"); err == nil {
		t.Error("an unknown team was accepted")
	}
}

func TestSetupStateGuideAndRefusals(t *testing.T) {
	api, _ := planTeam(t)
	if st := api.SetupState(); st.DataDir == "" || st.Teams == nil || len(st.Teams) == 0 {
		t.Fatalf("state = %+v", st)
	}
	if g := api.SetupGuide("https://gitlab.com/group/repo.git"); g.Steps == "" {
		t.Errorf("guide = %+v", g)
	}
	if o := api.SetupStorage("nonsense", "", ""); o.Problem == nil || o.Folder != "" {
		t.Errorf("an unknown way must be refused: %+v", o)
	}
	if p := api.SetupIdentity("", "x@example.org"); p == nil {
		t.Error("an empty name was accepted")
	}
}
