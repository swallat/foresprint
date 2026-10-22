package model_test

import (
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
)

func TestSprintDisplayName(t *testing.T) {
	d := func(y int, m time.Month, day int) time.Time { return time.Date(y, m, day, 0, 0, 0, 0, time.UTC) }
	hand := "Launch"
	from := "s3"
	team := model.NewTeam("t", "t")
	team.Sprint.Naming = []model.NamingRule{
		{Pattern: "S{JJ}-{NN}"},
		{From: &from, Pattern: "{JJJJ}/{N} (#{LFD})"},
	}
	sprints := []model.Sprint{
		{ID: "s1", Start: d(2026, 12, 7)},
		{ID: "s2", Start: d(2026, 12, 21)},
		{ID: "s3", Start: d(2027, 1, 4)},
		{ID: "s4", Start: d(2027, 1, 18), Name: &hand},
		{ID: "s5", Start: d(2027, 2, 1)},
	}
	want := map[string]string{
		"s1": "S26-01", "s2": "S26-02", "s3": "2027/1 (#3)", "s4": "Launch", "s5": "2027/3 (#5)", "zzz": "zzz",
	}
	for id, w := range want {
		if got := model.SprintDisplayName(&team, sprints, id); got != w {
			t.Errorf("%s: %q, want %q", id, got, w)
		}
	}
	team.Sprint.Naming = nil
	if got := model.SprintDisplayName(&team, sprints, "s1"); got != "s1" {
		t.Errorf("no pattern: %q", got)
	}
}
