package model

import (
	"regexp"
	"strings"
	"time"
)

// EstimateSource says where a ticket's estimate comes from.
type EstimateSource string

// The estimate sources.
const (
	// EstimateRefined: the ticket carries the refined label or fulfils tracker.refined_also_if.
	EstimateRefined EstimateSource = "refined"
	// EstimateRough is a rough value (not refined, or refined status unclear); the conservative
	// variant multiplies it by rough_factor.
	EstimateRough EstimateSource = "rough"
	// EstimateManual was entered by the PO in preplan.yaml.
	EstimateManual EstimateSource = "manual"
	// EstimateNone: no estimate at all, the ticket is not distributed.
	EstimateNone EstimateSource = "none"
)

// PlanningUses is the number the distribution calculates with (tracker.planning_uses).
type PlanningUses string

// The values of tracker.planning_uses.
const (
	// UsesRemaining: remaining effort if filled, otherwise the estimate (default).
	UsesRemaining PlanningUses = "remaining"
	// UsesEstimate: always the estimate.
	UsesEstimate PlanningUses = "estimate"
)

// BudgetBasis is what a sprint's budget for pre-planning is derived from.
type BudgetBasis string

// The budget bases.
const (
	// BudgetRoadmapShare: forecast PLAN times the plannable share (forecast.roadmap_share).
	BudgetRoadmapShare BudgetBasis = "roadmap_share"
	// BudgetPlan: the whole forecast PLAN.
	BudgetPlan BudgetBasis = "plan"
)

// RuleSources are the sources a rule leaf can refer to; the ticket facts carry one value list
// per source.
var RuleSources = []string{"epic", "component", "label", "status", "issue_type", "priority", "in_sprint"}

// RuleFieldName matches the names of configured rule fields (tracker.rule_fields): lower-case
// words, no clash with the fixed sources.
var RuleFieldName = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// RuleReserved are the words that cannot name a rule field: operators of the YAML form and
// keywords of the expressions.
var RuleReserved = []string{"any", "all", "none", "and", "or", "not", "in"}

// RuleSourcesWith returns the sources a rule can name: the fixed ones and the configured rule
// fields (in the given order).
func RuleSourcesWith(ruleFields OrderedMap[string]) []string {
	out := append([]string(nil), RuleSources...)
	for _, k := range ruleFields.Keys() {
		if !contains(RuleSources, k) {
			out = append(out, k)
		}
	}
	return out
}

func contains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// ContainsSuffix ends a leaf key in projects.yaml that searches parts of the values
// (label_contains).
const ContainsSuffix = "_contains"

// Rule operators. A leaf has the operator OpLeaf.
const (
	OpLeaf = "leaf"
	OpAny  = "any"
	OpAll  = "all"
	OpNone = "none"
)

// RuleOperators are the operators of the long form.
var RuleOperators = []string{OpAny, OpAll, OpNone}

// DefaultMatchOrder is the default order in which the sources decide between two matching
// projects.
var DefaultMatchOrder = []string{"epic", "component", "label"}

// DefaultPriorityOrder is Jira's standard priorities, most important first.
var DefaultPriorityOrder = []string{"Highest", "High", "Medium", "Low", "Lowest"}

// Rule is one node of an assignment rule.
//
// A leaf (Op == OpLeaf) names a source and a list of values; the values are OR-combined. An
// operator node (any, all, none) combines its children. The short form of projects.yaml
// (several sources directly under match:) is an any node with Short set; it is written back as
// the flat mapping. Unknown sources and operators without children are kept so that the
// validation can report them.
type Rule struct {
	Op       string
	Source   string
	Values   []string
	Children []*Rule
	Short    bool
	// Contains (leaf only): the values are searched as parts of the ticket's values,
	// case-insensitive.
	Contains bool
}

// Facts are the values of a ticket per rule source.
type Facts map[string][]string

