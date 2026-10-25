package assign

import (
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/rules"
)

var sources = []string{"component", "label"}

func rule(t *testing.T, text string) *rules.Rule {
	t.Helper()
	r, err := rules.ParseRule(text, sources)
	if err != nil {
		t.Fatalf("%q: %v", text, err)
	}
	return r
}

func TestProjectPicksTheOnlyMatch(t *testing.T) {
	facts := rules.Facts{"component": {"Portal"}}
	got, clash := Project(facts, []Candidate{
		{ID: "portal", Match: rule(t, `component = "Portal"`)},
		{ID: "app", Match: rule(t, `component = "App"`)},
		{ID: "none"}, // no rule never matches
	}, []string{"component", "label"})
	if got != "portal" || clash != nil {
		t.Fatalf("got %q, clash %v", got, clash)
	}
}

func TestProjectWithoutAnyMatchIsEmpty(t *testing.T) {
	got, clash := Project(rules.Facts{"component": {"Other"}}, []Candidate{{ID: "portal", Match: rule(t, `component = "Portal"`)}}, nil)
	if got != "" || clash != nil {
		t.Fatalf("got %q, clash %v", got, clash)
	}
}

func TestProjectTheEarlierSourceWins(t *testing.T) {
	facts := rules.Facts{"component": {"Portal"}, "label": {"mobile"}}
	candidates := []Candidate{
		{ID: "by-label", Match: rule(t, `label = "mobile"`)},
		{ID: "by-component", Match: rule(t, `component = "Portal"`)},
	}
	if got, clash := Project(facts, candidates, []string{"component", "label"}); got != "by-component" || clash != nil {
		t.Fatalf("component first: got %q, clash %v", got, clash)
	}
	if got, clash := Project(facts, candidates, []string{"label", "component"}); got != "by-label" || clash != nil {
		t.Fatalf("label first: got %q, clash %v", got, clash)
	}
}

func TestProjectSameSourceContradictsInFileOrder(t *testing.T) {
	facts := rules.Facts{"component": {"Portal"}}
	got, clash := Project(facts, []Candidate{
		{ID: "b", Match: rule(t, `component = "Portal"`)},
		{ID: "a", Match: rule(t, `component = "Portal"`)},
	}, []string{"component"})
	if got != "" || !reflect.DeepEqual(clash, []string{"b", "a"}) {
		t.Fatalf("got %q, clash %v", got, clash)
	}
}

func TestProjectSourcesOutsideTheOrderRankLast(t *testing.T) {
	facts := rules.Facts{"component": {"Portal"}, "label": {"mobile"}}
	got, clash := Project(facts, []Candidate{
		{ID: "unlisted", Match: rule(t, `label = "mobile"`)},
		{ID: "listed", Match: rule(t, `component = "Portal"`)},
	}, []string{"component"})
	if got != "listed" || clash != nil {
		t.Fatalf("got %q, clash %v", got, clash)
	}
}
