package app

import (
	"errors"
	"fmt"
	"math"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/analysis"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/preplan"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/storage"
)

const dateLayout = "2006-01-02"

func day(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format(dateLayout)
}

func parseDay(text, what string) (*time.Time, error) {
	if strings.TrimSpace(text) == "" {
		return nil, nil
	}
	t, err := time.ParseInLocation(dateLayout, strings.TrimSpace(text), time.UTC)
	if err != nil {
		return nil, errors.New(i18n.T("{what}: please enter a date as YYYY-MM-DD.", "what", what))
	}
	return &t, nil
}

func (a *API) today() time.Time {
	n := time.Now()
	if a.Now != nil {
		n = a.Now()
	}
	return time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, time.UTC)
}

// projectCtx is everything the project views calculate from.
type projectCtx struct {
	data  *storage.TeamData
	today time.Time
	dist  *preplan.Distribution // nil without tickets or when it could not be calculated
	rate  float64               // mean points per person day; 0 = unknown
	// doneRate and planRate are the rates of single sprints: the measured one (velocity per
	// capacity) for finished work, the one of the forecast for planned work. A sprint without
	// one uses the mean rate.
	doneRate, planRate map[string]float64
	sprint             map[string]model.Sprint
	// problem says why the distribution is missing.
	problem string
}

// effectiveProject is the project id of a ticket for the project's history: the decision of the
// PO, else the project the rules found. Unlike preplan.ProjectOf it also names closed projects,
// so that finished work stays with them.
func effectiveProject(data *storage.TeamData, t model.Ticket) string {
	if o := data.Preplan.OverrideFor(t.Key); o != nil {
		switch {
		case o.Daily:
			return ""
		case o.Project != nil && *o.Project != "":
			return *o.Project
		}
	}
	if t.Project != nil {
		return *t.Project
	}
	return ""
}

func (a *API) projectContext(team string) (*projectCtx, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, err
	}
	return buildProjectCtx(data, a.today()), nil
}

func buildProjectCtx(data *storage.TeamData, now time.Time) *projectCtx {
	c := &projectCtx{data: data, today: now, sprint: map[string]model.Sprint{}, doneRate: map[string]float64{}, planRate: map[string]float64{}}
	for _, s := range data.Sprints {
		c.sprint[s.ID] = s
	}
	if !data.Team.Features.Tickets && !data.Team.Features.Projects {
		return c
	}
	fc, err := analysis.HorizonForecast(data, now, analysis.DefaultMaxSprints)
	if err != nil {
		c.problem = err.Error()
		return c
	}
	for _, e := range fc.Entries {
		if _, ok := c.sprint[e.Sprint.ID]; !ok {
			c.sprint[e.Sprint.ID] = e.Sprint
		}
		r := e.Result
		if data.Team.Unit == model.UnitPT {
			continue // person days need no conversion
		}
		if r.Velocity.Value != nil && r.Capacity.Value != nil && *r.Capacity.Value > 0 && *r.Velocity.Value > 0 {
			c.doneRate[e.Sprint.ID] = *r.Velocity.Value / *r.Capacity.Value
		}
		// The plan is rounded down; the rate it is built from is the unrounded trend.
		if tr, ref := r.NormalizedVelocity.Trend, data.Team.Forecast.ReferenceCapacity; tr != nil && *tr > 0 && ref > 0 {
			c.planRate[e.Sprint.ID] = *tr / ref
		}
	}
	switch {
	case data.Team.Unit == model.UnitPT:
		c.rate = 1
	case analysis.AvailableCount(fc) >= engine.MinThinHistory && data.Team.Forecast.ReferenceCapacity > 0:
		hist := analysis.NormalizedHistory(fc)
		if len(hist) > 0 {
			c.rate = pymath.FMean(hist) / data.Team.Forecast.ReferenceCapacity
		}
	}
	if !data.Team.Features.Tickets {
		return c
	}
	c.dist, c.problem = distributeOpen(data, now)
	return c
}

