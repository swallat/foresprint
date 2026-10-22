package calendar_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/model"
)

func day(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

func sprintAt(id, start, end string) model.Sprint {
	return model.Sprint{ID: id, Start: day(start), End: day(end)}
}

func namedTeam(numbering model.Numbering, rules ...model.NamingRule) *model.Team {
	return &model.Team{Sprint: model.SprintSettings{LengthDays: 14, Numbering: numbering, Naming: rules}}
}

func str(s string) *string { return &s }

func TestChainWithoutNamingEqualsFollowingSprint(t *testing.T) {
	team := namedTeam(model.NumberingYearly)
	prev := sprintAt("2026.17", "2026-10-05", "2026-10-19")
	want, err := calendar.FollowingSprint(team, &prev)
	if err != nil {
		t.Fatal(err)
	}
	got, err := calendar.NewChain(team, []model.Sprint{prev}).Next()
	if err != nil || got.ID != want.ID || !got.Start.Equal(want.Start) || !got.End.Equal(want.End) {
		t.Errorf("got %v %v, want %v", got, err, want)
	}
}

func TestChainNamesFollowingSprints(t *testing.T) {
	rule := model.NamingRule{Pattern: "Atlas {JJ}-{NN}"}
	for _, c := range []struct {
		name      string
		numbering model.Numbering
		rules     []model.NamingRule
		saved     []model.Sprint
		want      string
	}{
		{"continues a numeric id", model.NumberingYearly, []model.NamingRule{rule},
			[]model.Sprint{sprintAt("2026.17", "2026-10-05", "2026-10-19")}, "Atlas 26-18"},
		{"continues a named id", model.NumberingYearly, []model.NamingRule{rule},
			[]model.Sprint{sprintAt("Atlas 26-18", "2026-10-05", "2026-10-19")}, "Atlas 26-19"},
		{"restarts in the new year", model.NumberingYearly, []model.NamingRule{rule},
			[]model.Sprint{sprintAt("Atlas 26-26", "2026-12-14", "2027-01-04")}, "Atlas 27-01"},
		{"running number from a sequential id", model.NumberingSequential,
			[]model.NamingRule{{Pattern: "S{LFD}"}},
			[]model.Sprint{sprintAt("40", "2026-10-05", "2026-10-19")}, "S41"},
		{"running number from a named id", model.NumberingSequential,
			[]model.NamingRule{{Pattern: "S{LFD}"}},
			[]model.Sprint{sprintAt("S40", "2026-10-05", "2026-10-19")}, "S41"},
		{"rule that begins with the next sprint", model.NumberingYearly,
			[]model.NamingRule{{From: str("2026.18"), Pattern: "Atlas {JJ}-{NN}"}},
			[]model.Sprint{sprintAt("2026.17", "2026-10-05", "2026-10-19")}, "Atlas 26-18"},
		{"rule that has not begun", model.NumberingYearly,
			[]model.NamingRule{{From: str("2026.30"), Pattern: "Atlas {JJ}-{NN}"}},
			[]model.Sprint{sprintAt("2026.17", "2026-10-05", "2026-10-19")}, "2026.18"},
		{"later rule wins", model.NumberingYearly,
			[]model.NamingRule{rule, {From: str("Atlas 26-05"), Pattern: "B{N}"}},
			[]model.Sprint{sprintAt("Atlas 26-04", "2026-10-05", "2026-10-19"), sprintAt("Atlas 26-05", "2026-10-19", "2026-11-02")}, "B6"},
		{"counts the year when the id says nothing", model.NumberingYearly,
			[]model.NamingRule{{Pattern: "{N}"}},
			[]model.Sprint{sprintAt("x", "2026-01-05", "2026-01-19"), sprintAt("y", "2026-01-19", "2026-02-02"), sprintAt("z", "2026-02-02", "2026-02-16")}, "4"},
	} {
		t.Run(c.name, func(t *testing.T) {
			team := namedTeam(c.numbering, c.rules...)
			got, err := calendar.NewChain(team, c.saved).Next()
			if err != nil {
				t.Fatal(err)
			}
			if got.ID != c.want {
				t.Errorf("ID = %q, want %q", got.ID, c.want)
			}
			if last := c.saved[len(c.saved)-1]; !got.Start.Equal(last.End) {
				t.Errorf("start = %v, want %v", got.Start, last.End)
			}
		})
	}
}

func TestChainKeepsCounting(t *testing.T) {
	team := namedTeam(model.NumberingYearly, model.NamingRule{Pattern: "{JJJJ}-{NN}"})
	chain := calendar.NewChain(team, []model.Sprint{sprintAt("2026.24", "2026-11-16", "2026-11-30")})
	var ids []string
	for i := 0; i < 4; i++ {
		s, err := chain.Next()
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, s.ID)
	}
	want := []string{"2026-25", "2026-26", "2026-27", "2027-01"}
	for i := range want {
		if ids[i] != want[i] {
			t.Fatalf("ids = %v, want %v", ids, want)
		}
	}
}

