package app

// The Backlog area: the ranked ticket list with lanes for the coming sprints, the ticket panel
// and the presentation view. Reading uses the pre-planning of the core (preplan); writing keeps
// the PO's decisions in preplan.yaml and, for work packages, the packages themselves in
// arbeitspakete.yaml. Nothing here talks to the tracker (that is Settings > Tickets).

import (
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/preplan"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/ticketimport"
	"github.com/swallat/foresprint/internal/workpackages"
)

// backlogMu serialises the changes of the ticket files (read, change, write).
var backlogMu sync.Mutex

func backlogStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func backlogStrPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func (a *API) loadTickets(team string) (*storage.Repository, *storage.TeamData, error) {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return nil, nil, err
	}
	return repo, data, nil
}

// view builds the row of one ticket. effective product and project honour the PO's decisions.
type backlogContext struct {
	data     *storage.TeamData
	order    map[string]int
	rankPos  map[string]int // place in the order of the tracker's rank, from 1
	sprints  map[string]model.Sprint
	proForma map[string]string // lower case name to name
	byKey    map[string]*model.Ticket
}

func newBacklogContext(data *storage.TeamData) *backlogContext {
	c := &backlogContext{
		data:     data,
		order:    map[string]int{},
		rankPos:  map[string]int{},
		sprints:  map[string]model.Sprint{},
		proForma: map[string]string{},
		byKey:    map[string]*model.Ticket{},
	}
	ordered, leftover := preplan.OrderTickets(data)
	for i, tk := range append(append([]model.Ticket{}, ordered...), leftover...) {
		c.order[tk.Key] = i
	}
	for i, tk := range backlogByRank(data) {
		c.rankPos[tk.Key] = i + 1
	}
	for _, s := range data.Sprints {
		c.sprints[s.ID] = s
	}
	for _, name := range data.Team.Sprint.ProForma {
		c.proForma[strings.ToLower(strings.TrimSpace(name))] = name
	}
	for i := range data.Tickets {
		c.byKey[data.Tickets[i].Key] = &data.Tickets[i]
	}
	return c
}

// proFormaName is the pro-forma sprint the ticket is in: the PO's placement if there is a valid
// one, else the sprint the tracker has it in; "" = none.
func (c *backlogContext) proFormaName(tk model.Ticket) string {
	if pl := c.placement(tk); pl != nil {
		return c.proForma[strings.ToLower(strings.TrimSpace(pl.Name))]
	}
	return c.trackerProForma(tk)
}

// placement is the PO's placement of the ticket as far as it still counts: it is dropped when the
// tracker has meanwhile put the ticket into a real sprint or agrees with it, when the ticket is
// done, or when the pro-forma sprint is not configured any more.
func (c *backlogContext) placement(tk model.Ticket) *model.ProFormaPlacement {
	pl := c.data.Preplan.ProFormaFor(tk.Key)
	if pl == nil || tk.Done {
		return nil
	}
	if backlogStr(tk.InSprint) != "" && c.trackerProForma(tk) == "" {
		return nil
	}
	name, known := "", true
	if pl.Name != "" {
		name, known = c.proForma[strings.ToLower(strings.TrimSpace(pl.Name))]
	}
	if !known || name == c.trackerProForma(tk) {
		return nil
	}
	return pl
}

// trackerProForma is the pro-forma sprint the tracker has the ticket in, or "".
func (c *backlogContext) trackerProForma(tk model.Ticket) string {
	for _, name := range []string{backlogStr(tk.SprintName), backlogStr(tk.InSprint)} {
		if p, ok := c.proForma[strings.ToLower(strings.TrimSpace(name))]; ok && name != "" {
			return p
		}
	}
	return ""
}

// learn adds the coming sprints of the timeline that have no file yet, so that dependencies
// between earmarks in them can be checked.
func (c *backlogContext) learn(upcoming []model.Sprint) {
	for _, s := range upcoming {
		if _, ok := c.sprints[s.ID]; !ok {
			c.sprints[s.ID] = model.Sprint{ID: s.ID, Start: s.Start}
		}
	}
}

func (c *backlogContext) sprintStart(id string) (time.Time, bool) {
	s, ok := c.sprints[id]
	return s.Start, ok
}

// plannedSprint is the sprint the ticket is in according to the tracker, else its earmark.
func (c *backlogContext) plannedSprint(tk model.Ticket) string {
	if id := backlogStr(tk.InSprint); id != "" {
		return id
	}
	if e := c.data.Preplan.EarmarkFor(tk.Key); e != nil {
		return e.Sprint
	}
	return ""
}

func backlogTrackerName(team model.Team) string {
	switch team.Tracker.Kind {
	case "jira":
		return "Jira"
	case "csv":
		return "CSV"
	}
	return ""
}

// backlogByRank returns the open tickets the way the tracker ranks them: the PO's own order
// (tracker teams, preplan.yaml) first, then the tracker's rank, tickets without rank last. This is
// the default order of the backlog; priority and project do not count here.
func backlogByRank(data *storage.TeamData) []model.Ticket {
	own := map[string]int{}
	if data.Team.Source() == model.SourceTracker {
		for i, key := range data.Preplan.Order {
			own[key] = i + 1
		}
	}
	var open []model.Ticket
	for _, tk := range data.Tickets {
		if !tk.Done {
			open = append(open, tk)
		}
	}
	sort.SliceStable(open, func(i, j int) bool {
		a, b := open[i], open[j]
		na, oa := own[a.Key]
		nb, ob := own[b.Key]
		switch {
		case oa != ob:
			return oa
		case oa && na != nb:
			return na < nb
		case (a.Rank == nil) != (b.Rank == nil):
			return b.Rank == nil
		case a.Rank != nil && *a.Rank != *b.Rank:
			return *a.Rank < *b.Rank
		}
		return a.Key < b.Key
	})
	return open
}