// distributeOpen distributes the open tickets; end dates act as target dates. The core treats
// the tickets of closed projects as daily business.
func distributeOpen(data *storage.TeamData, now time.Time) (*preplan.Distribution, string) {
	d := *data
	d.Projects = append([]model.Project(nil), data.Projects...)
	for i := range d.Projects {
		if p := &d.Projects[i]; p.Target == nil && p.End != nil {
			p.Target = p.End
		}
	}
	dist, err := preplan.Distribute(&d, now, analysis.DefaultMaxSprints, preplan.Median)
	if err != nil {
		return nil, err.Error()
	}
	return dist, ""
}

// pd converts points of one sprint to person days with the rate of that sprint; planned says
// whether the points are planned (forecast rate) or finished (measured rate). Without a
// rate of its own the sprint takes the mean rate.
func (c *projectCtx) pd(points float64, sprint string, planned bool) float64 {
	rates := c.doneRate
	if planned {
		rates = c.planRate
	}
	r := rates[sprint]
	if r <= 0 {
		r = c.rate
	}
	if r <= 0 {
		return 0
	}
	return points / r
}

// pdPtr is a sum of person days, nil while the team has no rate yet.
func (c *projectCtx) pdPtr(sum float64) *float64 {
	if c.rate <= 0 {
		return nil
	}
	return model.Ptr(round1(sum))
}

func round1(v float64) float64 { return math.Round(v*10) / 10 }

// lastDay is the last day of a sprint (End is exclusive).
func lastDay(s model.Sprint) time.Time { return s.End.AddDate(0, 0, -1) }

func monthOf(t time.Time) string { return t.Format("2006-01") }

// openPlacements are the placements of a project's open tickets.
func (c *projectCtx) placements(id string) []preplan.Placement {
	if c.dist == nil {
		return nil
	}
	var out []preplan.Placement
	for _, p := range c.dist.Placements {
		if p.Project != nil && *p.Project == id {
			out = append(out, p)
		}
	}
	return out
}

var lightOf = map[string]string{
	preplan.LightOnTrack: "ok",
	preplan.LightTight:   "warn",
	preplan.LightMissed:  "bad",
}

var lightRank = map[string]int{"none": 0, "ok": 1, "warn": 2, "bad": 3}

func worse(a, b string) string {
	if lightRank[b] > lightRank[a] {
		return b
	}
	return a
}

// milestoneViews evaluates the milestones of a project with the core (preplan.MilestoneStatuses):
// a light the PO set by hand wins, otherwise it is derived from the placements of the tickets.
func (c *projectCtx) milestoneViews(p model.Project) []MilestoneView {
	var sprints []model.Sprint
	for _, s := range c.sprint {
		sprints = append(sprints, s)
	}
	var dist *preplan.Distribution
	if c.data.Team.Features.Tickets {
		dist = c.dist
	}
	status := map[string]preplan.MilestoneStatus{}
	for _, st := range preplan.MilestoneStatuses(p, dist, c.data, sprints) {
		status[st.ID] = st
	}
	out := make([]MilestoneView, 0, len(p.Milestones))
	for _, m := range p.Milestones {
		v := MilestoneView{
			ID: m.ID, Name: m.Name, Date: m.Date.Format(dateLayout), Tickets: append([]string{}, m.Tickets...),
			Total: len(m.Tickets), Light: "none", Hand: m.Light, Source: preplan.LightNone, Late: []string{},
		}
		if c.data.Team.Features.Tickets {
			for _, key := range m.Tickets {
				if t := c.data.TicketByKey(key); t != nil && t.Done {
					v.Done++
				}
			}
		}
		if st, ok := status[m.ID]; ok {
			v.Light = map[string]string{model.LightGreen: "ok", model.LightYellow: "warn", model.LightRed: "bad"}[st.Light]
			if v.Light == "" {
				v.Light = "none"
			}
			v.Source = st.Source
			if st.Late != nil {
				v.Late = st.Late
			}
		}
		out = append(out, v)
	}
	return out
}

func ruleText(r *model.Rule) string {
	if r == nil {
		return ""
	}
	return rules.FormatRule(r)
}

