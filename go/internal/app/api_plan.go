package app

import (
	"errors"
	"math"
	"path/filepath"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/capacity"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/preplan"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/protocol"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/ticketimport"
)

// The methods for the Pre-plan and Plan pages (work package P3). PlanSprint reads, the others
// change one thing and write the file at once; the page reads again afterwards. Saving to the
// shared store is the job of the top bar (Save).

// now is the clock of the whole package; tests replace it so that the dated demo data does not
// depend on the day they run.
var now = time.Now

// planCtx is the team data of one call, with the forecast built on it.
type planCtx struct {
	data   *storage.TeamData
	fc     *forecast.Forecast
	entry  *forecast.TimelineEntry
	sprint model.Sprint
	today  time.Time
	repo   *storage.Repository
	// ranks is the place of each open ticket in the order of the tracker's rank (see backlogByRank).
	ranks map[string]int
}

func planToday() time.Time {
	y, m, d := now().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

func (a *API) planContext(team, sprintID string) (*planCtx, error) {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return nil, err
	}
	c := &planCtx{data: data, today: planToday(), repo: repo}
	if c.fc, err = forecast.Build(data, c.today); err != nil {
		return nil, err
	}
	s, err := c.fc.LookupSprint(sprintID, forecast.DefaultLookupAhead)
	if err != nil {
		return nil, err
	}
	if s == nil {
		return nil, errors.New(i18n.T("The sprint {id} does not exist.", "id", sprintID))
	}
	c.sprint = s.Clone()
	c.entry = c.fc.Entry(sprintID)
	return c, nil
}

// --- Ticket facts -----------------------------------------------------------------------

func (c *planCtx) tickets() bool { return c.data.Team.Source() != model.SourceNone }

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func (c *planCtx) ticketURL(key string) string {
	t := c.data.Team.Tracker
	if t.Kind != "jira" || t.BaseURL == nil || *t.BaseURL == "" {
		return ""
	}
	return strings.TrimRight(*t.BaseURL, "/") + "/browse/" + key
}

// earmarkSprint is the sprint a ticket is planned for: the earmark, else the sprint of the
// tracker, else the frozen plan of the sprint it is in.
func (c *planCtx) earmarkSprint(t model.Ticket) string {
	if e := c.data.Preplan.EarmarkFor(t.Key); e != nil {
		return e.Sprint
	}
	return str(t.InSprint)
}

// prodShare is the production share of a ticket and where it comes from: set in Foresprint,
// the production label, the first matching rule, otherwise 0.
func (c *planCtx) prodShare(t model.Ticket) (float64, string) {
	if p := c.data.Preplan.ProductionFor(t.Key); p != nil {
		return clampPct(p.Percent), "manual"
	}
	tr := c.data.Team.Tracker
	if tr.ProductionLabel != nil && *tr.ProductionLabel != "" {
		for _, l := range t.Labels {
			if strings.EqualFold(l, *tr.ProductionLabel) {
				return 100, "label"
			}
		}
	}
	facts := t.Facts()
	for _, r := range tr.ProductionRules {
		if r.Match != nil && r.Match.Matches(facts) {
			return clampPct(r.Percent), "rule"
		}
	}
	return 0, "none"
}

func clampPct(v float64) float64 { return math.Min(math.Max(v, 0), 100) }

// productOf is the product whose amount a ticket uses: the PO's decision, else the project's
// or the product rules'.
func (c *planCtx) productOf(t model.Ticket) string {
	if !c.data.Team.Features.Products {
		return ""
	}
	if o := c.data.Preplan.OverrideFor(t.Key); o != nil && o.Product != nil {
		return *o.Product
	}
	if t.Product != nil && *t.Product != "" {
		return *t.Product
	}
	p, _ := preplan.TicketProduct(t, c.data)
	return str(p)
}

func (c *planCtx) projectOf(t model.Ticket) string {
	if o := c.data.Preplan.OverrideFor(t.Key); o != nil {
		if o.Daily {
			return ""
		}
		if o.Project != nil {
			return *o.Project
		}
	}
	return str(t.Project)
}

func (c *planCtx) rankPos(key string) int {
	if c.ranks == nil {
		c.ranks = map[string]int{}
		for i, tk := range backlogByRank(c.data) {
			c.ranks[tk.Key] = i + 1
		}
	}
	return c.ranks[key]
}

func (c *planCtx) planTicket(t model.Ticket) PlanTicket {
	size, _ := preplan.TicketSize(t, c.data, 1)
	pct, src := c.prodShare(t)
	return PlanTicket{
		Key: t.Key, Title: t.Title, Status: str(t.Status), URL: c.ticketURL(t.Key),
		Estimate: t.Estimate, Size: size, Remaining: t.Remaining,
		Product: c.productOf(t), Project: c.projectOf(t),
		Refined: t.Estimate != nil && t.EstimateSource == model.EstimateRefined && !t.RefinedUnclear,
		Sprint:  c.earmarkSprint(t), InTracker: str(t.InSprint),
		ProdPct: pct, ProdSource: src, RankPos: c.rankPos(t.Key),
	}
}

// sizeOf is what a ticket counts in the sprint: nothing without a size.
func sizeOf(t PlanTicket) float64 {
	if t.Size == nil {
		return 0
	}
	return *t.Size
}

// inSprint reports whether the ticket belongs to the sprint's lane: earmarked for it, in it
// according to the tracker, or on the frozen list.
func (c *planCtx) inSprint(t model.Ticket) bool {
	if c.sprint.CommittedTickets != nil {
		for _, k := range c.sprint.CommittedTickets {
			if k == t.Key {
				return true
			}
		}
		return false
	}
	return c.earmarkSprint(t) == c.sprint.ID
}

func (c *planCtx) laneTickets() (in, candidates []PlanTicket) {
	if !c.tickets() {
		return nil, nil
	}
	// The order of the planning (priority, project, dependencies, the PO's own order), the same
	// one the backlog shows and MoveWorkPackage changes; done tickets follow.
	ordered, leftover := preplan.OrderTickets(c.data)
	var done []model.Ticket
	for _, t := range c.data.Tickets {
		if t.Done {
			done = append(done, t)
		}
	}
	var all []model.Ticket
	for _, o := range slices.Concat(ordered, leftover, preplan.TicketOrder(done)) {
		if t := c.data.TicketByKey(o.Key); t != nil {
			all = append(all, *t)
		}
	}
	for _, t := range all {
		pt := c.planTicket(t)
		switch {
		case c.inSprint(t) && !slices.Contains(c.sprint.Removed, t.Key):
			in = append(in, pt)
		case t.Done || strings.EqualFold(str(t.Status), "done"):
			continue
		default:
			// Everything unfinished that is not in this sprint can be taken in: no sprint yet,
			// planned for a later one, or left over from an earlier one.
			candidates = append(candidates, pt)
		}
	}
	return in, candidates
}

