package app

import (
	"errors"
	"fmt"
	"math"
	"regexp"
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
	data   *storage.TeamData
	today  time.Time
	dist   *preplan.Distribution // nil without tickets or when it could not be calculated
	rate   float64               // points per person day; 0 = unknown
	sprint map[string]model.Sprint
	// problem says why the distribution is missing.
	problem string
}

// effectiveProject is the project of a ticket after the decisions of the PO.
func effectiveProject(data *storage.TeamData, t model.Ticket) string {
	if o := data.Preplan.OverrideFor(t.Key); o != nil {
		if o.Daily || o.Project == nil {
			if o.Daily {
				return ""
			}
		} else {
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
	c := &projectCtx{data: data, today: now, sprint: map[string]model.Sprint{}}
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

// distributeOpen distributes with the open projects only; end dates act as target dates and
// the tickets of closed projects count as daily business (their rules no longer apply).
func distributeOpen(data *storage.TeamData, now time.Time) (*preplan.Distribution, string) {
	d := *data
	closed := map[string]bool{}
	d.Projects = nil
	for _, p := range data.Projects {
		if p.Closed() {
			closed[p.ID] = true
			continue
		}
		if p.Target == nil && p.End != nil {
			p.Target = p.End
		}
		d.Projects = append(d.Projects, p)
	}
	d.Tickets = append([]model.Ticket(nil), data.Tickets...)
	for i := range d.Tickets {
		if t := &d.Tickets[i]; t.Project != nil && closed[*t.Project] {
			t.Project = nil
		}
	}
	dist, err := preplan.Distribute(&d, now, analysis.DefaultMaxSprints, preplan.Median)
	if err != nil {
		return nil, err.Error()
	}
	return dist, ""
}

func (c *projectCtx) toPD(points float64) *float64 {
	if c.rate <= 0 {
		return nil
	}
	return model.Ptr(round1(points / c.rate))
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

// milestoneView calculates the light of a milestone from the placements of its tickets: all
// finished = ok; the last ticket ends on or before the date = ok, the date lies inside its
// sprint = warn, later or not distributable = bad. Without tickets no light is calculated.
func (c *projectCtx) milestoneView(m model.Milestone) MilestoneView {
	v := MilestoneView{ID: m.ID, Name: m.Name, Date: m.Date.Format(dateLayout), Tickets: append([]string{}, m.Tickets...), Light: "none"}
	v.Total = len(m.Tickets)
	if v.Total == 0 || !c.data.Team.Features.Tickets {
		return v
	}
	light := "ok"
	for _, key := range m.Tickets {
		t := c.data.TicketByKey(key)
		if t != nil && t.Done {
			v.Done++
			continue
		}
		if c.dist == nil {
			continue
		}
		p := c.dist.Placement(key)
		if p == nil || p.Sprint == nil || !p.Distributable() {
			light = worse(light, "bad")
			continue
		}
		s, ok := c.sprint[*p.Sprint]
		switch {
		case !ok:
			light = worse(light, "bad")
		case !lastDay(s).After(m.Date):
		case !s.Start.After(m.Date):
			light = worse(light, "warn")
		default:
			light = worse(light, "bad")
		}
	}
	v.Light = light
	return v
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
		Priority: p.Priority, Booked: p.Contingent.Total, OpenScope: p.OpenScope, State: string(p.State), Light: "none",
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
	for _, m := range p.Milestones {
		mv := c.milestoneView(m)
		v.Milestones = append(v.Milestones, mv)
		if !p.Closed() {
			v.Light = worse(v.Light, mv.Light)
		}
	}
	var plannedPts, donePts float64
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
			}
		}
	}
	if p.Start != nil && p.Start.Before(c.today) {
		v.History = true
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
			}
		}
	}
	if c.data.Team.Features.Tickets {
		if hasDone || plannedPts > 0 {
			v.Done = c.toPD(donePts)
		}
		if c.dist != nil && !p.Closed() {
			v.Planned = c.toPD(plannedPts)
		}
	}
	v.Months = c.monthRows(p)
	return v
}

