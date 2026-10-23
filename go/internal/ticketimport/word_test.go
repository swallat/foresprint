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
	} {
		got := ResolveSprint(name, tr, sprints)
		if (got == nil) != (want == "") || (got != nil && *got != want) {
			t.Errorf("%q: got %v, want %q", name, got, want)
		}
	}
}