func backlogTicketURL(team model.Team, key string) string {
	if team.Tracker.Kind != "jira" || team.Tracker.BaseURL == nil || *team.Tracker.BaseURL == "" {
		return ""
	}
	return strings.TrimRight(*team.Tracker.BaseURL, "/") + "/browse/" + key
}

func (c *backlogContext) row(tk model.Ticket) BacklogTicket {
	data := c.data
	size, source := preplan.TicketSize(tk, data, 1)
	r := BacklogTicket{
		Key:            tk.Key,
		Title:          tk.Title,
		Status:         backlogStr(tk.Status),
		Type:           backlogStr(tk.IssueType),
		Priority:       backlogStr(tk.Priority),
		Assignee:       backlogStr(tk.Assignee),
		URL:            backlogTicketURL(data.Team, tk.Key),
		Size:           size,
		SizeSource:     string(source),
		Refined:        source == model.EstimateRefined,
		RefinedUnclear: tk.RefinedUnclear,
		Earmark:        "",
		TrackerSprint:  backlogStr(tk.InSprint),
		Epic:           backlogStr(tk.Epic),
		SubtaskCount:   tk.SubtaskCount,
		Labels:         append([]string{}, tk.Labels...),
		DependsOn:      append([]string{}, tk.DependsOn...),
		RankPos:        c.rankPos[tk.Key],
	}
	if r.TrackerSprint == "" {
		r.TrackerSprint = backlogStr(tk.SprintName)
	}
	if e := data.Preplan.EarmarkFor(tk.Key); e != nil {
		r.Earmark, r.EarmarkNote = e.Sprint, backlogStr(e.Note)
	}
	r.Fixed = backlogStr(tk.InSprint) != ""
	if share := data.Preplan.ProductionFor(tk.Key); share != nil {
		p := share.Percent
		r.Production = &p
	}

	r.Project = backlogStr(tk.Project)
	over := data.Preplan.OverrideFor(tk.Key)
	if over != nil {
		if over.Daily {
			r.Project, r.ProjectSet = "", true
		} else if over.Project != nil {
			r.Project, r.ProjectSet = *over.Project, true
		}
	}
	if data.Team.Source() == model.SourcePackages {
		r.Product = backlogStr(tk.Product)
	} else {
		probe := tk
		if r.ProjectSet {
			probe.Project = backlogStrPtr(r.Project)
		}
		product, candidates := preplan.TicketProduct(probe, data)
		r.Product = backlogStr(product)
		if data.Team.Features.Products {
			switch {
			case product == nil && len(candidates) > 1:
				r.RuleHint, r.RuleProducts = "several", candidates
			case product == nil:
				r.RuleHint = "none"
			default:
				if other := preplan.ProductConflict(probe, data); other != nil {
					r.RuleHint, r.RuleProducts = "project", []string{*other}
				}
			}
		}
		if over != nil && over.Product != nil {
			r.Product, r.ProductSet = *over.Product, true
			r.RuleHint, r.RuleProducts = "", nil
		}
	}
	r.Blocked = c.blocked(tk, r.Earmark)
	return r
}

// blocked: the ticket is earmarked, but a ticket it depends on is not planned early enough.
func (c *backlogContext) blocked(tk model.Ticket, earmark string) bool {
	if earmark == "" {
		return false
	}
	mine, ok := c.sprintStart(earmark)
	if !ok {
		return false
	}
	gap := c.data.Team.Tracker.DependencyGap
	for _, key := range tk.DependsOn {
		dep := c.byKey[key]
		if dep == nil || dep.Done {
			continue
		}
		at := c.plannedSprint(*dep)
		if at == "" {
			return true
		}
		start, ok := c.sprintStart(at)
		if !ok {
			continue
		}
		if gap > 0 && !start.Before(mine) || gap == 0 && start.After(mine) {
			return true
		}
	}
	return false
}

func namedProducts(data *storage.TeamData) []Named {
	out := make([]Named, 0, len(data.Products))
	for _, p := range data.Products {
		out = append(out, Named{ID: p.ID, Name: p.Name, Closed: p.End != nil && p.End.Before(todayOf(data))})
	}
	return out
}

func namedProjects(data *storage.TeamData) []Named {
	out := make([]Named, 0, len(data.Projects))
	for _, p := range data.Projects {
		out = append(out, Named{ID: p.ID, Name: p.Name, Closed: p.Closed()})
	}
	return out
}

