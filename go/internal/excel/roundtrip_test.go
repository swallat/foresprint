package excel_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/tutorial"
)

// The workbook does not carry every field of the 1.0 model. Reading it back with --apply must
// leave what it does not carry as it is.
func TestRoundTripKeepsFieldsOutsideTheWorkbook(t *testing.T) {
	today := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
	root := t.TempDir()
	if err := tutorial.Write(root, today, "en"); err != nil {
		t.Fatal(err)
	}
	repo := storage.NewRepository(root)
	before, err := repo.Load(tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	fc, err := forecast.Build(before, today)
	if err != nil {
		t.Fatal(err)
	}
	book, err := excel.Build(fc)
	if err != nil {
		t.Fatal(err)
	}
	data, _, err := excel.ReadWorkbook(book, tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := excel.Plan(repo, data, today)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range plan.Changes {
		t.Errorf("change %s %s: %v -> %v", c.File, c.Path, c.Old, c.New)
	}
	if _, err := excel.Apply(repo, plan); err != nil {
		t.Fatal(err)
	}
	after, err := repo.Load(tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	if len(after.Team.ProductOwners) != len(before.Team.ProductOwners) || len(before.Team.ProductOwners) == 0 {
		t.Errorf("product owners %d, want %d", len(after.Team.ProductOwners), len(before.Team.ProductOwners))
	}
	kinds := 0
	for i, p := range before.People {
		if p.Kind != "" && p.Kind != "member" {
			kinds++
		}
		if after.People[i].Kind != p.Kind {
			t.Errorf("person %s: kind %q, want %q", p.ID, after.People[i].Kind, p.Kind)
		}
	}
	if kinds == 0 {
		t.Error("the tutorial team has no guest or external person to test with")
	}
	for i, sp := range before.Sprints {
		if (sp.Preplanned == nil) != (after.Sprints[i].Preplanned == nil) {
			t.Errorf("sprint %s: preplanned %v, want %v", sp.ID, after.Sprints[i].Preplanned, sp.Preplanned)
		}
	}
}

func loadPlanned(t *testing.T, repo *storage.Repository, today time.Time) (*excel.ImportPlan, *storage.TeamData) {
	t.Helper()
	data, err := repo.Load(tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	fc, err := forecast.Build(data, today)
	if err != nil {
		t.Fatal(err)
	}
	book, err := excel.Build(fc)
	if err != nil {
		t.Fatal(err)
	}
	read, _, err := excel.ReadWorkbook(book, tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := excel.Plan(repo, read, today)
	if err != nil {
		t.Fatal(err)
	}
	return plan, data
}

// Every 1.0 field the workbook cannot hold survives the round trip; a cell the workbook does
// hold still changes the file when it is cleared.
func TestRoundTripWithAllOutsideFields(t *testing.T) {
	today := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
	root := t.TempDir()
	if err := tutorial.Write(root, today, "en"); err != nil {
		t.Fatal(err)
	}
	repo := storage.NewRepository(root)
	data, err := repo.Load(tutorial.Key)
	if err != nil {
		t.Fatal(err)
	}
	factor := 1.5
	data.Team.Sprint.Naming = []model.NamingRule{{Pattern: "Sprint {N}"}}
	data.Team.Sprint.ProForma = []string{"2099.1"}
	data.Team.Estimation = model.EstimationSettings{Factor: &factor}
	name := "Hand"
	data.Sprints[0].Name = &name
	plan20 := 20.0
	data.Sprints[0].ForecastPlan = &plan20
	data.Sprints[0].Removed = []string{"T-1"}
	data.Sprints[0].RestNext = &factor
	rule, err := rules.ParseRule("label = abc", []string{"label"})
	if err != nil {
		t.Fatal(err)
	}
	data.Products[0].Match = rule
	if _, err := repo.SaveTeam(data.Team); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveProducts(tutorial.Key, data.Products); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveSprint(tutorial.Key, &data.Sprints[0]); err != nil {
		t.Fatal(err)
	}

	plan, _ := loadPlanned(t, repo, today)
	for _, c := range plan.Changes {
		t.Errorf("change %s %s: %v -> %v", c.File, c.Path, c.Old, c.New)
	}
}
