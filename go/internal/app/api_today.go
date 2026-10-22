package app

import (
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
)

// Steps of a sprint on the start page, in the order of the sprint workspace.
const (
	StepAbsences = "absences"
	StepPreplan  = "preplan"
	StepPlan     = "plan"
	StepReview   = "review"
)

// Step states: done, open (still to do) and none (does not apply yet or at all).
const (
	StepDone = "done"
	StepOpen = "open"
	StepNone = "none"
)

// Sources of the work of a team (decision 15 of flows.md).
const (
	SourceTracker  = "tracker"  // a tracker such as Jira
	SourcePackages = "packages" // work packages kept in Foresprint
	SourceNone     = "none"     // no tickets: amounts only
)

// TodayStep is one step of a sprint with its state.
type TodayStep struct {
	Key   string `json:"key"`   // one of the Step constants
	State string `json:"state"` // done, open or none
	// Detail says what is missing or what is done, e.g. "announced only (3 people)"; "" if
	// there is nothing to add.
	Detail string `json:"detail"`
}

// TodaySprint is a sprint on the start page.
type TodaySprint struct {
	ID    string `json:"id"`
	Start string `json:"start"` // YYYY-MM-DD
	End   string `json:"end"`   // YYYY-MM-DD
	// State is "running", "next" (the sprint after the running one), "later" or "past".
	State string `json:"state"`
	// DaysLeft is the number of days until the end of a running sprint, DaysToStart the number
	// of days until the start of a coming one; the other is 0.
	DaysLeft    int         `json:"daysLeft"`
	DaysToStart int         `json:"daysToStart"`
	Steps       []TodayStep `json:"steps"`
}

// TodayFinding is one finding of the data check, with the page that can fix it.
type TodayFinding struct {
	Level   string `json:"level"` // "error" or "notice"
	Where   string `json:"where"` // file, optionally with the entry
	Message string `json:"message"`
	Route   string `json:"route"` // page of the window, e.g. "/team/people"
}

// TodayData is what the start page shows for a team.
type TodayData struct {
	Date    string        `json:"date"` // YYYY-MM-DD
	Team    string        `json:"team"`
	Name    string        `json:"name"`
	Source  string        `json:"source"` // one of the Source constants
	Sprints []TodaySprint `json:"sprints"`
	// Findings are the errors first, then the notices, at most MaxFindings; Errors and Notices
	// count all of them.
	Findings []TodayFinding `json:"findings"`
	Errors   int            `json:"errors"`
	Notices  int            `json:"notices"`
}

// MaxFindings is the number of findings the start page lists.
const MaxFindings = 8

// Today returns the next steps per sprint and the findings of the data check for a team.
func (a *API) Today(team string) (TodayData, error) { return a.todayAt(team, time.Now()) }

func (a *API) todayAt(team string, now time.Time) (TodayData, error) {
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return TodayData{}, err
	}
	day := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	out := TodayData{
		Date:    day.Format("2006-01-02"),
		Team:    team,
		Name:    data.Team.Name,
		Source:  sourceOf(data.Team),
		Sprints: todaySprints(data, day),
	}
	issues := validate.CheckTeam(data, day)
	sort.SliceStable(issues, func(i, j int) bool { return issues[i].Level == validate.Error && issues[j].Level != validate.Error })
	for _, is := range issues {
		level := "notice"
		if is.Level == validate.Error {
			level = "error"
			out.Errors++
		} else {
			out.Notices++
		}
		if len(out.Findings) < MaxFindings {
			out.Findings = append(out.Findings, TodayFinding{Level: level, Where: is.Where, Message: is.Message, Route: routeOf(is.Where)})
		}
	}
	return out, nil
}

func sourceOf(t model.Team) string {
	switch {
	case !t.Features.Tickets:
		return SourceNone
	case t.Tracker.Kind == model.PackagesKind:
		return SourcePackages
	default:
		return SourceTracker
	}
}

