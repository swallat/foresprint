package forecast_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func TestResolveCapacityUsesAbsencePeriods(t *testing.T) {
	d := func(day int) time.Time { return time.Date(2026, 10, day, 0, 0, 0, 0, time.UTC) }
	data := &storage.TeamData{Team: model.NewTeam("t", "t")}
	data.People = []model.Person{{ID: "a", Name: "A", Memberships: []model.Membership{{Start: d(1).AddDate(-1, 0, 0), FTE: 1}}}}
	sprint := model.Sprint{ID: "s", Start: d(5), End: d(19)}

	calendar, source := forecast.ResolveCapacity(data, sprint, nil)
	if source == nil || *source != engine.SourceCalendar {
		t.Fatalf("source without periods = %v", source)
	}
	data.AbsencePeriods.Set("a", []model.AbsencePeriod{{From: d(5), To: d(9), Confirmed: true}})
	got, source := forecast.ResolveCapacity(data, sprint, nil)
	if *got != *calendar-5 {
		t.Errorf("capacity %v, want %v", *got, *calendar-5)
	}
	if *source != engine.SourcePeople {
		t.Errorf("confirmed period: source %v, want people", *source)
	}
	if sprint.Absences != nil {
		t.Error("the sprint was changed")
	}
	data.AbsencePeriods = model.Absences{}
	data.AbsencePeriods.Set("a", []model.AbsencePeriod{{From: d(5), To: d(9)}})
	if _, source := forecast.ResolveCapacity(data, sprint, nil); *source != engine.SourceExpected {
		t.Errorf("announced period: source %v, want expected", *source)
	}
}
