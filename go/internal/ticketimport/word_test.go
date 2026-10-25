package ticketimport

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
)

type knownSprints map[string]bool

func (k knownSprints) End(id string) (time.Time, bool) { return time.Time{}, k[id] }

func TestResolveSprintFindsTheIdAsWord(t *testing.T) {
	sprints := knownSprints{"3": true, "45": true, "2026.20": true, "2026.21": true}
	tr := model.TrackerSettings{}
	for name, want := range map[string]string{
		"Team Sprint 2026.20":    "2026.20",
		"2026.21":                "2026.21",
		"Wave 2026.200":          "",
		"Sprint 2026.20/2026.21": "",
		"Board 3 Iteration":      "",
		"Release 45":             "",
		"Sprint ohne Nummer":     "",
		"Team Sprint 3":          "3",
		"Team Sprint 4":          "",
		"Team Sprint 3.1":        "",
	} {
		got := ResolveSprint(name, tr, sprints)
		if (got == nil) != (want == "") || (got != nil && *got != want) {
			t.Errorf("%q: got %v, want %q", name, got, want)
		}
	}
}

func TestReresolveAppliesAChangedSprintTable(t *testing.T) {
	var names model.OrderedMap[string]
	names.Set("Old board 1", "2026.21")
	env := Env{Tracker: model.TrackerSettings{SprintNames: names}, Sprints: knownSprints{"2026.20": true, "2026.21": true}, Today: time.Time{}.Add(-time.Hour)}
	name, other := "Old board 1", "Elsewhere"
	pp := model.Preplan{Earmarks: []model.Earmark{{Ticket: "A-1", Sprint: "2026.20"}}}
	got, pp, changed := Reresolve([]model.Ticket{{Key: "A-1", SprintName: &name}, {Key: "A-2", SprintName: &other}, {Key: "A-3"}}, pp, env)
	if !changed || got[0].InSprint == nil || *got[0].InSprint != "2026.21" || got[1].InSprint != nil || got[2].InSprint != nil || len(pp.Earmarks) != 0 {
		t.Fatalf("got %+v", got)
	}
	if _, _, again := Reresolve(got, pp, env); again {
		t.Error("a second run must change nothing")
	}
}

func TestResolveSprintExactIgnoresBareNumbers(t *testing.T) {
	sprints := knownSprints{"3": true, "2026.20": true}
	var names model.OrderedMap[string]
	names.Set("BV Sprint 33", "2026.20")
	tr := model.TrackerSettings{SprintNames: names}
	for name, want := range map[string]string{
		"2026.20":             "2026.20",
		"Team Sprint 2026.20": "2026.20",
		"BV Sprint 33":        "2026.20",
		"3":                   "3",
		"Other Team Sprint 3": "",
		"Release 45":          "",
	} {
		got := ResolveSprintExact(name, tr, sprints)
		if (got == nil) != (want == "") || (got != nil && *got != want) {
			t.Errorf("%q: got %v, want %q", name, got, want)
		}
	}
}

func TestResolveSprintMatchesWithOrWithoutLeadingZero(t *testing.T) {
	tr := model.TrackerSettings{}
	padded := knownSprints{"2027.01": true, "2027.03": true, "2027.10": true}
	for name, want := range map[string]string{
		"AccSecc - BV Sprint 2027.3": "2027.03",
		"Team Sprint 2027.03":        "2027.03",
		"Team Sprint 2027.10":        "2027.10",
		"Team Sprint 2027.2":         "",
		"Team Sprint 2027.0":         "",
	} {
		got := ResolveSprint(name, tr, padded)
		if (got == nil) != (want == "") || (got != nil && *got != want) {
			t.Errorf("%q: got %v, want %q", name, got, want)
		}
	}
	plain := knownSprints{"2027.3": true}
	if got := ResolveSprint("BV Sprint 2027.03", tr, plain); got == nil || *got != "2027.3" {
		t.Errorf("a padded name for an unpadded calendar: %v", got)
	}
}