func (c *projectCtx) monthRows(p model.Project) []MonthRow {
	rows := []MonthRow{}
	if p.Contingent.PerMonth.Len() == 0 {
		return rows
	}
	planned := map[string]float64{}
	done := map[string]float64{}
	for _, pl := range c.placements(p.ID) {
		if pl.Sprint == nil || pl.Size == nil {
			continue
		}
		if s, ok := c.sprint[*pl.Sprint]; ok {
			planned[monthOf(lastDay(s))] += *pl.Size
		}
	}
	for _, t := range c.data.Tickets {
		if !t.Done || t.Estimate == nil || effectiveProject(c.data, t) != p.ID || t.InSprint == nil {
			continue
		}
		if s, ok := c.sprint[*t.InSprint]; ok {
			done[monthOf(lastDay(s))] += *t.Estimate
		}
	}
	months := p.Contingent.PerMonth.Keys()
	sort.Strings(months)
	for _, ym := range months {
		booked, _ := p.Contingent.PerMonth.Get(ym)
		r := MonthRow{Month: ym, Booked: booked}
		if c.data.Team.Features.Tickets {
			r.Done = c.toPD(done[ym])
			r.Planned = c.toPD(planned[ym])
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
	out := ProjectDetail{ProjectsView: c.view(), Project: c.projectView(*p), Report: []SprintRow{}, Tickets: []TicketLine{}}
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
func (c *projectCtx) report(p model.Project) []SprintRow {
	rows := []SprintRow{}
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
	perMonth := map[string]int{}
	for _, id := range ids {
		perMonth[monthOf(lastDay(c.sprint[id]))]++
	}
	planned := map[string]float64{}
	for _, pl := range c.placements(p.ID) {
		if pl.Sprint != nil && pl.Size != nil {
			planned[*pl.Sprint] += *pl.Size
		}
	}
	done := map[string]float64{}
	for _, t := range c.data.Tickets {
		if t.Done && t.Estimate != nil && t.InSprint != nil && effectiveProject(c.data, t) == p.ID {
			done[*t.InSprint] += *t.Estimate
		}
	}
	for _, id := range ids {
		s := c.sprint[id]
		state := "future"
		if !s.Start.After(c.today) {
			state = "current"
		}
		r := SprintRow{Sprint: id, State: state}
		ym := monthOf(lastDay(s))
		if v, ok := p.Contingent.PerMonth.Get(ym); ok {
			r.Booked = round1(v / float64(perMonth[ym]))
		} else if p.Contingent.PerMonth.Len() == 0 && p.Contingent.Total != nil && len(ids) > 0 {
			r.Booked = round1(*p.Contingent.Total / float64(len(ids)))
		}
		if c.data.Team.Features.Tickets {
			r.Planned = c.toPD(planned[id])
			r.Done = c.toPD(done[id])
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
	snap := projectSnapshot{team: team, projects: cloneProjects(data.Projects), preplan: data.Preplan, hasPlan: data.Team.Features.Tickets}
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
	a.mu.Lock()
	a.undo = append(a.undo, snap)
	if len(a.undo) > maxUndo {
		a.undo = a.undo[len(a.undo)-maxUndo:]
	}
	a.mu.Unlock()
	storage.ClearTeamCache()
	return nil
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
		proj.Contingent = model.Contingent{Total: in.Booked}
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
			proj.Milestones = append(proj.Milestones, model.Milestone{ID: mid, Name: strings.TrimSpace(m.Name), Date: *date, Tickets: m.Tickets})
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
		p.State, p.End = state, end
		if data.Team.Features.Tickets {
			for _, t := range data.Tickets {
				if t.Done || effectiveProject(data, t) != in.ID {
					continue
				}
				setOverride(&data.Preplan, t.Key, in.MoveTo)
			}
		} else {
			p.OpenScope = nil
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
		p.State = model.ProjectOpen
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

// RuleCheck is the live check of an assignment rule.
type RuleCheck struct {
	// Error is the reason the rule cannot be read; "" = fine.
	Error string `json:"error"`
	// Matches counts the tickets the rule matches, Keys lists the first of them.
	Matches int      `json:"matches"`
	Keys    []string `json:"keys"`
	// Conflicts are the other projects whose rule matches one of the same tickets.
	Conflicts []string `json:"conflicts"`
}

// CheckRule reads a rule and counts the tickets it matches. project is the project the rule
// belongs to (its own rule is not a conflict).
func (a *API) CheckRule(team, project, text string) (RuleCheck, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return RuleCheck{}, err
	}
	out := RuleCheck{Keys: []string{}, Conflicts: []string{}}
	if strings.TrimSpace(text) == "" {
		return out, nil
	}
	r, err := rules.ParseRule(text, a.ruleSources(data))
	if err != nil {
		out.Error = err.Error()
		return out, nil
	}
	clash := map[string]bool{}
	for _, t := range data.Tickets {
		facts := t.Facts()
		if !r.Matches(facts) {
			continue
		}
		out.Matches++
		if len(out.Keys) < 5 {
			out.Keys = append(out.Keys, t.Key)
		}
		for _, p := range data.Projects {
			if p.ID != project && !p.Closed() && p.Match != nil && p.Match.Matches(facts) {
				clash[p.Name] = true
			}
		}
	}
	for name := range clash {
		out.Conflicts = append(out.Conflicts, name)
	}
	sort.Strings(out.Conflicts)
	return out, nil
}
