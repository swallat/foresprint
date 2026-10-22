package model

import (
	"regexp"
	"time"

	"github.com/swallat/foresprint/internal/rules"
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
var RuleSources = rules.Sources

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
	OpLeaf = rules.OpLeaf
	OpAny  = rules.OpAny
	OpAll  = rules.OpAll
	OpNone = rules.OpNone
)

// RuleOperators are the operators of the long form.
var RuleOperators = []string{OpAny, OpAll, OpNone}

// DefaultMatchOrder is the default order in which the sources decide between two matching
// projects.
var DefaultMatchOrder = []string{"epic", "component", "label"}

// DefaultPriorityOrder is Jira's standard priorities, most important first.
var DefaultPriorityOrder = []string{"Highest", "High", "Medium", "Low", "Lowest"}

// Rule is one node of an assignment rule; the type, its evaluation and its text form live in
// package rules.
type Rule = rules.Rule

// Facts are the values of a ticket per rule source.
type Facts = rules.Facts

// TrackerFields are the display names of the tracker fields (as in the instance or the CSV
// export header).
type TrackerFields struct {
	Estimate  *string
	Remaining *string
	Epic      *string
	// Status, Acceptance, Product, Project, Refined and Production are the fields the values of
	// the same name come from; nil = not mapped (rules or by hand, decision 21).
	Status     *string
	Acceptance *string
	Product    *string
	Project    *string
	Refined    *string
	Production *string
}

// RemovedTargets are the places a ticket goes that was taken out of the tracker's sprint in
// planning (tracker.removed_target).
var RemovedTargets = []string{"backlog", "pro_forma", "next"}

// TrackerKinds are the kinds of ticket sources (tracker.kind).
var TrackerKinds = []string{"csv", "jira", PackagesKind}

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
	// ProductionLabel marks a ticket as production only (100 %); ProductionRules give other
	// tickets a share. Both apply when no value set in Foresprint or mapped field exists.
	ProductionLabel *string
	ProductionRules []ProductionRule
	// WriteSprint writes the planned sprint back to the tracker (off by default, only on an
	// explicit action). RemovedTarget says where a ticket taken out of the tracker's sprint
	// goes then, one of RemovedTargets ("" = backlog).
	WriteSprint   bool
	RemovedTarget string
	// PackagePrefix starts the keys of work packages; empty = DefaultPackagePrefix.
	PackagePrefix string
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
	// AlsoProducts are further products of the project besides Product; the project touches
	// all of them (decision: products per project as a list).
	AlsoProducts []string
	Start        *time.Time
	Milestones   []Milestone
	Contingent   Contingent
	// State and End: a closed project has an end date and is listed under "closed projects".
	State ProjectState
	End   *time.Time
	// ClosedAt is the day the project was finished or cancelled; End keeps the planned end.
	ClosedAt *time.Time
	// OpenScope is the open scope of the project without tickets, kept by hand.
	OpenScope *float64
	// Contact is the person to ask about the project (free text).
	Contact *string
}

// Products returns all products of the project, Product first.
func (p Project) Products() []string {
	var out []string
	if p.Product != nil && *p.Product != "" {
		out = append(out, *p.Product)
	}
	return append(out, p.AlsoProducts...)
}

// Closed reports whether the project is finished or cancelled.
func (p Project) Closed() bool { return p.State != ProjectOpen }

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
	// Description to Comments are kept in the team data only for work packages; for tracker
	// tickets they are read on each sync and cached per machine.
	Description *string
	Acceptance  *string
	Assignee    *string
	// Product is the product of a work package.
	Product  *string
	Subtasks []Subtask
	Comments []Comment
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
	// Production are the production shares set by hand, Overrides the product and project
	// decisions of the PO against the rules.
	Production []ProductionShare
	Overrides  []TicketOverride
}

// ProductionFor returns the production share set by hand for the ticket, or nil.
func (p Preplan) ProductionFor(key string) *ProductionShare {
	for i := range p.Production {
		if p.Production[i].Ticket == key {
			return &p.Production[i]
		}
	}
	return nil
}

// OverrideFor returns the product and project decision of the PO for the ticket, or nil.
func (p Preplan) OverrideFor(key string) *TicketOverride {
	for i := range p.Overrides {
		if p.Overrides[i].Ticket == key {
			return &p.Overrides[i]
		}
	}
	return nil
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

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func samePtr[T comparable](a, b *T) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// IsDefault reports whether the settings equal NewTrackerSettings (a rule counts as different).
func (t TrackerSettings) IsDefault() bool {
	d := NewTrackerSettings()
	return t.Kind == d.Kind && samePtr(t.BaseURL, d.BaseURL) && samePtr(t.Query, d.Query) &&
		t.Fields == d.Fields && t.PlanningUses == d.PlanningUses &&
		samePtr(t.RefinedLabel, d.RefinedLabel) && t.RefinedAlsoIf == nil &&
		sameStrings(t.ProjectMatchOrder, d.ProjectMatchOrder) && sameStrings(t.PriorityOrder, d.PriorityOrder) &&
		t.DependencyGap == d.DependencyGap && t.BudgetBasis == d.BudgetBasis && t.RoughFactor == d.RoughFactor &&
		t.WriteLabels == d.WriteLabels && t.SprintNames.Len() == 0 && t.LinkType == d.LinkType &&
		t.RuleFields.Len() == 0 && samePtr(t.ProductionLabel, d.ProductionLabel) &&
		len(t.ProductionRules) == 0 && !t.WriteSprint && t.RemovedTarget == "" && t.PackagePrefix == ""
}