func (c *projectCtx) projectView(p model.Project) ProjectView {
	v := ProjectView{
		ID: p.ID, Name: p.Name, Products: p.Products(), Start: day(p.Start), End: day(p.End), Rule: ruleText(p.Match),
		Priority: p.Priority, Booked: p.Contingent.Total, OpenScope: p.OpenScope, State: string(p.State), ClosedAt: day(p.ClosedAt), Light: "none",
		Milestones: []MilestoneView{}, Months: []MonthRow{},
	}
	if p.Note != nil {
		v.Note = *p.Note
	}
	if v.Products == nil {
		v.Products = []string{}
	}
	if p.End == nil && p.Target != nil {
		v.End = day(p.Target)
	}
	v.Milestones = c.milestoneViews(p)
	for _, mv := range v.Milestones {
		if !p.Closed() {
			v.Light = worse(v.Light, mv.Light)
		}
	}
	if p.Contact != nil {
		v.Contact = *p.Contact
	}
	cs := preplan.ContingentStatusOf(p.Contingent)
	v.Used, v.Remaining, v.UsedStatus, v.UsedHand = cs.Used, cs.Remaining, string(cs.Status), p.Contingent.Used
	var plannedPts, donePts, plannedPD, donePD float64
	hasDone := false
	for _, t := range c.data.Tickets {
		if effectiveProject(c.data, t) != p.ID {
			continue
		}
		v.History = true
		if t.Done {
			hasDone = true
			if t.Estimate != nil {
				donePts += *t.Estimate
				sprint := ""
				if t.InSprint != nil {
					sprint = *t.InSprint
				}
				donePD += c.pd(*t.Estimate, sprint, false)
			}
		}
	}
	if p.Start != nil && p.Start.Before(c.today) {
		v.History = true
	}
	thisMonth := monthOf(c.today)
	for _, ym := range p.Contingent.PerMonth.Keys() {
		if ym < thisMonth {
			v.History = true
		}
	}
	for _, m := range p.Milestones {
		if m.Date.Before(c.today) {
			v.History = true
		}
	}
	if c.dist != nil && !p.Closed() {
		if st := c.dist.Status(p.ID); st != nil {
			if l, ok := lightOf[st.Light]; ok {
				v.Light = worse(v.Light, l)
			}
			v.Open = st.OpenTickets
			v.Reason = i18n.T(preplan.Lights[st.Light])
		}
		for _, pl := range c.placements(p.ID) {
			if pl.Sprint != nil && pl.Size != nil {
				plannedPts += *pl.Size
				plannedPD += c.pd(*pl.Size, *pl.Sprint, true)
			}
		}
	}
	v.DonePoints, v.PlannedPoints = round1(donePts), round1(plannedPts)
	if c.data.Team.Features.Tickets {
		if hasDone || plannedPts > 0 {
			v.Done = c.pdPtr(donePD)
		}
		if c.dist != nil && !p.Closed() {
			v.Planned = c.pdPtr(plannedPD)
		}
	}
	v.Months = c.monthRows(p)
	return v
}

func (c *projectCtx) monthRows(p model.Project) []MonthRow {
	rows := []MonthRow{}
	planned := map[string]float64{}
	done := map[string]float64{}
	for _, pl := range c.placements(p.ID) {
		if pl.Sprint == nil || pl.Size == nil {
			continue
		}
		if s, ok := c.sprint[*pl.Sprint]; ok {
			planned[monthOf(lastDay(s))] += c.pd(*pl.Size, s.ID, true)
		}
	}
	for _, t := range c.data.Tickets {
		if !t.Done || t.Estimate == nil || effectiveProject(c.data, t) != p.ID || t.InSprint == nil {
			continue
		}
		if s, ok := c.sprint[*t.InSprint]; ok {
			done[monthOf(lastDay(s))] += c.pd(*t.Estimate, s.ID, false)
		}
	}
	// Months with planned or finished work but no booking belong in the table too: that is where
	// an overbooking shows.
	seen := map[string]bool{}
	var months []string
	add := func(ym string) {
		if !seen[ym] {
			seen[ym] = true
			months = append(months, ym)
		}
	}
	for _, ym := range p.Contingent.PerMonth.Keys() {
		add(ym)
	}
	cs := preplan.ContingentStatusOf(p.Contingent)
	byMonth := map[string]preplan.MonthStatus{}
	for _, m := range cs.Months {
		byMonth[m.Month] = m
		add(m.Month)
	}
	for ym := range planned {
		add(ym)
	}
	for ym := range done {
		add(ym)
	}
	sort.Strings(months)
	for _, ym := range months {
		booked, _ := p.Contingent.PerMonth.Get(ym)
		r := MonthRow{Month: ym, Booked: booked}
		if st, ok := byMonth[ym]; ok && st.Used != nil {
			r.Used, r.Remaining, r.Status = st.Used, st.Remaining, string(st.Status)
		}
		if c.data.Team.Features.Tickets {
			r.Done = c.pdPtr(done[ym])
			r.Planned = c.pdPtr(planned[ym])
		}
		rows = append(rows, r)
	}
	return rows
}

