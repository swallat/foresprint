package preplan

import (
	"slices"
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/planning"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/storage"
)

// Where a milestone light comes from.
const (
	LightByHand  = "hand"
	LightDerived = "derived"
	LightNone    = "none"
)

// MilestoneStatus is the light of a milestone: the one the PO set by hand, else derived from
// the distribution of its tickets (decision: milestone = date + optional tickets/light).
type MilestoneStatus struct {
	ID    string    `json:"id"`
	Name  string    `json:"name"`
	Date  time.Time `json:"date"`
	Light string    `json:"light"` // green, yellow, red; empty = none
	// Source is LightByHand, LightDerived or LightNone (no hand value and no open tickets).
	Source string `json:"source"`
	// Open are the milestone's tickets not yet done; Late those of them that the distribution
	// places after the date, or cannot place.
	Open int      `json:"open"`
	Late []string `json:"late"`
}

// MilestoneStatuses evaluates the milestones of a project. sprints are all known sprints (past,
// current and horizon), so that tickets in the running sprint resolve too. Derived light: green
// when every open ticket ends on or before the date; yellow when the late ones are in the sprint
// right after the one holding the date; red otherwise (also for tickets that cannot be placed or
// lie beyond the known sprints). Done tickets do not count; unknown ticket keys are ignored (the
// check reports them). Without a distribution there is no derived light.
func MilestoneStatuses(project model.Project, dist *Distribution, data *storage.TeamData, sprints []model.Sprint) []MilestoneStatus {
	sprints = slices.Clone(sprints)
	slices.SortStableFunc(sprints, func(a, b model.Sprint) int { return a.Start.Compare(b.Start) })
	order := map[string]int{}
	for i, s := range sprints {
		order[s.ID] = i
	}
	placement := map[string]Placement{}
	if dist != nil {
		for _, p := range dist.Placements {
			placement[p.Ticket] = p
		}
	}
	done := map[string]bool{}
	known := map[string]bool{}
	if data != nil {
		for _, tk := range data.Tickets {
			known[tk.Key] = true
			done[tk.Key] = tk.Done
		}
	}
	var out []MilestoneStatus
	for _, m := range project.Milestones {
		st := MilestoneStatus{ID: m.ID, Name: m.Name, Date: m.Date, Source: LightNone, Late: []string{}}
		// holding is the sprint with the date in it (the last one before it if none holds it).
		holding := -1
		for i, s := range sprints {
			if s.Start.After(m.Date) {
				break
			}
			holding = i
		}
		worst := 0 // 0 green, 1 yellow, 2 red
		seen := map[string]bool{}
		for _, key := range m.Tickets {
			if seen[key] || !known[key] || done[key] {
				continue
			}
			seen[key] = true
			st.Open++
			p, ok := placement[key]
			i, inList := -1, false
			if ok && p.Sprint != nil {
				i, inList = order[*p.Sprint]
			}
			switch {
			case !inList:
				st.Late = append(st.Late, key)
				// The first sprint after the known ones is the one right after the last of them.
				if _, later := laterOf(dist, p.Sprint); later && holding == len(sprints)-1 && holding >= 0 {
					worst = max(worst, 1)
				} else {
					worst = 2
				}
			case sprints[i].End.After(m.Date.Add(day)): // the sprint ends after the milestone day
				st.Late = append(st.Late, key)
				if holding >= 0 && i == holding+1 {
					worst = max(worst, 1)
				} else {
					worst = max(worst, 2)
				}
			}
		}
		sort.Strings(st.Late)
		if st.Open > 0 && dist != nil {
			st.Source = LightDerived
			st.Light = [...]string{model.LightGreen, model.LightYellow, model.LightRed}[worst]
		}
		if m.Light != "" {
			st.Light, st.Source = m.Light, LightByHand
		}
		out = append(out, st)
	}
	return out
}

// ContingentStatus is the consumption of a project's contingent (person days, booked by hand).
type ContingentStatus struct {
	Total     *float64 `json:"total"`
	Used      *float64 `json:"used"`
	Remaining *float64 `json:"remaining"`
	// Load is Used / Total; nil without a total (or a total of 0).
	Load   *float64        `json:"load"`
	Status planning.Status `json:"status"`
	// Months lists every month with a contingent or a consumption, oldest first.
	Months []MonthStatus `json:"months"`
}

// MonthStatus is the same for one month ("2026-07").
type MonthStatus struct {
	Month     string          `json:"month"`
	Booked    *float64        `json:"booked"`
	Used      *float64        `json:"used"`
	Remaining *float64        `json:"remaining"`
	Status    planning.Status `json:"status"`
}

func statusOf(used, total *float64) (planning.Status, *float64) {
	if total == nil {
		return planning.StatusOK, nil
	}
	u := 0.0
	if used != nil {
		u = *used
	}
	if *total <= 0 {
		if u > 0 {
			return planning.StatusOver, nil
		}
		return planning.StatusOK, nil
	}
	load := u / *total
	switch {
	case load > planning.OverAbove:
		return planning.StatusOver, &load
	case load > planning.TightAbove:
		return planning.StatusTight, &load
	}
	return planning.StatusOK, &load
}

func remainingOf(used, total *float64) *float64 {
	if total == nil {
		return nil
	}
	u := 0.0
	if used != nil {
		u = *used
	}
	r := *total - u
	return &r
}

// ContingentStatusOf evaluates the contingent: tight above 80 % consumed, over above 100 %. The
// used total is the entered total, else the sum of the monthly values. A hint, it never blocks.
func ContingentStatusOf(c model.Contingent) ContingentStatus {
	used := c.Used
	if used == nil && c.UsedPerMonth.Len() > 0 {
		var parts []float64
		for _, e := range c.UsedPerMonth.Entries {
			parts = append(parts, e.Value)
		}
		sum := pymath.Sum(parts)
		used = &sum
	}
	st := ContingentStatus{Total: c.Total, Used: used, Remaining: remainingOf(used, c.Total), Months: []MonthStatus{}}
	st.Status, st.Load = statusOf(used, c.Total)
	months := map[string]*MonthStatus{}
	add := func(key string) *MonthStatus {
		if m := months[key]; m != nil {
			return m
		}
		m := &MonthStatus{Month: key}
		months[key] = m
		return m
	}
	for _, e := range c.PerMonth.Entries {
		v := e.Value
		add(e.Key).Booked = &v
	}
	for _, e := range c.UsedPerMonth.Entries {
		v := e.Value
		add(e.Key).Used = &v
	}
	for _, m := range months {
		m.Remaining = remainingOf(m.Used, m.Booked)
		m.Status, _ = statusOf(m.Used, m.Booked)
		st.Months = append(st.Months, *m)
	}
	sort.Slice(st.Months, func(i, j int) bool { return st.Months[i].Month < st.Months[j].Month })
	return st
}

func laterOf(dist *Distribution, sprint *string) (*time.Time, bool) {
	if dist == nil || sprint == nil {
		return nil, false
	}
	t, ok := dist.Later[*sprint]
	return t, ok
}
