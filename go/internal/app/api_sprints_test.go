package app

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
)

// copyDemo copies the demo team to a temporary data folder, so that tests may write.
func copyDemo(t *testing.T) string {
	t.Helper()
	src := demoDir(t)
	dst := t.TempDir()
	err := filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, path)
		if info.IsDir() {
			return os.MkdirAll(filepath.Join(dst, rel), 0o755)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(dst, rel), b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	return dst
}

func TestAbsenceGridEditFreezeUnfreeze(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, err := api.AbsenceGrid(team, "", 3)
	if err != nil {
		t.Fatal(err)
	}
	if len(grid.Columns) != 3 || len(grid.Rows) == 0 {
		t.Fatalf("grid = %d columns, %d rows", len(grid.Columns), len(grid.Rows))
	}
	// A sprint beyond the recorded ones is generated from the calendar and still unknown.
	if grid, err = api.AbsenceGrid(team, "", 40); err != nil {
		t.Fatal(err)
	}
	col := grid.Columns[len(grid.Columns)-1]
	person := grid.Rows[0].Person
	if col.State != AbsenceUnknown {
		t.Fatalf("a future sprint should start unknown, got %q", col.State)
	}

	// Typing days announces them; a quarter day is rounded to half days, too many are cut.
	c, err := api.SetAbsence(team, col.ID, person, 2.3)
	if err != nil {
		t.Fatal(err)
	}
	if c.State != AbsenceAnnounced || c.Entries != 1 || c.Absent != 2.5 {
		t.Fatalf("after typing: %+v", c)
	}
	if c, err = api.SetAbsence(team, col.ID, person, 99); err != nil || c.Absent > float64(c.Workdays) {
		t.Fatalf("too many days not cut: %+v %v", c, err)
	}
	if _, err = api.SetAbsence(team, col.ID, person, -1); err == nil {
		t.Fatal("negative days accepted")
	}
	if _, err = api.SetAbsence(team, col.ID, "nobody", 1); err == nil {
		t.Fatal("unknown person accepted")
	}

	// Freezing confirms; empty cells then count as 0 days.
	frozen, err := api.FreezeAbsences(team, col.ID)
	if err != nil || frozen.State != AbsenceConfirmed {
		t.Fatalf("freeze: %+v %v", frozen, err)
	}
	if again, _ := api.AbsenceGrid(team, col.ID, 1); again.Columns[0].State != AbsenceConfirmed || again.Rows[0].Cells[0].Days == 0 {
		t.Fatalf("the frozen absences did not come back: %+v", again)
	}
	// Removing the last entry of a frozen sprint keeps it frozen ("nobody absent").
	if c, err = api.SetAbsence(team, col.ID, person, 0); err != nil || c.State != AbsenceConfirmed || c.Entries != 0 {
		t.Fatalf("nobody absent: %+v %v", c, err)
	}
	// Opening again: entries become announced, none left means unknown.
	if c, err = api.SetAbsence(team, col.ID, person, 1); err != nil {
		t.Fatal(err)
	}
	if c, err = api.UnfreezeAbsences(team, col.ID); err != nil || c.State != AbsenceAnnounced {
		t.Fatalf("unfreeze: %+v %v", c, err)
	}
	if _, err = api.SetAbsence(team, col.ID, person, 0); err != nil {
		t.Fatal(err)
	}
	if grid, _ = api.AbsenceGrid(team, col.ID, 1); grid.Columns[0].State != AbsenceUnknown {
		t.Fatalf("no entries left should be unknown, got %q", grid.Columns[0].State)
	}
}

func TestSprintPrepareReadiness(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, err := api.AbsenceGrid(team, "", 40)
	if err != nil {
		t.Fatal(err)
	}
	id := grid.Columns[len(grid.Columns)-1].ID
	p, err := api.SprintPrepare(team, id)
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Ready) < 2 || p.Ready[0].Kind != "absences" || p.Ready[0].State != ReadyOpen {
		t.Fatalf("readiness = %+v", p.Ready)
	}
	if p.CapacityBase < p.Sprint.Capacity {
		t.Fatalf("base capacity %v below capacity %v", p.CapacityBase, p.Sprint.Capacity)
	}
	if _, err := api.FreezeAbsences(team, id); err != nil {
		t.Fatal(err)
	}
	if p, _ = api.SprintPrepare(team, id); p.Ready[0].State != ReadyDone {
		t.Fatalf("frozen absences should be done: %+v", p.Ready[0])
	}
}