func (c *projectCtx) view() ProjectsView {
	data := c.data
	v := ProjectsView{
		Today: c.today.Format(dateLayout), Enabled: data.Team.Features.Tickets || data.Team.Features.Projects,
		Source: map[model.TicketSource]string{model.SourceNone: "none", model.SourcePackages: "packages", model.SourceTracker: "tracker"}[data.Team.Source()],
		Unit:   string(data.Team.Unit), Products: []ProductRef{}, Projects: []ProjectView{}, Closed: []ProjectView{},
		Sprints: []SprintInfo{}, SprintDays: data.Team.Sprint.LengthDays, Conflict: []ConflictRow{}, Problem: c.problem,
	}
	if c.rate > 0 && data.Team.Unit != model.UnitPT {
		v.Rate = model.Ptr(c.rate)
	}
	for _, p := range data.Products {
		v.Products = append(v.Products, ProductRef{ID: p.ID, Name: p.Name})
	}
	for _, s := range data.Sprints {
		state := "future"
		switch {
		case !s.End.After(c.today):
			state = "past"
		case !s.Start.After(c.today):
			state = "current"
		}
		v.Sprints = append(v.Sprints, SprintInfo{ID: s.ID, Start: s.Start.Format(dateLayout), End: lastDay(s).Format(dateLayout), State: state})
	}
	sort.SliceStable(v.Sprints, func(i, j int) bool { return v.Sprints[i].Start < v.Sprints[j].Start })
	for _, p := range preplan.ProjectOrder(data.Projects) {
		if p.Closed() {
			v.Closed = append(v.Closed, c.projectView(p))
		} else {
			v.Projects = append(v.Projects, c.projectView(p))
		}
	}
	v.ConflictSprint, v.Conflict = c.conflict()
	return v
}

// conflict is the demand of the projects in the next sprint against the budget of each product
// (a recommendation; the PO decides).
func (c *projectCtx) conflict() (string, []ConflictRow) {
	if c.dist == nil || len(c.dist.Sprints) == 0 {
		return "", []ConflictRow{}
	}
	sprint := c.dist.Sprints[0]
	rows := []ConflictRow{}
	products := c.data.Products
	if !c.data.Team.Features.Products || len(products) == 0 {
		products = []model.Product{{ID: "", Name: c.data.Team.Name}}
	}
	for _, pr := range products {
		var key *string
		if pr.ID != "" {
			id := pr.ID
			key = &id
		}
		b := c.dist.Budget(sprint, key)
		if b == nil {
			continue
		}
		row := ConflictRow{Product: pr.ID, Budget: round1(b.Base), Demand: []DemandCell{}}
		byProject := map[string]float64{}
		for _, pl := range c.dist.InSprint(sprint) {
			if pl.Project == nil || pl.Size == nil || !samePtr(pl.Product, key) {
				continue
			}
			byProject[*pl.Project] += *pl.Size
		}
		total := 0.0
		for _, p := range preplan.ProjectOrder(c.data.Projects) {
			if pts := byProject[p.ID]; pts > 0 {
				row.Demand = append(row.Demand, DemandCell{Project: p.ID, Points: round1(pts)})
				total += pts
			}
		}
		row.Rest = round1(b.Base - total)
		switch {
		case row.Rest <= 0:
			row.Light = "bad"
		case row.Rest <= b.Base*0.15:
			row.Light = "warn"
		default:
			row.Light = "ok"
		}
		rows = append(rows, row)
	}
	return sprint, rows
}

