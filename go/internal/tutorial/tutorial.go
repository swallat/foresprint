// Package tutorial writes the demo team of the window: "Team Atlas", an invented team that has
// every feature of 1.0 switched on (products with product owners, projects with milestones and
// contingents, work packages, pre-planning, absence periods, people of all kinds). The window
// opens it in a throwaway folder in demo mode, so the guided flows and the first-start wizard
// work on real data without touching the data of the person.
//
// The dates move with the clock: the current sprint is always the one that started last Monday,
// six finished sprints lie before it and the next one follows, still unprepared. examples/teams/demo is separate and stays as it is (the
// golden tests read it).
package tutorial

import (
	"bytes"
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"text/template"
	"time"
)

//go:embed files/*.tmpl
var files embed.FS

// Key is the folder name of the team in the data folder.
const Key = "atlas"

const (
	sprintDays = 14
	past       = 6 // finished sprints before the current one
)

// The teams and the sources of work the window offers (the choice on the first-start screen).
const (
	TeamAtlas      = "atlas"    // every feature: products with product owners, projects, production
	TeamSimple     = "simple"   // products only: no product owners, no projects, no production share
	SourcePackages = "packages" // work packages kept in Foresprint
	SourceTracker  = "tracker"  // tickets of a tracker such as Jira (the cached import)
	SourceNone     = "none"     // no tickets: amounts only
)

// Options choose the variant of the demo team. The zero value is the full Atlas with work
// packages.
type Options struct {
	Team   string // TeamAtlas (default) or TeamSimple
	Source string // SourcePackages (default), SourceTracker or SourceNone
}

// view is what the templates see.
type view struct {
	Full    bool   // all features (Atlas)
	Tickets bool   // the team has tickets
	Source  string // one of the Source constants
}

// Write creates the full Atlas with work packages below root; see WriteWith.
func Write(root string, today time.Time, lang string) error {
	return WriteWith(root, today, lang, Options{})
}

// WriteWith creates the team Key below root, with the dates relative to today. lang ("de", "en")
// chooses the language of titles and names.
func WriteWith(root string, today time.Time, lang string, opt Options) error {
	if opt.Team == "" {
		opt.Team = TeamAtlas
	}
	if opt.Source == "" {
		opt.Source = SourcePackages
	}
	if (opt.Team != TeamAtlas && opt.Team != TeamSimple) || (opt.Source != SourcePackages && opt.Source != SourceTracker && opt.Source != SourceNone) {
		return fmt.Errorf("unknown demo variant %q / %q", opt.Team, opt.Source)
	}
	v := view{Full: opt.Team == TeamAtlas, Tickets: opt.Source != SourceNone, Source: opt.Source}
	dir := filepath.Join(root, Key)
	if err := os.MkdirAll(filepath.Join(dir, "sprints"), 0o755); err != nil {
		return err
	}
	current := currentStart(today)
	fn := template.FuncMap{
		"day":      func(n int) string { return current.AddDate(0, 0, n).Format("2006-01-02") },
		"sprintID": func(n int) string { return fmt.Sprint(n + 1) },
		"tr":       func(s string) string { return quote(translate(lang, s)) },
		"perMonth": func(each float64, months ...int) string {
			parts := make([]string, len(months))
			for i, m := range months {
				parts[i] = fmt.Sprintf("%s: %g", monthAt(current, m).Format("2006-01"), each)
			}
			return "{" + strings.Join(parts, ", ") + "}"
		},
	}
	entries, err := files.ReadDir("files")
	if err != nil {
		return err
	}
	for _, e := range entries {
		raw, err := files.ReadFile("files/" + e.Name())
		if err != nil {
			return err
		}
		t, err := template.New(e.Name()).Funcs(fn).Parse(string(raw))
		if err != nil {
			return err
		}
		name := strings.TrimSuffix(e.Name(), ".tmpl")
		switch {
		case name == "projects.yaml" && !v.Full:
			continue
		case (name == "arbeitspakete.yaml" || name == "preplan.yaml") && !v.Tickets:
			continue
		}
		var buf bytes.Buffer
		if err := t.Execute(&buf, v); err != nil {
			return err
		}
		out := buf.Bytes()
		if !v.Full && name == "arbeitspakete.yaml" {
			out = projectLine.ReplaceAll(out, nil) // no projects, so no project of a ticket
		}
		if v.Source == SourceTracker {
			out = bytes.ReplaceAll(out, []byte("AP-"), []byte("ATL-"))
			if name == "arbeitspakete.yaml" {
				name = "tickets.yaml" // the cached import of the tracker
			}
		}
		if err := os.WriteFile(filepath.Join(dir, name), out, 0o644); err != nil {
			return err
		}
	}
	for i := 0; i <= past+1; i++ {
		start := current.AddDate(0, 0, (i-past)*sprintDays)
		id := fmt.Sprint(i + 1)
		if err := os.WriteFile(filepath.Join(dir, "sprints", id+".yaml"), []byte(sprintYAML(i, id, start)), 0o644); err != nil {
			return err
		}
	}
	return nil
}

