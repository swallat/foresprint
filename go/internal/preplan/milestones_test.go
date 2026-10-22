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
	// Different sprint lengths and a gap: the milestone on day 10 lies in b (7 days), c follows.
	short := []model.Sprint{
		{ID: "a", Start: day(0), End: day(7)}, {ID: "b", Start: day(7), End: day(21)}, {ID: "c", Start: day(35), End: day(49)},
	}
	dist2 := &Distribution{Placements: []Placement{{Ticket: "T-2", Sprint: sp("c"), Reason: ReasonPlaced}}}
	pr2 := model.Project{Milestones: []model.Milestone{{ID: "m", Date: day(10), Tickets: []string{"T-2", "T-2"}}}}
	if m := MilestoneStatuses(pr2, dist2, data, short)[0]; m.Light != model.LightYellow || m.Open != 1 {
		t.Errorf("gap case: %+v", m)
	}
	// A ticket in the first sprint after the known ones (dist.Later) is yellow after the last one.
	later := day(55)
	dist3 := &Distribution{Placements: []Placement{{Ticket: "T-2", Sprint: sp("z"), Reason: ReasonFixedSprint}},
		Later: map[string]*time.Time{"z": &later}}
	pr3 := model.Project{Milestones: []model.Milestone{{ID: "m", Date: day(45), Tickets: []string{"T-2"}}}}
	if m := MilestoneStatuses(pr3, dist3, data, short)[0]; m.Light != model.LightYellow {
		t.Errorf("later case: %+v", m)
	}
	// Without a distribution there is no derived light.
	if m := MilestoneStatuses(pr2, nil, data, short)[0]; m.Light != "" || m.Source != LightNone || m.Open != 1 {
		t.Errorf("no distribution: %+v", m)
	}
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
