package preplan

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/assign"
	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
)

// noProduct is the product key of a ticket without a known product (matches no budget).
const noProduct = "\x00no-product"

var (
	dateMin = time.Date(1, 1, 1, 0, 0, 0, 0, time.UTC)
	dateMax = time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC)
)

// DefaultMaxSprints is the length of the horizon.
const DefaultMaxSprints = 26

// --- Budget -----------------------------------------------------------------------------

// planOf is the Forecast PLAN of a horizon sprint. Beyond the people list the plan is
// recalculated with the average capacity of the last sprints.
func planOf(h analysis.HorizonEntry, data *storage.TeamData) *float64 {
	result := h.Entry.Result
	if !h.Trend || result.NormalizedVelocity.Trend == nil {
		return result.Plan
	}
	settings := data.Team.Forecast
	plan := engine.RoundDown(*result.NormalizedVelocity.Trend/settings.ReferenceCapacity*h.Capacity, settings.Rounding)
	plan = math.Max(plan, 0.0)
	return &plan
}

// baseAmount is the plannable amount of one product in one sprint: its share of the Forecast
// PLAN, by basis reduced to the plannable share of the team.
func baseAmount(plan *float64, basis model.BudgetBasis, share, roadmapShare float64) float64 {
	if plan == nil {
		return 0.0
	}
	amount := *plan * share
	if basis == model.BudgetRoadmapShare {
		return amount * roadmapShare
	}
	return amount
}

type productShare struct {
	product *string
	share   float64
}

// standardShares is the standard quantity per handled product in order of first appearance
// (the dict of standard_shares of products.py, for an available amount that exists).
func standardShares(active []model.Product, available float64) []productShare {
	shares := products.StandardShares(active, &available)
	var out []productShare
	seen := map[string]bool{}
	// Like the dict of Python: the fixed shares first, then the rest, each in order of first
	// appearance.
	for _, withShare := range []bool{true, false} {
		for _, p := range active {
			if _, ok := shares[p.ID]; ok && (p.Share != nil) == withShare && !seen[p.ID] {
				seen[p.ID] = true
				out = append(out, productShare{strPtr(p.ID), shares[p.ID]})
			}
		}
	}
	return out
}

// productShares is the share of each product in a sprint (sum 1). Without the products feature
// the team has one implicit product (nil) that takes everything.
func productShares(data *storage.TeamData, sprint model.Sprint) []productShare {
	if !data.Team.Features.Products {
		return []productShare{{nil, 1.0}}
	}
	var active []model.Product
	for _, p := range data.Products {
		if p.ActiveBetween(sprint.Start, sprint.End) {
			active = append(active, p)
		}
	}
	return standardShares(active, 1.0)
}

// variantPlans is the plan of every horizon sprint for the normalized velocity nvel.
func variantPlans(core *storage.TeamData, horizon []analysis.HorizonEntry, nvel float64) map[string]float64 {
	out := map[string]float64{}
	for _, h := range horizon {
		out[h.Entry.Sprint.ID] = math.Max(analysis.PlanAt(core.Team.Forecast, nvel, h.Capacity), 0.0)
	}
	return out
}

// budgets are the budgets per horizon sprint and product, before fixed points and
// distribution. plans replaces the Forecast PLAN per sprint id (variants).
func budgets(data *storage.TeamData, core *storage.TeamData, horizon []analysis.HorizonEntry, plans map[string]float64) []Budget {
	team := data.Team
	result := []Budget{}
	for _, h := range horizon {
		var plan *float64
		if plans == nil {
			plan = planOf(h, data)
		} else if v, ok := plans[h.Entry.Sprint.ID]; ok {
			plan = &v
		}
		var group *float64
		if team.Features.Production && plan != nil {
			if share, ok := capacity.ProductionShare(&core.Team, core.People, h.Entry.Sprint); ok {
				group = &share
			}
		}
		for _, ps := range productShares(data, h.Entry.Sprint) {
			whole := baseAmount(plan, model.BudgetPlan, ps.share, team.Forecast.RoadmapShare)
			roadmap := baseAmount(plan, model.BudgetRoadmapShare, ps.share, team.Forecast.RoadmapShare)
			base := roadmap
			if team.Tracker.BudgetBasis == model.BudgetPlan {
				base = whole
			}
			b := Budget{Sprint: h.Entry.Sprint.ID, Product: ps.product, Base: base, Plan: whole, Roadmap: roadmap}
			if group != nil {
				v := whole * *group
				b.ProductionAvailable = &v
			}
			result = append(result, b)
		}
	}
	return result
}