func TestAbsenceEditsRunTogetherWithoutLosingData(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, err := api.AbsenceGrid(team, "", 40)
	if err != nil {
		t.Fatal(err)
	}
	for _, col := range grid.Columns[len(grid.Columns)-6:] {
		person := grid.Rows[0].Person
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); _, _ = api.SetAbsence(team, col.ID, person, 2) }()
		go func() { defer wg.Done(); _, _ = api.FreezeAbsences(team, col.ID) }()
		wg.Wait()
		got, _ := api.AbsenceGrid(team, col.ID, 1)
		// Whatever ran first, both effects must be there: the sprint is frozen and, unless the
		// freeze came first and the entry was typed into the frozen sprint, the entry exists.
		if got.Columns[0].State != AbsenceConfirmed || got.Rows[0].Cells[0].Days != 2 {
			t.Fatalf("%s: state %q, days %v", col.ID, got.Columns[0].State, got.Rows[0].Cells[0].Days)
		}
	}
}

func TestFinishedSprintRefusesEdits(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	sprints, _ := api.Sprints(team)
	if _, err := api.SetAbsence(team, sprints[0].ID, "anna", 1); err == nil {
		t.Fatal("an edit of a finished sprint was accepted")
	}
	if _, err := api.FreezeAbsences(team, sprints[0].ID); err == nil {
		t.Fatal("freezing a finished sprint was accepted")
	}
}

