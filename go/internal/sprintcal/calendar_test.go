package sprintcal

import (
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
)

const dayLength = 24 * time.Hour

// window is n saved sprints from index from, the part of the calendar the page shows; the saved
// sprints after it are what a change shifts.
func window(data []model.Sprint, from, n int) []model.Sprint { return data[from : from+n] }

func TestTableMarksFinishedRunningAndPlanned(t *testing.T) {
	_, data := demoCopy(t)
	mid := data.Sprints[5]
	today := mid.Start.Add(dayLength) // the sixth sprint runs
	rows := Table(data, data.Sprints[3:8], today)
	want := []string{"finished", "finished", "running", "planned", "planned"}
	for i, r := range rows {
		if r.Status != want[i] {
			t.Errorf("%s: status %q, want %q", r.Sprint, r.Status, want[i])
		}
		if r.WorkingDays <= 0 || !r.Last.Equal(data.Sprints[3+i].End.Add(-dayLength)) {
			t.Errorf("row %+v", r)
		}
	}
}

func TestApplyUnchangedRowsChangeNothing(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 4)
	rows := Table(data, shown, shown[0].Start)
	after, problems, err := Apply(data, shown, rows)
	if err != nil || len(problems) != 0 {
		t.Fatalf("problems %v, err %v", problems, err)
	}
	if got := ToSave(data, shown, after, false); len(got) != 0 {
		t.Fatalf("nothing was edited, but %d sprints would be written", len(got))
	}
}

func TestApplyALongerSprintShiftsEverythingAfterIt(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	rows := Table(data, shown, shown[0].Start)
	rows[0].Last = rows[0].Last.Add(3 * dayLength) // the first of the window ends three days later
	after, problems, err := Apply(data, shown, rows)
	if err != nil || len(problems) != 0 {
		t.Fatalf("problems %v, err %v", problems, err)
	}
	if !after[0].End.Equal(shown[0].End.Add(3 * dayLength)) {
		t.Errorf("first end = %v", after[0].End)
	}
	// Each following sprint starts where its predecessor ends and keeps its length.
	for i := 1; i < len(shown); i++ {
		if !after[i].Start.Equal(after[i-1].End) || after[i].End.Sub(after[i].Start) != shown[i].End.Sub(shown[i].Start) {
			t.Errorf("sprint %d: %v - %v", i, after[i].Start, after[i].End)
		}
	}
	// The saved sprints after the window move by the same three days.
	if len(after) != len(data.Sprints)-2 {
		t.Fatalf("%d sprints after the change", len(after))
	}
	for _, moved := range after[len(shown):] {
		orig := data.SprintByID(moved.ID)
		if orig == nil || !moved.Start.Equal(orig.Start.Add(3*dayLength)) {
			t.Errorf("%s did not shift", moved.ID)
		}
	}
	if got := ToSave(data, shown, after, false); len(got) != len(data.Sprints)-2 {
		t.Errorf("to save: %d", len(got))
	}
}

func TestApplyReportsAMissingAndAnImpossibleLastDay(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 2)
	rows := Table(data, shown, shown[0].Start)
	rows[0].Last = time.Time{}
	rows[1].Last = shown[1].Start.Add(-5 * dayLength) // before its own start
	_, problems, err := Apply(data, shown, rows)
	if err != nil {
		t.Fatal(err)
	}
	if len(problems) != 2 || !strings.Contains(problems[0], "Row 1: last day missing") ||
		!strings.Contains(problems[1], "last day is before the start") {
		t.Fatalf("problems = %v", problems)
	}
}

func TestTableWorkingDaysWithoutHolidays(t *testing.T) {
	_, data := demoCopy(t)
	data.Team.Capacity.Country = "DE"
	data.Team.Capacity.Region = nil
	day := func(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }
	// 23.12.2026 to 05.01.2027: ten weekdays, of which 25.12. and 01.01. are holidays
	christmas := model.Sprint{ID: "x", Start: day(2026, 12, 23), End: day(2027, 1, 6)}
	// 28.09.2026 to 11.10.2026: ten weekdays, the holiday 03.10. is a Saturday
	weekend := model.Sprint{ID: "y", Start: day(2026, 9, 28), End: day(2026, 10, 12)}
	rows := Table(data, []model.Sprint{christmas, weekend}, day(2026, 1, 1))
	if rows[0].WorkingDays != 8 || rows[1].WorkingDays != 10 {
		t.Errorf("working days = %d and %d, want 8 and 10", rows[0].WorkingDays, rows[1].WorkingDays)
	}
}
