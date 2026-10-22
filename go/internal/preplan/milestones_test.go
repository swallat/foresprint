package preplan

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

func TestMilestoneStatuses(t *testing.T) {
	day := func(n int) time.Time { return time.Date(2026, 3, 1+n, 0, 0, 0, 0, time.UTC) }
	sprints := []model.Sprint{
		{ID: "a", Start: day(0), End: day(14)},
		{ID: "b", Start: day(14), End: day(28)},
		{ID: "c", Start: day(28), End: day(42)},
		{ID: "d", Start: day(42), End: day(56)},
	}
	data := &storage.TeamData{}
	data.Tickets = []model.Ticket{{Key: "T-1"}, {Key: "T-2"}, {Key: "T-3", Done: true}, {Key: "T-4"}}
	dist := &Distribution{Placements: []Placement{
		{Ticket: "T-1", Sprint: sp("a"), Reason: ReasonPlaced},
		{Ticket: "T-2", Sprint: sp("c"), Reason: ReasonPlaced},
		{Ticket: "T-4", Reason: ReasonUnestimated},
	}, Later: map[string]*time.Time{}}
	pr := model.Project{Milestones: []model.Milestone{
		{ID: "ok", Date: day(14), Tickets: []string{"T-1", "T-3"}},
		{ID: "yellow", Date: day(20), Tickets: []string{"T-1", "T-2"}},
		{ID: "red", Date: day(20), Tickets: []string{"T-4"}},
		{ID: "hand", Date: day(20), Tickets: []string{"T-4"}, Light: model.LightGreen},
		{ID: "none", Date: day(20)},
	}}
	got := map[string]MilestoneStatus{}
	for _, m := range MilestoneStatuses(pr, dist, data, sprints) {
		got[m.ID] = m
	}
	want := map[string][2]string{
		"ok": {model.LightGreen, LightDerived}, "yellow": {model.LightYellow, LightDerived},
		"red": {model.LightRed, LightDerived}, "hand": {model.LightGreen, LightByHand}, "none": {"", LightNone},
	}
	for id, w := range want {
		if got[id].Light != w[0] || got[id].Source != w[1] {
			t.Errorf("%s: %+v, want %v", id, got[id], w)
		}
	}
}

func TestContingentStatusOf(t *testing.T) {
	c := model.Contingent{Total: model.Ptr(40.0)}
	c.UsedPerMonth.Set("2026-07", 20)
	c.UsedPerMonth.Set("2026-08", 15)
	c.PerMonth.Set("2026-07", 20)
	st := ContingentStatusOf(c)
	if *st.Used != 35 || *st.Remaining != 5 || st.Status != "tight" || len(st.Months) != 2 {
		t.Fatalf("%+v", st)
	}
	if st.Months[0].Month != "2026-07" || *st.Months[0].Remaining != 0 || st.Months[0].Status != "tight" {
		t.Fatalf("%+v", st.Months)
	}
	over := ContingentStatusOf(model.Contingent{Total: model.Ptr(10.0), Used: model.Ptr(11.0)})
	if over.Status != "over" {
		t.Fatalf("%+v", over)
	}
}
