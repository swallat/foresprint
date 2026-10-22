// Package planning has the amounts the Pre-plan and Plan views show next to the Forecast PLAN:
// the plannable amount and the small stuff, the production demand against the production time,
// and the conversion between story points and person days. These are new in 1.0 (no Python
// original); the formulas are those of flows.md, decisions 19 and 20.
package planning

import (
	"math"

	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/pymath"
)

// Split is the Forecast PLAN of a sprint split into carry-over, plannable amount and small
// stuff, in the team's estimation unit.
type Split struct {
	Plan float64 `json:"plan"`
	// CarryIn is the carried-over rest that continues in this sprint (what occupies it
	// already).
	CarryIn float64 `json:"carry_in"`
	// Share is the plannable share (forecast.roadmap_share).
	Share float64 `json:"share"`
	// Plannable is "Verplanbar": (PLAN − CarryIn) × Share, rounded down.
	Plannable float64 `json:"plannable"`
	// SmallStuff is "Kleinkram": what remains of PLAN − CarryIn.
	SmallStuff float64 `json:"small_stuff"`
	// Overbooked: the carry-over alone exceeds the PLAN (nothing is plannable; a hint, no
	// block).
	Overbooked bool `json:"overbooked"`
}

// SplitPlan splits the PLAN: Plannable = rounded down((PLAN − CarryIn) × share) with the
// rounding digits of the team, SmallStuff the rest. A carry-over above the PLAN leaves nothing
// to plan (Overbooked).
func SplitPlan(plan, carryIn, share float64, digits int) Split {
	s := Split{Plan: plan, CarryIn: carryIn, Share: share}
	free := plan - carryIn
	if free < 0 {
		s.Overbooked = true
		free = 0
	}
	s.Plannable = engine.RoundDown(float64(free*share), digits)
	s.SmallStuff = free - s.Plannable
	if s.SmallStuff < 0 {
		s.SmallStuff = 0
	}
	return s
}

// Item is a piece of work with an estimate and its production share.
type Item struct {
	// Estimate in the team's estimation unit.
	Estimate float64
	// ProductionShare is the part of the estimate that needs production access, 0 to 1; 1 means
	// production only. Values outside 0..1 are cut.
	ProductionShare float64
}

// Status of the production load: a hint, it never blocks.
type Status string

// The statuses of the production load.
const (
	StatusOK    Status = "ok"
	StatusTight Status = "tight"
	StatusOver  Status = "over"
)

// TightAbove is the load above which the production time is tight; OverAbove the load above
// which it is exceeded (share of the available production time).
const (
	TightAbove = 0.8
	OverAbove  = 1.0
)

// Production compares the production demand of the planned work with the production time of a
// sprint, in PD.
type Production struct {
	// Demand is the production part of the planned work in PD.
	Demand float64 `json:"demand"`
	// Available is the production time in PD (after absences and the cap).
	Available float64 `json:"available"`
	// Load is Demand / Available; nil if there is no available time (and then Status says
	// whether there is demand at all).
	Load   *float64 `json:"load"`
	Status Status   `json:"status"`
}

// DemandOf is the production demand in PD of the items: Σ (estimate × production share) ÷ rate,
// rate being the unit per PD (points per person day; 1 if the team plans in PD). ok is false
// without a usable rate.
func DemandOf(items []Item, rate float64) (demand float64, ok bool) {
	if !(rate > 0) || math.IsInf(rate, 0) {
		return 0, false
	}
	parts := make([]float64, len(items))
	for i, it := range items {
		parts[i] = float64(it.Estimate * math.Min(math.Max(it.ProductionShare, 0), 1))
	}
	return pymath.Sum(parts) / rate, true
}

// Compare sets the demand against the available production time: tight above 80 %, over above
// 100 %. Without available time any demand is over, no demand is fine.
func Compare(demand, available float64) Production {
	p := Production{Demand: demand, Available: available, Status: StatusOK}
	if available > 0 {
		load := demand / available
		p.Load = &load
		switch {
		case load > OverAbove:
			p.Status = StatusOver
		case load > TightAbove:
			p.Status = StatusTight
		}
		return p
	}
	if demand > 0 {
		p.Status = StatusOver
	}
	return p
}

// Rate converts between story points and person days with a points-per-PD rate: the measured
// team rate (normalized velocity of the sprint) or a fixed factor of the team.
type Rate float64

// Valid reports whether the rate can convert.
func (r Rate) Valid() bool { return r > 0 && !math.IsInf(float64(r), 0) }

// ToPD converts points to person days; ok is false for an invalid rate.
func (r Rate) ToPD(points float64) (float64, bool) {
	if !r.Valid() {
		return 0, false
	}
	return points / float64(r), true
}

// ToPoints converts person days to points; ok is false for an invalid rate.
func (r Rate) ToPoints(pd float64) (float64, bool) {
	if !r.Valid() {
		return 0, false
	}
	return float64(pd * float64(r)), true
}
