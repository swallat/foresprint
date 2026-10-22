package app

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sprintcal"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
)

// pastShown is the number of finished sprints the calendar shows above the running one.
const pastShown = 3

func lastDayOf(s model.Sprint) time.Time { return s.End.Add(-24 * time.Hour) }

func calendarState(data *storage.TeamData, s model.Sprint, today time.Time) string {
	switch {
	case !s.End.After(today):
		return CalFinished
	case !s.Start.After(today):
		return CalRunning
	case data.SprintByID(s.ID) == nil:
		return CalPlanned
	}
	return CalOpen
}

func holidaysIn(data *storage.TeamData, s model.Sprint) []HolidayDTO {
	out := []HolidayDTO{}
	c := data.Team.Capacity
	region := ""
	if c.Region != nil {
		region = *c.Region
	}
	for d := s.Start; d.Before(s.End); d = d.Add(24 * time.Hour) {
		if calendar.IsHoliday(d, region, c.Country) {
			out = append(out, HolidayDTO{Date: d.Format(isoDay), Name: calendar.HolidayName(i18n.Language(), d, region, c.Country)})
		}
	}
	return out
}

func namingDTO(rules []model.NamingRule) []NamingRuleDTO {
	out := []NamingRuleDTO{}
	for _, r := range rules {
		from := ""
		if r.From != nil {
			from = *r.From
		}
		out = append(out, NamingRuleDTO{From: from, Pattern: r.Pattern})
	}
	return out
}

func (a *API) calendarWindow(data *storage.TeamData, count int) ([]model.Sprint, error) {
	fc, err := forecast.Build(data, a.day())
	if err != nil {
		return nil, err
	}
	if count < 1 {
		count = 1
	}
	return sprintcal.AbsenceSprints(data, fc, count, pastShown)
}

func (a *API) calendarView(data *storage.TeamData, sprints []model.Sprint) CalendarView {
	today := a.day()
	view := CalendarView{
		Today:        today.Format(isoDay),
		Country:      data.Team.Capacity.Country,
		Rows:         []CalendarRow{},
		Naming:       namingDTO(data.Team.Sprint.Naming),
		Placeholders: model.NamingPlaceholders,
		ProForma:     append([]string{}, data.Team.Sprint.ProForma...),
	}
	if r := data.Team.Capacity.Region; r != nil {
		view.Region = *r
	}
	if n := data.Team.Sprint.Naming; len(n) > 0 {
		view.Pattern = n[len(n)-1].Pattern
	}
	for _, s := range sprints {
		state := calendarState(data, s, today)
		view.Rows = append(view.Rows, CalendarRow{
			ID: s.ID, Start: s.Start.Format(isoDay), Last: lastDayOf(s).Format(isoDay),
			Workdays: len(calendar.TeamWorkdays(&data.Team, s.Start, s.End)),
			Holidays: holidaysIn(data, s),
			State:    state, Locked: state == CalFinished, Saved: data.SprintByID(s.ID) != nil,
		})
	}
	return view
}

// Calendar is the sprint calendar: the last finished sprints, the running one and count
// sprints from it on.
func (a *API) Calendar(team string, count int) (CalendarView, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return CalendarView{}, err
	}
	sprints, err := a.calendarWindow(data, count)
	if err != nil {
		return CalendarView{}, err
	}
	return a.calendarView(data, sprints), nil
}

