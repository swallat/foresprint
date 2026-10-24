package app

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// demoCopy copies the demo team into a temporary data folder, so tests can write.
func demoCopy(t *testing.T) (*API, string) {
	t.Helper()
	src := demoDir(t)
	dst := t.TempDir()
	err := filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, path)
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	api := newAPI(t, dst)
	api.Now = func() time.Time { return time.Date(2026, 10, 22, 12, 0, 0, 0, time.UTC) }
	return api, api.Teams()[0].Key
}

func TestPeopleRoundTrip(t *testing.T) {
	api, team := demoCopy(t)
	view, err := api.People(team)
	if err != nil {
		t.Fatal(err)
	}
	if len(view.People) == 0 || view.SprintDays == 0 {
		t.Fatalf("view = %+v", view)
	}
	before, _ := os.ReadFile(filepath.Join(api.DataDir(), team, "people.yaml"))
	again, err := api.SavePeople(team, view.People)
	if err != nil {
		t.Fatal(err)
	}
	after, _ := os.ReadFile(filepath.Join(api.DataDir(), team, "people.yaml"))
	if string(before) != string(after) {
		t.Errorf("saving without a change rewrote the file:\n%s\n---\n%s", before, after)
	}
	if len(again.People) != len(view.People) {
		t.Errorf("people = %d, want %d", len(again.People), len(view.People))
	}
}

func TestSavePeopleNewPersonAndChecks(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.People(team)
	list := append([]PersonDTO{}, view.People...)
	list = append(list, PersonDTO{Name: " Sam Beispiel ", Kind: "guest", Memberships: []MembershipDTO{{From: "2026-11-01", FTE: 0.5}}})
	got, err := api.SavePeople(team, list)
	if err != nil {
		t.Fatal(err)
	}
	added := got.People[len(got.People)-1]
	if added.ID != "sam-beispiel" || added.Name != "Sam Beispiel" || added.Kind != "guest" || added.Used {
		t.Errorf("added = %+v", added)
	}

	bad := []PersonDTO{{Name: "X", Memberships: []MembershipDTO{{From: "2026-01-01", FTE: 1.5}}}}
	if _, err := api.SavePeople(team, bad); err == nil {
		t.Error("an FTE above 1 was accepted")
	}
	overlap := []PersonDTO{{Name: "X", Memberships: []MembershipDTO{{From: "2026-01-01", To: "2026-06-30", FTE: 1}, {From: "2026-06-30", FTE: 1}}}}
	if _, err := api.SavePeople(team, overlap); err == nil || !strings.Contains(err.Error(), "overlap") {
		t.Errorf("overlap: %v", err)
	}
}

func TestSavePeopleRefusesToRemoveSomeoneWithHistory(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.People(team)
	var used string
	for _, p := range view.People {
		if p.Used {
			used = p.ID
		}
	}
	if used == "" {
		t.Skip("no used person in the demo team")
	}
	var rest []PersonDTO
	for _, p := range view.People {
		if p.ID != used {
			rest = append(rest, p)
		}
	}
	if _, err := api.SavePeople(team, rest); err == nil {
		t.Fatal("a person with history was removed")
	}
}

func TestAbsencePeriods(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.People(team)
	id := view.People[0].ID
	list := []AbsencePeriodDTO{{Person: id, From: "2026-12-14", To: "2027-01-08"}, {Person: id, From: "2026-11-02", To: "2026-11-03", Confirmed: true}}
	got, err := api.SaveAbsencePeriods(team, list)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].From != "2026-11-02" || !got[0].Confirmed {
		t.Errorf("saved = %+v", got)
	}
	data, _ := os.ReadFile(filepath.Join(api.DataDir(), team, "abwesenheiten.yaml"))
	if strings.Contains(string(data), "reason:") || strings.Contains(string(data), "type:") {
		t.Errorf("file holds a kind of absence:\n%s", data)
	}
	if _, err := api.SaveAbsencePeriods(team, []AbsencePeriodDTO{{Person: id, From: "2026-11-02", To: "2026-11-05"}, {Person: id, From: "2026-11-05", To: "2026-11-06"}}); err == nil {
		t.Error("overlapping absences accepted")
	}
	if _, err := api.SaveAbsencePeriods(team, []AbsencePeriodDTO{{Person: "nobody", From: "2026-11-02", To: "2026-11-05"}}); err == nil {
		t.Error("unknown person accepted")
	}
	again, _ := api.AbsencePeriods(team)
	if len(again) != 2 {
		t.Errorf("read back = %+v", again)
	}
}