// --- Figures ----------------------------------------------------------------------------

func sumPtr(m map[string]float64) float64 {
	t := 0.0
	for _, v := range m {
		t += v
	}
	return t
}

// capPercent is the team setting "Deckel Prod-Zeit" (100 = no cap).
func (c *planCtx) capPercent() float64 { return c.data.Team.Features.ProductionCap() }

// running returns the running sprint when the sprint of the view directly follows it.
func (c *planCtx) running() *forecast.TimelineEntry {
	cur := c.fc.Current()
	if cur == nil || cur.Sprint.ID == c.sprint.ID {
		return nil
	}
	for i := range c.fc.Entries {
		if c.fc.Entries[i].Sprint.ID == cur.Sprint.ID && i+1 < len(c.fc.Entries) &&
			c.fc.Entries[i+1].Sprint.ID == c.sprint.ID {
			return cur
		}
	}
	return nil
}

// definitiveCarry is the rest that continues in the sprint according to the review of the
// running (or last) sprint, or the newest saved assumption; the second result says which.
func (c *planCtx) savedCarry(prev *model.Sprint) (in, later float64) {
	add := func(items []model.CarryItem, restNext *float64) {
		if len(items) == 0 && restNext != nil {
			in += *restNext
			return
		}
		for _, it := range items {
			if it.Target == "" || it.Target == c.sprint.ID {
				in += it.Rest
			} else if it.Target != model.CarryBacklog && !strings.HasPrefix(it.Target, model.CarryProForma) {
				later += it.Rest
			}
		}
	}
	if len(prev.Carry) > 0 || prev.RestNext != nil {
		add(prev.Carry, prev.RestNext)
		return in, later
	}
	if p := newestPrognosis(prev, c.sprint.ID, ""); p != nil {
		add(p.Carry, p.RestNext)
	}
	return in, later
}

func newestPrognosis(prev *model.Sprint, target, label string) *model.Prognosis {
	var best *model.Prognosis
	for i := range prev.Prognoses {
		p := &prev.Prognoses[i]
		if str(p.Target) != target || (label != "" && labelOf(*p) != label) {
			continue
		}
		if best == nil || !p.At.Before(best.At) {
			best = p
		}
	}
	return best
}

func labelOf(p model.Prognosis) string {
	if p.Label != nil && *p.Label != "" {
		return *p.Label
	}
	return "A"
}

// PlanSprint returns the data of the Pre-plan and Plan pages for one sprint. With an
// assumption about the running sprint the figures follow it; without one they follow the
// definitive carry-over (Review) or the newest saved assumption.
func (a *API) PlanSprint(team, sprintID string, assume *Assumption) (*PlanSprint, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	v, err := c.view(team, assume)
	if err == nil {
		v.WriteUndo = len(a.writebackMoved(team, sprintID)) > 0
	}
	return v, err
}

func (c *planCtx) view(team string, assume *Assumption) (*PlanSprint, error) {
	d, s := c.data, c.sprint
	tm := d.Team
	v := &PlanSprint{
		Team: team, Sprint: s.ID,
		Start: s.Start.Format("2006-01-02"), End: s.End.Format("2006-01-02"),
		Unit: settingsUnitAt(d, s.Start), Source: string(tm.Source()),
		MultiProduct: tm.Features.Products, Production: tm.Features.Production,
		Share: tm.Forecast.RoadmapShare, StartRate: tm.Forecast.StartRate, Products: []PlanProduct{}, Tickets: []PlanTicket{},
		Candidates: []PlanTicket{}, Removed: []string{}, Projects: []PlanProject{}, Assumptions: []Assumption{}, Notes: []string{},
	}
	if v.Source == "tracker" && tm.Tracker.Kind == "jira" {
		v.TrackerName = "Jira"
	}
	v.WriteBack = c.writeEnabled()
	v.Days = workdays(c)
	v.Stage = c.stage()
	v.StartedOn, v.StartDue = startInfo(c.sprint, c.fc.Phase(c.sprint), c.today)
	v.Absences = absenceName(s)
	if len(s.Absences) > 0 {
		v.AbsenceDays = sumPtr(s.Absences)
	} else {
		v.AbsenceDays = sumPtr(s.ExpectedAbsences)
	}

	order := make([]string, 0, len(c.fc.Entries)+1)
	for _, e := range c.fc.Entries {
		order = append(order, e.Sprint.ID)
	}
	if !slices.Contains(order, s.ID) {
		order = append(order, s.ID)
	}
	// the unit of the sprint decides, not the one the team started with (decision 19)
	inSP := planning.UnitAt(&tm, order, s.ID) == model.UnitSP
	if c.entry != nil {
		v.Capacity = c.entry.Result.PlanCapacity
		v.Plan, v.PlanOriginal = c.entry.Result.Plan, c.entry.Result.Plan
		if src := c.entry.Result.PlanSource; src != nil && *src == engine.PlanStart {
			v.PlanSource = "start"
		}
		if b, ok := analysis.BandOf(c.fc, c.entry); ok {
			v.Low, v.High = &b.Low, &b.High
		}
		if t := c.entry.Result.NormalizedVelocity.Trend; t != nil && v.PlanSource == "" && tm.Forecast.ReferenceCapacity > 0 {
			r := *t / tm.Forecast.ReferenceCapacity
			v.TrendRate = &r
		}
		if v.Plan != nil && v.Capacity != nil && *v.Capacity > 0 && inSP {
			r := *v.Plan / *v.Capacity
			v.Rate = &r
		}
	}
	if inSP {
		v.OtherUnit = "PT"
		// a fixed factor wins over the measured rate (decision 19)
		if f := planning.FactorAt(&tm, order, s.ID); f != nil && *f > 0 {
			v.Rate = f
		}
	} else {
		one := 1.0
		v.Rate = &one
	}

	carryIn, carryLater := 0.0, 0.0
	if cur := c.running(); cur != nil {
		v.Running = cur.Sprint.ID
		seen := map[string]bool{}
		for _, p := range cur.Sprint.Prognoses {
			if l := labelOf(p); str(p.Target) == s.ID && !seen[l] {
				seen[l] = true
				v.Assumptions = append(v.Assumptions, assumptionOf(*newestPrognosis(&cur.Sprint, s.ID, l)))
			}
		}
		sort.SliceStable(v.Assumptions, func(i, j int) bool { return v.Assumptions[i].Label < v.Assumptions[j].Label })
		if assume != nil {
			w, err := c.whatIf(*assume)
			if err != nil {
				return nil, err
			}
			if w != nil && w.Touched {
				v.Plan, v.Low, v.High = w.Plan, w.Low, w.High
				v.TrendRate = nil
				carryIn, carryLater = w.Rest, w.Later
			} else {
				carryIn, carryLater = c.savedCarry(&cur.Sprint)
			}
		} else {
			carryIn, carryLater = c.savedCarry(&cur.Sprint)
		}
	} else if prev := c.previous(); prev != nil {
		carryIn, carryLater = c.savedCarry(prev)
	}
	v.CarryLater = carryLater
	if v.Plan != nil {
		sp := planning.SplitPlan(*v.Plan, carryIn, v.Share, tm.Forecast.Rounding)
		v.Split = &PlanSplit{Plan: sp.Plan, CarryIn: sp.CarryIn, Plannable: sp.Plannable,
			SmallStuff: sp.SmallStuff, Overbooked: sp.Overbooked}
	}

	in, candidates := c.laneTickets()
	if in != nil {
		v.Tickets = in
	}
	if candidates != nil {
		v.Candidates = candidates
	}
	for _, t := range v.Tickets {
		v.Earmarked += sizeOf(t)
	}
	c.fillProducts(v)
	c.fillProjects(v)
	c.fillMatrix(v)
	v.Prod = c.production(v)
	if s.CommittedTickets != nil || (v.Source == "none" && s.Commitment != nil && v.Stage != "past") {
		v.Frozen = &PlanFrozen{Tickets: len(s.CommittedTickets), Commitment: s.Commitment}
	}
	v.Committed = s.Commitment
	return v, nil
}

