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

// calendarPastShown is the number of finished sprints the calendar shows above the running one.
const calendarPastShown = 3

func calendarLastDayOf(s model.Sprint) time.Time { return s.End.Add(-24 * time.Hour) }

func calendarState(data *storage.TeamData, s model.Sprint, today time.Time) string {
	switch phase := model.PhaseOf(data.Sprints, s, today); {
	case phase == model.PhasePast:
		return CalFinished
	case phase == model.PhaseRunning:
		return CalRunning
	case data.SprintByID(s.ID) == nil:
		return CalPlanned
	}
	return CalOpen
}

// calendarHolidaysIn are the holidays that fall on a workday of the team in the sprint; holidays
// on a weekend take nothing away and are left out.
func calendarHolidaysIn(data *storage.TeamData, s model.Sprint) []HolidayDTO {
	out := []HolidayDTO{}
	c := data.Team.Capacity
	region := ""
	if c.Region != nil {
		region = *c.Region
	}
	for _, d := range calendar.TeamWorkdays(&data.Team, s.Start, s.End) {
		if calendar.IsHoliday(d, region, c.Country) {
			out = append(out, HolidayDTO{Date: d.Format(isoDay), Name: calendar.HolidayName(i18n.Language(), d, region, c.Country)})
		}
	}
	return out
}

func calendarNamingDTO(rules []model.NamingRule) []NamingRuleDTO {
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
	fc, err := forecast.Build(data, a.dayOf(data))
	if err != nil {
		return nil, err
	}
	if count < 1 {
		count = 1
	}
	return sprintcal.AbsenceSprints(data, fc, count, calendarPastShown)
}