// Backlog returns the open tickets in planning order, the lanes of the coming sprints with
// their earmarked tickets and the pro-forma sprints.
func (a *API) Backlog(team string) (*BacklogView, error) {
	_, data, err := a.loadTickets(team)
	if err != nil {
		return nil, err
	}
	view := &BacklogView{
		Source:     string(data.Team.Source()),
		Tracker:    backlogTrackerName(data.Team),
		Unit:       settingsUnitNow(data),
		Products:   namedProducts(data),
		Projects:   namedProjects(data),
		ProjectsOn: data.Team.Features.Projects,
		Tickets:    []BacklogTicket{},
		Lanes:      []BacklogLane{},
		ProForma:   []ProFormaSprint{},
		Multi:      data.Team.Features.Products,
		Production: data.Team.Features.Production,
		Cycles:     [][]string{},
		Adjust:     []BacklogAdjust{},
		OwnOrder:   data.Team.Source() == model.SourceTracker && len(data.Preplan.Order) > 0,

		UnmatchedSprints: []string{},
	}
	if data.TicketsImported != nil {
		view.Imported = data.TicketsImported.Format(time.RFC3339)
	}
	if data.Team.Source() == model.SourceNone {
		return view, nil
	}
	c := newBacklogContext(data)
	ordered, leftover := preplan.OrderTickets(data)
	all := append(append([]model.Ticket{}, ordered...), leftover...)
	view.Cycles = append(view.Cycles, cycles(leftover)...)

	lanes, upcoming := a.lanes(data)
	lanes, upcoming, view.UnmatchedSprints = a.backlogTrackerLanes(data, a.trackerBoardSprintsFor(team, data.Team), all, lanes, upcoming)
	c.learn(upcoming)
	laneAt := map[string]int{}
	for i, l := range lanes {
		laneAt[l.Sprint] = i
	}
	pro := map[string]*ProFormaSprint{}
	for _, name := range data.Team.Sprint.ProForma {
		view.ProForma = append(view.ProForma, ProFormaSprint{Name: name, Tickets: []BacklogTicket{}})
	}
	for i := range view.ProForma {
		pro[view.ProForma[i].Name] = &view.ProForma[i]
	}
	now := todayOf(data)
	for _, tk := range all {
		r := c.row(tk)
		if name := c.proFormaName(tk); name != "" {
			pro[name].Tickets = append(pro[name].Tickets, r)
			continue
		}
		sprint := c.plannedSprint(tk)
		if i, ok := laneAt[sprint]; ok {
			lanes[i].Tickets = append(lanes[i].Tickets, r)
			continue
		}
		if s, ok := c.sprints[backlogStr(tk.InSprint)]; ok && tk.InSprint != nil && !s.End.After(now) {
			continue // finished sprint: not backlog any more
		}
		if tk.InSprint != nil && *tk.InSprint != "" {
			continue // in the running sprint: the sprint pages show it
		}
		view.Tickets = append(view.Tickets, r)
	}
	view.Lanes = lanes
	view.Drift = backlogDrift(data, now)
	for _, pl := range data.Preplan.ProForma {
		tk := c.byKey[pl.Ticket]
		if tk == nil || c.placement(*tk) == nil {
			continue
		}
		view.Adjust = append(view.Adjust, BacklogAdjust{
			Key: tk.Key, Title: tk.Title, URL: backlogTicketURL(data.Team, tk.Key),
			From: c.trackerProForma(*tk), To: c.proFormaName(*tk),
		})
	}
	return view, nil
}

// backlogDrift compares the frozen list of the running sprint with the tracker's sprint. It is
// nil without a tracker, without a running sprint that is frozen, or when nothing differs.
func backlogDrift(data *storage.TeamData, now time.Time) *BacklogDrift {
	if data.Team.Source() != model.SourceTracker {
		return nil
	}
	for _, s := range data.Sprints {
		if model.PhaseOf(data.Sprints, s, now) != model.PhaseRunning {
			continue
		}
		d := ticketimport.DetectDrift(s.CommittedTickets, data.Tickets, s.ID)
		if len(d.PulledIn)+len(d.Dropped)+len(d.Unknown) == 0 {
			return nil
		}
		return &BacklogDrift{Sprint: s.ID, PulledIn: backlogKeys(d.PulledIn), Dropped: backlogKeys(d.Dropped), Unknown: backlogKeys(d.Unknown)}
	}
	return nil
}

func backlogKeys(keys []string) []string {
	if keys == nil {
		return []string{}
	}
	return keys
}

// cycles reports the dependency cycles among the tickets the order left over.
func cycles(left []model.Ticket) [][]string {
	if len(left) == 0 {
		return nil
	}
	keys := make([]string, 0, len(left))
	for _, tk := range left {
		keys = append(keys, tk.Key)
	}
	return [][]string{keys}
}

// lanes returns every coming sprint of the timeline as a lane with its Forecast PLAN (the same
// list as the second return value).
func (a *API) lanes(data *storage.TeamData) ([]BacklogLane, []model.Sprint) {
	now := todayOf(data)
	plans := map[string]*float64{}
	var upcoming []model.Sprint
	if fc, err := forecast.Build(data, now); err == nil {
		for i := range fc.Entries {
			e := fc.Entries[i]
			if fc.Phase(e.Sprint) == model.PhaseOpen {
				upcoming = append(upcoming, e.Sprint)
				plans[e.Sprint.ID] = e.Result.Plan
			}
		}
	} else {
		for _, s := range data.Sprints {
			if model.PhaseOf(data.Sprints, s, now) == model.PhaseOpen {
				upcoming = append(upcoming, s)
			}
		}
	}
	sort.SliceStable(upcoming, func(i, j int) bool { return upcoming[i].Start.Before(upcoming[j].Start) })
	out := make([]BacklogLane, 0, len(upcoming))
	for _, s := range upcoming {
		state := "unknown"
		switch s.AbsenceStatus() {
		case model.AbsencesConfirmed:
			state = "confirmed"
		case model.AbsencesExpected:
			state = "announced"
		}
		out = append(out, BacklogLane{
			Sprint:   s.ID,
			Start:    s.Start.Format("2006-01-02"),
			End:      s.End.Format("2006-01-02"),
			Plan:     plans[s.ID],
			Absences: state,
			Tickets:  []BacklogTicket{},
		})
	}
	return out, upcoming
}

