package ticketimport

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/sources"
)

type phasedSprints struct {
	end  time.Time
	over bool
}

func (p phasedSprints) End(string) (time.Time, bool) { return p.end, true }
func (p phasedSprints) Over(string) (bool, bool)     { return p.over, true }

// A sprint stays running after its last day until its Review is closed: a ticket of it keeps the
// sprint on a fetch made on the last day.
func TestConvertKeepsRunningSprintAfterItsEnd(t *testing.T) {
	today := time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	raw := sources.RawTicket{Key: "A-1", SprintName: "2026.21"}
	for _, c := range []struct {
		over bool
		want bool
	}{{false, true}, {true, false}} {
		env := Env{Sprints: phasedSprints{end: today, over: c.over}, Today: today}
		if got := Convert(raw, env).InSprint != nil; got != c.want {
			t.Errorf("over=%v: sprint kept = %v, want %v", c.over, got, c.want)
		}
	}
}
