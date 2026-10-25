// Package products distributes the sprint quantity across the team's products. It ports
// src/foresprint/products.py.
//
// Per product and sprint:
//
//	Standard     = available quantity × the product's agreed share, or (available quantity −
//	               Σ fixed shares) / number of products without a fixed share. Available is the
//	               Forecast PLAN (frozen at Planning, otherwise current) or only its plannable
//	               part (setting forecast.product_basis).
//	Pre-planning = intended on the PO side (before Planning)
//	Planning     = scheduled in Sprint Planning
//	Done         = actually completed, as recorded in Review
//	Balance      = Σ Done − Σ Standard over several sprints
package products

import (
	"slices"

	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
)

// Measures are the columns of the report, in order (attribute → display name, English).
var Measures = []Measure{
	{"standard", "Standard"},
	{"preplanned", "PO pre-planning"},
	{"planned", "Planning"},
	{"done", "Done"},
}

// ProductionMeasures are the "of which" values for tickets that require production access (a
// subset of Planning and Done).
var ProductionMeasures = []Measure{
	{"production_planned", "of which production access (planning)"},
	{"production_done", "of which production access (done)"},
}

// Measure is a column: its key and its English display name.
type Measure struct {
	Key  string
	Name string
}

// MeasureLabel is the display name of a measure in the language in use; a key that is not a
// measure gives the empty text.
func MeasureLabel(measure string) string {
	return MeasureLabelIn(i18n.Language(), measure)
}

// MeasureLabelIn is MeasureLabel for a given language.
func MeasureLabelIn(lang, measure string) string {
	for _, m := range append(slices.Clone(Measures), ProductionMeasures...) {
		if m.Key == measure {
			return i18n.TIn(lang, m.Name)
		}
	}
	return ""
}

// SprintProducts are the products handled in the sprint plus those with recorded values
// (catalog order). Unknown IDs appear with the ID as their name so that no values disappear
// (in the order of their IDs).
func SprintProducts(products []model.Product, sprint model.Sprint) []model.Product {
	known := map[string]bool{}
	for _, p := range products {
		known[p.ID] = true
	}
	var result []model.Product
	for _, p := range products {
		if p.ActiveBetween(sprint.Start, sprint.End) || !sprint.Products[p.ID].IsEmpty() {
			result = append(result, p)
		}
	}
	ids := make([]string, 0, len(sprint.Products))
	for id := range sprint.Products {
		if !known[id] {
			ids = append(ids, id)
		}
	}
	slices.Sort(ids)
	for _, id := range ids {
		result = append(result, model.Product{ID: id, Name: id})
	}
	return result
}

// Row is one product of a sprint.
type Row struct {
	Product model.Product
	// Active: handled in the sprint; only these products get a standard share.
	Active            bool
	Standard          *float64
	Preplanned        *float64
	Planned           *float64
	Done              *float64
	ProductionPlanned *float64
	ProductionDone    *float64
}

// Value is the value of a measure ("standard", "preplanned", "planned", "done",
// "production_planned", "production_done"); nil for no value or an unknown measure.
func (r Row) Value(measure string) *float64 {
	switch measure {
	case "standard":
		return r.Standard
	case "preplanned":
		return r.Preplanned
	case "planned":
		return r.Planned
	case "done":
		return r.Done
	case "production_planned":
		return r.ProductionPlanned
	case "production_done":
		return r.ProductionDone
	}
	return nil
}

// Production states of a distribution.
const (
	// ProductionUnconfigured: nobody is marked as authorized.
	ProductionUnconfigured = "unconfigured"
	// ProductionUnavailable: authorized people are marked, but without capacity in the sprint.
	ProductionUnavailable = "unavailable"
	// ProductionOK: the group has capacity.
	ProductionOK = "ok"
)

// Distribution is the distribution of one sprint over the products.
type Distribution struct {
	Sprint model.Sprint
	// Plan is the Forecast PLAN of the sprint and PlanFrozen says whether it was frozen at
	// Planning.
	Plan       *float64
	PlanFrozen bool
	Basis      model.ProductBasis
	// Available is the distributable quantity (Forecast PLAN or its plannable part).
	Available *float64
	Rows      []Row
	// ProductionShare is the share of capacity held by people with production access (nil = no
	// group) and ProductionAvailable the quantity this group can handle in the sprint (share ×
	// Forecast PLAN).
	ProductionShare     *float64
	ProductionAvailable *float64
	// ProductionConfigured: is anybody marked as authorized at all? Without any mark the
	// configuration is unknown, which is different from "authorized people are not available in
	// this sprint".
	ProductionConfigured bool
	// Features are the areas the team uses (controls columns and hints in the UI).
	Features model.Features
	// CurrentPlan is the currently calculated Forecast PLAN (differs from Plan if that one is
	// frozen).
	CurrentPlan *float64
}

