// Package preplan distributes the open tickets over the future sprints (ticket pre-planning);
// port of preplan.py. It is a pure calculation on top of the forecast; nothing is stored.
//
//	Budget[s, p] = share[p] × base[s] − fixed points (tickets in the sprint according to the
//	               tracker, earmarks) − tickets placed by the distribution
//	base[s]      = Forecast PLAN × plannable share (budget_basis roadmap_share) or the whole
//	               Forecast PLAN (plan); per team, overridable per project
//	Order        = tickets by priority, then project (target date, priority) and rank;
//	               dependencies first (topological)
//	Placement    = earliest sprint from (latest sprint of the dependencies + dependency_gap)
//	               whose free budget for the product suffices
//	Variants     = the same distribution with a conservative, median and optimistic plan per
//	               sprint; "median" is the Forecast PLAN as the forecast shows it
package preplan

import (
	"time"

	"github.com/swallat/foresprint/internal/model"
)

// Traffic lights of a project, from good to bad (empty = project without open tickets), and
// backlog for the tickets of a product without a project.
const (
	LightOnTrack = "on_track"
	LightTight   = "tight"
	LightMissed  = "missed"
	LightEmpty   = "empty"
	LightBacklog = "backlog"
)

// Lights are the display texts of the traffic lights (English source texts).
var Lights = map[string]string{
	LightOnTrack: "on track",
	LightTight:   "tight",
	LightMissed:  "missed",
	LightEmpty:   "empty",
	LightBacklog: "no target date",
}

// LightOrder lists the traffic lights from good to bad.
var LightOrder = []string{LightEmpty, LightOnTrack, LightTight, LightMissed}

// Variant says which plan per sprint the distribution calculates with.
type Variant string

// The variants. Median is the Forecast PLAN as the forecast shows it.
const (
	Conservative Variant = "conservative"
	Median       Variant = "median"
	Optimistic   Variant = "optimistic"
)

// VariantNames are the display texts of the variants (English source texts).
var VariantNames = map[Variant]string{
	Conservative: "conservative",
	Median:       "median",
	Optimistic:   "optimistic",
}

// Reasons why a ticket is in its sprint, or why it is not distributable.
const (
	ReasonPlaced        = "placed"
	ReasonFixedSprint   = "fixed_sprint"
	ReasonEarmark       = "earmark"
	ReasonUnestimated   = "unestimated"
	ReasonTooLarge      = "too_large"
	ReasonNoBudget      = "no_budget"
	ReasonNoProduct     = "no_product"
	ReasonCycle         = "cycle"
	ReasonBlocked       = "blocked"
	ReasonBeyondHorizon = "beyond_horizon"
)

// Reasons are the display texts of the reasons (English source texts).
var Reasons = map[string]string{
	ReasonPlaced:        "distributed",
	ReasonFixedSprint:   "sprint according to the tracker",
	ReasonEarmark:       "earmark",
	ReasonUnestimated:   "unestimated",
	ReasonTooLarge:      "too large, please split",
	ReasonNoBudget:      "no budget",
	ReasonNoProduct:     "without product",
	ReasonCycle:         "circular dependencies",
	ReasonBlocked:       "dependency not distributable",
	ReasonBeyondHorizon: "beyond the horizon",
}

// Sources are the display texts of where an estimate comes from (English source texts).
var Sources = map[model.EstimateSource]string{
	model.EstimateRefined: "refined",
	model.EstimateRough:   "rough estimate",
	model.EstimateManual:  "own estimate",
	model.EstimateNone:    "no estimate",
}

// placedReasons are the reasons of a ticket that is in a sprint (fixed or distributed).
func placedReason(reason string) bool {
	return reason == ReasonPlaced || reason == ReasonFixedSprint || reason == ReasonEarmark
}

// eps is the tolerance of the budget comparison (floating point).
const eps = 1e-9

// Budget is what a sprint can take on for one product.
type Budget struct {
	Sprint string `json:"sprint"`
	// Product is the product id; nil is the implicit product of a team without the products
	// feature.
	Product *string `json:"product"`
	// Base is the plannable amount by the team's budget basis.
	Base float64 `json:"base"`
	// Plan and Roadmap are the same amount by the whole Forecast PLAN and by its plannable
	// share (for projects that override the basis).
	Plan    float64 `json:"plan"`
	Roadmap float64 `json:"roadmap"`
	// Fixed is consumed by tickets that are in the sprint according to the tracker and by
	// earmarks.
	Fixed float64 `json:"fixed"`
	// Placed is consumed by the distribution.
	Placed float64 `json:"placed"`
	// ProductionAvailable is what the people with production access can do in the sprint (only
	// reported, never added).
	ProductionAvailable *float64 `json:"production_available"`
}