func assumptionOf(p model.Prognosis) Assumption {
	as := Assumption{Label: labelOf(p), Commitment: p.Commitment, NotDone: p.NotDone, Extra: p.AdditionalDone, RestNext: p.RestNext, FocusPercent: p.FocusPercent, ExtraAbsenceDays: p.ExtraAbsenceDays, Carry: []CarryInput{}}
	for _, it := range p.Carry {
		as.Carry = append(as.Carry, CarryInput{Ticket: str(it.Ticket), Rest: it.Rest, Target: it.Target})
	}
	return as
}

func (c *planCtx) previous() *model.Sprint {
	for i := range c.fc.Entries {
		if c.fc.Entries[i].Sprint.ID == c.sprint.ID && i > 0 {
			return &c.fc.Entries[i-1].Sprint
		}
	}
	return nil
}

func workdays(c *planCtx) int {
	n := 0
	for d := c.sprint.Start; !d.After(c.sprint.End); d = d.AddDate(0, 0, 1) {
		if wd := d.Weekday(); wd != time.Saturday && wd != time.Sunday {
			n++
		}
	}
	return n
}

func (c *planCtx) stage() string {
	s := c.sprint
	switch c.fc.Phase(s) {
	case model.PhasePast:
		return "past"
	case model.PhaseRunning:
		return "current"
	}
	switch {
	case s.CommittedTickets != nil:
		return "planned"
	case c.data.Team.Source() == model.SourceNone && s.Commitment != nil:
		return "planned"
	}
	return "open"
}

func absenceName(s model.Sprint) string {
	switch s.AbsenceStatus() {
	case model.AbsencesConfirmed:
		return "confirmed"
	case model.AbsencesExpected:
		return "announced"
	}
	return "unknown"
}

func (c *planCtx) fillProducts(v *PlanSprint) {
	d, s := c.data, c.sprint
	v.Removed = append(v.Removed, s.Removed...)
	if !d.Team.Features.Products {
		v.SprintPre = s.Preplanned
		if s.Preplanned != nil {
			v.Preplanned = *s.Preplanned
		}
		return
	}
	var active []model.Product
	for _, p := range products.SprintProducts(d.Products, s) {
		if p.ActiveBetween(s.Start, s.End) {
			active = append(active, p)
		}
	}
	var available *float64
	if v.Plan != nil {
		av := *v.Plan
		if d.Team.Forecast.ProductBasis == model.BasisRoadmap {
			av = *v.Plan * d.Team.Forecast.RoadmapShare
		}
		available = &av
	}
	standard := products.StandardShares(active, available)
	isActive := map[string]bool{}
	for _, p := range active {
		isActive[p.ID] = true
	}
	earmark := map[string]float64{}
	for _, t := range v.Tickets {
		earmark[t.Product] += sizeOf(t)
	}
	pos := map[string]bool{}
	for _, p := range products.SprintProducts(d.Products, s) {
		vals := s.Products[p.ID]
		row := PlanProduct{ID: p.ID, Name: p.Name, PO: str(p.PO), POName: str(p.PO), Pre: vals.Preplanned,
			Planned: vals.Planned, ProdPlanned: vals.ProductionPlanned, Done: vals.Done,
			Active: isActive[p.ID], Earmark: earmark[p.ID]}
		if sv, ok := standard[p.ID]; ok && isActive[p.ID] {
			sv = math.Round(sv)
			row.Default = &sv
		}
		switch {
		case row.Pre != nil:
			row.Budget = *row.Pre
		case row.Default != nil:
			row.Budget = *row.Default
		}
		if row.PO != "" {
			pos[row.PO] = true
		}
		v.Products = append(v.Products, row)
		if row.Pre != nil {
			v.Preplanned += *row.Pre
		}
	}
	v.MultiPO = len(pos) > 1
}

func (c *planCtx) fillProjects(v *PlanSprint) {
	rate := 0.0
	if v.Rate != nil {
		rate = *v.Rate
	}
	byProject := map[string]*PlanProject{}
	for _, p := range c.data.Projects {
		if p.Closed() {
			continue
		}
		pp := &PlanProject{ID: p.ID, Name: p.Name, Booked: p.Contingent.Total, UsedPD: preplan.ContingentStatusOf(p.Contingent).Used}
		byProject[p.ID] = pp
		if !c.tickets() {
			if vals, ok := c.sprint.Projects[p.ID]; ok && vals.Preplanned != nil {
				pp.Amount = *vals.Preplanned
			}
			pp.Manual = true
		}
	}
	for _, t := range v.Tickets {
		if pp := byProject[t.Project]; pp != nil && t.Project != "" {
			pp.Tickets++
			pp.Amount += sizeOf(t)
		}
	}
	for _, p := range c.data.Projects {
		pp := byProject[p.ID]
		if pp == nil || (pp.Amount == 0 && pp.Tickets == 0 && !pp.Manual && pp.Booked == nil) {
			continue
		}
		if rate > 0 && (pp.Amount > 0 || pp.Tickets > 0 || pp.Manual) {
			need := pp.Amount / rate
			pp.NeedPD = &need
		}
		v.Projects = append(v.Projects, *pp)
	}
}