// backlogTrackerLanes adds a lane for every coming sprint the timeline does not reach (further
// ahead than the forecast horizon) that a ticket is in according to the tracker or that the Jira
// board lists, also when it is empty, so that no sprint of the tracker is missing from the
// backlog. Board sprints that match no sprint of the calendar come back by name.
func (a *API) backlogTrackerLanes(data *storage.TeamData, board []sources.SprintValue, all []model.Ticket, lanes []BacklogLane, upcoming []model.Sprint) ([]BacklogLane, []model.Sprint, []string) {
	now := todayOf(data)
	have := map[string]bool{}
	for _, l := range lanes {
		have[l.Sprint] = true
	}
	var ids []string
	ticketSprint := map[string]bool{}
	for _, tk := range all {
		if id := backlogStr(tk.InSprint); id != "" {
			ids = append(ids, id)
			ticketSprint[id] = true
		}
	}
	// Sprints of the board, also those without a ticket. A board is often shared with other teams:
	// only a name that is a known id, is mapped in the settings or holds one yearly id counts, never
	// the looser guesses of the import (a bare number after "Sprint").
	unmatched := []string{}
	for _, s := range board {
		if strings.EqualFold(s.State, "closed") {
			continue
		}
		id := ticketimport.ResolveSprintExact(s.Name, data.Team.Tracker, knownSprints{data})
		if id == nil {
			// The looser guess of the import counts when a ticket of the team is in that sprint already.
			if loose := ticketimport.ResolveSprint(s.Name, data.Team.Tracker, knownSprints{data}); loose != nil && ticketSprint[*loose] {
				id = loose
			}
		}
		switch {
		case id == nil:
			unmatched = append(unmatched, s.Name)
		case *id != model.CarryBacklog:
			ids = append(ids, *id)
		}
	}
	var extra []model.Sprint
	for _, id := range ids {
		if have[id] {
			continue
		}
		have[id] = true // also a miss: look each sprint up once
		s, err := forecast.FindSprint(data, id, forecast.DefaultLookupAhead)
		if err != nil || s == nil || !s.Start.After(now) {
			continue
		}
		extra = append(extra, *s)
	}
	// No gaps: every coming sprint up to the last one a ticket or the board uses shows too.
	if len(extra) > 0 {
		last := extra[0].Start
		for _, s := range extra {
			if s.Start.After(last) {
				last = s.Start
			}
		}
		for _, id := range forecast.KnownSprintIDs(data, forecast.DefaultLookupAhead) {
			if have[id] {
				continue
			}
			s, err := forecast.FindSprint(data, id, forecast.DefaultLookupAhead)
			if err != nil || s == nil || !s.Start.After(now) || s.Start.After(last) {
				continue
			}
			have[id] = true
			extra = append(extra, *s)
		}
	}
	sort.SliceStable(extra, func(i, j int) bool { return extra[i].Start.Before(extra[j].Start) })
	for _, s := range extra {
		lanes = append(lanes, BacklogLane{
			Sprint: s.ID, Start: s.Start.Format("2006-01-02"), End: s.End.Format("2006-01-02"),
			Absences: "unknown", Tickets: []BacklogTicket{},
		})
		upcoming = append(upcoming, s)
	}
	return lanes, upcoming, unmatched
}

// Ticket returns one ticket with all details.
func (a *API) Ticket(team, key string) (*TicketDetail, error) {
	_, data, err := a.loadTickets(team)
	if err != nil {
		return nil, err
	}
	tk := data.TicketByKey(key)
	if tk == nil {
		return nil, fmt.Errorf("%s", i18n.T("Ticket {key} not found.", "key", key))
	}
	c := newBacklogContext(data)
	lanes, upcoming := a.lanes(data)
	c.learn(upcoming)
	d := &TicketDetail{
		BacklogTicket: c.row(*tk),
		Description:   backlogStr(tk.Description),
		Acceptance:    backlogStr(tk.Acceptance),
		Subtasks:      []Subtask{},
		Comments:      []Comment{},
		Dependencies:  []Dependency{},
		Components:    append([]string{}, tk.Components...),
		Estimate:      tk.Estimate,
		Remaining:     tk.Remaining,
		Editable:      data.Team.Source() == model.SourcePackages,
		Sprints:       []string{},
		Statuses:      backlogStatusChoices(data),
		Types:         []string{"Story", "Bug", "Task"},
		Priorities:    backlogPriorityChoices(data),
		People:        []string{},
	}
	if e := data.Preplan.EarmarkFor(key); e != nil {
		d.Note = backlogStr(e.Note)
	}
	for _, s := range tk.Subtasks {
		d.Subtasks = append(d.Subtasks, Subtask{Title: s.Title, Done: s.Done})
	}
	for _, cm := range tk.Comments {
		at := ""
		if cm.At != nil {
			at = cm.At.Format(time.RFC3339)
		}
		d.Comments = append(d.Comments, Comment{Author: cm.Author, At: at, Text: cm.Text})
	}
	for _, k := range tk.DependsOn {
		dep := Dependency{Key: k}
		if o := c.byKey[k]; o != nil {
			dep.Title = o.Title
			dep.Earmark = c.plannedSprint(*o)
		}
		d.Dependencies = append(d.Dependencies, dep)
	}
	for _, l := range lanes {
		d.Sprints = append(d.Sprints, l.Sprint)
	}
	for _, p := range data.People {
		d.People = append(d.People, p.Name)
	}
	return d, nil
}