// Limit is the plannable amount by basis ("" = the team's basis).
func (b Budget) Limit(basis model.BudgetBasis) float64 {
	switch basis {
	case model.BudgetPlan:
		return b.Plan
	case model.BudgetRoadmapShare:
		return b.Roadmap
	}
	return b.Base
}

// FreeFor is what is left for a project with basis; negative means the fixed points overflow.
func (b Budget) FreeFor(basis model.BudgetBasis) float64 {
	return b.Limit(basis) - b.Fixed - b.Placed
}

// Free is what is left on the team's basis.
func (b Budget) Free() float64 { return b.FreeFor("") }

// Placement says where a ticket ended up and why (one per open ticket).
type Placement struct {
	Ticket string `json:"ticket"`
	// Sprint is nil when the ticket is not distributable (see Reason).
	Sprint *string `json:"sprint"`
	Reason string  `json:"reason"`
	// Size is the number the distribution calculated with; nil = unestimated.
	Size   *float64             `json:"size"`
	Source model.EstimateSource `json:"source"`
	// Project is the ticket's project; Product the product whose budget the ticket uses (its
	// project's, else by a product rule); nil = none found, or no product distribution.
	Project *string `json:"project"`
	Product *string `json:"product"`
}

// Distributable reports whether the ticket is in a sprint.
func (p Placement) Distributable() bool { return placedReason(p.Reason) }

// ProjectStatus is the traffic light of a project.
type ProjectStatus struct {
	Project string `json:"project"`
	Light   string `json:"light"`
	// TargetSprint is the last sprint ending on or before the target date (the current sprint
	// when the target lies inside it); nil without target date or outside the horizon.
	TargetSprint *string `json:"target_sprint"`
	// LastSprint is the sprint of the project's last ticket; nil without placed tickets.
	LastSprint       *string `json:"last_sprint"`
	OpenTickets      int     `json:"open_tickets"`
	NotDistributable int     `json:"not_distributable"`
}

// RefinementItem is a ticket that has to be refined before its sprint is planned.
type RefinementItem struct {
	Ticket string `json:"ticket"`
	Sprint string `json:"sprint"`
	// Deadline is the Planning of the sprint = the sprint start.
	Deadline time.Time            `json:"deadline"`
	Source   model.EstimateSource `json:"source"`
	// Unclear: refined status unclear.
	Unclear bool `json:"unclear"`
}

// Distribution is the result of Distribute.
type Distribution struct {
	// Sprints are the future sprints of the horizon in order.
	Sprints    []string         `json:"sprints"`
	Budgets    []Budget         `json:"budgets"`
	Placements []Placement      `json:"placements"`
	Projects   []ProjectStatus  `json:"projects"`
	Refinement []RefinementItem `json:"refinement"`
	// Unclear lists the open tickets with unclear refined status.
	Unclear []string `json:"unclear"`
	// Cycles are the dependency cycles (keys in dependency order), each once.
	Cycles [][]string `json:"cycles"`
	// Later maps sprints of fixed tickets or earmarks that lie after the horizon or are unknown
	// to their last day; nil = unknown sprint.
	Later map[string]*time.Time `json:"later"`
	// NoForecast is true when no sprint of the horizon has any budget at all.
	NoForecast bool `json:"no_forecast"`
	// Variant is the variant this distribution was calculated for.
	Variant Variant `json:"variant"`
}

// Placement returns the placement of a ticket, or nil.
func (d *Distribution) Placement(key string) *Placement {
	for i := range d.Placements {
		if d.Placements[i].Ticket == key {
			return &d.Placements[i]
		}
	}
	return nil
}

// Budget returns the budget of a sprint and product (nil product = implicit), or nil.
func (d *Distribution) Budget(sprint string, product *string) *Budget {
	for i := range d.Budgets {
		if d.Budgets[i].Sprint == sprint && samePtr(d.Budgets[i].Product, product) {
			return &d.Budgets[i]
		}
	}
	return nil
}

// Status returns the traffic light of a project, or nil.
func (d *Distribution) Status(projectID string) *ProjectStatus {
	for i := range d.Projects {
		if d.Projects[i].Project == projectID {
			return &d.Projects[i]
		}
	}
	return nil
}

// InSprint returns the placements in a sprint.
func (d *Distribution) InSprint(sprint string) []Placement {
	var out []Placement
	for _, p := range d.Placements {
		if p.Sprint != nil && *p.Sprint == sprint {
			out = append(out, p)
		}
	}
	return out
}

// NotDistributable returns the placements that are not in a sprint.
func (d *Distribution) NotDistributable() []Placement {
	var out []Placement
	for _, p := range d.Placements {
		if !p.Distributable() {
			out = append(out, p)
		}
	}
	return out
}

func samePtr(a, b *string) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

func strPtr(s string) *string { return &s }