// --- Order ------------------------------------------------------------------------------

func projectLess(a, b model.Project) bool {
	if (a.Target == nil) != (b.Target == nil) {
		return b.Target == nil
	}
	if a.Target != nil && !a.Target.Equal(*b.Target) {
		return a.Target.Before(*b.Target)
	}
	if a.Priority != b.Priority {
		return a.Priority < b.Priority
	}
	return a.ID < b.ID
}

// ProjectOrder sorts projects by target date (without target last), priority and id.
func ProjectOrder(projects []model.Project) []model.Project {
	out := append([]model.Project(nil), projects...)
	sort.SliceStable(out, func(i, j int) bool { return projectLess(out[i], out[j]) })
	return out
}

func candidatesOf(products []model.Product) []assign.Candidate {
	out := make([]assign.Candidate, len(products))
	for i, p := range products {
		out[i] = assign.Candidate{ID: p.ID, Match: p.Match}
	}
	return out
}

func findProject(data *storage.TeamData, id *string) *model.Project {
	if id == nil || *id == "" {
		return nil
	}
	for i := range data.Projects {
		if data.Projects[i].ID == *id {
			return &data.Projects[i]
		}
	}
	return nil
}

// TicketProduct returns the product whose budget a ticket uses, and the candidates when
// several product rules contradict each other. A ticket of a known project takes the project's
// product; otherwise the product rules decide. Without the products feature there is only the
// one implicit product: (nil, nil).
func TicketProduct(ticket model.Ticket, data *storage.TeamData) (*string, []string) {
	if !data.Team.Features.Products {
		return nil, nil
	}
	if project := findProject(data, ticket.Project); project != nil && project.Product != nil && *project.Product != "" {
		return project.Product, nil
	}
	id, candidates := assign.Project(ticket.Facts(), candidatesOf(data.Products), data.Team.Tracker.ProjectMatchOrder)
	if id == "" {
		return nil, candidates
	}
	return &id, candidates
}

// ProductConflict is the product a product rule assigns although the ticket's project belongs
// to another one (the project wins); nil = no contradiction.
func ProductConflict(ticket model.Ticket, data *storage.TeamData) *string {
	project := findProject(data, ticket.Project)
	if project == nil || project.Product == nil || *project.Product == "" || !data.Team.Features.Products {
		return nil
	}
	other, _ := assign.Project(ticket.Facts(), candidatesOf(data.Products), data.Team.Tracker.ProjectMatchOrder)
	if other != "" && other != *project.Product {
		return &other
	}
	return nil
}

// TicketOrder sorts tickets by rank (as text, without rank last), then key.
func TicketOrder(tickets []model.Ticket) []model.Ticket {
	out := append([]model.Ticket(nil), tickets...)
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if (a.Rank == nil) != (b.Rank == nil) {
			return b.Rank == nil
		}
		if ra, rb := rankText(a), rankText(b); ra != rb {
			return ra < rb
		}
		return a.Key < b.Key
	})
	return out
}

func rankText(t model.Ticket) string {
	if t.Rank == nil {
		return ""
	}
	return *t.Rank
}

// casefold is str.casefold().
func casefold(s string) string { return pytext.Casefold(s) }

// PriorityRank is the position of a tracker priority in tracker.priority_order
// (case-insensitive; 0 = most important). Without or with an unknown priority: after all named
// ones. An empty order ignores the priority: every ticket gets the same rank.
func PriorityRank(priority *string, order []string) int {
	if len(order) == 0 {
		return 0
	}
	if priority != nil && *priority != "" {
		want := casefold(*priority)
		for i, name := range order {
			if casefold(name) == want {
				return i
			}
		}
	}
	return len(order)
}

type orderKey struct {
	priority   int
	noTarget   bool
	target     time.Time
	projectPri int
	unitID     string
	rankNil    bool
	rank       string
	key        string
}

