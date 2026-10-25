package sprintwrite

import (
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

func s(v string) *string { return &v }

type fake struct {
	calls []string
	fail  string
}

func (f *fake) MoveToSprint(id int, keys []string) error {
	f.calls = append(f.calls, "sprint:"+itoa(id)+":"+join(keys))
	if f.fail == "sprint" {
		return errors.New("boom")
	}
	return nil
}

func (f *fake) MoveToBacklog(keys []string) error {
	f.calls = append(f.calls, "backlog:"+join(keys))
	return nil
}

func itoa(i int) string { return string(rune('0' + i)) }
func join(k []string) string {
	out := ""
	for i, x := range k {
		if i > 0 {
			out += ","
		}
		out += x
	}
	return out
}

func input() Input {
	known := []sources.SprintValue{
		{ID: "5", Name: "2026.1", State: "ACTIVE"},
		{ID: "6", Name: "2026.2", State: "FUTURE"},
		{ID: "7", Name: "Refinement", State: "FUTURE"},
		{ID: "4", Name: "2025.26", State: "CLOSED"},
	}
	tracker := model.TrackerSettings{}
	return Input{
		SprintID:  "2026.1",
		Committed: []string{"A-1", "A-2", "A-4"},
		TakenOut:  []string{"A-3"},
		Tickets: []model.Ticket{
			{Key: "A-1", Title: "in", InSprint: s("2026.1"), SprintName: s("2026.1")},
			{Key: "A-2", Title: "backlog"},
			{Key: "A-3", Title: "taken out", InSprint: s("2026.1"), SprintName: s("2026.1")},
			{Key: "A-4", Title: "elsewhere", InSprint: s("2026.2"), SprintName: s("2026.2")},
			{Key: "A-5", Title: "done", InSprint: s("2026.1"), SprintName: s("2026.1"), Done: true},
		},
		Tracker:      tracker,
		Dir:          NewDirectory(known, tracker),
		ProForma:     []string{"Refinement"},
		NextSprintID: "2026.2",
	}
}

func moves(p Plan) []string {
	var out []string
	for _, m := range p.Moves {
		to := "backlog"
		if m.To != nil {
			to = m.To.Name
		}
		out = append(out, m.Key+">"+to)
	}
	return out
}

func TestBuild(t *testing.T) {
	in := input()
	got := moves(Build(in))
	want := []string{"A-2>2026.1", "A-3>backlog", "A-4>2026.1"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	in.Tracker.RemovedTarget = "pro_forma"
	if got := moves(Build(in)); got[1] != "A-3>Refinement" {
		t.Fatalf("pro forma: %v", got)
	}
	in.Tracker.RemovedTarget = "next"
	if got := moves(Build(in)); got[1] != "A-3>2026.2" {
		t.Fatalf("next: %v", got)
	}
	in.Committed, in.TakenOut = nil, nil // nothing frozen, nothing taken out
	if got := moves(Build(in)); len(got) != 0 {
		t.Fatalf("unfrozen: %v", got)
	}
}

func TestBuildProblems(t *testing.T) {
	in := input()
	in.SprintID = "2025.26"
	if p := Build(in); len(p.Moves) != 0 || len(p.Problems) != 1 {
		t.Fatalf("closed sprint: %+v", p)
	}
	in = input()
	in.SprintID = "2030.1"
	if p := Build(in); len(p.Problems) != 1 {
		t.Fatalf("unknown sprint: %+v", p)
	}
	in = input()
	in.Committed = append(in.Committed, "Z-9")
	if p := Build(in); len(p.Problems) != 1 || len(p.Moves) != 3 {
		t.Fatalf("unknown ticket: %+v", p)
	}
	in = input()
	in.Tracker.RemovedTarget = "pro_forma"
	in.ProForma = nil
	if p := Build(in); len(p.Problems) != 1 || len(p.Moves) != 2 {
		t.Fatalf("no pro forma: %+v", p)
	}
}

func TestApplyAndUndo(t *testing.T) {
	p := Build(input())
	p.Moves[1].Skip = true // A-3 stays where it is
	f := &fake{}
	res := Apply(p, f)
	if res.Err != nil || len(res.Done) != 2 {
		t.Fatalf("%+v", res)
	}
	if want := []string{"sprint:5:A-2,A-4"}; !reflect.DeepEqual(f.calls, want) {
		t.Fatalf("calls %v", f.calls)
	}
	f2 := &fake{}
	if r := Apply(UndoPlan(res.Done), f2); r.Err != nil {
		t.Fatal(r.Err)
	}
	// A-4 goes back to 2026.2, A-2 to the backlog.
	if len(f2.calls) != 2 {
		t.Fatalf("undo calls %v", f2.calls)
	}
}

func TestApplyStopsAtError(t *testing.T) {
	p := Build(input())
	f := &fake{fail: "sprint"}
	res := Apply(p, f)
	if res.Err == nil || len(res.Done) != 0 || len(res.Failed) != 3 {
		t.Fatalf("%+v", res)
	}
}

func TestPulledInTicketStays(t *testing.T) {
	in := input()
	in.TakenOut = nil // A-3 is in the tracker's sprint but not on the list: drift, not taken out
	for _, m := range Build(in).Moves {
		if m.Key == "A-3" {
			t.Fatalf("A-3 must stay: %+v", m)
		}
	}
}

func TestTrackerSprintDecidesNotToolId(t *testing.T) {
	in := input()
	in.Tickets[0].InSprint = nil // the tool sprint has ended, the tracker sprint is still active
	for _, m := range Build(in).Moves {
		if m.Key == "A-1" {
			t.Fatalf("A-1 is in the tracker sprint already: %+v", m)
		}
	}
}

func TestEmptyBoardSprintIsATarget(t *testing.T) {
	in := input()
	in.Dir = NewDirectory(nil, in.Tracker)
	if p := Build(in); len(p.Problems) != 1 {
		t.Fatalf("unknown: %+v", p)
	}
	in.Dir.Add([]sources.SprintValue{{ID: "9", Name: "2026.1", State: "FUTURE"}})
	if p := Build(in); len(p.Moves) == 0 {
		t.Fatalf("board sprint: %+v", p)
	}
}

type recorder struct {
	calls   [][]string
	failOn  int
	counter int
}

func (r *recorder) MoveToSprint(_ int, keys []string) error {
	r.counter++
	if r.counter == r.failOn {
		return errors.New("boom")
	}
	r.calls = append(r.calls, keys)
	return nil
}
func (r *recorder) MoveToBacklog([]string) error { return nil }

func TestBatchFailureKeepsWhatWentThrough(t *testing.T) {
	target := Ref{ID: "5", Name: "2026.1"}
	var p Plan
	for i := 0; i < 120; i++ {
		p.Moves = append(p.Moves, Move{Key: "A-" + itoaN(i+1), To: &target, FromKnown: true})
	}
	r := &recorder{failOn: 2}
	res := Apply(p, r)
	if res.Err == nil || len(res.Done) != 50 || len(res.Failed) != 70 {
		t.Fatalf("done %d failed %d err %v", len(res.Done), len(res.Failed), res.Err)
	}
}

func itoaN(i int) string {
	s := ""
	for ; i > 0; i /= 10 {
		s = string(rune('0'+i%10)) + s
	}
	return s
}

func TestUndoSkipsUnknownAndClosed(t *testing.T) {
	closed := Ref{ID: "4", Name: "old", State: "CLOSED"}
	open := Ref{ID: "5", Name: "now"}
	done := []Move{
		{Key: "A-1", To: &open, From: nil, FromKnown: false},
		{Key: "A-2", To: &open, From: &closed, FromKnown: true},
		{Key: "A-3", To: &open, From: nil, FromKnown: true},
	}
	p := UndoPlan(done)
	if len(p.Moves) != 1 || p.Moves[0].Key != "A-3" || p.Moves[0].To != nil || len(p.Problems) != 2 {
		t.Fatalf("%+v", p)
	}
}

type fakeBoard struct {
	asked int
	err   error
}

func (b *fakeBoard) ListBoardSprints(id int) ([]sources.SprintValue, error) {
	b.asked = id
	return []sources.SprintValue{{ID: "9", Name: "2026.3", State: "FUTURE"}}, b.err
}

func TestLoadDirectoryUsesTheBoard(t *testing.T) {
	tracker := model.TrackerSettings{}
	board := &fakeBoard{}
	d, err := LoadDirectory(nil, board, tracker)
	if err != nil || board.asked != 0 {
		t.Fatalf("no board_id must not ask: %v %d", err, board.asked)
	}
	if _, ok := d.ForSprint("2026.3"); ok {
		t.Fatal("unknown without board")
	}
	id := 3
	tracker.BoardID = &id
	d, err = LoadDirectory(nil, board, tracker)
	if err != nil || board.asked != 3 {
		t.Fatalf("%v %d", err, board.asked)
	}
	if r, ok := d.ForSprint("2026.3"); !ok || r.ID != "9" {
		t.Fatalf("board sprint: %+v", r)
	}
	board.err = errors.New("down")
	if _, err := LoadDirectory(nil, board, tracker); err == nil {
		t.Fatal("board error must be returned")
	}
}

func TestSprintNumber(t *testing.T) {
	for in, want := range map[string]int{"12": 12, "\t12\n": 12, "12.0": 12, "1234": 1234} {
		if got, ok := SprintNumber(in); !ok || got != want {
			t.Errorf("%q: %d %v", in, got, ok)
		}
	}
	for _, in := range []string{"", "abc", "12.5", "-3", "None"} {
		if _, ok := SprintNumber(in); ok {
			t.Errorf("%q must be refused", in)
		}
	}
}

// A sprint met in a ticket without id (Data Center text without "id=") must not hide the numeric
// id of the same sprint on the board.
func TestAddFillsMissingID(t *testing.T) {
	d := NewDirectory([]sources.SprintValue{{Name: "2026.3", State: "FUTURE"}}, model.TrackerSettings{})
	d.Add([]sources.SprintValue{{ID: "9", Name: "2026.3", State: "FUTURE"}})
	r, ok := d.ByName("2026.3")
	if !ok || r.ID != "9" {
		t.Fatalf("%+v %v", r, ok)
	}
}

func TestApplyFloatIDAndErrorNamesValue(t *testing.T) {
	f := &fake{}
	plan := Plan{Moves: []Move{{Key: "A-1", To: &Ref{ID: "7.0", Name: "x"}}}}
	if res := Apply(plan, f); res.Err != nil || !reflect.DeepEqual(f.calls, []string{"sprint:7:A-1"}) {
		t.Fatalf("%v %v", res.Err, f.calls)
	}
	plan = Plan{Moves: []Move{{Key: "A-1", To: &Ref{ID: "[id=x]", Name: "x"}}}}
	res := Apply(plan, f)
	if res.Err == nil || !strings.Contains(res.Err.Error(), "[id=x]") {
		t.Fatalf("%v", res.Err)
	}
}