var projectLine = regexp.MustCompile(`(?m)^  project: .*\n`)

// currentStart is the start of the current sprint: the Monday of last week, so that today lies
// in the second week of the sprint.
func currentStart(today time.Time) time.Time {
	d := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	back := (int(d.Weekday())+6)%7 + 7
	return d.AddDate(0, 0, -back)
}

// monthAt is the first day of the month m months from t (AddDate would spill 31 Sep into October).
func monthAt(t time.Time, m int) time.Time {
	return time.Date(t.Year(), t.Month()+time.Month(m), 1, 0, 0, 0, 0, time.UTC)
}

func quote(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

// history are the figures of the six finished sprints: capacity, velocity, planned and done per
// product (portal, mobile, billing, platform) and the absence days.
var history = []struct {
	capacity, velocity, carry float64
	done                      [4]float64
	absences                  string
}{
	{36, 28, 2, [4]float64{10, 6, 7, 5}, "  anna: 2\n  cem: 1\n"},
	{38, 31, 3, [4]float64{11, 7, 7, 6}, "  ben: 3\n"},
	{34, 27, 2, [4]float64{9, 6, 6, 6}, "  dora: 4\n  cem: 1\n"},
	{37, 30, 3, [4]float64{10, 7, 7, 6}, "  anna: 3\n"},
	{35, 29, 2, [4]float64{10, 6, 7, 6}, "  ben: 2\n  dora: 1\n"},
	{36, 30, 3, [4]float64{11, 6, 7, 6}, "  cem: 2\n"},
}

var productIDs = [4]string{"portal", "mobile", "billing", "platform"}

func sprintYAML(i int, id string, start time.Time) string {
	var b strings.Builder
	fmt.Fprintf(&b, "id: '%s'\nstart: %s\nend: %s\n", id, start.Format("2006-01-02"), start.AddDate(0, 0, sprintDays).Format("2006-01-02"))
	if i > len(history) {
		// The next sprint: nothing known yet, so Today asks for its preparation.
		b.WriteString("absence_state: expected\nabsences: {}\nexpected_absences:\n  anna: 5\n  dora: 3\n")
		return b.String()
	}
	if i == len(history) {
		// The current sprint: started, absences announced and confirmed per person, nothing frozen.
		b.WriteString("started_on: " + start.Format("2006-01-02") + "\n")
		b.WriteString("absence_state: open\nabsences:\n  cem: 3\nexpected_absences:\n  ben: 2\n")
		b.WriteString("products:\n  portal: {preplanned: 10}\n  mobile: {preplanned: 6}\n  billing: {preplanned: 7}\n  platform: {preplanned: 6}\n")
		b.WriteString("preplanned: 29\n")
		return b.String()
	}
	h := history[i]
	var total float64
	for _, d := range h.done {
		total += d
	}
	fmt.Fprintf(&b, "absences:\n%scapacity: %g\nvelocity: %g\nscope_creep: 0\n", h.absences, h.capacity, h.velocity)
	fmt.Fprintf(&b, "planning:\n  carryover: %g\n  backlog: %g\n  corrections:\n  - 0\n", h.carry, total-h.carry+1)
	b.WriteString("products:\n")
	for n, p := range productIDs {
		fmt.Fprintf(&b, "  %s: {preplanned: %g, planned: %g, done: %g}\n", p, h.done[n], h.done[n], h.done[n])
	}
	return b.String()
}