// SaveLastDays changes last days of open sprints; the following sprints keep their length and
// move along. Finished sprints are locked. The sprint files that change are written; a
// sprint that has no file yet gets one.
func (a *API) SaveLastDays(team string, changes []LastDay, count int) (CalendarResult, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	sprints, err := a.calendarWindow(data, count)
	if err != nil {
		return CalendarResult{}, err
	}
	today := a.day()
	rows := sprintcal.Table(data, sprints, today)
	for _, c := range changes {
		last, perr := time.Parse(isoDay, c.Last)
		idx := -1
		for i, r := range rows {
			if r.Sprint == c.ID {
				idx = i
			}
		}
		if idx < 0 || perr != nil {
			return CalendarResult{}, errors.New(i18n.T("Enter a valid last day."))
		}
		if calendarState(data, sprints[idx], today) == CalFinished {
			return CalendarResult{}, errors.New(i18n.T("A finished sprint is locked."))
		}
		rows[idx].Last = last
	}
	// Finished sprints stay as they are: only the sprints from the first one that has not ended
	// are placed again.
	first := 0
	for first < len(sprints) && calendarState(data, sprints[first], today) == CalFinished {
		first++
	}
	sprints, rows = sprints[first:], rows[first:]
	if len(sprints) == 0 {
		return CalendarResult{}, errors.New(i18n.T("A finished sprint is locked."))
	}
	after, problems, err := sprintcal.Apply(data, sprints, rows)
	if err != nil {
		return CalendarResult{}, err
	}
	if len(problems) > 0 {
		return CalendarResult{}, errors.New(strings.Join(problems, " "))
	}
	changed := sprintcal.ToSave(data, sprints, after, false)
	for _, i := range validate.CheckTeam(sprintcal.WithSprints(data, changed), today) {
		if i.Level == validate.Error && strings.HasPrefix(i.Where, "sprints/") {
			return CalendarResult{}, errors.New(i.Message)
		}
	}
	repo := storage.NewRepository(a.DataDir())
	var files []string
	for _, s := range changed {
		p, err := repo.SprintPath(team, s.ID)
		if err != nil {
			return CalendarResult{}, err
		}
		files = append(files, p)
	}
	token := 0
	if len(files) > 0 {
		token = a.remember(team, files...)
	}
	for i := range changed {
		if _, err := repo.SaveSprint(team, &changed[i]); err != nil {
			if token != 0 {
				_ = a.Undo(team, token) // no half-shifted calendar
			}
			return CalendarResult{}, err
		}
	}
	moved := 0
	edited := map[string]bool{}
	for _, c := range changes {
		edited[c.ID] = true
	}
	for i, s := range after[:len(sprints)] {
		if !edited[sprints[i].ID] && !s.Start.Equal(sprints[i].Start) {
			moved++
		}
	}
	fresh, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	window, err := a.calendarWindow(fresh, count)
	if err != nil {
		return CalendarResult{}, err
	}
	return CalendarResult{View: a.calendarView(fresh, window), Moved: moved, Undo: token}, nil
}

// numbersOfFirst are the number in the year and the running number of the first recorded
// sprint, read from its ID in the form of the numbering (1 and 1 if it has none).
func numbersOfFirst(data *storage.TeamData) (number, seq int) {
	number, seq = 1, 1
	if len(data.Sprints) == 0 {
		return
	}
	first := data.Sprints[0]
	if data.Team.Sprint.Numbering == model.NumberingSequential {
		if n, err := strconv.Atoi(first.ID); err == nil && n > 0 {
			seq = n
		}
		return
	}
	if year, counter, ok := strings.Cut(first.ID, "."); ok && year == strconv.Itoa(first.Start.Year()) {
		if n, err := strconv.Atoi(counter); err == nil && n > 0 {
			number = n
		}
	}
	return
}

// namingList is every recorded sprint plus the generated ones up to and including the last
// sprint of the window.
func (a *API) namingList(data *storage.TeamData, window []model.Sprint) ([]model.Sprint, error) {
	list := append([]model.Sprint(nil), data.Sprints...)
	if len(window) == 0 {
		return list, nil
	}
	end := window[len(window)-1].Start
	chain := calendar.NewChain(&data.Team, data.Sprints)
	for guard := 0; guard < 200; guard++ {
		if n := len(list); n > 0 && !list[n-1].Start.Before(end) {
			break
		}
		next, err := chain.Next()
		if err != nil {
			return nil, err
		}
		if len(list) > 0 && !next.Start.After(list[len(list)-1].Start) {
			break
		}
		list = append(list, next)
	}
	return list, nil
}