func samePtr(a, b *string) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// Projects returns the portfolio of a team: open and closed projects with lights, contingents
// and the conflict view of the next sprint.
func (a *API) Projects(team string) (ProjectsView, error) {
	c, err := a.projectContext(team)
	if err != nil {
		return ProjectsView{}, err
	}
	return c.view(), nil
}

// Project returns one project with the report for the project lead.
func (a *API) Project(team, id string) (ProjectDetail, error) {
	c, err := a.projectContext(team)
	if err != nil {
		return ProjectDetail{}, err
	}
	p := c.data.ProjectByID(id)
	if p == nil {
		return ProjectDetail{}, errors.New(i18n.T("The project {id} does not exist.", "id", id))
	}
	out := ProjectDetail{ProjectsView: c.view(), Project: c.projectView(*p), Report: []ProjectSprintRow{}, Tickets: []TicketLine{}}
	out.Report = c.report(*p)
	for _, t := range c.data.Tickets {
		if effectiveProject(c.data, t) != id {
			continue
		}
		line := TicketLine{Key: t.Key, Title: t.Title, Estimate: t.Estimate, Done: t.Done}
		if t.Status != nil {
			line.Status = *t.Status
		}
		if c.dist != nil {
			if pl := c.dist.Placement(t.Key); pl != nil && pl.Sprint != nil {
				line.Sprint = *pl.Sprint
			}
		}
		if line.Sprint == "" && t.InSprint != nil {
			line.Sprint = *t.InSprint
		}
		out.Tickets = append(out.Tickets, line)
	}
	return out, nil
}

// report is the booked, planned and finished amount per sprint from the running sprint on.
func (c *projectCtx) report(p model.Project) []ProjectSprintRow {
	rows := []ProjectSprintRow{}
	var ids []string
	for id, s := range c.sprint {
		if s.End.After(c.today) {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return c.sprint[ids[i]].Start.Before(c.sprint[ids[j]].Start) })
	if c.dist != nil && len(c.dist.Sprints) > 0 {
		keep := map[string]bool{}
		for _, id := range c.dist.Sprints {
			keep[id] = true
		}
		var cut []string
		for _, id := range ids {
			if keep[id] || (!c.sprint[id].Start.After(c.today)) {
				cut = append(cut, id)
			}
		}
		ids = cut
	} else if len(ids) > 4 {
		ids = ids[:4]
	}
	perMonth := map[string]int{} // all sprints of a month, also those already over
	for _, s := range c.sprint {
		perMonth[monthOf(lastDay(s))]++
	}
	inWindow := 0 // shown sprints within the term of the project
	for _, id := range ids {
		s := c.sprint[id]
		if (p.Start == nil || !lastDay(s).Before(*p.Start)) && (p.End == nil || !s.Start.After(*p.End)) {
			inWindow++
		}
	}
	planned := map[string]float64{}
	for _, pl := range c.placements(p.ID) {
		if pl.Sprint != nil && pl.Size != nil {
			planned[*pl.Sprint] += c.pd(*pl.Size, *pl.Sprint, true)
		}
	}
	done := map[string]float64{}
	for _, t := range c.data.Tickets {
		if t.Done && t.Estimate != nil && t.InSprint != nil && effectiveProject(c.data, t) == p.ID {
			done[*t.InSprint] += c.pd(*t.Estimate, *t.InSprint, false)
		}
	}
	for _, id := range ids {
		s := c.sprint[id]
		state := "future"
		if !s.Start.After(c.today) {
			state = "current"
		}
		r := ProjectSprintRow{Sprint: id, State: state}
		ym := monthOf(lastDay(s))
		if v, ok := p.Contingent.PerMonth.Get(ym); ok {
			r.Booked = round1(v / float64(perMonth[ym]))
		} else if p.Contingent.PerMonth.Len() == 0 && p.Contingent.Total != nil && inWindow > 0 &&
			(p.Start == nil || !lastDay(s).Before(*p.Start)) && (p.End == nil || !s.Start.After(*p.End)) {
			r.Booked = round1(*p.Contingent.Total / float64(inWindow))
		}
		if c.data.Team.Features.Tickets {
			r.Planned = c.pdPtr(planned[id])
			r.Done = c.pdPtr(done[id])
		}
		rows = append(rows, r)
	}
	return rows
}

// --- Changes ---------------------------------------------------------------------------