func (c *planCtx) production(v *PlanSprint) *PlanProduction {
	if !c.data.Team.Features.Production {
		return nil
	}
	rate := 1.0
	if v.Rate != nil {
		rate = *v.Rate
	}
	absRate := 0.0
	if c.fc.Absences != nil && c.fc.Absences.Rate != nil && c.sprint.AbsenceStatus() == model.AbsencesUnknown {
		absRate = *c.fc.Absences.Rate
	}
	pt := capacity.ProductionTimeOf(&c.data.Team, c.data.People, c.sprint, absRate, c.capPercent())
	out := &PlanProduction{Time: pt.Time, CapPercent: pt.CapPercent, Available: pt.Available, People: []PlanProdPerson{}}
	for _, p := range pt.People {
		out.People = append(out.People, PlanProdPerson{Name: p.Person.Name, Capacity: p.Capacity, Absence: p.AbsenceDays})
	}
	if c.tickets() {
		var items []planning.Item
		for _, t := range v.Tickets {
			if t.ProdPct > 0 {
				items = append(items, planning.Item{Estimate: sizeOf(t), ProductionShare: t.ProdPct / 100})
				out.DemandAmount += sizeOf(t) * t.ProdPct / 100
			}
		}
		out.DemandSet = true
		out.Demand, _ = planning.DemandOf(items, rate)
	} else if m := c.sprint.ProductionPlanned; m != nil {
		out.Manual = m
		out.DemandSet = true
		out.Demand = *m
		out.DemandAmount = *m * rate
	}
	// The time of the people with access is gross (presence), the plannable amount is net (the
	// velocity already holds meetings, small stuff and the like). So the production that can be
	// planned is the plannable amount times the share of the production time in the capacity,
	// like the Forecast PLAN is scaled from the capacity.
	if v.Split != nil && v.Capacity != nil && rate > 0 {
		basis := v.Split.Plannable / rate
		if avail, share, ok := planning.AvailableOf(basis, pt.Time, *v.Capacity, pt.CapPercent); ok {
			out.Share, out.Basis, out.Scaled, out.Available = share, basis, true, avail
		}
	}
	cmp := planning.Compare(out.Demand, out.Available)
	out.Load, out.Status = cmp.Load, string(cmp.Status)
	return out
}

// --- What-if ----------------------------------------------------------------------------

// RunningTickets lists the tickets of the running sprint for the what-if table of the sprint
// that follows it. It is empty without tickets or without a running sprint before it.
func (a *API) RunningTickets(team, sprintID string) ([]RunningTicket, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	out := []RunningTicket{}
	cur := c.running()
	if cur == nil || !c.tickets() {
		return out, nil
	}
	frozen := cur.Sprint.CommittedTickets
	listed := map[string]bool{}
	for _, k := range frozen {
		listed[k] = true
	}
	for _, t := range preplan.TicketOrder(c.data.Tickets) {
		if str(t.InSprint) != cur.Sprint.ID && !listed[t.Key] {
			continue
		}
		out = append(out, RunningTicket{PlanTicket: c.planTicket(t),
			Done: t.Done || strings.EqualFold(str(t.Status), "done"), Added: frozen != nil && !listed[t.Key]})
	}
	return out, nil
}

// RunningHint says why the what-if table can be empty: open tickets that sit in a tracker
// sprint Foresprint does not know. Names are the first few of these sprint names.
func (a *API) RunningHint(team, sprintID string) (*RunningHint, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	h := &RunningHint{Names: []string{}}
	if !c.tickets() {
		return h, nil
	}
	seen := map[string]bool{}
	for _, t := range c.data.Tickets {
		name := strings.TrimSpace(str(t.SprintName))
		if t.Done || t.InSprint != nil || name == "" || trackerProForma(c.data, name) {
			continue
		}
		if ticketimport.ResolveSprint(name, c.data.Team.Tracker, ticketimport.ForecastSprints{Forecast: c.fc}) != nil {
			continue
		}
		h.Unresolved++
		if !seen[name] && len(h.Names) < 3 {
			seen[name] = true
			h.Names = append(h.Names, name)
		}
	}
	return h, nil
}

// WhatIf calculates an assumption about the running sprint: the expected velocity, the
// Forecast PLAN of the sprint with it and what is left to plan. It returns nil if no sprint
// runs directly before this one.
func (a *API) WhatIf(team, sprintID string, as Assumption) (*WhatIf, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return nil, err
	}
	return c.whatIf(as)
}