func TestChainAfterMiddleSprint(t *testing.T) {
	team := namedTeam(model.NumberingYearly, model.NamingRule{Pattern: "Atlas {JJ}-{NN}"})
	saved := []model.Sprint{
		sprintAt("Atlas 26-01", "2026-01-05", "2026-01-19"),
		sprintAt("Atlas 26-02", "2026-01-19", "2026-02-02"),
		sprintAt("Atlas 26-03", "2026-02-02", "2026-02-16"),
	}
	got, err := calendar.NewChain(team, saved).After(&saved[0])
	if err != nil || got.ID != "Atlas 26-02" {
		t.Errorf("got %q %v", got.ID, err)
	}
}

func TestChainWithoutFirstSprint(t *testing.T) {
	team := namedTeam(model.NumberingYearly, model.NamingRule{Pattern: "S{LFD}"})
	if _, err := calendar.NewChain(team, nil).Next(); err == nil {
		t.Error("want an error without a first sprint")
	}
	first := "S1"
	start := day("2026-01-05")
	team.Sprint.FirstID, team.Sprint.FirstStart = &first, &start
	chain := calendar.NewChain(team, nil)
	one, err := chain.Next()
	if err != nil || one.ID != "S1" {
		t.Fatalf("first = %q %v", one.ID, err)
	}
	two, err := chain.Next()
	if err != nil || two.ID != "S2" {
		t.Errorf("second = %q %v", two.ID, err)
	}
}

func TestNameAll(t *testing.T) {
	sprints := []model.Sprint{
		sprintAt("a", "2026-12-07", "2026-12-21"),
		sprintAt("b", "2026-12-21", "2027-01-04"),
		sprintAt("c", "2027-01-04", "2027-01-18"),
		sprintAt("d", "2027-01-18", "2027-02-01"),
	}
	got, err := calendar.NameAll("{JJJJ}.{NN} (#{LFD})", sprints, 25, 60)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"2026.25 (#60)", "2026.26 (#61)", "2027.01 (#62)", "2027.02 (#63)"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
	if _, err := calendar.NameAll("{XX}", sprints, 1, 1); err == nil {
		t.Error("want an error for an unknown placeholder")
	}
}

func TestChainRuleFromFutureSprintStaysOn(t *testing.T) {
	team := namedTeam(model.NumberingYearly, model.NamingRule{From: str("2026.18"), Pattern: "Atlas {JJ}-{NN}"})
	chain := calendar.NewChain(team, []model.Sprint{sprintAt("2026.17", "2026-10-05", "2026-10-19")})
	want := []string{"Atlas 26-18", "Atlas 26-19", "Atlas 26-20"}
	for _, w := range want {
		s, err := chain.Next()
		if err != nil || s.ID != w {
			t.Fatalf("got %q %v, want %q", s.ID, err, w)
		}
	}
	// A fresh chain over the recorded result continues the same way.
	saved := []model.Sprint{sprintAt("2026.17", "2026-10-05", "2026-10-19"), sprintAt("Atlas 26-18", "2026-10-19", "2026-11-02")}
	s, err := calendar.NewChain(team, saved).Next()
	if err != nil || s.ID != "Atlas 26-19" {
		t.Errorf("got %q %v", s.ID, err)
	}
}

func TestChainNamesWithoutYearRepeat(t *testing.T) {
	team := namedTeam(model.NumberingYearly, model.NamingRule{Pattern: "Sprint {NN}"})
	saved := []model.Sprint{
		sprintAt("Sprint 01", "2026-01-05", "2026-01-19"),
		sprintAt("Sprint 25", "2026-11-30", "2026-12-14"),
		sprintAt("Sprint 26", "2026-12-14", "2026-12-28"),
	}
	chain := calendar.NewChain(team, saved)
	var got []string
	for i := 0; i < 4; i++ {
		s, err := chain.Next()
		if err != nil {
			t.Fatal(err)
		}
		got = append(got, s.ID)
	}
	want := []string{"Sprint 27", "Sprint 01", "Sprint 02", "Sprint 03"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}