func (a orderKey) less(b orderKey) bool {
	switch {
	case a.priority != b.priority:
		return a.priority < b.priority
	case a.noTarget != b.noTarget:
		return b.noTarget
	case !a.target.Equal(b.target):
		return a.target.Before(b.target)
	case a.projectPri != b.projectPri:
		return a.projectPri < b.projectPri
	case a.unitID != b.unitID:
		return a.unitID < b.unitID
	case a.rankNil != b.rankNil:
		return b.rankNil
	case a.rank != b.rank:
		return a.rank < b.rank
	}
	return a.key < b.key
}

// OrderTickets returns the open tickets in distribution order: by ticket priority
// (tracker.priority_order), then by the ticket's unit, its project (target date, project
// priority) or, without a project, its product's own tickets (after the projects), then by
// rank. Tickets without project and product last; dependencies always before their successors.
// The second list holds the tickets that cannot be ordered because they are in a dependency
// cycle or depend on one (in the same order).
func OrderTickets(data *storage.TeamData) (ordered, leftover []model.Ticket) {
	var open []model.Ticket
	for _, tk := range data.Tickets {
		if !tk.Done {
			open = append(open, tk)
		}
	}
	projects := map[string]model.Project{}
	for _, p := range data.Projects {
		projects[p.ID] = p
	}
	order := data.Team.Tracker.PriorityOrder
	type keyed struct {
		key orderKey
		tk  model.Ticket
	}
	var items []keyed
	var unassigned []model.Ticket
	for _, tk := range open {
		k := orderKey{priority: PriorityRank(tk.Priority, order), rankNil: tk.Rank == nil, rank: rankText(tk), key: tk.Key}
		if pr, ok := projects[strOr(tk.Project)]; ok && tk.Project != nil {
			k.noTarget = pr.Target == nil
			k.target = dateMin
			if pr.Target != nil {
				k.target = *pr.Target
			}
			k.projectPri, k.unitID = pr.Priority, pr.ID
		} else {
			product, _ := TicketProduct(tk, data)
			if product == nil && data.Team.Features.Products {
				unassigned = append(unassigned, tk)
				continue
			}
			k.noTarget, k.target, k.projectPri, k.unitID = true, dateMax, 0, strOr(product)
		}
		items = append(items, keyed{k, tk})
	}
	sort.SliceStable(items, func(i, j int) bool { return items[i].key.less(items[j].key) })
	sequence := make([]model.Ticket, 0, len(open))
	for _, it := range items {
		sequence = append(sequence, it.tk)
	}
	// Tickets without project and product (not distributable, but reported).
	var groups []*string
	seen := map[string]bool{}
	nilSeen := false
	for _, tk := range unassigned {
		if tk.Project == nil {
			if !nilSeen {
				nilSeen = true
				groups = append(groups, nil)
			}
		} else if !seen[*tk.Project] {
			seen[*tk.Project] = true
			groups = append(groups, tk.Project)
		}
	}
	sort.SliceStable(groups, func(i, j int) bool {
		a, b := groups[i], groups[j]
		if (a == nil) != (b == nil) {
			return b == nil
		}
		return a != nil && *a < *b
	})
	for _, g := range groups {
		var members []model.Ticket
		for _, tk := range unassigned {
			if samePtr(tk.Project, g) {
				members = append(members, tk)
			}
		}
		sequence = append(sequence, TicketOrder(members)...)
	}

	known := map[string]bool{}
	for _, tk := range open {
		known[tk.Key] = true
	}
	placed := map[string]bool{}
	pending := sequence
	for len(pending) > 0 {
		pick := -1
		for i, tk := range pending {
			ready := true
			for _, d := range tk.DependsOn {
				if !placed[d] && known[d] {
					ready = false
					break
				}
			}
			if ready {
				pick = i
				break
			}
		}
		if pick < 0 {
			break
		}
		ordered = append(ordered, pending[pick])
		placed[pending[pick].Key] = true
		pending = append(append([]model.Ticket(nil), pending[:pick]...), pending[pick+1:]...)
	}
	return ordered, pending
}

func strOr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// --- Size -------------------------------------------------------------------------------