type namingPlan struct {
	list     []model.Sprint
	names    []string
	fromIdx  int
	changes  []bool
	windowAt int // index in list of the first sprint of the window
}

func (a *API) planNaming(data *storage.TeamData, window []model.Sprint, pattern, from string, all bool) (*namingPlan, error) {
	list, err := a.namingList(data, window)
	if err != nil {
		return nil, err
	}
	number, seq := numbersOfFirst(data)
	names, err := calendar.NameAll(pattern, list, number, seq)
	if err != nil {
		return nil, err
	}
	today := a.day()
	p := &namingPlan{list: list, names: names, changes: make([]bool, len(list))}
	switch {
	case all:
		p.fromIdx = 0
	case from != "":
		p.fromIdx = -1
		for i, s := range list {
			if s.ID == from {
				p.fromIdx = i
			}
		}
		if p.fromIdx < 0 {
			return nil, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", from))
		}
	default:
		p.fromIdx = len(list)
		for i, s := range list {
			if s.Start.After(today) {
				p.fromIdx = i
				break
			}
		}
	}
	for i := range list {
		p.changes[i] = i >= p.fromIdx && names[i] != list[i].ID
	}
	for i, s := range list {
		if len(window) > 0 && s.ID == window[0].ID {
			p.windowAt = i
		}
	}
	return p, nil
}

func hasNumber(pattern string) bool {
	for _, p := range []string{"{NN}", "{N}", "{LFD}", "{KW}"} {
		if strings.Contains(pattern, p) {
			return true
		}
	}
	return false
}

// NamingPreview shows what the pattern would do from the sprint from on ("" = the first sprint
// that has not begun); all also takes the running and finished sprints.
func (a *API) NamingPreview(team, pattern, from string, all bool, count int) (NamingPreview, error) {
	prev := NamingPreview{Rows: []NamePreview{}, NoNumber: !hasNumber(pattern)}
	if bad := model.NamingProblem(pattern); bad != "" {
		prev.Problem = bad
		return prev, nil
	}
	data, err := a.loadTeam(team)
	if err != nil {
		return prev, err
	}
	window, err := a.calendarWindow(data, count)
	if err != nil {
		return prev, err
	}
	plan, err := a.planNaming(data, window, pattern, from, all)
	if err != nil {
		return prev, err
	}
	today := a.day()
	final := map[string]bool{}
	for i, s := range plan.list {
		name := s.ID
		if plan.changes[i] {
			name = plan.names[i]
			prev.Count++
		}
		if final[name] && prev.Duplicate == "" {
			prev.Duplicate = name
		}
		final[name] = true
		if i < plan.windowAt {
			continue
		}
		prev.Rows = append(prev.Rows, NamePreview{
			Index: i, Start: s.Start.Format(isoDay), Old: s.ID, New: plan.names[i],
			Locked:  calendarState(data, s, today) == CalFinished && !all,
			Saved:   data.SprintByID(s.ID) != nil,
			Changes: plan.changes[i],
		})
	}
	return prev, nil
}