// Matches reports whether a ticket with these facts (see Ticket.Facts) fulfils the rule.
func (r *Rule) Matches(facts Facts) bool {
	if r.Op == OpLeaf {
		have := facts[r.Source]
		if r.Contains {
			for _, v := range r.Values {
				for _, h := range have {
					if strings.Contains(strings.ToLower(h), strings.ToLower(v)) {
						return true
					}
				}
			}
			return false
		}
		for _, v := range r.Values {
			if contains(have, v) {
				return true
			}
		}
		return false
	}
	switch r.Op {
	case OpAll:
		for _, c := range r.Children {
			if !c.Matches(facts) {
				return false
			}
		}
		return true
	case OpNone:
		for _, c := range r.Children {
			if c.Matches(facts) {
				return false
			}
		}
		return true
	}
	for _, c := range r.Children {
		if c.Matches(facts) {
			return true
		}
	}
	return false
}

// LeafSources returns all sources the rule refers to (also unknown ones).
func (r *Rule) LeafSources() map[string]bool {
	out := map[string]bool{}
	if r.Op == OpLeaf {
		out[r.Source] = true
		return out
	}
	for _, c := range r.Children {
		for s := range c.LeafSources() {
			out[s] = true
		}
	}
	return out
}

// MatchedSources returns the sources of the leaves that the facts fulfil (project_match_order
// decides between two matching projects by the source of the match).
func (r *Rule) MatchedSources(facts Facts) map[string]bool {
	out := map[string]bool{}
	if r.Op == OpLeaf {
		if r.Matches(facts) {
			out[r.Source] = true
		}
		return out
	}
	if r.Op == OpNone {
		return out
	}
	for _, c := range r.Children {
		for s := range c.MatchedSources(facts) {
			out[s] = true
		}
	}
	return out
}

// Leaves returns all leaves in document order.
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

// TrackerFields are the display names of the tracker fields (as in the instance or the CSV
// export header).
type TrackerFields struct {
	Estimate  *string
	Remaining *string
	Epic      *string
}

// TrackerKinds are the kinds of ticket sources (tracker.kind).
var TrackerKinds = []string{"csv", "jira"}

// TrackerSettings is the section tracker of team.yaml.
type TrackerSettings struct {
	Kind         string
	BaseURL      *string
	Query        *string
	Fields       TrackerFields
	PlanningUses PlanningUses
	// RefinedLabel marks a refined ticket; RefinedAlsoIf counts as refined without the label.
	RefinedLabel      *string
	RefinedAlsoIf     *Rule
	ProjectMatchOrder []string
	// PriorityOrder are the tracker's priority names, most important first. The distribution
	// takes the tickets of a product in this order before target date and rank
	// (case-insensitive; a ticket without or with an unknown priority comes last). Empty =
	// ticket priority is ignored.
	PriorityOrder []string
	// DependencyGap: 1 = a dependent ticket goes at least one sprint after its dependency, 0 =
	// same sprint allowed.
	DependencyGap int
	BudgetBasis   BudgetBasis
	// RoughFactor is the factor for rough estimates in the conservative variant.
	RoughFactor float64
	// WriteLabels writes planned_for_<sprint_id> labels to the tracker.
	WriteLabels bool
	// SprintNames maps sprint names of the tracker to sprint ids of the tool, when they differ.
	SprintNames OrderedMap[string]
	// LinkType is the name of the Jira issue link type whose inward side means "is blocked by".
	LinkType string
	// RuleFields maps the rule name of an additional field to its display name in the tracker
	// (or header of the CSV column).
	RuleFields OrderedMap[string]
}

// NewTrackerSettings returns the defaults.
func NewTrackerSettings() TrackerSettings {
	return TrackerSettings{
		Kind:              "csv",
		PlanningUses:      UsesRemaining,
		ProjectMatchOrder: append([]string(nil), DefaultMatchOrder...),
		PriorityOrder:     append([]string(nil), DefaultPriorityOrder...),
		DependencyGap:     1,
		BudgetBasis:       BudgetRoadmapShare,
		RoughFactor:       1.5,
		LinkType:          "Blocks",
	}
}

