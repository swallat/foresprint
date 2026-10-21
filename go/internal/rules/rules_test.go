package rules_test

import (
	"errors"
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/rules"
)

type tree struct {
	Op       string   `json:"op"`
	Source   *string  `json:"source"`
	Values   []string `json:"values"`
	Children []tree   `json:"children"`
	Short    bool     `json:"short"`
	Contains bool     `json:"contains"`
}

type refFile struct {
	Facts []map[string][]string `json:"facts"`
	Valid []struct {
		Text           string     `json:"text"`
		Tree           tree       `json:"tree"`
		Formatted      string     `json:"formatted"`
		Reparsed       tree       `json:"reparsed"`
		Matches        []bool     `json:"matches"`
		MatchedSources [][]string `json:"matched_sources"`
		LeafSources    []string   `json:"leaf_sources"`
	} `json:"valid"`
	Invalid []struct {
		Text     string `json:"text"`
		Message  string `json:"message"`
		Position int    `json:"position"`
		OK       bool   `json:"ok"`
	} `json:"invalid"`
	Formatted []struct {
		Tree tree   `json:"tree"`
		Text string `json:"text"`
	} `json:"formatted"`
	FormatNone string `json:"format_none"`
}

func toTree(r *rules.Rule) tree {
	t := tree{Op: r.Op, Values: nonNil(r.Values), Children: []tree{}, Short: r.Short, Contains: r.Contains}
	if r.Op == rules.OpLeaf {
		s := r.Source
		t.Source = &s
	}
	for _, c := range r.Children {
		t.Children = append(t.Children, toTree(c))
	}
	return t
}

func fromTree(t tree) *rules.Rule {
	r := &rules.Rule{Op: t.Op, Values: t.Values, Short: t.Short, Contains: t.Contains}
	if t.Source != nil {
		r.Source = *t.Source
	}
	for _, c := range t.Children {
		r.Children = append(r.Children, fromTree(c))
	}
	return r
}

func nonNil(v []string) []string {
	if v == nil {
		return []string{}
	}
	return v
}

func nonNilList(v []string) []string { return nonNil(v) }

func configured() []string { return append(append([]string{}, rules.Sources...), "customer") }

func TestGolden(t *testing.T) {
	var ref refFile
	golden.Load(t, &ref, "ruleexpr", "cases.json")
	facts := make([]rules.Facts, len(ref.Facts))
	for i, f := range ref.Facts {
		facts[i] = rules.Facts(f)
	}
	for _, c := range ref.Valid {
		t.Run(c.Text, func(t *testing.T) {
			rule, err := rules.ParseRule(c.Text, configured())
			if err != nil {
				t.Fatal(err)
			}
			golden.Compare(t, c.Tree, toTree(rule))
			if got := rules.FormatRule(rule); got != c.Formatted {
				t.Errorf("format: got %q want %q", got, c.Formatted)
			}
			again, err := rules.ParseRule(rules.FormatRule(rule), configured())
			if err != nil {
				t.Fatal(err)
			}
			golden.Compare(t, c.Reparsed, toTree(again))
			for i, f := range facts {
				if got := rule.Matches(f); got != c.Matches[i] {
					t.Errorf("facts %d: matches %v want %v", i, got, c.Matches[i])
				}
				if got := nonNilList(rule.MatchedSources(f)); !reflect.DeepEqual(got, nonNilList(c.MatchedSources[i])) {
					t.Errorf("facts %d: matched sources %v want %v", i, got, c.MatchedSources[i])
				}
			}
			if got := rule.LeafSources(); !reflect.DeepEqual(got, c.LeafSources) {
				t.Errorf("leaf sources %v want %v", got, c.LeafSources)
			}
		})
	}
	for _, c := range ref.Invalid {
		_, err := rules.ParseRule(c.Text, rules.Sources)
		if c.OK {
			if err != nil {
				t.Errorf("%q: %v", c.Text, err)
			}
			continue
		}
		var se *rules.SyntaxError
		if !errors.As(err, &se) {
			t.Errorf("%q: got %v, want a syntax error", c.Text, err)
			continue
		}
		if se.Message != c.Message || se.Position != c.Position {
			t.Errorf("%q: got %q at %d, want %q at %d", c.Text, se.Message, se.Position, c.Message, c.Position)
		}
	}
	for _, c := range ref.Formatted {
		if got := rules.FormatRule(fromTree(c.Tree)); got != c.Text {
			t.Errorf("format of %+v: got %q want %q", c.Tree, got, c.Text)
		}
	}
	if rules.FormatRule(nil) != ref.FormatNone {
		t.Errorf("format of no rule: %q", rules.FormatRule(nil))
	}
}
