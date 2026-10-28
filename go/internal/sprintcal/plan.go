package sprintcal

import (
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// Placed is one sprint of the calendar after a change: where it now stands, what it was (Old is
// the ID before, "" if it had none) and whether it falls away.
type Placed struct {
	Sprint   model.Sprint
	Old      string
	OldStart time.Time
	OldEnd   time.Time
	Gone     bool
}

// Plan is the calendar after a change that has not been written yet.
type Plan struct {
	// Rows are the shown sprints and the saved ones after them, in the order of the calendar.
	Rows []Placed
	// Save are the sprint files to write, Dropped the saved sprints whose files go.
	Save    []model.Sprint
	Dropped []model.Sprint
	// Target is the ID of the sprint that takes over the days of the dropped sprints.
	Target string
}

// beyond are the saved sprints that begin after the shown ones.
func beyond(data *storage.TeamData, window []model.Sprint) []model.Sprint {
	var out []model.Sprint
	if len(window) == 0 {
		return out
	}
	for _, s := range data.Sprints {
		if !s.Start.Before(window[len(window)-1].End) {
			out = append(out, s.Clone())
		}
	}
	return out
}

func lastBeforeStart(s model.Sprint) error {
	return &storage.DataError{Msg: i18n.P("Sprint {id}: last day is before the start {start}",
		"id", s.ID, "start", s.Start.Format("2006-01-02"))}
}

// ShiftLater sets the last day of window[idx] (or, with firstStart, the start of window[idx]) and
// moves every later sprint by the difference; each keeps its length.
func ShiftLater(data *storage.TeamData, window []model.Sprint, idx int, last time.Time, firstStart *time.Time) (Plan, error) {
	var out Plan
	if idx < 0 || idx >= len(window) {
		return out, nil
	}
	shown := window[idx:]
	rows := Table(data, shown, time.Time{})
	if firstStart == nil {
		rows[0].Last = last
	}
	after, problems, err := ApplyFrom(data, shown, rows, firstStart)
	if err != nil {
		return out, err
	}
	if len(problems) > 0 {
		return out, &storage.DataError{Msg: problems[0]}
	}
	for i, old := range append(append([]model.Sprint(nil), shown...), beyond(data, window)...) {
		placed := old.Clone()
		if i < len(after) {
			placed = after[i]
		}
		out.Rows = append(out.Rows, Placed{Sprint: placed, Old: old.ID, OldStart: old.Start, OldEnd: old.End})
	}
	out.Save = ToSave(data, shown, after, false)
	return out, nil
}

// KeepLater sets the last day of window[idx] and leaves the later sprints where they are: a
// sprint that lies completely within the longer sprint falls away, the one that is cut starts on
// the day after, and a shorter sprint is followed by a longer one that starts earlier. window is
// the part of the calendar the page shows (oldest first, generated sprints included); saved
// sprints after it are looked at too.
func KeepLater(data *storage.TeamData, window []model.Sprint, idx int, last time.Time) (Plan, error) {
	var out Plan
	if idx < 0 || idx >= len(window) {
		return out, nil
	}
	end := last.Add(day)
	changed := window[idx].Clone()
	if !end.After(changed.Start) {
		return out, lastBeforeStart(changed)
	}
	changed.End = end
	out.Rows = append(out.Rows, Placed{Sprint: changed, Old: window[idx].ID, OldStart: window[idx].Start, OldEnd: window[idx].End})
	if !end.Equal(window[idx].End) {
		out.Save = append(out.Save, changed)
	}
	rest := append(append([]model.Sprint(nil), window[idx+1:]...), beyond(data, window)...)
	// The sprints after the changed one count on from it: those without a file are named again by
	// the chain, those with a file keep their name.
	counted := historyBefore(data, window[:idx], changed)
	cut := false
	for _, s := range rest {
		p := Placed{Sprint: s.Clone(), Old: s.ID, OldStart: s.Start, OldEnd: s.End}
		saved := data.SprintByID(s.ID) != nil
		if !s.End.After(end) {
			p.Gone = true
			if saved {
				out.Dropped = append(out.Dropped, s.Clone())
			}
			out.Rows = append(out.Rows, p)
			continue
		}
		starts := !cut && !s.Start.Equal(end)
		if starts {
			p.Sprint.Start = end
		}
		if !saved {
			named, err := calendar.NewChain(&data.Team, counted).After(&counted[len(counted)-1])
			if err != nil {
				return out, err
			}
			p.Sprint.ID = named.ID
		}
		if !cut {
			cut = true
			out.Target = p.Sprint.ID
		}
		if starts {
			out.Save = append(out.Save, p.Sprint)
		}
		counted = append(counted, p.Sprint)
		out.Rows = append(out.Rows, p)
	}
	return out, nil
}

// historyBefore are the saved sprints before the shown ones, the shown ones before the changed
// sprint, and the changed sprint: the sprints the chain counts on from.
func historyBefore(data *storage.TeamData, before []model.Sprint, last model.Sprint) []model.Sprint {
	var history []model.Sprint
	for _, s := range data.Sprints {
		if len(before) == 0 || s.Start.Before(before[0].Start) {
			history = append(history, s)
		}
	}
	history = append(history, before...)
	return append(history, last)
}

// Regular puts the sprints from window[idx] on back into the team's rhythm: the sprint keeps its
// start, and it and every later sprint (saved ones after the shown part included) get the
// regular length and follow each other without a gap. Sprints without a file are named by the
// chain again.
func Regular(data *storage.TeamData, window []model.Sprint, idx int) (Plan, error) {
	var out Plan
	if idx < 0 || idx >= len(window) {
		return out, nil
	}
	shown := append(append([]model.Sprint(nil), window[idx:]...), beyond(data, window)...)
	length := time.Duration(data.Team.Sprint.LengthDays) * day
	counted := historyBefore(data, window[:idx], shown[0])
	counted = counted[:len(counted)-1]
	start := shown[0].Start
	for _, old := range shown {
		s := old.Clone()
		s.Start, s.End = start, start.Add(length)
		start = s.End
		if data.SprintByID(old.ID) == nil && len(counted) > 0 {
			named, err := calendar.NewChain(&data.Team, counted).After(&counted[len(counted)-1])
			if err != nil {
				return out, err
			}
			s.ID = named.ID
		}
		counted = append(counted, s)
		if !s.Start.Equal(old.Start) || !s.End.Equal(old.End) {
			out.Save = append(out.Save, s)
		}
		out.Rows = append(out.Rows, Placed{Sprint: s, Old: old.ID, OldStart: old.Start, OldEnd: old.End})
	}
	return out, nil
}
