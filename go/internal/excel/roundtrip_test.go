package excel_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/forecast"
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