// ApplyNaming renames the sprints that change (files, minutes and references move along) and
// remembers the pattern for the sprints that follow.
func (a *API) ApplyNaming(team, pattern, from string, all bool, count int) (CalendarResult, error) {
	if bad := model.NamingProblem(pattern); bad != "" {
		return CalendarResult{}, fmt.Errorf("%s", i18n.T("unknown placeholder {name} in sprint naming pattern", "name", bad))
	}
	data, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	window, err := a.calendarWindow(data, count)
	if err != nil {
		return CalendarResult{}, err
	}
	plan, err := a.planNaming(data, window, pattern, from, all)
	if err != nil {
		return CalendarResult{}, err
	}
	if !all && plan.fromIdx < len(plan.list) && calendarState(data, plan.list[plan.fromIdx], a.day()) == CalFinished {
		return CalendarResult{}, errors.New(i18n.T("A finished sprint is locked."))
	}
	final := map[string]bool{}
	var renames []sprintcal.Rename
	for i, s := range plan.list {
		name := s.ID
		if plan.changes[i] {
			name = plan.names[i]
			if data.SprintByID(s.ID) != nil {
				if problem := storage.FileNameProblem(name, false); problem != "" {
					return CalendarResult{}, fmt.Errorf("%s", i18n.T("ID not allowed as a file name ({problem}).", "problem", problem))
				}
				renames = append(renames, sprintcal.Rename{Old: s.ID, New: name})
			}
		}
		if final[name] {
			return CalendarResult{}, fmt.Errorf("%s", i18n.T("Sprint ID {id} is already taken (by an earlier sprint).", "id", name))
		}
		final[name] = true
	}
	repo := storage.NewRepository(a.DataDir())
	token := a.rememberTree(team)
	if _, err := sprintcal.ApplyRenames(repo, data, renames); err != nil {
		_ = a.Undo(team, token)
		return CalendarResult{}, err
	}
	// The rule begins at the first sprint of the change; earlier rules stay for earlier sprints.
	var rules []model.NamingRule
	indexOf := func(id string) int {
		for i, s := range plan.list {
			if s.ID == id {
				return i
			}
		}
		return -1
	}
	for _, r := range data.Team.Sprint.Naming {
		if plan.fromIdx > 0 && (r.From == nil || (indexOf(*r.From) >= 0 && indexOf(*r.From) < plan.fromIdx)) {
			rules = append(rules, r)
		}
	}
	rule := model.NamingRule{Pattern: pattern}
	if plan.fromIdx > 0 && plan.fromIdx < len(plan.list) {
		id := plan.list[plan.fromIdx].ID
		if plan.changes[plan.fromIdx] && data.SprintByID(id) != nil {
			id = plan.names[plan.fromIdx]
		}
		rule.From = &id
	}
	rules = append(rules, rule)
	data.Team.Sprint.Naming = rules
	if _, err := repo.SaveTeam(data.Team); err != nil {
		_ = a.Undo(team, token)
		return CalendarResult{}, err
	}
	fresh, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	shown, err := a.calendarWindow(fresh, count)
	if err != nil {
		return CalendarResult{}, err
	}
	return CalendarResult{View: a.calendarView(fresh, shown), Moved: len(renames), Undo: token}, nil
}

// RenameSprint gives one sprint another ID (an exception to the pattern). Tickets, minutes and
// the history move along; the new ID must be free.
func (a *API) RenameSprint(team, sprintID, newID string, count int) (CalendarResult, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	newID = strings.TrimSpace(newID)
	switch {
	case newID == "":
		return CalendarResult{}, errors.New(i18n.T("Please enter a new sprint ID."))
	case data.SprintByID(sprintID) == nil:
		return CalendarResult{}, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", sprintID))
	case newID != sprintID && data.SprintByID(newID) != nil:
		return CalendarResult{}, fmt.Errorf("%s", i18n.T("Sprint ID {id} is already taken (by an earlier sprint).", "id", newID))
	}
	if problem := storage.FileNameProblem(newID, false); problem != "" {
		return CalendarResult{}, fmt.Errorf("%s", i18n.T("ID not allowed as a file name ({problem}).", "problem", problem))
	}
	if old := data.SprintByID(sprintID); old != nil && calendarState(data, *old, a.day()) == CalFinished {
		return CalendarResult{}, errors.New(i18n.T("A finished sprint is locked."))
	}
	token := 0
	if newID != sprintID {
		token = a.rememberTree(team)
		if _, err := sprintcal.ApplyRenames(storage.NewRepository(a.DataDir()), data, []sprintcal.Rename{{Old: sprintID, New: newID}}); err != nil {
			_ = a.Undo(team, token)
			return CalendarResult{}, err
		}
	}
	fresh, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	shown, err := a.calendarWindow(fresh, count)
	if err != nil {
		return CalendarResult{}, err
	}
	return CalendarResult{View: a.calendarView(fresh, shown), Undo: token}, nil
}