func (c *planCtx) whatIf(as Assumption) (*WhatIf, error) {
	cur := c.running()
	if cur == nil || c.entry == nil {
		return nil, nil
	}
	w := &WhatIf{Running: cur.Sprint.ID, PlanOriginal: c.entry.Result.Plan}
	tickets := c.tickets()
	if tickets {
		carried := map[string]CarryInput{}
		for _, it := range as.Carry {
			carried[it.Ticket] = it
		}
		listed := map[string]bool{}
		for _, k := range cur.Sprint.CommittedTickets {
			listed[k] = true
		}
		frozen := cur.Sprint.CommittedTickets != nil
		found := 0
		for _, t := range c.data.Tickets {
			if str(t.InSprint) != cur.Sprint.ID && !listed[t.Key] {
				continue
			}
			found++
			est := 0.0
			if t.Estimate != nil {
				est = *t.Estimate
			}
			added := frozen && !listed[t.Key]
			it, isCarried := carried[t.Key]
			switch {
			case !added:
				w.Commitment += est
				if isCarried {
					w.NotDone += est
				}
			case !isCarried:
				w.Extra += est
			}
			if isCarried {
				c.sortRest(w, it)
			}
		}
		// With tickets the sum of the tickets is the commitment; a typed number only counts when
		// no ticket of the sprint is known.
		typed := as.Commitment != nil && found == 0
		if typed {
			w.Commitment = *as.Commitment
		}
		w.Touched = len(as.Carry) > 0 || typed
	} else {
		w.Commitment = floatOr(as.Commitment, floatOr(cur.Sprint.Commitment, 0))
		w.NotDone, w.Extra = floatOr(as.NotDone, 0), floatOr(as.Extra, 0)
		rest := math.Min(floatOr(as.RestNext, w.NotDone), w.NotDone)
		w.Rest, w.Later = rest, w.NotDone-rest
		w.Touched = w.Commitment != floatOr(cur.Sprint.Commitment, 0) || w.NotDone > 0 || w.Extra > 0
	}
	w.Velocity = math.Max(w.Commitment-w.NotDone+w.Extra, 0)

	plan, low, high := c.entry.Result.Plan, (*float64)(nil), (*float64)(nil)
	if b, ok := analysis.BandOf(c.fc, c.entry); ok {
		low, high = &b.Low, &b.High
	}
	ent := c.entry
	adjusted := as.FocusPercent != nil || as.ExtraAbsenceDays != nil
	if adjusted && (floatOr(as.FocusPercent, 100) < 0 || floatOr(as.ExtraAbsenceDays, 0) < 0) {
		return nil, errors.New(i18n.T("Absence days, focus and velocity must not be negative."))
	}
	// the Forecast page plans with the running sprint's expected velocity, so the page does too
	w.Touched = w.Touched || adjusted
	if w.Touched {
		if e, fc2, err := c.refore(cur.Sprint.ID, w.Commitment, w.Velocity); err != nil {
			return nil, err
		} else if e != nil {
			ent = e
			plan = e.Result.Plan
			low, high = nil, nil
			if b, ok := analysis.BandOf(fc2, e); ok {
				low, high = &b.Low, &b.High
			}
		}
	}
	if adjusted {
		// focus and extra absence of the Forecast page change the plan the same way there
		before := plan
		plan = planAdjusted(&c.data.Team, ent.Result, as.ExtraAbsenceDays, as.FocusPercent)
		if before != nil && plan != nil && *before > 0 {
			scale := func(b *float64) *float64 {
				if b == nil {
					return nil
				}
				return model.Ptr(engine.RoundDown(*b**plan / *before, c.data.Team.Forecast.Rounding))
			}
			low, high = scale(low), scale(high)
		}
	}
	w.Plan, w.Low, w.High = plan, low, high
	if plan != nil {
		sp := planning.SplitPlan(*plan, w.Rest, c.data.Team.Forecast.RoadmapShare, c.data.Team.Forecast.Rounding)
		w.Plannable, w.SmallStuff = sp.Plannable, sp.SmallStuff
	}
	return w, nil
}

// sortRest adds the rest of a carried ticket to what continues in this sprint or later.
func (c *planCtx) sortRest(w *WhatIf, it CarryInput) {
	if it.Target == "" || it.Target == c.sprint.ID {
		w.Rest += it.Rest
		return
	}
	w.Later += it.Rest
}

// refore builds the forecast again as if the running sprint ended with the velocity.
func (c *planCtx) refore(curID string, commitment, velocity float64) (*forecast.TimelineEntry, *forecast.Forecast, error) {
	d2 := *c.data
	d2.Sprints = append([]model.Sprint(nil), c.data.Sprints...)
	found := false
	for i := range d2.Sprints {
		if d2.Sprints[i].ID == curID {
			d2.Sprints[i] = d2.Sprints[i].Clone()
			d2.Sprints[i].Velocity = &velocity
			d2.Sprints[i].Commitment = &commitment
			found = true
		}
	}
	if !found {
		return nil, nil, nil
	}
	fc2, err := forecast.Build(&d2, c.today)
	if err != nil {
		return nil, nil, err
	}
	return fc2.Entry(c.sprint.ID), fc2, nil
}

func floatOr(p *float64, def float64) float64 {
	if p == nil {
		return def
	}
	return *p
}

// SaveAssumption keeps an assumption about the running sprint as a forecast ("prognosis") with
// the label. The running sprint's file holds it; the review compares it with the result.
func (a *API) SaveAssumption(team, sprintID string, as Assumption) error {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return err
	}
	cur := c.running()
	if cur == nil {
		return errors.New(i18n.T("No sprint is running before {id}.", "id", sprintID))
	}
	w, err := c.whatIf(as)
	if err != nil || w == nil {
		return err
	}
	cs := cur.Sprint.Clone()
	var restNext *float64
	if !c.tickets() {
		restNext = &w.Rest // the default (all of "not done") is saved as it counted
	}
	label := as.Label
	if label == "" {
		label = "A"
	}
	p := model.Prognosis{At: time.Date(now().Year(), now().Month(), now().Day(), now().Hour(), now().Minute(), now().Second(), 0, time.UTC),
		Commitment: &w.Commitment, ExpectedDone: &w.Velocity, Target: &sprintID, Plan: w.Plan, Label: &label,
		RestNext: restNext}
	if w.NotDone > 0 {
		p.NotDone = &w.NotDone
	}
	if w.Extra > 0 {
		p.AdditionalDone = &w.Extra
	}
	p.FocusPercent, p.ExtraAbsenceDays = as.FocusPercent, as.ExtraAbsenceDays
	for _, it := range as.Carry {
		key := it.Ticket
		p.Carry = append(p.Carry, model.CarryItem{Ticket: &key, Rest: it.Rest, Target: it.Target})
	}
	pre := model.OrderedMap[float64]{}
	for id, vals := range c.sprint.Products {
		if vals.Preplanned != nil {
			pre.Set(id, *vals.Preplanned)
		}
	}
	p.Preplanned = pre
	// the same label replaces the older entry of the same target
	kept := make([]model.Prognosis, 0, len(cs.Prognoses)+1)
	for _, old := range cs.Prognoses {
		if str(old.Target) != sprintID || labelOf(old) != label {
			kept = append(kept, old)
		}
	}
	kept = append(kept, p)
	cs.Prognoses = kept
	_, err = c.repo.SaveSprint(team, &cs)
	storage.ClearTeamCache()
	return err
}

// --- Changes ----------------------------------------------------------------------------

// editSprint loads the sprint of the view, lets fn change a copy and writes it.
func (a *API) planEdit(team, sprintID string, fn func(c *planCtx, s *model.Sprint) error) error {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return err
	}
	s := c.sprint.Clone()
	if err := fn(c, &s); err != nil {
		return err
	}
	if _, err := c.repo.SaveSprint(team, &s); err != nil {
		return err
	}
	storage.ClearTeamCache()
	return nil
}

func planNonNegative(v *float64) error {
	if v != nil && (*v < 0 || math.IsNaN(*v) || math.IsInf(*v, 0)) {
		return errors.New(i18n.T("The amount must be a number of 0 or more."))
	}
	return nil
}

func (c *planCtx) knownProduct(id string) error {
	for _, p := range c.data.Products {
		if p.ID == id {
			return nil
		}
	}
	return errors.New(i18n.T("The product {id} does not exist.", "id", id))
}

