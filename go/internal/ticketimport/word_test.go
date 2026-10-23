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
	got, changed := Reresolve([]model.Ticket{{Key: "A-1", SprintName: &name}, {Key: "A-2", SprintName: &other}, {Key: "A-3"}}, env)
	if !changed || got[0].InSprint == nil || *got[0].InSprint != "2026.21" || got[1].InSprint != nil || got[2].InSprint != nil {
		t.Fatalf("got %+v", got)
	}
	if _, again := Reresolve(got, env); again {
		t.Error("a second run must change nothing")
	}
}