func (a *API) calendarView(data *storage.TeamData, sprints []model.Sprint) CalendarView {
	today := a.dayOf(data)
	view := CalendarView{
		Today:        today.Format(isoDay),
		Country:      data.Team.Capacity.Country,
		Rows:         []CalendarRow{},
		Naming:       calendarNamingDTO(data.Team.Sprint.Naming),
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
		holidays := calendarHolidaysIn(data, s)
		view.Rows = append(view.Rows, CalendarRow{
			ID: s.ID, Start: s.Start.Format(isoDay), Last: calendarLastDayOf(s).Format(isoDay),
			Workdays: len(calendar.TeamWorkdays(&data.Team, s.Start, s.End)) - len(holidays),
			Holidays: holidays,
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
	today := a.dayOf(data)
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

// calendarNumbersOfFirst are the number in the year and the running number of the first recorded
// sprint, read from its ID in the form of the numbering (1 and 1 if it has none).
func calendarNumbersOfFirst(data *storage.TeamData) (number, seq int) {
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

// calendarNamingList is every recorded sprint plus the generated ones up to and including the last
// sprint of the window.
func (a *API) calendarNamingList(data *storage.TeamData, window []model.Sprint) ([]model.Sprint, error) {
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

type calendarNamingPlan struct {
	list     []model.Sprint
	names    []string
	fromIdx  int
	changes  []bool
	windowAt int // index in list of the first sprint of the window
}

func (a *API) calendarPlanNaming(data *storage.TeamData, window []model.Sprint, pattern, from string, all bool) (*calendarNamingPlan, error) {
	list, err := a.calendarNamingList(data, window)
	if err != nil {
		return nil, err
	}
	number, seq := calendarNumbersOfFirst(data)
	names, err := calendar.NameAll(pattern, list, number, seq)
	if err != nil {
		return nil, err
	}
	today := a.dayOf(data)
	p := &calendarNamingPlan{list: list, names: names, changes: make([]bool, len(list))}
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
			if st := calendarState(data, s, today); st != CalRunning && st != CalFinished {
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

func calendarHasNumber(pattern string) bool {
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
	prev := NamingPreview{Rows: []NamePreview{}, NoNumber: !calendarHasNumber(pattern)}
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
	plan, err := a.calendarPlanNaming(data, window, pattern, from, all)
	if err != nil {
		return prev, err
	}
	today := a.dayOf(data)
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
	plan, err := a.calendarPlanNaming(data, window, pattern, from, all)
	if err != nil {
		return CalendarResult{}, err
	}
	if !all && plan.fromIdx < len(plan.list) && calendarState(data, plan.list[plan.fromIdx], a.dayOf(data)) == CalFinished {
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
	if old := data.SprintByID(sprintID); old != nil && calendarState(data, *old, a.dayOf(data)) == CalFinished {
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

const (
	calendarChangeLast   = "last"
	calendarChangeStart  = "start"
	calendarChangeRemove = "remove"
	calendarChangeRhythm = "rhythm"

	calendarChangeShift = "shift"
	calendarChangeKeep  = "keep"

	calendarNamingKeep     = "keep"
	calendarNamingRenumber = "renumber"
)

// calendarProblem is a change that cannot be made; the text goes to the person.
type calendarProblem string

func (p calendarProblem) Error() string { return string(p) }

type calendarChangePlan struct {
	plan    sprintcal.Plan
	via     string
	forced  bool
	mode    string
	renames []sprintcal.Rename
	choice  bool
	from    time.Time
	after   *storage.TeamData
}

// calendarChangeWindow is the calendar window of a change: it reaches at least to the last saved
// sprint (and, within reason, to the last earmarked one), so that no saved sprint lies beyond it
// with generated ones in between.
func (a *API) calendarChangeWindow(data *storage.TeamData, count int) ([]model.Sprint, error) {
	earmarked := map[string]bool{}
	for _, e := range data.Preplan.Earmarks {
		earmarked[e.Sprint] = true
	}
	for {
		w, err := a.calendarWindow(data, count)
		if err != nil || len(w) == 0 {
			return w, err
		}
		last := w[len(w)-1]
		covered := true
		for _, s := range data.Sprints {
			if s.End.After(last.End) {
				covered = false
			}
		}
		if covered && count < 120 {
			for _, s := range w {
				delete(earmarked, s.ID)
			}
			covered = len(earmarked) == 0
		}
		if covered || count >= 400 {
			return w, nil
		}
		count += max(8, count)
	}
}

func calendarCopyWithout(data *storage.TeamData, plan sprintcal.Plan) *storage.TeamData {
	after := sprintcal.WithSprints(data, plan.Save)
	dropped := map[string]bool{}
	for _, s := range plan.Dropped {
		dropped[s.ID] = true
	}
	for _, s := range plan.Save { // a sprint that reuses the ID of a dropped one stays
		delete(dropped, s.ID)
	}
	kept := after.Sprints[:0:0]
	for _, s := range after.Sprints {
		if !dropped[s.ID] {
			kept = append(kept, s)
		}
	}
	after.Sprints = kept
	return after
}

// calendarRenumber are the renames that make the saved sprints from the day on follow the
// count: the first saved sprint whose name differs from what the chain gives is renamed, and the
// saved ones after it count on (see sprintcal.PlanRenames).
func calendarRenumber(data *storage.TeamData, from time.Time, today time.Time) ([]sprintcal.Rename, error) {
	saved := data.Sprints
	for k := 1; k < len(saved); k++ {
		s := saved[k]
		if s.Start.Before(from) || !s.End.After(today) {
			continue
		}
		prev := saved[k-1]
		next, err := calendar.NewChain(&data.Team, saved[:k]).After(&prev)
		if err != nil || next.ID == s.ID || !next.Start.Equal(s.Start) {
			continue
		}
		return sprintcal.PlanRenames(data, s.ID, next.ID)
	}
	return nil, nil
}

func (a *API) calendarPlanChange(data *storage.TeamData, window []model.Sprint, ch CalendarChange) (*calendarChangePlan, error) {
	today := a.dayOf(data)
	idx := -1
	for i, s := range window {
		if s.ID == ch.ID {
			idx = i
		}
	}
	if idx < 0 {
		return nil, fmt.Errorf("%s", i18n.T("Sprint {id} does not exist.", "id", ch.ID))
	}
	locked := calendarProblem(i18n.T("A finished sprint is locked."))
	if calendarState(data, window[idx], today) == CalFinished {
		return nil, locked
	}
	out := &calendarChangePlan{mode: ch.Mode}
	if out.mode != calendarChangeKeep {
		out.mode = calendarChangeShift
	}
	var date time.Time
	if ch.Kind != calendarChangeRemove && ch.Kind != calendarChangeRhythm {
		d, err := time.Parse(isoDay, ch.Date)
		if err != nil {
			return nil, calendarProblem(i18n.T("Enter a valid last day."))
		}
		date = d
	}
	var err error
	switch ch.Kind {
	case calendarChangeRemove:
		state := calendarState(data, window[idx], today)
		if state == CalRunning {
			return nil, calendarProblem(i18n.T("The running sprint cannot be removed."))
		}
		if idx == 0 || calendarState(data, window[idx-1], today) == CalFinished {
			return nil, calendarProblem(i18n.T("The sprint before is finished and locked, so it cannot take over the days."))
		}
		out.mode, out.via = calendarChangeKeep, window[idx-1].ID
		out.plan, err = sprintcal.KeepLater(data, window, idx-1, calendarLastDayOf(window[idx]))
	case calendarChangeRhythm:
		out.mode = calendarChangeShift
		out.plan, err = sprintcal.Regular(data, window, idx)
	case calendarChangeStart:
		if idx > 0 && calendarState(data, window[idx-1], today) != CalFinished {
			out.via = window[idx-1].ID
			last := date.Add(-24 * time.Hour)
			if out.mode == calendarChangeKeep {
				out.plan, err = sprintcal.KeepLater(data, window, idx-1, last)
			} else {
				out.plan, err = sprintcal.ShiftLater(data, window, idx-1, last, nil)
			}
			break
		}
		if idx > 0 && date.Before(window[idx-1].End) {
			return nil, calendarProblem(i18n.T("The start is before the end of the finished sprint {id}.", "id", window[idx-1].ID))
		}
		out.forced, out.mode = true, calendarChangeShift
		out.plan, err = sprintcal.ShiftLater(data, window, idx, time.Time{}, &date)
	case calendarChangeLast:
		if date.Before(window[idx].Start) {
			return nil, calendarProblem(i18n.T("Sprint {id}: last day is before the start {start}", "id", window[idx].ID, "start", window[idx].Start.Format(isoDay)))
		}
		if out.mode == calendarChangeKeep {
			out.plan, err = sprintcal.KeepLater(data, window, idx, date)
		} else {
			out.plan, err = sprintcal.ShiftLater(data, window, idx, date, nil)
		}
	default:
		return nil, calendarProblem(i18n.T("Enter a valid last day."))
	}
	if err != nil {
		return nil, err
	}
	out.after = calendarCopyWithout(data, out.plan)
	from := window[idx].Start
	if out.via != "" {
		from = window[idx-1].Start
	}
	renames, err := calendarRenumber(out.after, from, today)
	if err != nil {
		return nil, err
	}
	out.from = from
	out.choice = len(renames) > 0
	if ch.Naming == calendarNamingRenumber && len(renames) > 0 {
		out.renames = renames
		if err := calendarRenumberRows(data, &out.plan, renames); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// calendarRenumberRows puts the IDs that the renumbering gives into the rows of the plan: sprints
// with a file are renamed, the ones without count on from their predecessor. The earmarks move by
// these rows too.
func calendarRenumberRows(data *storage.TeamData, plan *sprintcal.Plan, renames []sprintcal.Rename) error {
	renamed := map[string]string{}
	for _, r := range renames {
		renamed[r.Old] = r.New
	}
	saves := map[string]bool{}
	for _, s := range plan.Save {
		saves[s.ID] = true
	}
	var counted []model.Sprint
	if len(plan.Rows) > 0 {
		for _, s := range data.Sprints {
			if s.Start.Before(plan.Rows[0].OldStart) {
				if n, ok := renamed[s.ID]; ok {
					s.ID = n
				}
				counted = append(counted, s)
			}
		}
	}
	targetAt := -1
	for i := range plan.Rows {
		pl := &plan.Rows[i]
		if pl.Gone {
			continue
		}
		if targetAt < 0 && pl.Sprint.ID == plan.Target {
			targetAt = i
		}
		if data.SprintByID(pl.Old) != nil || saves[pl.Sprint.ID] {
			if n, ok := renamed[pl.Sprint.ID]; ok {
				pl.Sprint.ID = n
			}
		} else if len(counted) > 0 {
			named, err := calendar.NewChain(&data.Team, counted).After(&counted[len(counted)-1])
			if err != nil {
				return err
			}
			pl.Sprint.ID = named.ID
		}
		counted = append(counted, pl.Sprint)
	}
	if targetAt >= 0 {
		plan.Target = plan.Rows[targetAt].Sprint.ID
	}
	return nil
}

func (a *API) calendarChangeRows(data *storage.TeamData, p *calendarChangePlan, first string) []ChangeRow {
	rows := []ChangeRow{}
	started := false
	for _, pl := range p.plan.Rows {
		if pl.Old == first {
			started = true
		}
		if !started {
			continue
		}
		s := pl.Sprint
		id := s.ID
		saved := data.SprintByID(pl.Old) != nil
		for _, w := range p.plan.Save {
			saved = saved || w.ID == s.ID
		}
		row := ChangeRow{
			ID: id, Old: pl.Old, OldStart: pl.OldStart.Format(isoDay), OldLast: pl.OldEnd.Add(-24 * time.Hour).Format(isoDay), Start: s.Start.Format(isoDay), Last: calendarLastDayOf(s).Format(isoDay),
			Gone: pl.Gone, Saved: saved, Notes: []ChangeNote{},
		}
		if !pl.Gone {
			row.Workdays = len(calendar.TeamWorkdays(&data.Team, s.Start, s.End)) - len(calendarHolidaysIn(data, s))
		}
		days := func(a, b time.Time) int { return int(b.Sub(a).Hours() / 24) }
		switch {
		case pl.Gone:
			row.Notes = append(row.Notes, ChangeNote{Kind: "gone"})
		default:
			ds, de := days(pl.OldStart, s.Start), days(pl.OldEnd, s.End)
			switch {
			case ds != 0 && ds == de:
				row.Notes = append(row.Notes, ChangeNote{Kind: "moved", Days: ds})
			case ds != 0:
				kind := "starts-later"
				if ds < 0 {
					kind, ds = "starts-earlier", -ds
				}
				row.Notes = append(row.Notes, ChangeNote{Kind: kind, Days: ds})
			case de != 0:
				kind := "longer"
				if de < 0 {
					kind, de = "shorter", -de
				}
				row.Notes = append(row.Notes, ChangeNote{Kind: kind, Days: de})
			}
			if id != pl.Old {
				row.Notes = append(row.Notes, ChangeNote{Kind: "renamed", From: pl.Old})
			}
		}
		rows = append(rows, row)
	}
	return rows
}

// PreviewCalendarChange shows what the change would do; nothing is written.
func (a *API) PreviewCalendarChange(team string, ch CalendarChange, count int) (CalendarPreview, error) {
	prev := CalendarPreview{Rows: []ChangeRow{}, Lost: []string{}, Free: []string{}}
	data, err := a.loadTeam(team)
	if err != nil {
		return prev, err
	}
	window, err := a.calendarChangeWindow(data, count)
	if err != nil {
		return prev, err
	}
	p, err := a.calendarPlanChange(data, window, ch)
	if err != nil {
		var problem calendarProblem
		var dataErr *storage.DataError
		switch {
		case errors.As(err, &problem):
			prev.Problem = string(problem)
		case errors.As(err, &dataErr):
			prev.Problem = dataErr.Msg
		default:
			return prev, err
		}
		return prev, nil
	}
	first := ch.ID
	if p.via != "" {
		first = p.via
	}
	prev.Rows = a.calendarChangeRows(data, p, first)
	for _, s := range p.plan.Dropped {
		prev.Lost = append(prev.Lost, s.ID)
	}
	for _, r := range p.plan.Rows {
		if r.Gone && data.SprintByID(r.Old) == nil {
			prev.Free = append(prev.Free, r.Old)
		}
	}
	prev.Target, prev.Via, prev.Forced, prev.Mode, prev.NamingChoice = p.plan.Target, p.via, p.forced, p.mode, p.choice
	return prev, nil
}

// ApplyCalendarChange writes the change: sprint files, earmarks of sprints that fall away, and
// (if asked) the new numbering. One undo step covers all of it.
func (a *API) ApplyCalendarChange(team string, ch CalendarChange, count int) (CalendarResult, error) {
	data, err := a.loadTeam(team)
	if err != nil {
		return CalendarResult{}, err
	}
	window, err := a.calendarChangeWindow(data, count)
	if err != nil {
		return CalendarResult{}, err
	}
	p, err := a.calendarPlanChange(data, window, ch)
	if err != nil {
		var dataErr *storage.DataError
		if errors.As(err, &dataErr) {
			return CalendarResult{}, calendarProblem(dataErr.Msg)
		}
		return CalendarResult{}, err
	}
	today := a.dayOf(data)
	for _, s := range p.plan.Save {
		if _, err := storage.NewRepository(a.DataDir()).SprintPath(team, s.ID); err != nil {
			return CalendarResult{}, err
		}
	}
	for _, r := range p.renames {
		if problem := storage.FileNameProblem(r.New, false); problem != "" {
			return CalendarResult{}, fmt.Errorf("%s", i18n.T("ID not allowed as a file name ({problem}).", "problem", problem))
		}
	}
	for _, i := range validate.CheckTeam(p.after, today) {
		if i.Level == validate.Error && strings.HasPrefix(i.Where, "sprints/") {
			return CalendarResult{}, calendarProblem(i.Message)
		}
	}
	repo := storage.NewRepository(a.DataDir())
	token := a.rememberTree(team)
	fail := func(err error) (CalendarResult, error) {
		_ = a.Undo(team, token)
		return CalendarResult{}, err
	}
	for _, s := range p.plan.Dropped {
		if err := repo.DeleteSprint(team, s.ID); err != nil {
			return fail(err)
		}
	}
	for i := range p.plan.Save {
		if _, err := repo.SaveSprint(team, &p.plan.Save[i]); err != nil {
			return fail(err)
		}
	}
	// Earmarks of sprints that fall away (or whose generated name changed) follow the sprint that
	// takes over.
	moves := map[string]string{}
	for _, s := range p.plan.Dropped {
		if p.plan.Target != "" {
			moves[s.ID] = p.plan.Target
		}
	}
	for _, r := range p.plan.Rows {
		if !r.Gone && r.Old != r.Sprint.ID {
			moves[r.Old] = r.Sprint.ID
		}
	}
	if len(moves) > 0 {
		pp, changed := data.Preplan, false
		pp.Earmarks = append([]model.Earmark(nil), pp.Earmarks...)
		for i, e := range pp.Earmarks {
			if to, ok := moves[e.Sprint]; ok {
				pp.Earmarks[i].Sprint, changed = to, true
			}
		}
		if changed {
			if _, err := repo.SavePreplan(team, pp); err != nil {
				return fail(err)
			}
		}
	}
	if ch.Naming == calendarNamingRenumber {
		fresh, err := a.loadTeam(team)
		if err != nil {
			return fail(err)
		}
		renames, err := calendarRenumber(fresh, p.from, today)
		if err != nil {
			return fail(err)
		}
		if _, err := sprintcal.ApplyRenames(repo, fresh, renames); err != nil {
			return fail(err)
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
	moved := 0
	for _, r := range p.plan.Rows {
		if r.Gone || !r.Sprint.Start.Equal(r.OldStart) || !r.Sprint.End.Equal(r.OldEnd) {
			moved++
		}
	}
	return CalendarResult{View: a.calendarView(fresh, shown), Moved: moved, Undo: token}, nil
}
