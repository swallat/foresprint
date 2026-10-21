// Package rules holds the assignment rules of Foresprint: the rule tree that projects.yaml
// uses, its evaluation on the facts of a ticket, and the text form (a small JQL-like expression
// language, see ParseRule and FormatRule). Port of Rule in model.py and ruleexpr.py.
package rules

import (
	"sort"
	"strings"
)

// Rule operators. A leaf names a source and values; the others combine children.
const (
	OpLeaf = "leaf"
	OpAny  = "any"
	OpAll  = "all"
	OpNone = "none"
)

// Sources a rule leaf can refer to; the ticket facts carry one value list per source.
var Sources = []string{"epic", "component", "label", "status", "issue_type", "priority", "in_sprint"}

// Facts are the values of a ticket per source (see Ticket.facts in the Python core).
type Facts map[string][]string

// Rule is one node of an assignment rule. A leaf (Op == OpLeaf) names a source and a list of
// values; the values are OR-combined. The short form of projects.yaml (several sources directly
// under "match:") is an OpAny node with Short set; it is written back as the flat mapping.
// Unknown sources and operators without children are kept so that the check can report them.
type Rule struct {
	Op       string
	Source   string
	Values   []string
	Children []*Rule
	Short    bool
	// Leaf only: the values are searched as parts of the ticket's values (case-insensitive).
	Contains bool
}

// NewLeaf returns a leaf for source and values.
func NewLeaf(source string, values ...string) *Rule {
	return &Rule{Op: OpLeaf, Source: source, Values: values}
}

// Matches reports whether a ticket with these facts fulfils the rule.
func (r *Rule) Matches(facts Facts) bool {
	if r.Op == OpLeaf {
		have := facts[r.Source]
		for _, v := range r.Values {
			for _, h := range have {
				if r.Contains {
					if strings.Contains(strings.ToLower(h), strings.ToLower(v)) {
						return true
					}
				} else if v == h {
					return true
				}
			}
		}
		return false
	}
	results := make([]bool, len(r.Children))
	for i, c := range r.Children {
		results[i] = c.Matches(facts)
	}
	switch r.Op {
	case OpAll:
		for _, b := range results {
			if !b {
				return false
			}
		}
		return true
	case OpNone:
		for _, b := range results {
			if b {
				return false
			}
		}
		return true
	}
	for _, b := range results {
		if b {
			return true
		}
	}
	return false
}

// LeafSources are all sources the rule refers to (also unknown ones), sorted.
func (r *Rule) LeafSources() []string {
	set := map[string]bool{}
	r.collectSources(set)
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

func (r *Rule) collectSources(set map[string]bool) {
	if r.Op == OpLeaf {
		set[r.Source] = true
		return
	}
	for _, c := range r.Children {
		c.collectSources(set)
	}
}

// MatchedSources are the sources of the leaves that the facts fulfil (the project match order
// decides between two matching projects by the source of the match), sorted.
func (r *Rule) MatchedSources(facts Facts) []string {
	set := map[string]bool{}
	r.collectMatched(facts, set)
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

func (r *Rule) collectMatched(facts Facts, set map[string]bool) {
	switch r.Op {
	case OpLeaf:
		if r.Matches(facts) {
			set[r.Source] = true
		}
	case OpNone:
	default:
		for _, c := range r.Children {
			c.collectMatched(facts, set)
		}
	}
}

// Leaves are all leaves in document order.
func (r *Rule) Leaves() []*Rule {
	if r.Op == OpLeaf {
		return []*Rule{r}
	}
	var out []*Rule
	for _, c := range r.Children {
		out = append(out, c.Leaves()...)
	}
	return out
}