func backlogStatusChoices(data *storage.TeamData) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range []string{"New", "In progress", "In review", "Done"} {
		seen[s] = true
		out = append(out, s)
	}
	for _, tk := range data.Tickets {
		if s := backlogStr(tk.Status); s != "" && !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

func backlogPriorityChoices(data *storage.TeamData) []string {
	if len(data.Team.Tracker.PriorityOrder) > 0 {
		return append([]string{}, data.Team.Tracker.PriorityOrder...)
	}
	return append([]string{}, model.DefaultPriorityOrder...)
}

// --- Changes ------------------------------------------------------------------------------

// change loads the team, lets edit change it and returns the repository; the caller writes.
func (a *API) change(team, key string, edit func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (write func() error, err error)) error {
	backlogMu.Lock()
	defer backlogMu.Unlock()
	repo, data, err := a.loadTickets(team)
	if err != nil {
		return err
	}
	tk := data.TicketByKey(key)
	if tk == nil {
		return fmt.Errorf("%s", i18n.T("Ticket {key} not found.", "key", key))
	}
	write, err := edit(repo, data, tk)
	if err != nil {
		return err
	}
	return write()
}

func backlogSavePreplan(repo *storage.Repository, team string, data *storage.TeamData) func() error {
	return func() error {
		_, err := repo.SavePreplan(team, data.Preplan)
		return err
	}
}

func backlogSavePackages(repo *storage.Repository, team string, data *storage.TeamData) func() error {
	return func() error {
		_, err := repo.SavePackages(team, storage.TicketsFile{Tickets: data.Tickets, Imported: data.TicketsImported, Source: data.TicketsSource})
		return err
	}
}

func backlogSaveBoth(repo *storage.Repository, team string, data *storage.TeamData) func() error {
	return func() error {
		if err := backlogSavePackages(repo, team, data)(); err != nil {
			return err
		}
		return backlogSavePreplan(repo, team, data)()
	}
}

func (a *API) writePackages(data *storage.TeamData) bool {
	return data.Team.Source() == model.SourcePackages
}

func backlogRemoveEarmark(p *model.Preplan, key string) {
	out := p.Earmarks[:0:0]
	for _, e := range p.Earmarks {
		if e.Ticket != key {
			out = append(out, e)
		}
	}
	p.Earmarks = out
}

// EarmarkTicket earmarks the ticket for a coming sprint; "" takes the earmark away. note is the
// PO's note on the decision ("" keeps an existing note when only the sprint changes).
func (a *API) EarmarkTicket(team, key, sprint, note string) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if sprint == "" {
			backlogRemoveEarmark(&data.Preplan, key)
			return backlogSavePreplan(repo, team, data), nil
		}
		if tk.Done {
			return nil, fmt.Errorf("%s", i18n.T("{key} is done and cannot be earmarked.", "key", key))
		}
		if backlogStr(tk.InSprint) != "" {
			return nil, fmt.Errorf("%s", i18n.T("{key} is in a sprint in the tracker.", "key", key))
		}
		s := data.SprintByID(sprint)
		if s == nil {
			fc, err := forecast.Build(data, todayOf(data))
			if err == nil {
				if e := fc.Entry(sprint); e != nil {
					s = &e.Sprint
				}
			}
		}
		if s == nil {
			s, _ = forecast.FindSprint(data, sprint, forecast.DefaultLookupAhead) // a tracker sprint beyond the horizon
		}
		if s == nil {
			return nil, fmt.Errorf("%s", i18n.T("Sprint {id} is not known.", "id", sprint))
		}
		if !s.End.After(todayOf(data)) {
			return nil, fmt.Errorf("%s", i18n.T("Sprint {id} is over.", "id", sprint))
		}
		if c := newBacklogContext(data); c.proFormaName(*tk) != "" {
			backlogSetProForma(data, c, *tk, "") // leaves the pro-forma sprint
		}
		prev := ""
		if e := data.Preplan.EarmarkFor(key); e != nil {
			prev = backlogStr(e.Note)
		}
		backlogRemoveEarmark(&data.Preplan, key)
		if note == "" {
			note = prev
		}
		data.Preplan.Earmarks = append(data.Preplan.Earmarks, model.Earmark{Ticket: key, Sprint: sprint, Note: backlogStrPtr(note)})
		return backlogSavePreplan(repo, team, data), nil
	})
}

// backlogSetProForma records where the PO wants the ticket; the placement is kept only while
// it differs from what the tracker has.
func backlogSetProForma(data *storage.TeamData, c *backlogContext, tk model.Ticket, name string) {
	pp := &data.Preplan
	kept := pp.ProForma[:0:0]
	for _, pl := range pp.ProForma {
		other := c.byKey[pl.Ticket]
		if pl.Ticket != tk.Key && other != nil && c.placement(*other) != nil { // drops the stale ones as well
			kept = append(kept, pl)
		}
	}
	pp.ProForma = kept
	if name != c.trackerProForma(tk) {
		pp.ProForma = append(pp.ProForma, model.ProFormaPlacement{Ticket: tk.Key, Name: name})
	}
}

// MoveTicketByRank puts a ticket next to another one in the order of the tracker's rank (the
// default order of the backlog): before the anchor, after it when after is set, "" = to the end.
// Nothing decides here but the position, so it always works, as in the tracker. For a tracker
// the order is kept in preplan.yaml beside the tracker's rank and never written back.
func (a *API) MoveTicketByRank(team, key, anchor string, after bool) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if data.Team.Source() == model.SourceNone {
			return nil, fmt.Errorf("%s", i18n.T("There are no tickets to order."))
		}
		if tk.Done {
			return nil, fmt.Errorf("%s", i18n.T("{key} is done and has no place in the backlog.", "key", key))
		}
		if anchor == key {
			return func() error { return nil }, nil
		}
		var keys []string
		for _, o := range backlogByRank(data) {
			if o.Key != key {
				keys = append(keys, o.Key)
			}
		}
		at := len(keys)
		if anchor != "" {
			at = slices.Index(keys, anchor)
			if at < 0 {
				return nil, fmt.Errorf("%s", i18n.T("{key} is not in the backlog.", "key", anchor))
			}
			if after {
				at++
			}
		}
		keys = slices.Insert(keys, at, key)
		if a.writePackages(data) {
			for n, k := range keys {
				r := fmt.Sprintf("%08d", (n+1)*10)
				if t := data.TicketByKey(k); t != nil {
					t.Rank = &r
				}
			}
			return backlogSavePackages(repo, team, data), nil
		}
		data.Preplan.Order = keys
		return backlogSavePreplan(repo, team, data), nil
	})
}

