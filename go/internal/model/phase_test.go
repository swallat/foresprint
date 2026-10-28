package model

import (
	"testing"
	"time"
)

func TestPhaseOfFollowsTheStartAndTheReviewNotTheDates(t *testing.T) {
	d := func(day int) time.Time { return Date(2026, 10, day) }
	today := d(28)
	s20 := Sprint{ID: "2026.20", Start: d(14), End: d(28), Commitment: Ptr(10.0)}
	s21 := Sprint{ID: "2026.21", Start: d(28), End: d(31)}
	all := func() []Sprint { return []Sprint{s20, s21} }
	phases := func() (Phase, Phase) { a := all(); return PhaseOf(a, s20, today), PhaseOf(a, s21, today) }

	// The changeover day: the old sprint is still running (plan frozen, Review open), the new
	// one is open although its first day has come.
	if a, b := phases(); a != PhaseRunning || b != PhaseOpen {
		t.Fatalf("changeover day: %s, %s", a, b)
	}
	// Starting the new sprint ends the old one, also without a Review.
	s21.StartedOn = &today
	if a, b := phases(); a != PhasePast || b != PhaseRunning {
		t.Fatalf("after the start: %s, %s", a, b)
	}
	// Taking the start back opens it again; the old one runs again.
	s21.StartedOn, s21.StartPending = nil, true
	if a, b := phases(); a != PhaseRunning || b != PhaseOpen {
		t.Fatalf("start taken back: %s, %s", a, b)
	}
	// A closed Review (from the last day on) ends the sprint.
	s20.Velocity = Ptr(9.0)
	if a, _ := phases(); a != PhasePast {
		t.Fatalf("reviewed: %s", a)
	}
}

func TestStartedFromOlderFilesAndExplicitMarks(t *testing.T) {
	d := func(day int) time.Time { return Date(2026, 10, day) }
	frozen := Sprint{ID: "a", Start: d(10), End: d(24), CommittedTickets: []string{"X-1"}}
	if !frozen.Started(d(11)) {
		t.Error("an older file with a frozen plan counts as started after its first day")
	}
	if frozen.Started(d(10)) {
		t.Error("the first day itself is not enough")
	}
	frozen.StartPending = true
	if frozen.Started(d(20)) {
		t.Error("a sprint waiting for its start is not started by its frozen plan")
	}
	later := d(12)
	frozen.StartedOn = &later
	if !frozen.Started(d(12)) || frozen.Started(d(11)) {
		t.Error("an explicit start counts from the day entered")
	}
	if (Sprint{ID: "b", Start: d(10), End: d(24)}).Started(d(20)) {
		t.Error("a sprint without plan or mark is not started")
	}
}

func TestANeverStartedSprintIsPastAfterItsLastDay(t *testing.T) {
	d := func(day int) time.Time { return Date(2026, 10, day) }
	s := Sprint{ID: "a", Start: d(1), End: d(15)}
	if got := PhaseOf([]Sprint{s}, s, d(14)); got != PhaseOpen {
		t.Errorf("before its end: %s", got)
	}
	if got := PhaseOf([]Sprint{s}, s, d(15)); got != PhasePast {
		t.Errorf("after its last day: %s", got)
	}
}

func TestAResultInsideTheSprintDoesNotCloseItYet(t *testing.T) {
	d := func(day int) time.Time { return Date(2026, 10, day) }
	s := Sprint{ID: "a", Start: d(1), End: d(15), Velocity: Ptr(5.0)}
	if got := PhaseOf([]Sprint{s}, s, d(10)); got != PhaseRunning {
		t.Errorf("replay inside the sprint: %s", got)
	}
	if got := PhaseOf([]Sprint{s}, s, d(14)); got != PhasePast {
		t.Errorf("on the last day: %s", got)
	}
}
