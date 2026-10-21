package products_test

import (
	"testing"

	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
)

type rowView struct {
	Product           string   `json:"product"`
	Name              string   `json:"name"`
	PO                *string  `json:"po"`
	Active            bool     `json:"active"`
	Standard          *float64 `json:"standard"`
	Preplanned        *float64 `json:"preplanned"`
	Planned           *float64 `json:"planned"`
	Done              *float64 `json:"done"`
	ProductionPlanned *float64 `json:"production_planned"`
	ProductionDone    *float64 `json:"production_done"`
}

type poView struct {
	PO     string              `json:"po"`
	Totals map[string]*float64 `json:"totals"`
}

type distributionView struct {
	Sprint               string              `json:"sprint"`
	Plan                 *float64            `json:"plan"`
	PlanFrozen           bool                `json:"plan_frozen"`
	Basis                string              `json:"basis"`
	Available            *float64            `json:"available"`
	CurrentPlan          *float64            `json:"current_plan"`
	ProductionShare      *float64            `json:"production_share"`
	ProductionAvailable  *float64            `json:"production_available"`
	ProductionConfigured bool                `json:"production_configured"`
	ProductionState      string              `json:"production_state"`
	ProductionOverload   *float64            `json:"production_overload"`
	ActiveCount          int                 `json:"active_count"`
	Rows                 []rowView           `json:"rows"`
	Totals               map[string]*float64 `json:"totals"`
	Has                  map[string]bool     `json:"has"`
	ByPO                 []poView            `json:"by_po"`
}

type planView struct {
	Sprint     string   `json:"sprint"`
	Current    *float64 `json:"current"`
	Frozen     *float64 `json:"frozen"`
	Difference *float64 `json:"difference"`
}

type handledView struct {
	Sprint   string   `json:"sprint"`
	Products []string `json:"products"`
}

type balanceView struct {
	Product    string  `json:"product"`
	Sprints    int     `json:"sprints"`
	Standard   float64 `json:"standard"`
	Done       float64 `json:"done"`
	Missing    int     `json:"missing"`
	Difference float64 `json:"difference"`
}

func balances(fc *forecast.Forecast, entries []*forecast.TimelineEntry) []balanceView {
	out := []balanceView{}
	for _, b := range products.BalanceOf(fc, entries) {
		out = append(out, balanceView{b.Product.ID, b.Sprints, b.Standard, b.Done, b.Missing, b.Difference()})
	}
	return out
}

func view(d *products.Distribution) distributionView {
	v := distributionView{
		Sprint: d.Sprint.ID, Plan: d.Plan, PlanFrozen: d.PlanFrozen, Basis: string(d.Basis),
		Available: d.Available, CurrentPlan: d.CurrentPlan, ProductionShare: d.ProductionShare,
		ProductionAvailable: d.ProductionAvailable, ProductionConfigured: d.ProductionConfigured,
		ProductionState: d.ProductionState(), ProductionOverload: d.ProductionOverload(),
		ActiveCount: d.ActiveCount(), Rows: []rowView{}, Totals: map[string]*float64{},
		Has: map[string]bool{}, ByPO: []poView{},
	}
	for _, r := range d.Rows {
		v.Rows = append(v.Rows, rowView{
			Product: r.Product.ID, Name: r.Product.Name, PO: r.Product.PO, Active: r.Active,
			Standard: r.Standard, Preplanned: r.Preplanned, Planned: r.Planned, Done: r.Done,
			ProductionPlanned: r.ProductionPlanned, ProductionDone: r.ProductionDone,
		})
	}
	for _, m := range append(append([]products.Measure{}, products.Measures...), products.ProductionMeasures...) {
		v.Totals[m.Key] = d.Total(m.Key)
		v.Has[m.Key] = d.Has(m.Key)
	}
	for _, po := range products.ByPO(d) {
		v.ByPO = append(v.ByPO, poView{PO: po.PO, Totals: po.Totals})
	}
	return v
}

// The distribution of every sprint of every golden case equals the one of the Python core.
func TestDistributionMatchesPython(t *testing.T) {
	for _, c := range golden.Cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			var want any
			golden.Load(t, &want, "products", c.Name+".json")
			fc, err := forecast.Build(coretest.Load(t, c), coretest.Today(t, c))
			if err != nil {
				t.Fatal(err)
			}
			got := map[string]any{
				"distributions":   []distributionView{},
				"plan_views":      []planView{},
				"sprint_products": []handledView{},
			}
			var all []*forecast.TimelineEntry
			var dist []distributionView
			var plans []planView
			var handled []handledView
			for i := range fc.Entries {
				e := &fc.Entries[i]
				all = append(all, e)
				d := products.Distribute(fc, e)
				dist = append(dist, view(&d))
				pv := products.ViewOf(e)
				plans = append(plans, planView{e.Sprint.ID, pv.Current, pv.Frozen, pv.Difference()})
				ids := []string{}
				for _, p := range products.SprintProducts(fc.Data.Products, e.Sprint) {
					ids = append(ids, p.ID)
				}
				handled = append(handled, handledView{e.Sprint.ID, ids})
			}
			got["distributions"] = dist
			got["plan_views"] = plans
			got["sprint_products"] = handled
			got["balance"] = balances(fc, all)
			got["balance_last3"] = balances(fc, fc.HistoryLast(3))
			golden.Compare(t, want, coretest.JSON(t, got))
		})
	}
}

// The standard shares, the labels and the footnote equal those of the Python core.
func TestMiscMatchesPython(t *testing.T) {
	var want struct {
		StandardShares []struct {
			Available *float64            `json:"available"`
			Shares    map[string]*float64 `json:"shares"`
			Result    map[string]float64  `json:"result"`
		} `json:"standard_shares"`
		Labels   map[string]string `json:"labels"`
		Footnote string            `json:"footnote"`
	}
	golden.Load(t, &want, "products", "misc.json")
	if len(want.StandardShares) == 0 {
		t.Fatal("no references")
	}
	for i, c := range want.StandardShares {
		var active []model.Product
		// The reference lists the shares in the order of the products (JSON object order is
		// lost), so the active products are rebuilt in the order of their IDs: a, b, c, d.
		for _, id := range []string{"a", "b", "c", "d"} {
			if share, ok := c.Shares[id]; ok {
				active = append(active, model.Product{ID: id, Name: id, Share: share})
			}
		}
		got := products.StandardShares(active, c.Available)
		golden.Compare(t, coretest.JSON(t, c.Result), coretest.JSON(t, got))
		if len(got) != len(c.Result) {
			t.Errorf("case %d: %v, Python %v", i, got, c.Result)
		}
	}
	for key, label := range want.Labels {
		if got := products.MeasureLabelIn("en", key); got != label {
			t.Errorf("label %s = %q, Python %q", key, got, label)
		}
	}
	if got := products.MissingFootnote(); got != want.Footnote {
		t.Errorf("footnote:\n got %q\nwant %q", got, want.Footnote)
	}
	if i18n.TIn("de", want.Footnote) == want.Footnote {
		t.Error("the footnote has no German text in the catalog")
	}
}
