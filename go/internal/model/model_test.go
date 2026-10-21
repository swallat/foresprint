package model

import (
	"testing"
	"time"
)

func TestMembership(t *testing.T) {
	end := Date(2026, 6, 30)
	p := Person{Memberships: []Membership{{Start: Date(2025, 3, 1), End: &end, FTE: 0.5}}}
	for _, c := range []struct {
		day  time.Time
		want float64
	}{
		{Date(2025, 2, 28), 0}, {Date(2025, 3, 1), 0.5}, {Date(2026, 6, 30), 0.5}, {Date(2026, 7, 1), 0},
	} {
		if got := p.FTEOn(c.day); got != c.want {
			t.Errorf("FTEOn(%v) = %v, want %v", c.day, got, c.want)
		}
	}
	if !p.ActiveBetween(Date(2026, 6, 30), Date(2026, 7, 14)) {
		t.Error("a membership ending on the first day is active")
	}
	if p.ActiveBetween(Date(2026, 7, 1), Date(2026, 7, 14)) {
		t.Error("ended before the period")
	}
	if p.ActiveBetween(Date(2024, 1, 1), Date(2025, 3, 1)) {
		t.Error("starts on the exclusive end")
	}
	if !p.IsCurrent(Date(2026, 6, 30)) || p.IsCurrent(Date(2026, 7, 1)) {
		t.Error("IsCurrent")
	}
}

func TestNewPersonID(t *testing.T) {
	existing := map[string]bool{"joerg-mueller": true, "joerg-mueller-2": true}
	if got := NewPersonID("Jörg Müller", existing, "person"); got != "joerg-mueller-3" {
		t.Errorf("got %q", got)
	}
	if got := NewPersonID("???", nil, "person"); got != "person" {
		t.Errorf("got %q", got)
	}
	if got := NewPersonID("Weiß  Ägidius", nil, "person"); got != "weiss-aegidius" {
		t.Errorf("got %q", got)
	}
}

func TestAbsenceStatus(t *testing.T) {
	var s Sprint
	if s.AbsenceStatus() != AbsencesUnknown {
		t.Error("empty sprint")
	}
	s.ExpectedAbsences = map[string]float64{"a": 1}
	if s.AbsenceStatus() != AbsencesExpected {
		t.Error("expected")
	}
	s.Commitment = Ptr(30.0)
	if s.AbsenceStatus() != AbsencesConfirmed {
		t.Error("legacy: evaluated sprint counts as confirmed")
	}
	s.AbsenceState = Ptr(AbsencesUnknown)
	if s.AbsenceStatus() != AbsencesExpected || !s.ExplicitStateNeeded() {
		t.Error("stored state wins and must be written")
	}
	s.SetAbsencesConfirmed(true)
	if !s.AbsencesConfirmed() || s.ExplicitStateNeeded() {
		t.Error("confirmed equals the derivation, nothing to store")
	}
	s.SetAbsencesConfirmed(false)
	if s.AbsenceStatus() == AbsencesConfirmed {
		t.Error("revoked")
	}
}

func TestPlanning(t *testing.T) {
	p := Planning{Carryover: 5, Backlog: 25, Corrections: []float64{2, 1}}
	if p.Committed() != 30 || p.Total() != 27 {
		t.Errorf("%v %v", p.Committed(), p.Total())
	}
}

func TestRule(t *testing.T) {
	tk := Ticket{Epic: Ptr("E1"), Labels: []string{"Backend-Fix"}, InSprint: Ptr("2026.22")}
	facts := tk.Facts()
	leaf := func(src string, contains bool, v ...string) *Rule {
		return &Rule{Op: OpLeaf, Source: src, Values: v, Contains: contains}
	}
	cases := []struct {
		name string
		rule *Rule
		want bool
	}{
		{"epic", leaf("epic", false, "E1"), true},
		{"case sensitive", leaf("epic", false, "e1"), false},
		{"contains", leaf("label", true, "BACKEND"), true},
		{"in_sprint true", leaf("in_sprint", false, "true"), true},
		{"in_sprint id", leaf("in_sprint", false, "2026.22"), true},
		{"all", &Rule{Op: OpAll, Children: []*Rule{leaf("epic", false, "E1"), leaf("label", false, "x")}}, false},
		{"none", &Rule{Op: OpNone, Children: []*Rule{leaf("label", false, "x")}}, true},
		{"any", &Rule{Op: OpAny, Children: []*Rule{leaf("label", false, "x"), leaf("epic", false, "E1")}}, true},
	}
	for _, c := range cases {
		if got := c.rule.Matches(facts); got != c.want {
			t.Errorf("%s: got %v", c.name, got)
		}
	}
	any := &Rule{Op: OpAny, Short: true, Children: []*Rule{leaf("epic", false, "E1"), leaf("label", false, "x")}}
	if got := any.MatchedSources(facts); len(got) != 1 || !got["epic"] {
		t.Errorf("matched sources %v", got)
	}
	if got := any.LeafSources(); len(got) != 2 {
		t.Errorf("leaf sources %v", got)
	}
}

func TestTicketSize(t *testing.T) {
	tk := Ticket{Estimate: Ptr(5.0), Remaining: Ptr(2.0)}
	if *tk.Size(UsesRemaining) != 2 || *tk.Size(UsesEstimate) != 5 {
		t.Error("size")
	}
	if (Ticket{}).Size(UsesRemaining) != nil {
		t.Error("unestimated")
	}
}

func TestBaseURLProblem(t *testing.T) {
	for in, want := range map[string]string{
		"https://jira.example.com":          "",
		"https://jira.example.com/jira":     "",
		"jira.example.com":                  URLInvalid,
		"ftp://jira.example.com":            URLInvalid,
		"https://u:p@jira.example.com":      URLCredentials,
		"https://jira.example.com?x=1":      URLExtra,
		"https://jira.example.com/#top":     URLExtra,
		"https://jira.example.com:99999":    URLInvalid,
		"https://jira.example.com:8443/abc": "",
	} {
		if got := BaseURLProblem(in); got != want {
			t.Errorf("%q: got %q, want %q", in, got, want)
		}
	}
}

func TestOrderedMap(t *testing.T) {
	var m OrderedMap[string]
	m.Set("b", "1")
	m.Set("a", "2")
	m.Set("b", "3")
	if got := m.Keys(); len(got) != 2 || got[0] != "b" || got[1] != "a" {
		t.Errorf("keys %v", got)
	}
	if v, _ := m.Get("b"); v != "3" {
		t.Error("replace keeps position")
	}
	c := m.Clone()
	c.Set("b", "x")
	if v, _ := m.Get("b"); v != "3" {
		t.Error("clone shares")
	}
}

func TestProductActiveBetween(t *testing.T) {
	p := Product{Start: Ptr(Date(2026, 2, 1)), End: Ptr(Date(2026, 3, 1))}
	if p.ActiveBetween(Date(2026, 1, 1), Date(2026, 2, 1)) {
		t.Error("starts on the exclusive end")
	}
	if !p.ActiveBetween(Date(2026, 3, 1), Date(2026, 3, 15)) {
		t.Error("ends on the first day")
	}
}

func TestNewTeamDefaults(t *testing.T) {
	tm := NewTeam("k", "K")
	if tm.Forecast.TrendMode != TrendFlat || tm.Capacity.AbsenceHistory != 4 || tm.Tracker.LinkType != "Blocks" {
		t.Errorf("%+v", tm)
	}
}
