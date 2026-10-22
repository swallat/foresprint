package preplan

import (
	"slices"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/storage"
)

// carryIns are the carried rests that continue in the horizon sprints (decisions 14 and 17), by
// planning.CarryInto: per sprint id the amount per product (nil = the implicit product), the
// production part of it, and the tickets whose rest is counted that way, with the sprint they
// continue in (they must neither be counted again as fixed points nor distributed again). A
// rest without ticket, or of a ticket without product, is split over the products by share.
type carryIns struct {
	Amount     map[cellKey]float64
	Production map[cellKey]float64
	Target     map[string]string
}

func carryInsOf(data *storage.TeamData, horizon []model.Sprint, resolve func(model.Ticket) *string) carryIns {
	out := carryIns{Amount: map[cellKey]float64{}, Production: map[cellKey]float64{}, Target: map[string]string{}}
	byKey := map[string]model.Ticket{}
	for _, tk := range data.Tickets {
		byKey[tk.Key] = tk
	}
	// All sprints oldest first, so that a rest without target finds the sprint after its own.
	all := append([]model.Sprint(nil), data.Sprints...)
	for _, h := range horizon {
		if !slices.ContainsFunc(all, func(s model.Sprint) bool { return s.ID == h.ID }) {
			all = append(all, h)
		}
	}
	slices.SortStableFunc(all, func(a, b model.Sprint) int { return a.Start.Compare(b.Start) })
	for _, to := range horizon {
		for _, it := range planning.CarryInto(all, to.ID, "").Items {
			if it.Rest <= 0 {
				continue
			}
			var product *string
			var share float64
			named := false
			if it.Ticket != nil && *it.Ticket != "" {
				if tk, ok := byKey[*it.Ticket]; ok {
					product = resolve(tk)
					share, _ = ProductionShareOf(tk, data)
					named = product != nil || !data.Team.Features.Products
					out.Target[tk.Key] = to.ID
				}
			}
			if named {
				out.Amount[keyOf(to.ID, product)] += it.Rest
				out.Production[keyOf(to.ID, product)] += it.Rest * share / 100
				continue
			}
			for _, ps := range productShares(data, to) {
				out.Amount[keyOf(to.ID, ps.product)] += it.Rest * ps.share
				out.Production[keyOf(to.ID, ps.product)] += it.Rest * ps.share * share / 100
			}
		}
	}
	return out
}

// applyCarry takes the carried rests off the budgets: the plannable amount is (PLAN − carry) ×
// share, rounded down (planning.SplitPlan); with the whole-PLAN basis the plain difference.
func applyCarry(list []Budget, carry carryIns, data *storage.TeamData) {
	for i := range list {
		b := &list[i]
		in := carry.Amount[keyOf(b.Sprint, b.Product)]
		if in <= 0 {
			continue
		}
		fc := data.Team.Forecast
		whole := max(b.Plan-in, 0)
		roadmap := splitRoadmap(b.Plan, in, fc.RoadmapShare, fc.Rounding)
		if data.Team.Tracker.BudgetBasis == model.BudgetPlan {
			b.Base = whole
		} else {
			b.Base = roadmap
		}
		b.Plan, b.Roadmap = whole, roadmap
	}
}

func splitRoadmap(plan, carry, share float64, digits int) float64 {
	return planning.SplitPlan(plan, carry, share, digits).Plannable
}