type projectSnapshot struct {
	team     string
	projects []model.Project
	preplan  model.Preplan
	hasPlan  bool
	// after is the state this change left behind; UndoProjects only goes back when nothing
	// else has changed since.
	afterProjects []model.Project
	afterPreplan  model.Preplan
}

const maxUndo = 20

// edit loads the team, lets change modify its projects (and decisions of the PO), writes the
// files and remembers the previous state for UndoProjects.
func (a *API) edit(team string, change func(data *storage.TeamData) error) error {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return err
	}
	if !data.Team.Features.Tickets && !data.Team.Features.Projects {
		return errors.New(i18n.T("This team keeps no projects. Switch them on under Settings > Team."))
	}
	snap := projectSnapshot{team: team, projects: cloneProjects(data.Projects), preplan: clonePreplan(data.Preplan), hasPlan: data.Team.Features.Tickets}
	if err := change(data); err != nil {
		return err
	}
	if _, err := repo.SaveProjects(team, data.Projects); err != nil {
		return err
	}
	if data.Team.Features.Tickets {
		if _, err := repo.SavePreplan(team, data.Preplan); err != nil {
			return err
		}
	}
	storage.ClearTeamCache()
	if saved, err := repo.Load(team); err == nil {
		snap.afterProjects, snap.afterPreplan = cloneProjects(saved.Projects), clonePreplan(saved.Preplan)
	}
	a.mu.Lock()
	a.undo = append(a.undo, snap)
	if len(a.undo) > maxUndo {
		a.undo = a.undo[len(a.undo)-maxUndo:]
	}
	a.mu.Unlock()
	return nil
}

func clonePreplan(in model.Preplan) model.Preplan {
	return model.Preplan{
		Earmarks:   slices.Clone(in.Earmarks),
		Estimates:  slices.Clone(in.Estimates),
		Production: slices.Clone(in.Production),
		Overrides:  slices.Clone(in.Overrides),
		ProForma:   slices.Clone(in.ProForma),
		Order:      slices.Clone(in.Order),
	}
}

func cloneProjects(in []model.Project) []model.Project {
	out := make([]model.Project, len(in))
	copy(out, in)
	return out
}

