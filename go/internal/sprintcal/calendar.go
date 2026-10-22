// Package sprintcal changes the sprint calendar: the table of upcoming sprints with their last
// days, creating missing sprint files, and renaming sprint IDs after the fact (port of the
// calendar part of web/logic.py and of renaming.py).
package sprintcal

import (
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

const day = 24 * time.Hour

// WithSprints is a copy of the data in which the given sprints are replaced or added.
func WithSprints(data *storage.TeamData, sprints []model.Sprint) *storage.TeamData {
	result := *data
	byID := map[string]model.Sprint{}
	for _, s := range data.Sprints {
		byID[s.ID] = s.Clone()
	}
	for _, s := range sprints {
		byID[s.ID] = s.Clone()
	}
	result.Sprints = result.Sprints[:0:0]
	for _, s := range byID {
		result.Sprints = append(result.Sprints, s)
	}
	sort.SliceStable(result.Sprints, func(i, j int) bool {
		if !result.Sprints[i].Start.Equal(result.Sprints[j].Start) {
			return result.Sprints[i].Start.Before(result.Sprints[j].Start)
		}
		return result.Sprints[i].ID < result.Sprints[j].ID
	})
	return &result
}

// AbsenceSprints are the running sprint and the following ones (recorded or generated from the
// calendar), optionally preceded by the last past finished sprints.
func AbsenceSprints(data *storage.TeamData, fc *forecast.Forecast, count, past int) ([]model.Sprint, error) {
	start := fc.Current()
	if start == nil {
		var err error
		if start, err = fc.DefaultEntry(forecast.PurposeNext); err != nil {
			return nil, err
		}
	}
	if start == nil {
		return nil, nil
	}
	var result []model.Sprint
	if past > 0 {
		history := fc.History()
		if len(history) > past {
			history = history[len(history)-past:]
		}
		for _, e := range history {
			if s := data.SprintByID(e.Sprint.ID); s != nil {
				result = append(result, s.Clone())
			}
		}
	}
	chainStart := len(result)
	sprint := start.Sprint.Clone()
	if stored := data.SprintByID(start.Sprint.ID); stored != nil {
		sprint = stored.Clone()
	}
	chain := calendar.NewChain(&data.Team, data.Sprints)
	for len(result)-chainStart < count {
		result = append(result, sprint.Clone())
		following, err := chain.After(&sprint)
		if err != nil {
			return nil, err
		}
		sprint = following
		if stored := data.SprintByID(following.ID); stored != nil {
			sprint = stored.Clone()
		}
	}
	return result, nil
}

// Row is one line of the sprint calendar.
type Row struct {
	Sprint string
	Start  time.Time
	// Last is the last day (the end of the sprint minus one day); the next sprint starts the day
	// after. The zero time means "missing".
	Last        time.Time
	WorkingDays int
	// Status is "finished", "running", "planned" or "no file yet" (English source texts).
	Status string
}

// Table makes one row per sprint.
func Table(data *storage.TeamData, sprints []model.Sprint, today time.Time) []Row {
	rows := make([]Row, 0, len(sprints))
	for _, s := range sprints {
		state := "planned"
		switch {
		case !s.End.After(today):
			state = "finished"
		case !s.Start.After(today):
			state = "running"
		case data.SprintByID(s.ID) == nil:
			state = "no file yet"
		}
		rows = append(rows, Row{
			Sprint: s.ID, Start: s.Start, Last: s.End.Add(-day),
			WorkingDays: len(calendar.TeamWorkdays(&data.Team, s.Start, s.End)), Status: state,
		})
	}
	return rows
}

// Apply applies changed last days: each following sprint starts the day after and keeps its
// length unless its own last day was changed. IDs of sprints not yet created are reassigned.
// Saved sprints after the shown period shift by the same difference. It returns the sprints and
// the messages about wrong input.
func Apply(data *storage.TeamData, sprints []model.Sprint, rows []Row) ([]model.Sprint, []string, error) {
	var errs []string
	var result []model.Sprint
	persisted := map[string]bool{}
	for _, s := range data.Sprints {
		persisted[s.ID] = true
	}
	for i, original := range sprints {
		sprint := original.Clone()
		if len(result) > 0 {
			previous := result[len(result)-1]
			sprint.Start = previous.End
			if data.SprintByID(original.ID) == nil {
				// The sprints before the window and the ones already placed give the numbers.
				var history []model.Sprint
				for _, s := range data.Sprints {
					if s.Start.Before(sprints[0].Start) {
						history = append(history, s)
					}
				}
				history = append(history, result...)
				created, err := calendar.NewChain(&data.Team, history).After(&previous)
				if err != nil {
					return nil, nil, err
				}
				sprint.ID = created.ID
			}
		}
		last := rows[i].Last
		if last.IsZero() {
			errs = append(errs, i18n.P("Row {row}: last day missing", "row", i+1))
			last = original.End.Add(-day)
		}
		var end time.Time
		if last.Equal(original.End.Add(-day)) {
			// unchanged: keep the length, i.e. shift along with the predecessor
			end = sprint.Start.Add(original.End.Sub(original.Start))
		} else {
			end = last.Add(day)
		}
		if !end.After(sprint.Start) {
			errs = append(errs, i18n.P("Sprint {id}: last day is before the start {start}",
				"id", sprint.ID, "start", sprint.Start.Format("2006-01-02")))
			sprint.End = original.End
		} else {
			sprint.End = end
		}
		if sprint.ID != original.ID {
			taken := persisted[sprint.ID]
			for _, s := range result {
				taken = taken || s.ID == sprint.ID
			}
			if taken {
				errs = append(errs, i18n.P("Sprint ID {id} would be duplicated – please adjust the following "+
					"sprints first.", "id", sprint.ID))
			}
		}
		result = append(result, sprint)
	}
	if len(sprints) > 0 && len(result) > 0 {
		shown := sprints[len(sprints)-1]
		if delta := result[len(result)-1].End.Sub(shown.End); delta != 0 {
			for _, later := range data.Sprints {
				if !later.Start.Before(shown.End) {
					moved := later.Clone()
					moved.Start = moved.Start.Add(delta)
					moved.End = moved.End.Add(delta)
					result = append(result, moved)
				}
			}
		}
	}
	return result, errs, nil
}

// ToSave are the sprints to write: changed dates, missing files on request, and the saved
// sprints shifted after the shown period.
func ToSave(data *storage.TeamData, originals, after []model.Sprint, createMissing bool) []model.Sprint {
	window, shifted := after[:len(originals)], after[len(originals):]
	var changed []model.Sprint
	for i, old := range originals {
		n := window[i]
		if !old.Start.Equal(n.Start) || !old.End.Equal(n.End) || (createMissing && data.SprintByID(n.ID) == nil) {
			changed = append(changed, n)
		}
	}
	return append(changed, shifted...)
}