func TestUnfreezeKeepsConfirmedDays(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, _ := api.AbsenceGrid(team, "", 40)
	col := grid.Columns[len(grid.Columns)-1]
	person := grid.Rows[0].Person
	if _, err := api.SetAbsence(team, col.ID, person, 3); err != nil {
		t.Fatal(err)
	}
	if _, err := api.FreezeAbsences(team, col.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := api.UnfreezeAbsences(team, col.ID); err != nil {
		t.Fatal(err)
	}
	if got, _ := api.AbsenceGrid(team, col.ID, 1); got.Rows[0].Cells[0].Days != 3 {
		t.Fatalf("days after unfreeze: %v", got.Rows[0].Cells[0].Days)
	}
}

func TestAbsenceCellsAreLockedOneByOne(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, _ := api.AbsenceGrid(team, "", 40)
	col := grid.Columns[len(grid.Columns)-1]
	anna, ben := grid.Rows[0].Person, grid.Rows[1].Person
	cell := func(row int) AbsenceCell {
		g, err := api.AbsenceGrid(team, col.ID, 1)
		if err != nil {
			t.Fatal(err)
		}
		return g.Rows[row].Cells[0]
	}
	if _, err := api.SetAbsence(team, col.ID, anna, 2); err != nil {
		t.Fatal(err)
	}
	if _, err := api.SetAbsence(team, col.ID, ben, 1); err != nil {
		t.Fatal(err)
	}
	if cell(0).State != CellAnnounced || cell(1).State != CellAnnounced {
		t.Fatalf("typed days are announced: %v %v", cell(0).State, cell(1).State)
	}
	// Locking one cell leaves the sprint open and the other cell announced.
	c, err := api.SetAbsenceConfirmed(team, col.ID, anna, true)
	if err != nil {
		t.Fatal(err)
	}
	if c.State != AbsenceAnnounced {
		t.Errorf("one locked cell must not freeze the sprint: %q", c.State)
	}
	if cell(0).State != CellConfirmed || cell(1).State != CellAnnounced || cell(0).Days != 2 {
		t.Errorf("after locking anna: %+v %+v", cell(0), cell(1))
	}
	// Typing into a confirmed cell keeps it confirmed.
	if _, err := api.SetAbsence(team, col.ID, anna, 3); err != nil {
		t.Fatal(err)
	}
	if cell(0).State != CellConfirmed || cell(0).Days != 3 {
		t.Errorf("anna after typing: %+v", cell(0))
	}
	// The capacity counts both kinds of cell.
	if g, _ := api.AbsenceGrid(team, col.ID, 1); g.Columns[0].Absent != 4 {
		t.Errorf("absent days %v, want 4", g.Columns[0].Absent)
	}
	// Freezing confirms the rest; the other cells are empty = 0 days, confirmed.
	if c, _ = api.FreezeAbsences(team, col.ID); c.State != AbsenceConfirmed || cell(1).State != CellConfirmed {
		t.Errorf("frozen: %q %+v", c.State, cell(1))
	}
	if _, err := api.SetAbsenceConfirmed(team, col.ID, ben, false); err != nil || cell(1).State != CellConfirmed {
		t.Errorf("a frozen sprint keeps its cells confirmed: %+v %v", cell(1), err)
	}
}

func TestSprintOverview(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	o, err := api.SprintOverview(team, 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(o.Rows) < 4 || o.Reference <= 0 || o.CurrentIndex < 0 {
		t.Fatalf("overview = %d rows, reference %v, current %d", len(o.Rows), o.Reference, o.CurrentIndex)
	}
	pastRows, spans := 0, 0
	for _, r := range o.Rows {
		if r.PlanLow != nil && r.PlanHigh != nil && r.Plan != nil {
			spans++
			if *r.PlanLow > *r.PlanHigh || *r.Plan < *r.PlanLow-1 || *r.Plan > *r.PlanHigh+1 {
				t.Errorf("plan %v outside %v-%v", *r.Plan, *r.PlanLow, *r.PlanHigh)
			}
		}
		if r.State == SprintPast {
			pastRows++
			if r.Next != NextNone || r.Plan != nil {
				t.Errorf("past row %+v", r)
			}
			if r.Velocity != nil && r.Capacity != nil && (r.Rate == nil || r.Normalized == nil) {
				t.Errorf("rate missing in %+v", r)
			}
		}
	}
	if spans == 0 {
		t.Error("no row has a PLAN range")
	}
	if pastRows != 5 {
		t.Errorf("%d past rows, want the last 5", pastRows)
	}
	cur := o.Rows[o.CurrentIndex]
	if cur.State != SprintCurrent && cur.State != SprintFuture && cur.State != SprintPlanned {
		t.Errorf("row at CurrentIndex is %+v", cur)
	}
	if all, _ := api.SprintOverview(team, -1); len(all.Rows) <= len(o.Rows) {
		t.Errorf("past -1 should list all finished sprints: %d vs %d", len(all.Rows), len(o.Rows))
	}
}

func TestAbsenceGridShowsPeriodsAndFreezeKeepsThem(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	grid, err := api.AbsenceGrid(team, "", 40)
	if err != nil {
		t.Fatal(err)
	}
	col := grid.Columns[len(grid.Columns)-1]
	person := grid.Rows[0].Person
	if _, err := api.SaveAbsencePeriods(team, []AbsencePeriodDTO{{Person: person, From: col.Start, To: col.End}}); err != nil {
		t.Fatal(err)
	}
	grid, err = api.AbsenceGrid(team, col.ID, 1)
	if err != nil {
		t.Fatal(err)
	}
	cell := grid.Rows[0].Cells[0]
	if cell.Days == 0 || !cell.FromPeriod || cell.State != CellAnnounced {
		t.Fatalf("the period should show as announced days: %+v", cell)
	}
	if c := grid.Columns[0]; c.State != AbsenceAnnounced || c.Entries != 1 {
		t.Fatalf("column does not count the period: %+v", c)
	}
	// Freezing keeps the days of the period; changing the period later leaves the frozen sprint alone.
	if _, err := api.FreezeAbsences(team, col.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := api.SaveAbsencePeriods(team, []AbsencePeriodDTO{}); err != nil {
		t.Fatal(err)
	}
	grid, _ = api.AbsenceGrid(team, col.ID, 1)
	if cell := grid.Rows[0].Cells[0]; cell.Days == 0 || cell.FromPeriod || cell.State != CellConfirmed {
		t.Fatalf("frozen days lost: %+v", cell)
	}
}