// ResetOrder takes the PO's own order of tracker tickets away: the tracker's rank counts again.
func (a *API) ResetOrder(team string) error {
	backlogMu.Lock()
	defer backlogMu.Unlock()
	repo, data, err := a.loadTickets(team)
	if err != nil {
		return err
	}
	data.Preplan.Order = nil
	return backlogSavePreplan(repo, team, data)()
}

// MoveToProForma puts a tracker ticket into the pro-forma sprint of that name, or ("") back
// into the backlog. The tool only remembers the decision; the list "adjust in the tracker"
// shows what still differs from the tracker.
func (a *API) MoveToProForma(team, key, name string) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if data.Team.Source() != model.SourceTracker {
			return nil, fmt.Errorf("%s", i18n.T("Pro-forma sprints exist only for tickets from a tracker."))
		}
		c := newBacklogContext(data)
		if name != "" {
			canon, ok := c.proForma[strings.ToLower(strings.TrimSpace(name))]
			if !ok {
				return nil, fmt.Errorf("%s", i18n.T("{name} is not a pro-forma sprint of this team.", "name", name))
			}
			name = canon
		}
		if tk.Done {
			return nil, fmt.Errorf("%s", i18n.T("{key} is done and cannot be moved.", "key", key))
		}
		if backlogStr(tk.InSprint) != "" && c.trackerProForma(*tk) == "" {
			return nil, fmt.Errorf("%s", i18n.T("{key} is in a sprint in the tracker.", "key", key))
		}
		backlogSetProForma(data, c, *tk, name)
		if name != "" {
			backlogRemoveEarmark(&data.Preplan, key)
		}
		return backlogSavePreplan(repo, team, data), nil
	})
}

// SetEarmarkNote sets the PO's note on an existing earmark; "" takes the note away.
func (a *API) SetEarmarkNote(team, key, note string) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		for i := range data.Preplan.Earmarks {
			if data.Preplan.Earmarks[i].Ticket == key {
				data.Preplan.Earmarks[i].Note = backlogStrPtr(note)
				return backlogSavePreplan(repo, team, data), nil
			}
		}
		return nil, fmt.Errorf("%s", i18n.T("{key} is not earmarked.", "key", key))
	})
}

// SetEstimate sets the estimate of a ticket: for a work package its estimate, for a tracker
// ticket without an estimate the PO's own estimate; nil takes it away.
func (a *API) SetEstimate(team, key string, value *float64) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if value != nil && *value < 0 {
			return nil, fmt.Errorf("%s", i18n.T("The estimate cannot be negative."))
		}
		if a.writePackages(data) {
			refined := tk.EstimateSource == model.EstimateRefined
			tk.Estimate = value
			tk.EstimateSource = estimateSource(value, refined)
			return backlogSavePackages(repo, team, data), nil
		}
		if tk.Estimate != nil || tk.Remaining != nil {
			return nil, fmt.Errorf("%s", i18n.T("The estimate of {key} comes from the tracker.", "key", key))
		}
		pp := &data.Preplan
		kept := pp.Estimates[:0:0]
		for _, m := range pp.Estimates {
			if m.Ticket != key {
				kept = append(kept, m)
			}
		}
		pp.Estimates = kept
		if value != nil {
			pp.Estimates = append(pp.Estimates, model.ManualEstimate{Ticket: key, Estimate: value})
		}
		return backlogSavePreplan(repo, team, data), nil
	})
}

func estimateSource(estimate *float64, refined bool) model.EstimateSource {
	switch {
	case estimate == nil:
		return model.EstimateNone
	case refined:
		return model.EstimateRefined
	}
	return model.EstimateRough
}

// SetRefined sets the refined state of a work package (a tracker ticket is refined in the
// tracker).
func (a *API) SetRefined(team, key string, refined bool) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if !a.writePackages(data) {
			return nil, fmt.Errorf("%s", i18n.T("{key} is refined in the tracker.", "key", key))
		}
		tk.EstimateSource = estimateSource(tk.Estimate, refined)
		return backlogSavePackages(repo, team, data), nil
	})
}

// SetAssignment sets product and project of a ticket. For a work package they are its fields;
// for a tracker ticket they are the PO's decision against the rules. product "" keeps the rule,
// project "" with daily true says daily business; project "" with daily false keeps the rule.
func (a *API) SetAssignment(team, key, product, project string, daily bool) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if product != "" && !backlogHasID(namedProducts(data), product) {
			return nil, fmt.Errorf("%s", i18n.T("Product {id} is not known.", "id", product))
		}
		projectsOn := data.Team.Features.Projects
		if projectsOn && project != "" && !backlogHasID(namedProjects(data), project) {
			return nil, fmt.Errorf("%s", i18n.T("Project {id} is not known.", "id", project))
		}
		if a.writePackages(data) {
			tk.Product = backlogStrPtr(product)
			if projectsOn { // off: the project stays as it was, the window does not offer it
				tk.Project = backlogStrPtr(project)
			}
			return backlogSavePackages(repo, team, data), nil
		}
		pp := &data.Preplan
		kept := pp.Overrides[:0:0]
		for _, o := range pp.Overrides {
			if o.Ticket != key {
				kept = append(kept, o)
			} else if !projectsOn { // keep the earlier decision about the project
				project, daily = "", o.Daily
				if o.Project != nil {
					project = *o.Project
				}
			}
		}
		pp.Overrides = kept
		if product != "" || project != "" || daily {
			pp.Overrides = append(pp.Overrides, model.TicketOverride{Ticket: key, Product: backlogStrPtr(product), Project: backlogStrPtr(project), Daily: daily && project == ""})
		}
		return backlogSavePreplan(repo, team, data), nil
	})
}