// Project is an undertaking of the PO with target date, product and assignment rule (not a Jira
// project). A ticket belongs to the project whose rule it fulfils.
type Project struct {
	ID      string
	Name    string
	Product *string
	Target  *time.Time
	// Priority: lower = more important when two projects share a target date.
	Priority int
	// BudgetBasis overrides tracker.budget_basis for this project.
	BudgetBasis *BudgetBasis
	Match       *Rule
	Note        *string
}

// Ticket is a unit of work as last imported from the tracker (tickets.yaml).
type Ticket struct {
	Key       string
	Title     string
	Status    *string
	IssueType *string
	// Priority as the tracker names it (e.g. "High"); only for assignment rules.
	Priority *string
	// Extra are the values of the configured tracker.rule_fields, per rule name.
	Extra          OrderedMap[[]string]
	Estimate       *float64
	Remaining      *float64
	EstimateSource EstimateSource
	// RefinedUnclear: counts as refined only via refined_also_if, or carries the label without
	// an estimate.
	RefinedUnclear bool
	// InSprint is the real sprint according to the tracker, as sprint id of the tool (resolved
	// on import).
	InSprint *string
	// SprintName is the sprint name as the tracker exports it (kept when it could not be
	// resolved).
	SprintName *string
	// Rank of the tracker (order within the backlog); compared as text.
	Rank       *string
	Epic       *string
	Labels     []string
	Components []string
	// DependsOn are the keys of tickets that must be finished first.
	DependsOn []string
	Project   *string
	// ProjectCandidates are the projects whose rules match via the same source (contradiction;
	// Project stays empty).
	ProjectCandidates []string
	Done              bool
}

// Facts returns the ticket's values per rule source. in_sprint carries "true"/"false" and, when
// set, the sprint id, so that in_sprint: [true] and in_sprint: [2026.22] both work.
func (t Ticket) Facts() Facts {
	one := func(s *string) []string {
		if s == nil || *s == "" {
			return []string{}
		}
		return []string{*s}
	}
	inSprint := []string{"false"}
	if t.InSprint != nil && *t.InSprint != "" {
		inSprint = []string{"true", *t.InSprint}
	}
	facts := Facts{}
	for _, e := range t.Extra.Entries {
		facts[e.Key] = e.Value
	}
	facts["epic"] = one(t.Epic)
	facts["component"] = append([]string{}, t.Components...)
	facts["label"] = append([]string{}, t.Labels...)
	facts["status"] = one(t.Status)
	facts["issue_type"] = one(t.IssueType)
	facts["priority"] = one(t.Priority)
	facts["in_sprint"] = inSprint
	return facts
}

// Size is the number the distribution calculates with; nil = unestimated.
func (t Ticket) Size(uses PlanningUses) *float64 {
	if uses == UsesRemaining && t.Remaining != nil {
		return t.Remaining
	}
	return t.Estimate
}

// Earmark is the intent of the PO to put a ticket into a future sprint (preplan.yaml).
type Earmark struct {
	Ticket string
	Sprint string
	Note   *string
}

// ManualEstimate is an estimate entered by the PO for a ticket without (usable) estimate
// (preplan.yaml).
type ManualEstimate struct {
	Ticket   string
	Estimate *float64
	Note     *string
}

// Preplan is the content of preplan.yaml: earmarks and manual estimates, each at most once per
// ticket.
type Preplan struct {
	Earmarks  []Earmark
	Estimates []ManualEstimate
}

// EarmarkFor returns the earmark of the ticket, or nil.
func (p Preplan) EarmarkFor(key string) *Earmark {
	for i := range p.Earmarks {
		if p.Earmarks[i].Ticket == key {
			return &p.Earmarks[i]
		}
	}
	return nil
}

// EstimateFor returns the manual estimate of the ticket, or nil.
func (p Preplan) EstimateFor(key string) *ManualEstimate {
	for i := range p.Estimates {
		if p.Estimates[i].Ticket == key {
			return &p.Estimates[i]
		}
	}
	return nil
}
