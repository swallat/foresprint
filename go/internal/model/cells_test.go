package model

import "testing"

func TestAbsenceCells(t *testing.T) {
	var s Sprint

	// Typing announces; a confirmed cell next to it keeps the sprint open.
	s.SetCell("anna", 2, AbsencesExpected)
	s.SetCell("ben", 3, AbsencesConfirmed)
	if s.AbsenceStatus() != AbsencesExpected {
		t.Fatalf("a sprint with one confirmed cell is open, got %v", s.AbsenceStatus())
	}
	if s.CellState("anna") != AbsencesExpected || s.CellState("ben") != AbsencesConfirmed || s.CellState("cem") != AbsencesUnknown {
		t.Errorf("cell states: %v %v %v", s.CellState("anna"), s.CellState("ben"), s.CellState("cem"))
	}
	if s.CellDays("anna") != 2 || s.CellDays("ben") != 3 || s.CellDays("cem") != 0 {
		t.Errorf("cell days: %v %v %v", s.CellDays("anna"), s.CellDays("ben"), s.CellDays("cem"))
	}

	// A cell moves between the states and 0 removes it.
	s.SetCell("anna", 2, AbsencesConfirmed)
	if s.CellState("anna") != AbsencesConfirmed || len(s.ExpectedAbsences) != 0 {
		t.Errorf("anna confirmed: %v %v", s.CellState("anna"), s.ExpectedAbsences)
	}
	s.SetCell("ben", 0, AbsencesExpected)
	if _, ok := s.Absences["ben"]; ok {
		t.Error("0 days must remove the cell")
	}

	// Freezing confirms every cell; confirmed days win over announced ones.
	s.SetCell("cem", 1, AbsencesExpected)
	s.ExpectedAbsences["anna"] = 9 // stale announced value next to the confirmed one
	s.Freeze()
	if s.AbsenceStatus() != AbsencesConfirmed || s.CellState("dora") != AbsencesConfirmed {
		t.Errorf("frozen: %v %v", s.AbsenceStatus(), s.CellState("dora"))
	}
	if s.Absences["anna"] != 2 || s.Absences["cem"] != 1 || s.ExpectedAbsences != nil {
		t.Errorf("frozen days: %v %v", s.Absences, s.ExpectedAbsences)
	}
	if s.CellDays("dora") != 0 {
		t.Error("an empty cell of a frozen sprint is 0 days")
	}
	// A cell edited in a frozen sprint stays confirmed.
	s.SetCell("dora", 1, AbsencesExpected)
	if s.CellState("dora") != AbsencesConfirmed || s.Absences["dora"] != 1 {
		t.Errorf("edit in frozen sprint: %v", s.Absences)
	}

	// Unfreezing announces all entries.
	s.Unfreeze()
	if s.AbsenceStatus() != AbsencesExpected || s.CellState("anna") != AbsencesExpected || len(s.Absences) != 0 {
		t.Errorf("unfrozen: %v %v %v", s.AbsenceStatus(), s.CellState("anna"), s.Absences)
	}
	for _, p := range []string{"anna", "cem", "dora"} {
		s.SetCell(p, 0, AbsencesExpected)
	}
	if s.AbsenceStatus() != AbsencesUnknown {
		t.Errorf("no entries left: %v", s.AbsenceStatus())
	}
}

func TestLegacyAbsencesAreFrozen(t *testing.T) {
	// 0.8: entered absences confirm the whole sprint, whatever state is stored.
	s := Sprint{Absences: map[string]float64{"anna": 2}, AbsenceState: Ptr(AbsencesExpected)}
	if s.AbsenceStatus() != AbsencesConfirmed || s.CellState("ben") != AbsencesConfirmed {
		t.Errorf("legacy: %v %v", s.AbsenceStatus(), s.CellState("ben"))
	}
	// Only the explicit state "open" of 1.0 opens such a sprint.
	s.AbsenceState = Ptr(AbsencesOpen)
	if s.AbsenceStatus() != AbsencesExpected || s.CellState("ben") != AbsencesUnknown || s.CellState("anna") != AbsencesConfirmed {
		t.Errorf("open: %v %v %v", s.AbsenceStatus(), s.CellState("ben"), s.CellState("anna"))
	}
}

func TestEmptyingAFrozenLegacySprintKeepsItFrozen(t *testing.T) {
	// 0.8 file with entries and a stored "expected": frozen, and still frozen when the last
	// cell is cleared.
	s := Sprint{Absences: map[string]float64{"anna": 2}, AbsenceState: Ptr(AbsencesExpected)}
	s.SetCell("anna", 0, AbsencesConfirmed)
	if s.AbsenceStatus() != AbsencesConfirmed {
		t.Errorf("status %v, want confirmed", s.AbsenceStatus())
	}
}

func TestOpenStateIsOnlyStoredForConfirmedCells(t *testing.T) {
	var s Sprint
	s.SetCell("anna", 1, AbsencesExpected)
	if *s.AbsenceState != AbsencesExpected { // the 0.8 state
		t.Errorf("announced only: %v", *s.AbsenceState)
	}
	s.SetCell("ben", 1, AbsencesConfirmed)
	if *s.AbsenceState != AbsencesOpen {
		t.Errorf("with a confirmed cell: %v", *s.AbsenceState)
	}
}