func backlogHasID(list []Named, id string) bool {
	for _, n := range list {
		if n.ID == id {
			return true
		}
	}
	return false
}

// SetProduction sets the share (0 to 100) of the ticket that needs production access; nil
// takes the value set here away.
func (a *API) SetProduction(team, key string, percent *float64) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if percent != nil && (*percent < 0 || *percent > 100) {
			return nil, fmt.Errorf("%s", i18n.T("The production share is between 0 and 100 percent."))
		}
		pp := &data.Preplan
		kept := pp.Production[:0:0]
		for _, s := range pp.Production {
			if s.Ticket != key {
				kept = append(kept, s)
			}
		}
		pp.Production = kept
		if percent != nil {
			pp.Production = append(pp.Production, model.ProductionShare{Ticket: key, Percent: *percent})
		}
		return backlogSavePreplan(repo, team, data), nil
	})
}

// --- Work packages ------------------------------------------------------------------------

func nextPackageKey(data *storage.TeamData) string {
	return workpackages.NextKey(data.Tickets, workpackages.Prefix(data.Team.Tracker))
}

// rankFirst gives the work package the first rank: below the lowest numeric rank if there is
// room, else all others are renumbered in their order.
func rankFirst(data *storage.TeamData, key string) {
	lowest := -1
	for _, tk := range data.Tickets {
		if tk.Key == key {
			continue
		}
		n, err := strconv.Atoi(backlogStr(tk.Rank))
		if err != nil || n < 0 {
			lowest = -2
			break
		}
		if lowest == -1 || n < lowest {
			lowest = n
		}
	}
	if lowest == -1 || lowest > 0 {
		r := fmt.Sprintf("%08d", max(lowest-1, 0))
		if lowest == -1 {
			r = fmt.Sprintf("%08d", 1000)
		}
		for i := range data.Tickets {
			if data.Tickets[i].Key == key {
				data.Tickets[i].Rank = &r
			}
		}
		return
	}
	var rest []model.Ticket
	for _, tk := range data.Tickets {
		if tk.Key != key {
			rest = append(rest, tk)
		}
	}
	rest = preplan.TicketOrder(rest)
	rank := map[string]string{key: fmt.Sprintf("%08d", 1000)}
	for i, tk := range rest {
		rank[tk.Key] = fmt.Sprintf("%08d", 2000+i*1000)
	}
	for i := range data.Tickets {
		r := rank[data.Tickets[i].Key]
		data.Tickets[i].Rank = &r
	}
}

// SaveWorkPackage creates (Key "") or changes a work package and returns its key. A new one goes
// first among the tickets of its priority.
func (a *API) SaveWorkPackage(team string, in WorkPackageInput) (string, error) {
	backlogMu.Lock()
	defer backlogMu.Unlock()
	repo, data, err := a.loadTickets(team)
	if err != nil {
		return "", err
	}
	if !a.writePackages(data) {
		return "", fmt.Errorf("%s", i18n.T("This team gets its tickets from a tracker, not from work packages."))
	}
	title := strings.TrimSpace(in.Title)
	if title == "" {
		return "", fmt.Errorf("%s", i18n.T("A work package needs a title."))
	}
	if in.Estimate != nil && *in.Estimate < 0 {
		return "", fmt.Errorf("%s", i18n.T("The estimate cannot be negative."))
	}
	if in.Product != "" && !backlogHasID(namedProducts(data), in.Product) {
		return "", fmt.Errorf("%s", i18n.T("Product {id} is not known.", "id", in.Product))
	}
	if data.Team.Features.Projects && in.Project != "" && !backlogHasID(namedProjects(data), in.Project) {
		return "", fmt.Errorf("%s", i18n.T("Project {id} is not known.", "id", in.Project))
	}
	tk := data.TicketByKey(in.Key)
	created := tk == nil
	if created {
		if in.Key != "" {
			return "", fmt.Errorf("%s", i18n.T("Ticket {key} not found.", "key", in.Key))
		}
		data.Tickets = append(data.Tickets, model.Ticket{Key: nextPackageKey(data)})
		tk = &data.Tickets[len(data.Tickets)-1]
	}
	for _, dep := range in.DependsOn {
		if dep == tk.Key {
			return "", fmt.Errorf("%s", i18n.T("A work package cannot depend on itself."))
		}
		if data.TicketByKey(dep) == nil {
			return "", fmt.Errorf("%s", i18n.T("Ticket {key} not found.", "key", dep))
		}
	}
	status := strings.TrimSpace(in.Status)
	tk.Title = title
	tk.Status = backlogStrPtr(status)
	tk.IssueType = backlogStrPtr(strings.TrimSpace(in.Type))
	tk.Priority = backlogStrPtr(strings.TrimSpace(in.Priority))
	tk.Assignee = backlogStrPtr(strings.TrimSpace(in.Assignee))
	tk.Product = backlogStrPtr(in.Product)
	if data.Team.Features.Projects { // off: the project stays as it was
		tk.Project = backlogStrPtr(in.Project)
	}
	tk.Estimate = in.Estimate
	tk.EstimateSource = estimateSource(in.Estimate, in.Refined)
	tk.Labels = backlogCleanList(in.Labels)
	tk.Description = backlogStrPtr(strings.TrimSpace(in.Description))
	tk.Acceptance = backlogStrPtr(strings.TrimSpace(in.Acceptance))
	tk.DependsOn = backlogCleanList(in.DependsOn)
	tk.Done = in.Done || status == "Done"
	tk.Subtasks = nil
	for _, s := range in.Subtasks {
		if strings.TrimSpace(s.Title) != "" {
			tk.Subtasks = append(tk.Subtasks, model.Subtask{Title: strings.TrimSpace(s.Title), Done: s.Done})
		}
	}
	tk.Comments = nil
	for _, c := range in.Comments {
		if strings.TrimSpace(c.Text) == "" {
			continue
		}
		comment := model.Comment{Author: c.Author, Text: strings.TrimSpace(c.Text)}
		if at, err := time.Parse(time.RFC3339, c.At); err == nil {
			comment.At = &at
		}
		tk.Comments = append(tk.Comments, comment)
	}
	key := tk.Key
	if created {
		rankFirst(data, key)
	}
	if tk.Done {
		backlogRemoveEarmark(&data.Preplan, key)
	}
	if err := backlogSaveBoth(repo, team, data)(); err != nil {
		return "", err
	}
	return key, nil
}