func setProductValue(s *model.Sprint, product string, f func(v *model.ProductValues)) {
	if s.Products == nil {
		s.Products = map[string]model.ProductValues{}
	}
	v := s.Products[product]
	f(&v)
	if v.IsEmpty() {
		delete(s.Products, product)
	} else {
		s.Products[product] = v
	}
}

// SetPreplanned sets (or, with nil, clears) the pre-planned amount of a product in a sprint.
func (a *API) SetPreplanned(team, sprintID, product string, value *float64) error {
	if err := planNonNegative(value); err != nil {
		return err
	}
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		if err := c.knownProduct(product); err != nil {
			return err
		}
		setProductValue(s, product, func(v *model.ProductValues) { v.Preplanned = value })
		return nil
	})
}

// SetSprintPreplanned sets (or, with nil, clears) the pre-planned amount of a whole sprint; it
// is for teams without the products feature.
func (a *API) SetSprintPreplanned(team, sprintID string, value *float64) error {
	if err := planNonNegative(value); err != nil {
		return err
	}
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		s.Preplanned = value
		return nil
	})
}

// SetRemoved marks a ticket that the tracker keeps in the sprint as taken out by the team (or
// takes the mark away again). The plan lists it under "adjust in the tracker" when frozen.
func (a *API) SetRemoved(team, sprintID, ticket string, removed bool) error {
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		if c.data.TicketByKey(ticket) == nil {
			return errors.New(i18n.T("The ticket {key} does not exist.", "key", ticket))
		}
		kept := make([]string, 0, len(s.Removed)+1)
		for _, k := range s.Removed {
			if k != ticket {
				kept = append(kept, k)
			}
		}
		if removed {
			kept = append(kept, ticket)
		}
		s.Removed = kept
		return nil
	})
}

// TakeEarmarks sets the pre-planned amount of every product to the sum of its earmarked tickets.
func (a *API) TakeEarmarks(team, sprintID string) error {
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		v, err := c.view(team, nil)
		if err != nil {
			return err
		}
		for _, p := range v.Products {
			e := math.Round(p.Earmark*100) / 100
			setProductValue(s, p.ID, func(v *model.ProductValues) { v.Preplanned = &e })
		}
		return nil
	})
}

// UseDefaults sets the pre-planned amount of every product to its standard amount.
func (a *API) UseDefaults(team, sprintID string) error {
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		v, err := c.view(team, nil)
		if err != nil {
			return err
		}
		for _, p := range v.Products {
			if p.Default == nil {
				continue
			}
			d := *p.Default
			setProductValue(s, p.ID, func(v *model.ProductValues) { v.Preplanned = &d })
		}
		return nil
	})
}

// SetProjectAmount sets (or clears) the part of a sprint's amount that goes to a project; used
// by teams without tickets.
func (a *API) SetProjectAmount(team, sprintID, project string, value *float64) error {
	if err := planNonNegative(value); err != nil {
		return err
	}
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		if c.data.ProjectByID(project) == nil {
			return errors.New(i18n.T("The project {id} does not exist.", "id", project))
		}
		if s.Projects == nil {
			s.Projects = map[string]model.ProductValues{}
		}
		v := s.Projects[project]
		v.Preplanned = value
		if v.IsEmpty() {
			delete(s.Projects, project)
		} else {
			s.Projects[project] = v
		}
		return nil
	})
}

// SetProductionPT sets the production work of a sprint in person days (teams without tickets).
func (a *API) SetProductionPT(team, sprintID string, value *float64) error {
	if err := planNonNegative(value); err != nil {
		return err
	}
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		s.ProductionPlanned = value
		return nil
	})
}

func firstSprint(a *API, team, sprintID string) string {
	if sprintID != "" {
		return sprintID
	}
	if s, err := a.Sprints(team); err == nil && len(s) > 0 {
		return s[0].ID
	}
	return sprintID
}

// SetProductionPercent sets the production share of a ticket (0 to 100) in Foresprint; nil
// removes the value so that the label or a rule decides again.
func (a *API) SetProductionPercent(team, ticket string, percent *float64) error {
	c, err := a.planContext(team, firstSprint(a, team, ""))
	if err != nil {
		return err
	}
	if c.data.TicketByKey(ticket) == nil {
		return errors.New(i18n.T("The ticket {key} does not exist.", "key", ticket))
	}
	pp := c.data.Preplan
	kept := pp.Production[:0:0]
	for _, p := range pp.Production {
		if p.Ticket != ticket {
			kept = append(kept, p)
		}
	}
	if percent != nil {
		kept = append(kept, model.ProductionShare{Ticket: ticket, Percent: clampPct(*percent)})
	}
	pp.Production = kept
	if _, err := c.repo.SavePreplan(team, pp); err != nil {
		return err
	}
	storage.ClearTeamCache()
	return nil
}

