package storage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/model"
)

// idempotent checks that what is written reads back to the same text.
func idempotent(t *testing.T, kind, text string) string {
	t.Helper()
	first, err := roundTrip(kind, loadMap(t, text))
	if err != nil {
		t.Fatalf("%s: %v", kind, err)
	}
	second, err := roundTrip(kind, loadMap(t, first))
	if err != nil {
		t.Fatalf("%s again: %v", kind, err)
	}
	if first != second {
		t.Errorf("%s is not stable:\n%s\n---\n%s", kind, first, second)
	}
	return first
}

const v1Team = `name: Atlas
unit: SP
features: {products: true, po: true, production: true, tickets: true, projects: true}
sprint:
  length_days: 14
  numbering: yearly
  naming:
    - pattern: "S{JJ}-{NN}"
    - from: "2026.5"
      pattern: "{JJJJ}/{N} KW{KW}"
  pro_forma: [Refinement, Spikes]
estimation:
  factor: 1.5
  changes:
    - {from: "2026.9", unit: PT, factor: 2}
tracker:
  kind: packages
  package_prefix: AP
  production_label: prod-only
  production_rules:
    - match: {component: [Betrieb]}
      share: 100
    - match: {label: [ops]}
      share: 40
  write_sprint: true
  removed_target: pro_forma
  fields: {estimate: Punkte, status: Status, acceptance: Kriterien, product: Produkt, project: Vorhaben, refined: Bereit, production: Anteil}
`

func TestTeamV1Fields(t *testing.T) {
	m := loadMap(t, v1Team)
	team, err := TeamFromDict("atlas", m, where)
	if err != nil {
		t.Fatal(err)
	}
	if team.Source() != model.SourcePackages || !team.Features.Projects {
		t.Errorf("source %v projects %v", team.Source(), team.Features.Projects)
	}
	if len(team.Sprint.Naming) != 2 || team.Sprint.Naming[1].From == nil || *team.Sprint.Naming[1].From != "2026.5" {
		t.Errorf("naming %+v", team.Sprint.Naming)
	}
	if got := strings.Join(team.Sprint.ProForma, ","); got != "Refinement,Spikes" {
		t.Errorf("pro forma %q", got)
	}
	e := team.Estimation
	if e.Factor == nil || *e.Factor != 1.5 || len(e.Changes) != 1 || e.Changes[0].Unit != model.UnitPT || *e.Changes[0].Factor != 2 {
		t.Errorf("estimation %+v", e)
	}
	tr := team.Tracker
	if len(tr.ProductionRules) != 2 || tr.ProductionRules[1].Percent != 40 || !tr.WriteSprint ||
		tr.RemovedTarget != "pro_forma" || tr.PackagePrefix != "AP" || *tr.ProductionLabel != "prod-only" ||
		*tr.Fields.Production != "Anteil" || *tr.Fields.Acceptance != "Kriterien" {
		t.Errorf("tracker %+v", tr)
	}
	out := idempotent(t, "team", v1Team)
	for _, want := range []string{"naming:", "pro_forma:", "estimation:", "production_rules:", "removed_target: pro_forma"} {
		if !strings.Contains(out, want) {
			t.Errorf("written team lacks %q:\n%s", want, out)
		}
	}
}