// ProductionState is ProductionUnconfigured, ProductionUnavailable or ProductionOK.
func (d *Distribution) ProductionState() string {
	switch {
	case !d.ProductionConfigured:
		return ProductionUnconfigured
	case d.ProductionShare == nil || *d.ProductionShare == 0:
		return ProductionUnavailable
	}
	return ProductionOK
}

// ProductionOverload is by how much the Planning with production access exceeds the group; nil
// if it does not (or if either is unknown).
func (d *Distribution) ProductionOverload() *float64 {
	planned := d.Total("production_planned")
	if planned == nil || d.ProductionAvailable == nil {
		return nil
	}
	over := *planned - *d.ProductionAvailable
	if over > 0.05 {
		return &over
	}
	return nil
}

// ActiveCount is the number of products handled in the sprint.
func (d *Distribution) ActiveCount() int {
	n := 0
	for _, r := range d.Rows {
		if r.Active {
			n++
		}
	}
	return n
}

// Total is the sum of a measure over the products; nil if no product has a value.
func (d *Distribution) Total(measure string) *float64 {
	var values []float64
	for _, r := range d.Rows {
		if v := r.Value(measure); v != nil {
			values = append(values, *v)
		}
	}
	if len(values) == 0 {
		// Teams without a product distribution record the production-access quantities per
		// sprint.
		switch measure {
		case "production_planned":
			return d.Sprint.ProductionPlanned
		case "production_done":
			return d.Sprint.ProductionDone
		}
		return nil
	}
	return model.Ptr(pymath.Sum(values))
}

// Has reports whether any product has a value for the measure.
func (d *Distribution) Has(measure string) bool {
	for _, r := range d.Rows {
		if r.Value(measure) != nil {
			return true
		}
	}
	return false
}

// PlanOf is the Forecast PLAN of a sprint: frozen at Planning, otherwise as currently
// calculated; the flag says whether it is the frozen one.
func PlanOf(entry *forecast.TimelineEntry) (*float64, bool) {
	if entry.Sprint.ForecastPlan != nil {
		return entry.Sprint.ForecastPlan, true
	}
	return entry.Result.Plan, false
}

// PlanView are both states of a sprint's Forecast PLAN: currently calculated and frozen at
// Planning (nil until frozen).
type PlanView struct {
	Current *float64
	Frozen  *float64
}

// ViewOf is the PlanView of a sprint.
func ViewOf(entry *forecast.TimelineEntry) PlanView {
	return PlanView{Current: entry.Result.Plan, Frozen: entry.Sprint.ForecastPlan}
}

// Difference is current − at Planning; nil without a frozen or current value.
func (v PlanView) Difference() *float64 {
	if v.Current == nil || v.Frozen == nil {
		return nil
	}
	return model.Ptr(*v.Current - *v.Frozen)
}

// StandardShares is the standard quantity per handled product: fixed shares first, the rest
// evenly.
func StandardShares(active []model.Product, available *float64) map[string]float64 {
	if available == nil || len(active) == 0 {
		return map[string]float64{}
	}
	// Like the dicts of the Python original: a product ID that appears twice counts once (the
	// last value stays, at the position of the first).
	fixedValue := map[string]float64{}
	var fixedOrder []string
	var rest []model.Product
	for _, p := range active {
		if p.Share == nil {
			rest = append(rest, p)
			continue
		}
		if _, seen := fixedValue[p.ID]; !seen {
			fixedOrder = append(fixedOrder, p.ID)
		}
		fixedValue[p.ID] = float64(*available * *p.Share)
	}
	result := make(map[string]float64, len(active))
	fixed := make([]float64, 0, len(fixedOrder))
	for _, id := range fixedOrder {
		result[id] = fixedValue[id]
		fixed = append(fixed, fixedValue[id])
	}
	if len(rest) == 0 {
		return result
	}
	left := *available - pymath.Sum(fixed)
	if 0.0 > left { // like max(left, 0.0): keeps -0.0
		left = 0.0
	}
	for _, p := range rest {
		result[p.ID] = left / float64(len(rest))
	}
	return result
}