// UndoProjects takes back the last change to the projects of a team (until the program closes
// or the change is saved to the shared data).
func (a *API) UndoProjects(team string) error {
	a.mu.Lock()
	var snap *projectSnapshot
	for i := len(a.undo) - 1; i >= 0; i-- {
		if a.undo[i].team == team {
			s := a.undo[i]
			snap = &s
			a.undo = append(a.undo[:i], a.undo[i+1:]...)
			break
		}
	}
	a.mu.Unlock()
	if snap == nil {
		return errors.New(i18n.T("There is nothing to undo."))
	}
	repo := storage.NewRepository(a.DataDir())
	storage.ClearTeamCache()
	if now, err := repo.Load(team); err != nil {
		return err
	} else if snap.afterProjects == nil || !reflect.DeepEqual(cloneProjects(now.Projects), snap.afterProjects) ||
		(snap.hasPlan && !reflect.DeepEqual(clonePreplan(now.Preplan), snap.afterPreplan)) {
		return errors.New(i18n.T("The data changed in the meantime, so this change can no longer be taken back."))
	}
	if _, err := repo.SaveProjects(team, snap.projects); err != nil {
		return err
	}
	if snap.hasPlan {
		if _, err := repo.SavePreplan(team, snap.preplan); err != nil {
			return err
		}
	}
	storage.ClearTeamCache()
	return nil
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

func slug(name string) string {
	s := strings.Trim(slugRe.ReplaceAllString(strings.ToLower(name), "-"), "-")
	if s == "" {
		s = "project"
	}
	return s
}

func uniqueID(projects []model.Project, name string) string {
	base, id := slug(name), slug(name)
	for n := 2; ; n++ {
		taken := false
		for _, p := range projects {
			taken = taken || p.ID == id
		}
		if !taken {
			return id
		}
		id = fmt.Sprintf("%s-%d", base, n)
	}
}

func (a *API) ruleSources(data *storage.TeamData) []string {
	return model.RuleSourcesWith(data.Team.Tracker.RuleFields)
}

// SaveProject creates (empty ID) or changes a project and returns its ID.
func (a *API) SaveProject(team string, in ProjectInput) (string, error) {
	id := in.ID
	err := a.edit(team, func(data *storage.TeamData) error {
		name := strings.TrimSpace(in.Name)
		if name == "" {
			return errors.New(i18n.T("Please enter a name."))
		}
		if data.Team.Features.Products && len(in.Products) == 0 {
			return errors.New(i18n.T("Please choose at least one product."))
		}
		for _, p := range data.Projects {
			if p.ID != in.ID && strings.EqualFold(p.Name, name) {
				return errors.New(i18n.T("A project named {name} exists already.", "name", name))
			}
		}
		end, err := parseDay(in.End, i18n.T("End date"))
		if err != nil {
			return err
		}
		if end == nil {
			return errors.New(i18n.T("Please enter an end date."))
		}
		start, err := parseDay(in.Start, i18n.T("Start date"))
		if err != nil {
			return err
		}
		if start != nil && start.After(*end) {
			return errors.New(i18n.T("The start date lies after the end date."))
		}
		var proj model.Project
		idx := -1
		for i := range data.Projects {
			if data.Projects[i].ID == in.ID {
				idx = i
			}
		}
		if idx >= 0 {
			proj = data.Projects[idx]
		} else {
			if in.ID != "" {
				return errors.New(i18n.T("The project {id} does not exist.", "id", in.ID))
			}
			proj.ID = uniqueID(data.Projects, name)
			proj.Priority = len(data.Projects) + 1
			for _, p := range data.Projects {
				if p.Priority >= proj.Priority {
					proj.Priority = p.Priority + 1
				}
			}
			id = proj.ID
		}
		proj.Name, proj.Start, proj.End = name, start, end
		proj.Target = end // the form shows one date; an older target would win in the distribution
		proj.Product, proj.AlsoProducts = nil, nil
		for i, pr := range in.Products {
			if i == 0 {
				first := pr
				proj.Product = &first
			} else {
				proj.AlsoProducts = append(proj.AlsoProducts, pr)
			}
		}
		if n := strings.TrimSpace(in.Note); n != "" {
			proj.Note = &n
		} else {
			proj.Note = nil
		}
		proj.Match = nil
		if text := strings.TrimSpace(in.Rule); text != "" {
			r, err := rules.ParseRule(text, a.ruleSources(data))
			if err != nil {
				return err
			}
			proj.Match = r
		}
		if in.Booked != nil && *in.Booked < 0 {
			return errors.New(i18n.T("The contingent cannot be negative."))
		}
		proj.Contingent = model.Contingent{Total: in.Booked, Used: in.Used, UsedPerMonth: proj.Contingent.UsedPerMonth}
		if in.UsedMonths != nil {
			proj.Contingent.UsedPerMonth = model.OrderedMap[float64]{}
		}
		if in.Used != nil && *in.Used < 0 {
			return errors.New(i18n.T("The contingent cannot be negative."))
		}
		if n := strings.TrimSpace(in.Contact); n != "" {
			proj.Contact = &n
		} else {
			proj.Contact = nil
		}
		months := make([]string, 0, len(in.Months))
		for ym := range in.Months {
			months = append(months, ym)
		}
		sort.Strings(months)
		for _, ym := range months {
			if _, err := time.Parse("2006-01", ym); err != nil || in.Months[ym] < 0 {
				return errors.New(i18n.T("The contingent per month needs a month and a number from 0."))
			}
			proj.Contingent.PerMonth.Set(ym, in.Months[ym])
		}
		usedMonths := make([]string, 0, len(in.UsedMonths))
		for ym := range in.UsedMonths {
			usedMonths = append(usedMonths, ym)
		}
		sort.Strings(usedMonths)
		for _, ym := range usedMonths {
			if _, err := time.Parse("2006-01", ym); err != nil || in.UsedMonths[ym] < 0 {
				return errors.New(i18n.T("The contingent per month needs a month and a number from 0."))
			}
			proj.Contingent.UsedPerMonth.Set(ym, in.UsedMonths[ym])
		}
		proj.OpenScope = in.OpenScope
		proj.Milestones = nil
		for i, m := range in.Milestones {
			date, err := parseDay(m.Date, i18n.T("Milestone date"))
			if err != nil {
				return err
			}
			if date == nil {
				return errors.New(i18n.T("Please enter a date for every milestone."))
			}
			mid := m.ID
			if mid == "" {
				mid = fmt.Sprintf("m%d", i+1)
				for taken := true; taken; {
					taken = false
					for _, o := range proj.Milestones {
						taken = taken || o.ID == mid
					}
					if taken {
						mid += "x"
					}
				}
			}
			if m.Light != "" && !slices.Contains(model.MilestoneLights, m.Light) {
				return errors.New(i18n.T("Please choose a traffic light for the milestone."))
			}
			proj.Milestones = append(proj.Milestones, model.Milestone{ID: mid, Name: strings.TrimSpace(m.Name), Date: *date, Tickets: m.Tickets, Light: m.Light})
		}
		if idx >= 0 {
			data.Projects[idx] = proj
		} else {
			data.Projects = append(data.Projects, proj)
		}
		return nil
	})
	return id, err
}

// CloseProject ends a project as finished or cancelled; its open tickets go to daily business
// or to another project. A project is not deleted when it has history.
func (a *API) CloseProject(team string, in CloseInput) error {
	return a.edit(team, func(data *storage.TeamData) error {
		p := data.ProjectByID(in.ID)
		if p == nil {
			return errors.New(i18n.T("The project {id} does not exist.", "id", in.ID))
		}
		state := model.ProjectState(in.How)
		if state != model.ProjectFinished && state != model.ProjectCancelled {
			return errors.New(i18n.T("Please choose how the project ends."))
		}
		end, err := parseDay(in.At, i18n.T("End date"))
		if err != nil {
			return err
		}
		if end == nil {
			now := a.today()
			end = &now
		}
		if in.MoveTo != "" {
			if to := data.ProjectByID(in.MoveTo); to == nil || to.Closed() || to.ID == in.ID {
				return errors.New(i18n.T("The project {id} does not exist.", "id", in.MoveTo))
			}
		}
		p.State, p.ClosedAt = state, end
		if p.End == nil {
			p.End = end
		}
		if data.Team.Features.Tickets {
			// Without a decision the core treats the tickets of a closed project as daily
			// business; a target project is a decision of the PO per ticket.
			for _, t := range data.Tickets {
				if in.MoveTo != "" && !t.Done && effectiveProject(data, t) == in.ID {
					setOverride(&data.Preplan, t.Key, in.MoveTo)
				}
			}
		}
		return nil
	})
}

// setOverride sends a ticket to a project, or to daily business when project is "".
func setOverride(pp *model.Preplan, key, project string) {
	var o *model.TicketOverride
	for i := range pp.Overrides {
		if pp.Overrides[i].Ticket == key {
			o = &pp.Overrides[i]
		}
	}
	if o == nil {
		pp.Overrides = append(pp.Overrides, model.TicketOverride{Ticket: key})
		o = &pp.Overrides[len(pp.Overrides)-1]
	}
	if project == "" {
		o.Project, o.Daily = nil, true
	} else {
		o.Project, o.Daily = &project, false
	}
}

// ReopenProject opens a closed project again; the PO checks end date and contingent.
func (a *API) ReopenProject(team, id string) error {
	return a.edit(team, func(data *storage.TeamData) error {
		p := data.ProjectByID(id)
		if p == nil {
			return errors.New(i18n.T("The project {id} does not exist.", "id", id))
		}
		p.State, p.ClosedAt = model.ProjectOpen, nil
		return nil
	})
}

// DeleteProject removes a project without history; one with history is closed instead.
func (a *API) DeleteProject(team, id string) error {
	return a.edit(team, func(data *storage.TeamData) error {
		p := data.ProjectByID(id)
		if p == nil {
			return errors.New(i18n.T("The project {id} does not exist.", "id", id))
		}
		c := buildProjectCtx(data, a.today())
		if c.projectView(*p).History {
			return errors.New(i18n.T("{name} has history and can only be closed.", "name", p.Name))
		}
		var kept []model.Project
		for _, o := range data.Projects {
			if o.ID != id {
				kept = append(kept, o)
			}
		}
		data.Projects = kept
		return nil
	})
}
