package sprintwrite

import (
	"errors"
	"reflect"
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
	in.Committed = nil // not frozen: nothing is taken out, nothing is put in
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