func TestRemovingAPersonDropsTheirAbsencesAndUndoStepIsForgotten(t *testing.T) {
	api, team := demoCopy(t)
	view, _ := api.People(team)
	if len(view.People) < 2 {
		t.Skip("demo team too small")
	}
	// Someone without history in a sprint: a new person with a future absence.
	view.People = append(view.People, PersonDTO{Name: "Zora Neu", Kind: "member", Memberships: []MembershipDTO{{From: "2027-03-01", FTE: 1}}})
	view, err := api.SavePeople(team, view.People)
	if err != nil {
		t.Fatal(err)
	}
	var zora PersonDTO
	for _, p := range view.People {
		if p.Name == "Zora Neu" {
			zora = p
		}
	}
	if _, err := api.SaveAbsencePeriods(team, []AbsencePeriodDTO{{Person: zora.ID, From: "2027-03-02", To: "2027-03-03"}}); err != nil {
		t.Fatal(err)
	}
	var rest []PersonDTO
	for _, p := range view.People {
		if p.ID != zora.ID {
			rest = append(rest, p)
		}
	}
	if _, err := api.SavePeople(team, rest); err != nil {
		t.Fatal(err)
	}
	left, _ := api.AbsencePeriods(team)
	for _, a := range left {
		if a.Person == zora.ID {
			t.Errorf("absence of a removed person stays: %+v", a)
		}
	}
	if _, err := api.SaveAbsencePeriods(team, left); err != nil {
		t.Errorf("saving the absences fails after the removal: %v", err)
	}
}

func TestPersonOwnHolidayRegion(t *testing.T) {
	api, team := copyDemoTeam(t)
	view, err := api.People(team)
	if err != nil {
		t.Fatal(err)
	}
	if view.Country == "" {
		t.Error("the view names no country of the team")
	}
	list := view.People
	list[0].Country, list[0].Region = "AT", "9"
	got, err := api.SavePeople(team, list)
	if err != nil {
		t.Fatal(err)
	}
	if got.People[0].Country != "AT" || got.People[0].Region != "9" {
		t.Errorf("person = %+v", got.People[0])
	}
	list = got.People
	list[0].Region = "ZZ"
	if _, err := api.SavePeople(team, list); err == nil {
		t.Error("an unknown region was accepted")
	}
	list[0].Country, list[0].Region = "", ""
	got, err = api.SavePeople(team, list)
	if err != nil || got.People[0].Country != "" {
		t.Errorf("reset: %v %+v", err, got.People[0])
	}
}

func TestNewMemberJoinsAtTheStartOfTheFirstSprint(t *testing.T) {
	team := model.NewTeam("t", "T")
	id, start := "2026.16", time.Date(2026, 10, 20, 0, 0, 0, 0, time.UTC)
	team.Sprint.FirstID, team.Sprint.FirstStart = &id, &start
	data := &storage.TeamData{Team: team}
	at := func(y int, m time.Month, d int) *API {
		return &API{Now: func() time.Time { return time.Date(y, m, d, 12, 0, 0, 0, time.UTC) }}
	}
	if got := at(2026, 10, 24).peopleNewMemberDay(data); !got.Equal(start) {
		t.Errorf("in the first sprint: %v, want its start", got)
	}
	later := time.Date(2026, 11, 10, 0, 0, 0, 0, time.UTC)
	if got := at(2026, 11, 10).peopleNewMemberDay(data); !got.Equal(later) {
		t.Errorf("after the first sprint: %v, want today", got)
	}
}
