package preplan

import (
	"slices"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/storage"
)

// carryOf is the carry-over of a sprint that counts: the rest entered in the Review, else the
// one of the latest assumption (prognosis) with a carry-over.
func carryOf(s model.Sprint) []model.CarryItem {
	if len(s.Carry) > 0 {
		return s.Carry
	}
	for i := len(s.Prognoses) - 1; i >= 0; i-- {
		if len(s.Prognoses[i].Carry) > 0 {
			return s.Prognoses[i].Carry
		}
	}
	return nil
}

// carryIns are the carried rests that continue in the horizon sprints (decisions 14 and 17):
// per sprint id the amount per product (nil = the implicit product or no ticket), and the
// tickets whose rest is counted that way (they must not be counted again as fixed points).
// A rest with target "" continues in the sprint after the one it comes from, with a sprint id
// there; backlog and pro-forma sprints take no capacity. A rest without ticket is split over
// the products by their shares.
type carryIns struct {
	Amount  map[cellKey]float64
	Tickets map[string]map[string]bool
}

func carryInsOf(data *storage.TeamData, sprints []model.Sprint, resolve func(model.Ticket) *string) carryIns {
	out := carryIns{Amount: map[cellKey]float64{}, Tickets: map[string]map[string]bool{}}
	byKey := map[string]model.Ticket{}
	for _, tk := range data.Tickets {
		byKey[tk.Key] = tk
	}
	inHorizon := func(id string) bool {
		return slices.ContainsFunc(sprints, func(s model.Sprint) bool { return s.ID == id })
	}
	for _, from := range data.Sprints {
		items := carryOf(from)
		for _, it := range items {
			if it.Rest <= 0 {
				continue
			}
			target := it.Target
			if target == "" {
				for _, s := range sprints {
					if !s.Start.Before(from.End) && s.ID != from.ID {
						target = s.ID
						break
					}
				}
			}
			if target == "" || target == model.CarryBacklog || len(target) >= len(model.CarryProForma) && target[:len(model.CarryProForma)] == model.CarryProForma {
				continue
			}
			if !inHorizon(target) {
				continue
			}
			if it.Ticket != nil && *it.Ticket != "" {
				var product *string
				if tk, ok := byKey[*it.Ticket]; ok {
					product = resolve(tk)
				}
				out.Amount[keyOf(target, product)] += it.Rest
				if out.Tickets[target] == nil {
					out.Tickets[target] = map[string]bool{}
				}
				out.Tickets[target][*it.Ticket] = true
				continue
			}
			var to model.Sprint
			for _, s := range sprints {
				if s.ID == target {
					to = s
				}
			}
			for _, ps := range productShares(data, to) {
				out.Amount[keyOf(target, ps.product)] += it.Rest * ps.share
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
