package sprintcal

import (
	"testing"
	"time"
)

func TestKeepLaterSwallowsAFullyCoveredSprint(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 4)
	got, err := KeepLater(data, shown, 0, shown[1].End.Add(-dayLength))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Dropped) != 1 || got.Dropped[0].ID != shown[1].ID || !got.Rows[1].Gone {
		t.Fatalf("dropped %+v, want only %s", got.Dropped, shown[1].ID)
	}
	if len(got.Save) != 1 || !got.Save[0].End.Equal(shown[1].End) {
		t.Fatalf("save %+v", got.Save)
	}
	if got.Target != shown[2].ID {
		t.Errorf("target %q, want %q", got.Target, shown[2].ID)
	}
	if !got.Rows[2].Sprint.Start.Equal(shown[2].Start) {
		t.Errorf("the sprint after the swallowed one must stay where it is")
	}
}

func TestKeepLaterCutsThePartlyCoveredSprint(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	got, err := KeepLater(data, shown, 0, shown[0].End.Add(dayLength))
	if err != nil || len(got.Dropped) != 0 || len(got.Save) != 2 {
		t.Fatalf("%+v, %v", got, err)
	}
	if !got.Save[1].Start.Equal(shown[0].End.Add(2*dayLength)) || !got.Save[1].End.Equal(shown[1].End) {
		t.Errorf("cut sprint %v–%v", got.Save[1].Start, got.Save[1].End)
	}
}

func TestKeepLaterShorterSprintLetsTheNextOneStartEarlier(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	got, err := KeepLater(data, shown, 0, shown[0].End.Add(-3*dayLength))
	if err != nil || len(got.Dropped) != 0 || len(got.Save) != 2 {
		t.Fatalf("%+v, %v", got, err)
	}
	if !got.Save[1].Start.Equal(shown[0].End.Add(-2 * dayLength)) {
		t.Errorf("next start %v", got.Save[1].Start)
	}
}

func TestKeepLaterRejectsALastDayBeforeTheStart(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	if _, err := KeepLater(data, shown, 0, shown[0].Start.Add(-2*dayLength)); err == nil {
		t.Fatal("expected an error")
	}
}

func TestShiftLaterWithANewStartMovesTheSprintAndTheFollowing(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	start := shown[0].Start.Add(2 * dayLength)
	got, err := ShiftLater(data, shown, 0, time.Time{}, &start)
	if err != nil {
		t.Fatal(err)
	}
	for i, r := range got.Rows[:3] {
		if !r.Sprint.Start.Equal(shown[i].Start.Add(2*dayLength)) || !r.Sprint.End.Equal(shown[i].End.Add(2*dayLength)) {
			t.Errorf("row %d: %v–%v", i, r.Sprint.Start, r.Sprint.End)
		}
	}
}

func TestRegularGivesEverySprintTheRegularLength(t *testing.T) {
	_, data := demoCopy(t)
	shown := window(data.Sprints, 2, 3)
	odd := shown[0].Clone()
	odd.End = odd.End.Add(5 * dayLength) // a long sprint that breaks the rhythm
	shown[0] = odd
	got, err := Regular(data, shown, 0)
	if err != nil {
		t.Fatal(err)
	}
	length := time.Duration(data.Team.Sprint.LengthDays) * dayLength
	for i, r := range got.Rows {
		if r.Sprint.End.Sub(r.Sprint.Start) != length {
			t.Errorf("row %d: %v–%v is not %d days", i, r.Sprint.Start, r.Sprint.End, data.Team.Sprint.LengthDays)
		}
		if i > 0 && !r.Sprint.Start.Equal(got.Rows[i-1].Sprint.End) {
			t.Errorf("row %d does not follow row %d", i, i-1)
		}
	}
	if !got.Rows[0].Sprint.Start.Equal(shown[0].Start) {
		t.Error("the first sprint moved its start")
	}
}