// todaySprints picks the sprints worth showing: the last past sprint without review, the
// running one and the two after it.
func todaySprints(data *storage.TeamData, day time.Time) []TodaySprint {
	list := append([]model.Sprint(nil), data.Sprints...)
	sort.SliceStable(list, func(i, j int) bool { return list[i].Start.Before(list[j].Start) })
	running := -1
	for i, s := range list {
		if !s.Start.After(day) && !s.End.Before(day) {
			running = i
		}
	}
	var out []TodaySprint
	add := func(s model.Sprint, state string) {
		ts := TodaySprint{
			ID: s.ID, Start: s.Start.Format("2006-01-02"), End: s.End.Format("2006-01-02"), State: state,
			Steps: stepsOf(s, state),
		}
		if state == "running" {
			ts.DaysLeft = int(s.End.Sub(day).Hours() / 24)
		} else if state != "past" {
			ts.DaysToStart = int(s.Start.Sub(day).Hours() / 24)
		}
		out = append(out, ts)
	}
	// A finished sprint without velocity still needs its review.
	for i := len(list) - 1; i >= 0; i-- {
		s := list[i]
		if s.End.Before(day) {
			if s.Velocity == nil {
				add(s, "past")
			}
			break
		}
	}
	next := running + 1 // the sprint that starts next
	if running < 0 {
		next = len(list)
		for i, s := range list {
			if s.Start.After(day) {
				next = i
				break
			}
		}
	}
	from := next
	if running >= 0 {
		from = running
	}
	for i := from; i < len(list) && i < from+3; i++ {
		state := "later"
		switch i {
		case running:
			state = "running"
		case next:
			state = "next"
		}
		add(list[i], state)
	}
	return out
}

func stepsOf(s model.Sprint, state string) []TodayStep {
	step := func(key string, done bool, detail string) TodayStep {
		if done {
			return TodayStep{Key: key, State: StepDone, Detail: detail}
		}
		return TodayStep{Key: key, State: StepOpen, Detail: detail}
	}
	if state == "past" || state == "running" {
		return []TodayStep{step(StepReview, s.Velocity != nil, "")}
	}
	var abs string
	switch s.AbsenceStatus() {
	case model.AbsencesExpected:
		abs = i18n.T("announced only ({count} people)", "count", len(s.ExpectedAbsences))
	case model.AbsencesUnknown:
		abs = i18n.T("not entered yet")
	}
	pre, products := 0, 0
	for _, v := range s.Products {
		products++
		if v.Preplanned != nil {
			pre++
		}
	}
	var preDetail string
	if products > 0 && pre < products {
		preDetail = i18n.T("{done} of {total} products", "done", pre, "total", products)
	}
	planned := s.Planning != nil || s.CommittedTickets != nil
	return []TodayStep{
		step(StepAbsences, s.AbsencesConfirmed(), abs),
		step(StepPreplan, products > 0 && pre == products, preDetail),
		step(StepPlan, planned, ""),
	}
}

// routeOf maps the file of a finding to the page that edits it.
func routeOf(where string) string {
	file := strings.TrimSpace(strings.SplitN(where, ":", 2)[0])
	file = strings.ReplaceAll(file, "\\", "/")
	switch {
	case strings.HasPrefix(file, "sprints/") || strings.Contains(file, "/sprints/"):
		return "/sprints"
	case strings.HasSuffix(file, "people.yaml") || strings.HasSuffix(file, "abwesenheiten.yaml"):
		return "/team/people"
	case strings.HasSuffix(file, "products.yaml"):
		return "/team/products"
	case strings.HasSuffix(file, "projects.yaml"):
		return "/projects"
	case strings.HasSuffix(file, "tickets.yaml"), strings.HasSuffix(file, "arbeitspakete.yaml"), strings.HasSuffix(file, "preplan.yaml"):
		return "/backlog"
	case strings.HasSuffix(file, "team.yaml"):
		return "/settings/team"
	}
	return "/data"
}
