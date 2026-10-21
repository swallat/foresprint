package validate_test

import (
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/validate"
)

type issue struct {
	Level   string `json:"level"`
	Where   string `json:"where"`
	Message string `json:"message"`
}

type ruleTree struct {
	Op       string     `json:"op"`
	Source   *string    `json:"source"`
	Values   []string   `json:"values"`
	Children []ruleTree `json:"children"`
	Short    bool       `json:"short"`
	Contains bool       `json:"contains"`
}

func (t ruleTree) rule() *rules.Rule {
	r := &rules.Rule{Op: t.Op, Values: t.Values, Short: t.Short, Contains: t.Contains}
	if t.Source != nil {
		r.Source = *t.Source
	}
	for _, c := range t.Children {
		r.Children = append(r.Children, c.rule())
	}
	return r
}

type refs struct {
	YAMLText []struct {
		Name   string  `json:"name"`
		Text   string  `json:"text"`
		Issues []issue `json:"issues"`
	} `json:"yaml_text"`
	Rules struct {
		Sources  []string `json:"sources"`
		Problems []struct {
			Name           string   `json:"name"`
			Tree           ruleTree `json:"tree"`
			Problems       []string `json:"problems"`
			WithConfigured []string `json:"with_configured"`
		} `json:"problems"`
		Cycles []struct {
			Name      string     `json:"name"`
			DependsOn [][]any    `json:"depends_on"`
			Cycles    [][]string `json:"cycles"`
		} `json:"cycles"`
	} `json:"rules"`
}

func load(t *testing.T) refs {
	var r refs
	golden.Load(t, &r, "validate", "cases.json")
	return r
}

func TestYAMLText(t *testing.T) {
	for _, c := range load(t).YAMLText {
		got := validate.CheckYAMLText(c.Text, "x.yaml")
		var want, have []issue
		want = append(want, c.Issues...)
		for _, g := range got {
			have = append(have, issue{string(g.Level), g.Where, g.Message})
		}
		if len(want) != len(have) {
			t.Errorf("%s: %d issues, want %d: %+v", c.Name, len(have), len(want), have)
			continue
		}
		for i := range want {
			if want[i] != have[i] {
				t.Errorf("%s: issue %d:\n got %+v\nwant %+v", c.Name, i, have[i], want[i])
			}
		}
	}
}

func TestRuleProblems(t *testing.T) {
	r := load(t)
	configured := r.Rules.Sources
	for _, c := range r.Rules.Problems {
		rule := c.Tree.rule()
		if got := validate.RuleProblems(rule, rules.Sources); !reflect.DeepEqual(nonNil(got), nonNil(c.Problems)) {
			t.Errorf("%s: got %q want %q", c.Name, got, c.Problems)
		}
		if got := validate.RuleProblems(rule, configured); !reflect.DeepEqual(nonNil(got), nonNil(c.WithConfigured)) {
			t.Errorf("%s (configured): got %q want %q", c.Name, got, c.WithConfigured)
		}
	}
}

func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

func TestFindCycles(t *testing.T) {
	for _, c := range load(t).Rules.Cycles {
		var deps []validate.Dependency
		for _, pair := range c.DependsOn {
			d := validate.Dependency{Key: pair[0].(string)}
			for _, x := range pair[1].([]any) {
				d.DependsOn = append(d.DependsOn, x.(string))
			}
			deps = append(deps, d)
		}
		got := validate.FindCycles(deps)
		if len(got) != len(c.Cycles) || (len(got) > 0 && !reflect.DeepEqual(got, c.Cycles)) {
			t.Errorf("%s: got %v want %v", c.Name, got, c.Cycles)
		}
	}
}