// TicketSize is the number the distribution calculates with and where it comes from: the
// ticket's size by tracker.planning_uses; a manual estimate of the PO replaces a missing size.
// Values count as they are unless roughFactor (the conservative variant passes
// tracker.rough_factor) differs from 1: it multiplies rough estimates and estimates of tickets
// whose refined status is unclear; refined and manual estimates are not inflated.
func TicketSize(ticket model.Ticket, data *storage.TeamData, roughFactor float64) (*float64, model.EstimateSource) {
	size := ticket.Size(data.Team.Tracker.PlanningUses)
	if size == nil {
		if manual := data.Preplan.EstimateFor(ticket.Key); manual != nil && manual.Estimate != nil {
			return manual.Estimate, model.EstimateManual
		}
		return nil, model.EstimateNone
	}
	source := ticket.EstimateSource
	if roughFactor != 1.0 && (source == model.EstimateRough || (ticket.RefinedUnclear && source != model.EstimateManual)) {
		scaled := *size * roughFactor
		size = &scaled
	}
	return size, source
}

// --- Distribution -----------------------------------------------------------------------

// VariantVelocity is the normalized velocity a variant calculates with: the lowest
// (conservative) or highest (optimistic) of the history; nil for the median (the Forecast PLAN
// counts) and when the history is too short for a range (fewer than two values).
func VariantVelocity(history []float64, variant Variant) *float64 {
	if variant == Median || len(history) < 2 {
		return nil
	}
	v := history[0]
	for _, h := range history {
		if variant == Conservative && h < v || variant == Optimistic && h > v {
			v = h
		}
	}
	return &v
}

// Distribute distributes the open tickets over the future sprints. The variant changes only
// the plan per sprint: Median is the Forecast PLAN as the forecast shows it; Conservative and
// Optimistic recalculate it from the lowest and highest normalized velocity of the history (at
// least two values are needed, otherwise an error is returned; DistributeVariants handles that
// case). The conservative variant also inflates rough estimates by tracker.rough_factor.
func Distribute(data *storage.TeamData, today time.Time, maxSprints int, variant Variant) (*Distribution, error) {
	switch variant {
	case Conservative, Median, Optimistic:
	default:
		return nil, fmt.Errorf("%q is not a valid Variant", variant)
	}
	core := data
	fc, err := analysis.HorizonForecast(core, today, maxSprints)
	if err != nil {
		return nil, err
	}
	horizon := analysis.HorizonEntries(fc, maxSprints)
	nvel := VariantVelocity(analysis.NormalizedHistory(fc), variant)
	if variant != Median && nvel == nil {
		return nil, fmt.Errorf("variant %s needs at least two sprints with velocity", variant)
	}
	return distribute(data, core, today, fc, horizon, variant, nvel)
}

type cellKey struct {
	sprint  string
	product string
	named   bool // false = the implicit product
}

func keyOf(sprint string, product *string) cellKey {
	if product == nil {
		return cellKey{sprint: sprint}
	}
	return cellKey{sprint, *product, true}
}