// FreezePlan freezes the agreement: it stores the ticket list (or amounts) and the commitment
// in the sprint, freezes the Forecast PLAN and writes the planning minutes. It returns the name
// of the minutes file. Freezing again replaces the plan; the older minutes are marked obsolete.
func (a *API) FreezePlan(team, sprintID string, in FreezeInput) (string, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return "", err
	}
	if c.stage() == "past" || c.stage() == "current" {
		return "", errors.New(i18n.T("The sprint {id} has started; its plan cannot be frozen any more.", "id", sprintID))
	}
	if err := planNonNegative(in.Commitment); err != nil {
		return "", err
	}
	s := c.sprint.Clone()
	view, err := c.view(team, nil)
	if err != nil {
		return "", err
	}
	byKey := map[string]PlanTicket{}
	for _, t := range append(append([]PlanTicket{}, view.Tickets...), view.Candidates...) {
		byKey[t.Key] = t
	}
	var commit float64
	planned := map[string]float64{}
	prodPlanned := map[string]float64{}
	var noProduct, noProductProd float64
	if c.tickets() {
		keys := []string{}
		for _, k := range in.Tickets {
			t, ok := byKey[k]
			if !ok {
				return "", errors.New(i18n.T("The ticket {key} does not exist.", "key", k))
			}
			keys = append(keys, k)
			commit += sizeOf(t)
			if t.Product == "" && c.data.Team.Features.Products {
				noProduct += sizeOf(t)
				noProductProd += sizeOf(t) * t.ProdPct / 100
				continue
			}
			planned[t.Product] += sizeOf(t)
			prodPlanned[t.Product] += sizeOf(t) * t.ProdPct / 100
		}
		// Tickets without a product are split over the products by their shares.
		for id, v := range preplan.SplitByShare(c.data, s, noProduct) {
			planned[id] += v
		}
		for id, v := range preplan.SplitByShare(c.data, s, noProductProd) {
			prodPlanned[id] += v
		}
		s.CommittedTickets = keys
		// s.Removed stays: the write-back to the tracker needs to know what the team took out.
	} else {
		for id, v := range in.Amounts {
			if v < 0 {
				return "", errors.New(i18n.T("The amount must be a number of 0 or more."))
			}
			planned[id] = v
			commit += v
		}
		if in.Commitment != nil {
			commit = *in.Commitment
		}
	}
	for _, p := range c.data.Products {
		v, ok := planned[p.ID]
		if !ok && !c.tickets() {
			continue
		}
		pv, pp := v, prodPlanned[p.ID]
		setProductValue(&s, p.ID, func(x *model.ProductValues) {
			x.Planned = &pv
			if c.data.Team.Features.Production && c.tickets() {
				x.ProductionPlanned = &pp
			}
		})
	}
	commit = math.Round(commit*100) / 100
	s.Commitment = &commit
	if s.StartedOn == nil {
		s.StartPending = true // the sprint is started by hand, not by the frozen plan
	}
	forecast.FreezePlan(&s, c.entry, c.today, true)

	store := &protocol.Store{Dir: c.repo.TeamDir(team)}
	text := protocol.Render(protocol.Planning, c.data.Team.Name, sprintID, now(), c.planFacts(view, commit, in), nil, c.planNotes(in, byKey), "", false)
	// The old minutes are marked obsolete and the new ones written together with the sprint: if
	// the sprint cannot be saved, the minutes are as they were.
	path, err := store.ReplaceWithSave(sprintID, protocol.Planning, text, func() error {
		_, serr := c.repo.SaveSprint(team, &s)
		return serr
	})
	if err != nil {
		return "", err
	}
	storage.ClearTeamCache()
	return filepath.Base(path), nil
}

// planTicketLine is a ticket in the minutes: key, title, size, tracker status and, for a ticket that
// is already worked on (carried over from an earlier sprint), its rest.
func planTicketLine(t PlanTicket) string {
	size := "–"
	if t.Size != nil {
		size = strconv.FormatFloat(math.Round(*t.Size*100)/100, 'f', -1, 64)
	}
	line := t.Key + " " + t.Title + " (" + size + ")"
	if t.Status != "" {
		line += " – " + i18n.T("Status: {status}", "status", t.Status)
	}
	if t.Remaining != nil {
		line += ", " + i18n.T("carried over, rest {rest}", "rest", strconv.FormatFloat(math.Round(*t.Remaining*100)/100, 'f', -1, 64))
	}
	return line
}

func (c *planCtx) planFacts(v *PlanSprint, commit float64, in FreezeInput) []protocol.Fact {
	unit := settingsUnitAt(c.data, c.sprint.Start)
	f := func(x *float64) string {
		if x == nil {
			return "–"
		}
		return strconv.FormatFloat(math.Round(*x*10)/10, 'f', -1, 64)
	}
	facts := []protocol.Fact{
		{Label: i18n.T("Forecast PLAN"), Value: f(v.Plan) + " " + unit},
		{Label: i18n.T("Commitment"), Value: f(&commit) + " " + unit},
	}
	if v.Split != nil {
		facts = append(facts, protocol.Fact{Label: i18n.T("Plannable"), Value: f(&v.Split.Plannable) + " " + unit})
	}
	if c.tickets() {
		facts = append(facts, protocol.Fact{Label: i18n.T("Tickets"), Value: strconv.Itoa(len(in.Tickets))})
	}
	return facts
}

func (c *planCtx) planNotes(in FreezeInput, byKey map[string]PlanTicket) []protocol.Note {
	var notes []protocol.Note
	if c.tickets() {
		agreed := protocol.Note{Title: i18n.T("Agreed tickets")}
		for _, k := range in.Tickets {
			agreed.Items = append(agreed.Items, planTicketLine(byKey[k]))
		}
		notes = append(notes, agreed)
	}
	if len(in.Removed) > 0 {
		adj := protocol.Note{Title: i18n.T("Adjust in the tracker")}
		for _, k := range in.Removed {
			adj.Items = append(adj.Items, k+" "+byKey[k].Title)
		}
		notes = append(notes, adj)
	}
	return notes
}

// ReopenPlan takes the frozen list back so that the team can plan again; the minutes are
// marked obsolete at once.
func (a *API) ReopenPlan(team, sprintID string) error {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return err
	}
	if st := c.stage(); st == "past" || st == "current" {
		return errors.New(i18n.T("The sprint {id} has started; its plan cannot be frozen any more.", "id", sprintID))
	}
	s := c.sprint.Clone()
	s.CommittedTickets = nil
	for id, v := range s.Products {
		v.Planned, v.ProductionPlanned = nil, nil
		setProductValue(&s, id, func(x *model.ProductValues) { *x = v })
	}
	s.Commitment = nil
	store := &protocol.Store{Dir: c.repo.TeamDir(team)}
	if _, err := store.ObsoleteWithSave(sprintID, protocol.Planning, func() ([]string, error) {
		path, serr := c.repo.SaveSprint(team, &s)
		return []string{path}, serr
	}); err != nil {
		return err
	}
	storage.ClearTeamCache()
	return nil
}