// Distribute distributes the sprint of the entry over the products.
func Distribute(fc *forecast.Forecast, entry *forecast.TimelineEntry) Distribution {
	data := fc.Data
	sprint := entry.Sprint
	basis := data.Team.Forecast.ProductBasis
	plan, frozen := PlanOf(entry)
	available := plan
	if plan != nil && basis == model.BasisRoadmap {
		available = model.Ptr(float64(*plan * data.Team.Forecast.RoadmapShare))
	}
	handled := SprintProducts(data.Products, sprint)
	known := map[string]bool{}
	for _, p := range data.Products {
		known[p.ID] = true
	}
	var active []model.Product
	isActive := make([]bool, len(handled))
	for i, p := range handled {
		if known[p.ID] && p.ActiveBetween(sprint.Start, sprint.End) {
			active = append(active, p)
			isActive[i] = true
		}
	}
	shares := StandardShares(active, available)
	rows := make([]Row, 0, len(handled))
	for i, p := range handled {
		values := sprint.Products[p.ID]
		row := Row{
			Product:           p,
			Active:            isActive[i],
			Preplanned:        values.Preplanned,
			Planned:           values.Planned,
			Done:              values.Done,
			ProductionPlanned: values.ProductionPlanned,
			ProductionDone:    values.ProductionDone,
		}
		if row.Active {
			if v, ok := shares[p.ID]; ok {
				row.Standard = model.Ptr(v)
			}
		}
		rows = append(rows, row)
	}
	d := Distribution{
		Sprint:     sprint,
		Plan:       plan,
		PlanFrozen: frozen,
		Basis:      basis,
		Available:  available,
		Rows:       rows,
		Features:   data.Team.Features,
		// The plan the entry carries now.
		CurrentPlan: entry.Result.Plan,
	}
	for _, p := range data.People {
		if p.ProductionAccess {
			d.ProductionConfigured = true
			break
		}
	}
	if share, ok := capacity.ProductionShare(&data.Team, data.People, sprint); ok {
		d.ProductionShare = &share
		if plan != nil {
			d.ProductionAvailable = model.Ptr(float64(*plan * share))
		}
	}
	return d
}

// MissingFootnote is the footnote for the "no value" column (terminal and report; plain text,
// no markup).
func MissingFootnote() string {
	return i18n.T("\"no value\": sprints in which the product was worked on but no done value is " +
		"entered, although it is entered for other products (empty, not 0). They do not " +
		"count towards the balance; please add the value in the sprint. Sprints without " +
		"any done value (e.g. the current one) and sprints outside the product's period " +
		"are left out.")
}

// Balance is the balance of a product over several sprints.
type Balance struct {
	Product  model.Product
	Sprints  int
	Standard float64
	Done     float64
	// Missing counts the sprints in which no "Done" is recorded for the product (missing is not
	// 0): they are not counted.
	Missing int
}

// Difference is Done − Standard; positive = more done than the standard share.
func (b Balance) Difference() float64 { return b.Done - b.Standard }

// BalanceOf is the balance per product over the sprints in which Done was recorded for the
// product. A missing value does not count as 0; such sprints are counted (Missing) and
// contribute neither to Done nor to the standard.
func BalanceOf(fc *forecast.Forecast, entries []*forecast.TimelineEntry) []Balance {
	order := map[string]int{}
	for i, p := range fc.Data.Products {
		order[p.ID] = i
	}
	var sums []*Balance
	index := map[string]*Balance{}
	for _, e := range entries {
		d := Distribute(fc, e)
		if !d.Has("done") {
			continue
		}
		for _, r := range d.Rows {
			if r.Standard == nil && r.Done == nil {
				continue
			}
			b := index[r.Product.ID]
			if b == nil {
				b = &Balance{Product: r.Product}
				index[r.Product.ID] = b
				sums = append(sums, b)
			}
			if r.Done == nil { // value missing: count neither as 0 nor with the standard
				b.Missing++
				continue
			}
			b.Sprints++
			if r.Standard != nil {
				b.Standard += *r.Standard
			}
			b.Done += *r.Done
		}
	}
	rank := func(b *Balance) int {
		if i, ok := order[b.Product.ID]; ok {
			return i
		}
		return len(order)
	}
	slices.SortStableFunc(sums, func(a, b *Balance) int { return rank(a) - rank(b) })
	result := make([]Balance, len(sums))
	for i, b := range sums {
		result[i] = *b
	}
	return result
}

// POTotals are the totals of the measures Standard, Pre-planning, Planning and Done for the
// products of one PO.
type POTotals struct {
	PO     string
	Totals map[string]*float64
}

// ByPO are the totals per PO in the order of first appearance (only if at least one product
// has a PO; otherwise nil).
func ByPO(d *Distribution) []POTotals {
	hasPO := false
	for _, r := range d.Rows {
		if r.Product.PO != nil && *r.Product.PO != "" {
			hasPO = true
		}
	}
	if !hasPO {
		return nil
	}
	var order []string
	groups := map[string][]Row{}
	for _, r := range d.Rows {
		po := ""
		if r.Product.PO != nil {
			po = *r.Product.PO
		}
		if po == "" {
			po = i18n.T("(no PO)")
		}
		if _, ok := groups[po]; !ok {
			order = append(order, po)
		}
		groups[po] = append(groups[po], r)
	}
	result := make([]POTotals, 0, len(order))
	for _, po := range order {
		totals := map[string]*float64{}
		for _, m := range Measures {
			var values []float64
			for _, r := range groups[po] {
				if v := r.Value(m.Key); v != nil {
					values = append(values, *v)
				}
			}
			if len(values) > 0 {
				totals[m.Key] = model.Ptr(pymath.Sum(values))
			} else {
				totals[m.Key] = nil
			}
		}
		result = append(result, POTotals{PO: po, Totals: totals})
	}
	return result
}