func distribute(data *storage.TeamData, core *storage.TeamData, today time.Time, fc *forecast.Forecast,
	horizon []analysis.HorizonEntry, variant Variant, nvel *float64) (*Distribution, error) {
	sprints := make([]model.Sprint, len(horizon))
	index := map[string]int{}
	for i, h := range horizon {
		sprints[i] = h.Entry.Sprint
		index[h.Entry.Sprint.ID] = i
	}
	var plans map[string]float64
	if nvel != nil {
		plans = variantPlans(core, horizon, *nvel)
	}
	budgetList := budgets(data, core, horizon, plans)
	roughFactor := 1.0
	if variant == Conservative {
		roughFactor = data.Team.Tracker.RoughFactor
	}
	byCell := map[cellKey]*Budget{}
	for i := range budgetList {
		byCell[keyOf(budgetList[i].Sprint, budgetList[i].Product)] = &budgetList[i]
	}
	defaultBasis := data.Team.Tracker.BudgetBasis
	basisOf := map[string]model.BudgetBasis{}
	for _, p := range data.Projects {
		if p.BudgetBasis != nil {
			basisOf[p.ID] = *p.BudgetBasis
		} else {
			basisOf[p.ID] = defaultBasis
		}
	}
	resolved := map[string]*string{}
	resolve := func(tk model.Ticket) *string {
		if p, ok := resolved[tk.Key]; ok {
			return p
		}
		p, _ := TicketProduct(tk, data)
		resolved[tk.Key] = p
		return p
	}

	gap := data.Team.Tracker.DependencyGap
	var current *model.Sprint
	if c := fc.Current(); c != nil {
		current = &c.Sprint
	}
	known := map[string]*model.Sprint{}
	var lookupErr error
	sprintOfID := func(id string) *model.Sprint {
		if s, ok := known[id]; ok {
			return s
		}
		s, err := fc.LookupSprint(id, forecast.DefaultLookupAhead)
		if err != nil && lookupErr == nil {
			lookupErr = err
		}
		known[id] = s
		return s
	}
	ended := func(id string) bool {
		s := sprintOfID(id)
		return s != nil && !s.End.After(today)
	}
	// position: its index; -1 = before the horizon (current or past sprint); len(sprints) =
	// after it or unknown.
	position := func(id string) int {
		if i, ok := index[id]; ok {
			return i
		}
		if s := sprintOfID(id); s != nil && (len(sprints) == 0 || s.Start.Before(sprints[0].Start)) {
			return -1
		}
		return len(sprints)
	}
	// productKey: the cell key of the product a ticket's budget is in. Without the products
	// feature every ticket counts against the one implicit product; with it, a ticket without
	// product counts against no product.
	productKey := func(sprint string, tk model.Ticket) (cellKey, bool) {
		product := resolve(tk)
		if product == nil && data.Team.Features.Products {
			return cellKey{sprint, noProduct, true}, true
		}
		return keyOf(sprint, product), false
	}

	ordered, leftover := OrderTickets(data)
	openTickets := append(append([]model.Ticket(nil), ordered...), leftover...)
	openKeys := map[string]bool{}
	deps := make([]validate.Dependency, len(openTickets))
	for i, tk := range openTickets {
		openKeys[tk.Key] = true
		deps[i] = validate.Dependency{Key: tk.Key, DependsOn: tk.DependsOn}
	}
	cycles := validate.FindCycles(deps)
	inCycle := map[string]bool{}
	for _, c := range cycles {
		for _, k := range c {
			inCycle[k] = true
		}
	}
	placements := map[string]*Placement{}

	// Fixed points: real sprint according to the tracker, then earmarks of the PO.
	for _, tk := range openTickets {
		earmark := data.Preplan.EarmarkFor(tk.Key)
		var sprint, reason string
		switch {
		case tk.InSprint != nil && *tk.InSprint != "" && !ended(*tk.InSprint):
			// A sprint of the tracker that is over does not count: earmark or distribution apply.
			sprint, reason = *tk.InSprint, ReasonFixedSprint
		case earmark != nil && !ended(earmark.Sprint):
			// An earmark of a sprint that is over would put an open ticket into the past.
			sprint, reason = earmark.Sprint, ReasonEarmark
		default:
			continue
		}
		size, source := TicketSize(tk, data, roughFactor)
		placements[tk.Key] = &Placement{Ticket: tk.Key, Sprint: strPtr(sprint), Reason: reason, Size: size,
			Source: source, Project: tk.Project, Product: resolve(tk)}
		key, _ := productKey(sprint, tk)
		if cell := byCell[key]; cell != nil && size != nil {
			cell.Fixed += *size
		}
	}

	sprintIndex := func(key string) (int, bool) {
		p := placements[key]
		if p == nil || p.Sprint == nil {
			return 0, false
		}
		return position(*p.Sprint), true
	}

	for _, tk := range ordered {
		if _, done := placements[tk.Key]; done {
			continue
		}
		size, source := TicketSize(tk, data, roughFactor)
		p := &Placement{Ticket: tk.Key, Reason: ReasonPlaced, Size: size, Source: source, Project: tk.Project, Product: resolve(tk)}
		placements[tk.Key] = p
		if _, none := productKey("", tk); none {
			p.Reason = ReasonNoProduct
			continue
		}
		if size == nil {
			p.Reason = ReasonUnestimated
			continue
		}
		first := 0
		for _, dep := range tk.DependsOn {
			if !openKeys[dep] {
				continue // done or unknown ticket: nothing to wait for
			}
			depIndex, placed := sprintIndex(dep)
			if !placed {
				p.Reason = ReasonBlocked
				break
			}
			first = max(first, depIndex+gap)
		}
		if p.Reason == ReasonBlocked {
			continue
		}
		product := resolve(tk)
		basis, ok := basisOf[strOr(tk.Project)]
		if !ok {
			basis = defaultBasis
		}
		best, any := 0.0, false
		for _, s := range sprints {
			if cell := byCell[keyOf(s.ID, product)]; cell != nil {
				if v := cell.Limit(basis); !any || v > best {
					best, any = v, true
				}
			}
		}
		if *size > best+eps {
			// No budget at all (no forecast, or no budget cell of the product) is not the
			// ticket's fault; only a ticket above every positive budget is too large.
			if best <= eps {
				p.Reason = ReasonNoBudget
			} else {
				p.Reason = ReasonTooLarge
			}
			continue
		}
		placed := false
		for i := max(first, 0); i < len(sprints); i++ {
			cell := byCell[keyOf(sprints[i].ID, product)]
			if cell != nil && cell.FreeFor(basis)+eps >= *size {
				cell.Placed += *size
				p.Sprint = strPtr(sprints[i].ID)
				placed = true
				break
			}
		}
		if !placed {
			p.Reason = ReasonBeyondHorizon
		}
	}

	for _, tk := range leftover {
		if _, done := placements[tk.Key]; done {
			continue
		}
		size, source := TicketSize(tk, data, roughFactor)
		reason := ReasonBlocked
		if inCycle[tk.Key] {
			reason = ReasonCycle
		}
		placements[tk.Key] = &Placement{Ticket: tk.Key, Sprint: nil, Reason: reason, Size: size, Source: source,
			Project: tk.Project, Product: resolve(tk)}
	}

	if cycles == nil {
		cycles = [][]string{}
	}
	result := &Distribution{
		Sprints: make([]string, len(sprints)),
		Budgets: budgetList,
		Cycles:  cycles,
		Later:   map[string]*time.Time{},

		Placements: []Placement{},
		Projects:   []ProjectStatus{},
		Refinement: []RefinementItem{},
		Unclear:    []string{},
		Variant:    variant,
	}
	for i, s := range sprints {
		result.Sprints[i] = s.ID
	}
	for _, tk := range data.Tickets {
		if p := placements[tk.Key]; p != nil {
			result.Placements = append(result.Placements, *p)
		}
	}
	for _, p := range placements {
		if p.Sprint != nil && position(*p.Sprint) >= len(sprints) {
			result.Later[*p.Sprint] = lastDay(sprintOfID(*p.Sprint))
		}
	}
	result.NoForecast = true
	for _, b := range budgetList {
		if b.Plan > eps {
			result.NoForecast = false
		}
	}
	if lookupErr != nil {
		return nil, lookupErr
	}
	length := data.Team.Sprint.LengthDays
	for _, pr := range ProjectOrder(data.Projects) {
		result.Projects = append(result.Projects, TrafficLight(pr, result, sprints, length, current, &today))
	}
	result.Refinement = refinementList(data, result, sprints)
	for _, tk := range openTickets {
		if tk.RefinedUnclear {
			result.Unclear = append(result.Unclear, tk.Key)
		}
	}
	return result, nil
}

