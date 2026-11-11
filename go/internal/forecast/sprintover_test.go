package forecast

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// A started sprint is not over on its last day: it runs until its Review is closed.
func TestSprintOverRunningOnLastDay(t *testing.T) {
	day := func(d int) time.Time { return time.Date(2026, 11, d, 0, 0, 0, 0, time.UTC) }
	started := day(1)
	data := &storage.TeamData{Sprints: []model.Sprint{{ID: "2026.21", Start: day(1), End: day(11), StartedOn: &started}}}
	if over, ok := SprintOver(data, "2026.21", day(11)); !ok || over {
		t.Errorf("last day: over=%v ok=%v, want running", over, ok)
	}
	data.Sprints[0].StartedOn = nil
	data.Sprints[0].StartPending = true
	if over, ok := SprintOver(data, "2026.21", day(11)); !ok || !over {
		t.Errorf("never started: over=%v ok=%v, want past", over, ok)
	}
}
