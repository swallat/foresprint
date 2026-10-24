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
	if len(after) != len(shown)+len(data.Sprints)-5 {
		t.Fatalf("%d sprints after the change", len(after))
	}
	for _, moved := range after[len(shown):] {
		orig := data.SprintByID(moved.ID)
		if orig == nil || !moved.Start.Equal(orig.Start.Add(3*dayLength)) {
			t.Errorf("%s did not shift", moved.ID)
		}
	}
	if got := ToSave(data, shown, after, false); len(got) != len(shown)+len(data.Sprints)-5 {
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
	if len(problems) != 2 || !strings.Contains(problems[0], "Row 1") {
		t.Fatalf("problems = %v", problems)
	}
}