// SprintSum is the amount a product takes up in a sprint (nil product = implicit).
type SprintSum struct {
	Product *string
	Amount  float64
}

// SprintSums is the amount per product that the tickets take up in sprint (tickets of the
// tracker, earmarks and distributed tickets). A sprint outside the horizon (e.g. the one
// starting today) has no budget; there only the tickets that sit in it according to the
// tracker or an earmark count.
func SprintSums(dist *Distribution, sprint string, data *storage.TeamData) []SprintSum {
	var cells []SprintSum
	for _, b := range dist.Budgets {
		if b.Sprint == sprint {
			cells = append(cells, SprintSum{b.Product, b.Fixed + b.Placed})
		}
	}
	if len(cells) > 0 {
		return cells
	}
	var sums []SprintSum
	for _, p := range dist.Placements {
		if p.Sprint == nil || *p.Sprint != sprint || p.Size == nil {
			continue
		}
		product := p.Product
		if !data.Team.Features.Products {
			product = nil
		} else if product == nil {
			continue
		}
		found := false
		for i := range sums {
			if samePtr(sums[i].Product, product) {
				sums[i].Amount += *p.Size
				found = true
			}
		}
		if !found {
			sums = append(sums, SprintSum{product, *p.Size})
		}
	}
	return sums
}
