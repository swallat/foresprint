package app

import (
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/storage"
)

func ptr[T any](v T) *T { return &v }

func ruleData() *storage.TeamData {
	return &storage.TeamData{
		Products: []model.Product{
			{ID: "portal", Name: "Portal", Match: rules.MustParse(`component = "Portal"`)},
			{ID: "app", Name: "App", Match: rules.MustParse(`label = "mobile"`)},
		},
		Tickets: []model.Ticket{
			{Key: "A-1", Components: []string{"Portal"}, Estimate: ptr(5.0)},
			{Key: "A-2", Components: []string{"Portal"}, Labels: []string{"mobile"}, Estimate: ptr(3.0)},
			{Key: "A-3", Labels: []string{"mobile"}},
		},
	}
}

func TestCheckRuleCountsAndClashes(t *testing.T) {
	got := checkRule(ruleData(), `component = "Portal"`, RuleOwner{Kind: "product", ID: "portal"})
	if !got.Valid || got.Matches != 2 || got.Points != 8 || got.Clash != 1 {
		t.Fatalf("preview = %+v", got)
	}
	if got.Normalized != `component = "Portal"` && got.Normalized != `component = Portal` {
		t.Errorf("normalized = %q", got.Normalized)
	}
	if len(got.Sample) != 2 || got.Sample[0] != "A-1" {
		t.Errorf("sample = %v", got.Sample)
	}
}

func TestCheckRuleReportsTheProblem(t *testing.T) {
	got := checkRule(ruleData(), `component = `, RuleOwner{Kind: "product", ID: "portal"})
	if got.Valid || got.Error == "" || got.Pos < 0 {
		t.Fatalf("preview = %+v", got)
	}
	got = checkRule(ruleData(), `colour = "red"`, RuleOwner{Kind: "product", ID: "portal"})
	if got.Valid || got.Error == "" {
		t.Fatalf("unknown field accepted: %+v", got)
	}
	if len(got.Fields) < 7 {
		t.Errorf("fields = %v", got.Fields)
	}
}