func TestTeamV1Errors(t *testing.T) {
	for name, c := range map[string]struct{ text, want string }{
		"placeholder": {"sprint:\n  naming:\n    - pattern: \"{XX}\"\n", "unknown placeholder {XX}"},
		"share":       {"features: {tickets: true}\ntracker:\n  production_rules:\n    - {match: {label: [a]}, share: 150}\n", "between 0 and 100"},
		"factor":      {"estimation:\n  factor: 0\n", "greater than 0"},
		"removed":     {"features: {tickets: true}\ntracker:\n  removed_target: elsewhere\n", "removed_target"},
	} {
		if _, err := TeamFromDict("t", loadMap(t, c.text), where); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestPeopleKindAndAbsences(t *testing.T) {
	people := `people:
- id: anna
  name: Anna
  kind: guest
  memberships:
  - {from: 2026-01-01, to: 2026-03-31, fte: 0.5}
- id: ben
  name: Ben
  memberships:
  - {from: 2026-01-01, to: null, fte: 1.0}
`
	v, err := PeopleFromDict(loadMap(t, people), where)
	if err != nil || v[0].Kind != model.KindGuest || v[1].Kind != model.KindMember {
		t.Fatalf("%+v %v", v, err)
	}
	out := idempotent(t, "people", people)
	if strings.Count(out, "kind:") != 1 {
		t.Errorf("member must not be written with a kind:\n%s", out)
	}
	if _, err := PeopleFromDict(loadMap(t, "people:\n- {id: x, kind: contractor}\n"), where); err == nil {
		t.Error("unknown kind accepted")
	}

	text := `schema: 1
absences:
  anna:
  - {from: 2026-07-20, to: 2026-07-24}
  - {from: 2026-07-06, to: 2026-07-10, confirmed: true}
`
	a, err := AbsencesFromDict(loadMap(t, text), where)
	if err != nil {
		t.Fatal(err)
	}
	list, _ := a.Get("anna")
	if len(list) != 2 || !list[1].Confirmed || list[0].Confirmed {
		t.Fatalf("%+v", list)
	}
	written := DumpYAML(AbsencesToDict(a))
	if strings.Index(written, "2026-07-06") > strings.Index(written, "2026-07-20") {
		t.Errorf("periods not sorted:\n%s", written)
	}
	for _, reason := range []string{"reason", "type", "kind"} {
		if strings.Contains(written, reason) {
			t.Errorf("absence file carries %q:\n%s", reason, written)
		}
	}
	if _, err := AbsencesFromDict(loadMap(t, "absences:\n  anna:\n  - {from: 2026-07-10, to: 2026-07-06}\n"), where); err == nil {
		t.Error("period ending before it starts accepted")
	}
}

func TestProjectsV1(t *testing.T) {
	text := `schema: 1
projects:
- id: p1
  name: Portal
  products: [web, app]
  target: 2026-12-01
  priority: 0
  start: 2026-02-01
  state: finished
  end: 2026-11-15
  open_scope: 12
  milestones:
  - {id: m1, name: Beta, date: 2026-06-01, tickets: [AP-1, AP-2]}
  contingent:
    total: 40
    per_month: {2026-07: 10, 2026-08: 12.5}
  match: {epic: [E1]}
`
	d := loadMap(t, text)
	projects, err := ProjectsFromDict(d, where)
	if err != nil {
		t.Fatal(err)
	}
	p := projects[0]
	if p.Product == nil || *p.Product != "web" || len(p.AlsoProducts) != 1 || strings.Join(p.Products(), ",") != "web,app" ||
		!p.Closed() || p.State != model.ProjectFinished || *p.OpenScope != 12 ||
		len(p.Milestones) != 1 || len(p.Milestones[0].Tickets) != 2 ||
		*p.Contingent.Total != 40 || p.Contingent.PerMonth.Len() != 2 {
		t.Fatalf("%+v", p)
	}
	first := DumpYAML(ProjectsToDict(projects))
	again, err := ProjectsFromDict(loadMap(t, first), where)
	if err != nil || DumpYAML(ProjectsToDict(again)) != first {
		t.Errorf("not stable: %v\n%s", err, first)
	}
	// One product is still written as in 0.8.
	one := []model.Project{{ID: "x", Name: "X", Product: model.Ptr("web")}}
	if out := DumpYAML(ProjectsToDict(one)); !strings.Contains(out, "product: web") || strings.Contains(out, "products:") {
		t.Errorf("single product:\n%s", out)
	}
}

func TestPackagesAndPreplanV1(t *testing.T) {
	text := `schema: 1
tickets:
- key: AP-1
  title: Login
  status: Open
  issue_type: Story
  estimate: 3
  estimate_source: manual
  description: Let users sign in
  acceptance: Works with SSO
  assignee: Anna
  product: web
  subtasks:
  - {title: Design, done: true}
  - {title: Build}
  comments:
  - {author: Ben, at: 2026-07-01T10:00:00, text: Looks fine}
`
	f, err := TicketsFromDict(loadMap(t, text), where)
	if err != nil {
		t.Fatal(err)
	}
	tk := f.Tickets[0]
	if *tk.Description != "Let users sign in" || *tk.Product != "web" || len(tk.Subtasks) != 2 || !tk.Subtasks[0].Done ||
		len(tk.Comments) != 1 || tk.Comments[0].At == nil {
		t.Fatalf("%+v", tk)
	}
	first := DumpYAML(TicketsToDict(f))
	f2, err := TicketsFromDict(loadMap(t, first), where)
	if err != nil || DumpYAML(TicketsToDict(f2)) != first {
		t.Errorf("not stable: %v\n%s", err, first)
	}

	pre := `schema: 1
earmarks: []
estimates: []
production:
- {ticket: AP-1, share: 60, note: nightly job}
overrides:
- {ticket: AP-1, product: app, project: p1}
- {ticket: AP-2, daily: true}
`
	pp, err := PreplanFromDict(loadMap(t, pre), where)
	if err != nil {
		t.Fatal(err)
	}
	if s := pp.ProductionFor("AP-1"); s == nil || s.Percent != 60 {
		t.Errorf("production %+v", pp.Production)
	}
	if o := pp.OverrideFor("AP-2"); o == nil || !o.Daily || pp.OverrideFor("AP-9") != nil {
		t.Errorf("overrides %+v", pp.Overrides)
	}
	out := DumpYAML(PreplanToDict(pp))
	pp2, err := PreplanFromDict(loadMap(t, out), where)
	if err != nil || DumpYAML(PreplanToDict(pp2)) != out {
		t.Errorf("not stable: %v\n%s", err, out)
	}
	if bad := "production:\n- {ticket: A, share: -1}\n"; true {
		if _, err := PreplanFromDict(loadMap(t, bad), where); err == nil {
			t.Error("negative share accepted")
		}
	}
}

func TestSprintV1(t *testing.T) {
	text := `id: "2026.8"
start: 2026-07-06
end: 2026-07-19
absences: {}
name: Summer sprint
committed_tickets: [AP-1, AP-2]
carry:
- {ticket: AP-3, rest: 2, target: backlog}
- {ticket: AP-4, rest: 1.5}
rest_next: 3
projects:
  p1: {planned: 5, done: 4}
prognoses:
- at: 2026-07-01T09:00:00
  label: A
  finish: [AP-1]
  carry:
  - {ticket: AP-3, rest: 2, target: "2026.10"}
  rest_next: 1
`
	s, err := SprintFromDict(loadMap(t, text), where)
	if err != nil {
		t.Fatal(err)
	}
	if *s.Name != "Summer sprint" || len(s.CommittedTickets) != 2 || len(s.Carry) != 2 || s.Carry[0].Target != model.CarryBacklog ||
		*s.RestNext != 3 || *s.Projects["p1"].Planned != 5 || *s.Prognoses[0].Label != "A" ||
		s.Prognoses[0].Carry[0].Target != "2026.10" || *s.Prognoses[0].RestNext != 1 || s.Prognoses[0].Finish[0] != "AP-1" {
		t.Fatalf("%+v", s)
	}
	idempotent(t, "sprint", text)
	c := s.Clone()
	c.Carry[0].Rest = 99
	c.CommittedTickets[0] = "X"
	if s.Carry[0].Rest == 99 || s.CommittedTickets[0] == "X" {
		t.Error("Clone shares slices")
	}
}

func TestRepositoryV1(t *testing.T) {
	repo := NewRepository(t.TempDir())
	team := model.NewTeam("atlas", "Atlas")
	team.Features.Tickets = true
	team.Features.Projects = true
	team.Tracker.Kind = model.PackagesKind
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SavePackages("atlas", TicketsFile{Tickets: []model.Ticket{{Key: "AP-1", Title: "Login", EstimateSource: model.EstimateNone}}}); err != nil {
		t.Fatal(err)
	}
	var abs model.Absences
	abs.Set("anna", []model.AbsencePeriod{{From: model.Date(2026, 7, 6), To: model.Date(2026, 7, 10)}})
	if _, err := repo.SaveAbsences("atlas", abs); err != nil {
		t.Fatal(err)
	}
	data, err := repo.Load("atlas")
	if err != nil || len(data.Tickets) != 1 || data.Tickets[0].Key != "AP-1" || data.AbsencePeriods.Len() != 1 {
		t.Fatalf("%+v %v", data, err)
	}
	if TicketFileName(data.Team) != "arbeitspakete.yaml" {
		t.Error("ticket file name")
	}
	// Projects without tickets: read because of features.projects.
	team.Features.Tickets = false
	team.Tracker = model.NewTrackerSettings()
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	if _, err := repo.SaveProjects("atlas", []model.Project{{ID: "p1", Name: "P"}}); err != nil {
		t.Fatal(err)
	}
	data, err = repo.Load("atlas")
	if err != nil || len(data.Projects) != 1 || len(data.Tickets) != 0 {
		t.Fatalf("%+v %v", data, err)
	}
	team.Features.Projects = false
	if _, err := repo.SaveTeam(team); err != nil {
		t.Fatal(err)
	}
	if data, _ = repo.Load("atlas"); len(data.Projects) != 0 {
		t.Error("projects read although the feature is off")
	}
	if _, err := os.Stat(filepath.Join(repo.Root, "atlas", "abwesenheiten.yaml")); err != nil {
		t.Error(err)
	}
}

func TestCloneCopiesPrognosisLists(t *testing.T) {
	s := model.Sprint{Prognoses: []model.Prognosis{{Finish: []string{"A"}, Carry: []model.CarryItem{{Rest: 1}}}}}
	c := s.Clone()
	c.Prognoses[0].Finish[0] = "B"
	c.Prognoses[0].Carry[0].Rest = 2
	if s.Prognoses[0].Finish[0] != "A" || s.Prognoses[0].Carry[0].Rest != 1 {
		t.Error("Clone shares the lists of a prognosis")
	}
}

func TestAbsenceCellsRoundTrip(t *testing.T) {
	// 1.0: confirmed and announced cells side by side in an open sprint.
	open := "id: s1\nstart: 2026-01-05\nend: 2026-01-19\nabsences:\n  anna: 2\nabsence_state: open\nexpected_absences:\n  ben: 1\n"
	d := loadMap(t, open)
	s, err := SprintFromDict(d, where)
	if err != nil {
		t.Fatal(err)
	}
	if s.AbsenceStatus() != model.AbsencesExpected || s.CellState("anna") != model.AbsencesConfirmed || s.CellState("ben") != model.AbsencesExpected {
		t.Fatalf("read: %v %v %v", s.AbsenceStatus(), s.CellState("anna"), s.CellState("ben"))
	}
	out := idempotent(t, "sprint", open)
	if !strings.Contains(out, "absence_state: open") {
		t.Errorf("the open state is not written:\n%s", out)
	}
	// Announced cells only need no stored state: the file is the 0.8 form.
	only := "id: s1\nstart: 2026-01-05\nend: 2026-01-19\nabsences: {}\nexpected_absences:\n  ben: 1\n"
	if out := idempotent(t, "sprint", only); strings.Contains(out, "absence_state") {
		t.Errorf("announced-only sprint got a state:\n%s", out)
	}
	// A 0.8 file with absences stays a frozen sprint and is written back without a state.
	legacy := "id: s1\nstart: 2026-01-05\nend: 2026-01-19\nabsences:\n  anna: 2\n"
	if out := idempotent(t, "sprint", legacy); strings.Contains(out, "absence_state") {
		t.Errorf("legacy sprint got a state:\n%s", out)
	}
	ls, _ := SprintFromDict(loadMap(t, legacy), where)
	if ls.CellState("ben") != model.AbsencesConfirmed {
		t.Errorf("legacy sprint is not frozen: %v", ls.CellState("ben"))
	}
}