func backlogCleanList(in []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, s := range in {
		if s = strings.TrimSpace(s); s != "" && !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

// DeleteWorkPackage removes a work package with its earmark, own estimate, decisions and the
// dependencies on it.
func (a *API) DeleteWorkPackage(team, key string) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if !a.writePackages(data) {
			return nil, fmt.Errorf("%s", i18n.T("Only work packages can be deleted here."))
		}
		kept := data.Tickets[:0:0]
		for _, o := range data.Tickets {
			if o.Key == key {
				continue
			}
			var deps []string
			for _, d := range o.DependsOn {
				if d != key {
					deps = append(deps, d)
				}
			}
			o.DependsOn = deps
			kept = append(kept, o)
		}
		data.Tickets = kept
		pp := &data.Preplan
		backlogRemoveEarmark(pp, key)
		var est []model.ManualEstimate
		for _, m := range pp.Estimates {
			if m.Ticket != key {
				est = append(est, m)
			}
		}
		pp.Estimates = est
		var prod []model.ProductionShare
		for _, s := range pp.Production {
			if s.Ticket != key {
				prod = append(prod, s)
			}
		}
		pp.Production = prod
		var over []model.TicketOverride
		for _, o := range pp.Overrides {
			if o.Ticket != key {
				over = append(over, o)
			}
		}
		pp.Overrides = over
		return backlogSaveBoth(repo, team, data), nil
	})
}

// MoveWorkPackage puts a work package next to another one in the backlog order: before it, or
// after it when after is set; anchor "" means to the end. The rank decides only among packages
// of the same priority and project and behind dependencies, so a move the order does not show
// is refused instead of silently doing nothing. For a tracker the order is kept in preplan.yaml
// beside the tracker's rank and never written back to the tracker.
func (a *API) MoveWorkPackage(team, key, anchor string, after bool) error {
	return a.change(team, key, func(repo *storage.Repository, data *storage.TeamData, tk *model.Ticket) (func() error, error) {
		if data.Team.Source() == model.SourceNone {
			return nil, fmt.Errorf("%s", i18n.T("There are no tickets to order."))
		}
		if tk.Done {
			return nil, fmt.Errorf("%s", i18n.T("{key} is done and has no place in the backlog.", "key", key))
		}
		if anchor == key {
			return func() error { return nil }, nil
		}
		// The stored order is the order of the rank with this one ticket moved, so that a move
		// in the planning order does not turn the rank order of the others into planning order.
		var keys []string
		for _, o := range backlogByRank(data) {
			if o.Key != key {
				keys = append(keys, o.Key)
			}
		}
		at := len(keys)
		if anchor != "" {
			at = -1
			for i, k := range keys {
				if k == anchor {
					at = i
				}
			}
			if at < 0 {
				return nil, fmt.Errorf("%s", i18n.T("{key} is not in the backlog.", "key", anchor))
			}
			if after {
				at++
			}
		}
		keys = append(keys[:at], append([]string{key}, keys[at:]...)...)
		if a.writePackages(data) {
			for n, k := range keys {
				r := fmt.Sprintf("%08d", (n+1)*10)
				if t := data.TicketByKey(k); t != nil {
					t.Rank = &r
				}
			}
		} else {
			// Tracker tickets keep the tracker's rank; the order of the PO is stored beside it.
			data.Preplan.Order = keys
		}
		// The new order must show; otherwise priority, project or a dependency keeps the package
		// where it is. Nothing is saved then.
		reordered, rest := preplan.OrderTickets(data)
		got := slices.Concat(reordered, rest)
		for i := range got {
			if got[i].Key != key {
				continue
			}
			wantBefore := at+1 < len(keys) && !after
			if (after && (i == 0 || got[i-1].Key != anchor)) || (wantBefore && (i+1 >= len(got) || got[i+1].Key != anchor)) || (anchor == "" && i != len(got)-1) {
				return nil, fmt.Errorf("%s", i18n.T("{key} has to stay where it is: priority, project or a dependency decides here. Change that in the panel first.", "key", key))
			}
		}
		if a.writePackages(data) {
			return backlogSavePackages(repo, team, data), nil
		}
		return backlogSavePreplan(repo, team, data), nil
	})
}