// SavePreplanMinutes writes the minutes of the PO pre-planning of a sprint that has not started:
// the figures, the amount per product and the earmarked tickets with their status. Writing
// again marks the earlier minutes of the sprint as obsolete. It returns the file name.
func (a *API) SavePreplanMinutes(team, sprintID string) (string, error) {
	c, err := a.planContext(team, sprintID)
	if err != nil {
		return "", err
	}
	if st := c.stage(); st == "past" || st == "current" {
		return "", errors.New(i18n.T("The sprint {id} has started; its pre-planning minutes cannot be written any more.", "id", sprintID))
	}
	view, err := c.view(team, nil)
	if err != nil {
		return "", err
	}
	unit := settingsUnitAt(c.data, c.sprint.Start)
	f := func(x *float64) string {
		if x == nil {
			return "–"
		}
		return strconv.FormatFloat(math.Round(*x*10)/10, 'f', -1, 64)
	}
	facts := []protocol.Fact{{Label: i18n.T("Forecast PLAN"), Value: f(view.Plan) + " " + unit}}
	if view.Split != nil {
		facts = append(facts, protocol.Fact{Label: i18n.T("Plannable"), Value: f(&view.Split.Plannable) + " " + unit})
	}
	if view.SprintPre != nil {
		facts = append(facts, protocol.Fact{Label: i18n.T("Pre-planned"), Value: f(view.SprintPre) + " " + unit})
	} else if !c.data.Team.Features.Products || view.Preplanned > 0 {
		facts = append(facts, protocol.Fact{Label: i18n.T("Pre-planned"), Value: f(&view.Preplanned) + " " + unit})
	}
	var notes []protocol.Note
	if c.tickets() {
		facts = append(facts, protocol.Fact{Label: i18n.T("Earmarked"), Value: f(&view.Earmarked) + " " + unit})
		earmarked := protocol.Note{Title: i18n.T("Earmarked tickets")}
		for _, t := range view.Tickets {
			earmarked.Items = append(earmarked.Items, planTicketLine(t))
		}
		notes = append(notes, earmarked)
		if len(view.Removed) > 0 {
			out := protocol.Note{Title: i18n.T("Adjust in the tracker")}
			out.Items = append(out.Items, view.Removed...)
			notes = append(notes, out)
		}
	}
	var d *protocol.Distribution
	if c.data.Team.Features.Products {
		d = &protocol.Distribution{}
		for _, p := range view.Products {
			if !p.Active && p.Pre == nil && p.Earmark == 0 {
				continue
			}
			d.Rows = append(d.Rows, protocol.Row{Name: p.Name, PO: p.POName, Active: true, Standard: p.Default, Preplanned: p.Pre})
		}
	}
	text := protocol.Render(protocol.Preplanning, c.data.Team.Name, sprintID, now(), facts, d, notes, "", view.MultiPO)
	store := &protocol.Store{Dir: c.repo.TeamDir(team)}
	path, err := store.ReplaceWithSave(sprintID, protocol.Preplanning, text, func() error { return nil })
	if err != nil {
		return "", err
	}
	return filepath.Base(path), nil
}

// fillMatrix lists the cells of the table product x project.
func (c *planCtx) fillMatrix(v *PlanSprint) {
	if !c.data.Team.Features.Products {
		return
	}
	m := &PlanMatrix{Projects: []PlanRef{}, Cells: []PlanCell{}}
	for _, p := range c.data.Projects {
		if !p.Closed() {
			m.Projects = append(m.Projects, PlanRef{ID: p.ID, Name: p.Name})
		}
	}
	if len(m.Projects) == 0 || len(v.Products) == 0 {
		return
	}
	for _, p := range v.Products {
		if !p.Active {
			continue
		}
		for _, pr := range m.Projects {
			if x := c.sprint.Matrix[p.ID][pr.ID]; x != 0 {
				m.Cells = append(m.Cells, PlanCell{Product: p.ID, Project: pr.ID, Value: x})
			}
		}
	}
	v.Matrix = m
}

// SetMatrixCell sets (or, with nil or 0, clears) the amount of a product in a project.
func (a *API) SetMatrixCell(team, sprintID, product, project string, value *float64) error {
	if err := planNonNegative(value); err != nil {
		return err
	}
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		if err := c.knownProduct(product); err != nil {
			return err
		}
		p := c.data.ProjectByID(project)
		if p == nil {
			return errors.New(i18n.T("The project {id} does not exist.", "id", project))
		}
		clearing := value == nil || *value == 0
		if p.Closed() && !clearing { // a cell of a closed project can still be cleared
			return errors.New(i18n.T("The project {id} is closed.", "id", project))
		}
		if clearing {
			delete(s.Matrix[product], project)
			if len(s.Matrix[product]) == 0 {
				delete(s.Matrix, product)
			}
			if len(s.Matrix) == 0 {
				s.Matrix = nil
			}
			return nil
		}
		if s.Matrix == nil {
			s.Matrix = map[string]map[string]float64{}
		}
		if s.Matrix[product] == nil {
			s.Matrix[product] = map[string]float64{}
		}
		s.Matrix[product][project] = *value
		return nil
	})
}

// UseMatrix takes the sums of the table as the pre-planned amounts. Only the open projects and
// the active products count, and amounts are only raised, never lowered: a product keeps the
// budget it has (pre-planned or standard) when its row is smaller, and a project amount that
// is higher stays. Project amounts are for teams without tickets; with tickets they come from
// the tickets.
func (a *API) UseMatrix(team, sprintID string) error {
	return a.planEdit(team, sprintID, func(c *planCtx, s *model.Sprint) error {
		v, err := c.view(team, nil)
		if err != nil {
			return err
		}
		budget := map[string]float64{}
		for _, p := range v.Products {
			if p.Active {
				budget[p.ID] = p.Budget
			}
		}
		cols := map[string]float64{}
		for product, row := range s.Matrix {
			b, active := budget[product]
			if !active {
				continue
			}
			sum := 0.0
			for project, x := range row {
				if pr := c.data.ProjectByID(project); pr == nil || pr.Closed() {
					continue
				}
				sum += x
				cols[project] += x
			}
			if sum = math.Round(sum*100) / 100; sum > b+1e-9 {
				setProductValue(s, product, func(v *model.ProductValues) { v.Preplanned = &sum })
			}
		}
		if c.tickets() {
			return nil
		}
		for project, sum := range cols {
			sum = math.Round(sum*100) / 100
			if s.Projects == nil {
				s.Projects = map[string]model.ProductValues{}
			}
			pv := s.Projects[project]
			if pv.Preplanned == nil || *pv.Preplanned < sum {
				pv.Preplanned = &sum
				s.Projects[project] = pv
			}
		}
		return nil
	})
}

// planAdjusted is the plan of a forecast result with person days off in addition to the known
// absences and a share (percent, 100 = as measured) of the capacity that turns into points. It
// is the Forecast page's what-if, so a saved prognosis plans the same on both pages.
func planAdjusted(team *model.Team, r engine.SprintResult, extraAbsence, focusPercent *float64) *float64 {
	trend, ref := r.NormalizedVelocity.Trend, team.Forecast.ReferenceCapacity
	if r.Plan != nil && r.PlanCapacity != nil && r.PlanSource != nil && *r.PlanSource == engine.PlanStart {
		capacity := max(0, *r.PlanCapacity-floatOr(extraAbsence, 0))
		return model.Ptr(engine.RoundDown(capacity*team.Forecast.StartRate*floatOr(focusPercent, 100)/100, team.Forecast.Rounding))
	}
	if r.Plan == nil || r.PlanCapacity == nil || trend == nil || ref <= 0 {
		return r.Plan
	}
	capacity := max(0, *r.PlanCapacity-floatOr(extraAbsence, 0))
	return model.Ptr(engine.RoundDown(*trend/ref*capacity*floatOr(focusPercent, 100)/100, team.Forecast.Rounding))
}
