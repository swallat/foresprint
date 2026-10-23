package tutorial

import (
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/validate"
)

func TestTeamLoadsAndChecks(t *testing.T) {
	for _, lang := range []string{"en", "de"} {
		root := t.TempDir()
		today := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
		if err := Write(root, today, lang); err != nil {
			t.Fatal(err)
		}
		data, err := storage.NewRepository(root).Load(Key)
		if err != nil {
			t.Fatal(err)
		}
		f := data.Team.Features
		if !f.Products || !f.PO || !f.Production || !f.Tickets || !f.Projects {
			t.Errorf("features %+v", f)
		}
		found := false
		for _, p := range data.Projects {
			if p.ID == "self-service" {
				found = true
			}
		}
		if !found || len(data.Projects) != 4 || len(data.Products) != 4 || len(data.People) != 6 ||
			len(data.Tickets) != 17 || data.AbsencePeriods.Len() == 0 || len(data.Sprints) != 8 ||
			len(data.Team.ProductOwners) != 2 {
			t.Errorf("%s: projects %d products %d people %d tickets %d sprints %d", lang,
				len(data.Projects), len(data.Products), len(data.People), len(data.Tickets), len(data.Sprints))
		}
		for _, issue := range validate.CheckTeam(data, today) {
			t.Logf("%v %s: %s", issue.Level, issue.Where, issue.Message)
			if issue.Level == validate.Error {
				t.Errorf("%s: %s: %s", lang, issue.Where, issue.Message)
			}
		}
	}
}

func TestCurrentSprintContainsToday(t *testing.T) {
	for d := 0; d < 14; d++ {
		today := time.Date(2026, 10, 12+d, 0, 0, 0, 0, time.UTC)
		start := currentStart(today)
		if today.Before(start) || !today.Before(start.AddDate(0, 0, sprintDays)) || start.Weekday() != time.Monday {
			t.Errorf("%s: sprint starts %s", today.Format("2006-01-02"), start.Format("2006-01-02"))
		}
	}
}

func TestMonthsStayDistinctAtMonthEnds(t *testing.T) {
	for _, day := range []time.Time{time.Date(2026, 8, 31, 0, 0, 0, 0, time.UTC), time.Date(2027, 3, 29, 0, 0, 0, 0, time.UTC)} {
		seen := map[string]bool{}
		for m := -1; m <= 3; m++ {
			k := monthAt(day, m).Format("2006-01")
			if seen[k] {
				t.Errorf("%s: month %s twice", day.Format("2006-01-02"), k)
			}
			seen[k] = true
		}
	}
}

func TestVariantsLoadAndCheck(t *testing.T) {
	today := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
	for _, team := range []string{TeamAtlas, TeamSimple} {
		for _, source := range []string{SourcePackages, SourceTracker, SourceNone} {
			root := t.TempDir()
			if err := WriteWith(root, today, "en", Options{Team: team, Source: source}); err != nil {
				t.Fatal(err)
			}
			data, err := storage.NewRepository(root).Load(Key)
			if err != nil {
				t.Fatalf("%s/%s: %v", team, source, err)
			}
			f := data.Team.Features
			if f.Tickets != (source != SourceNone) || f.Projects != (team == TeamAtlas) || f.PO != (team == TeamAtlas) || f.Production != (team == TeamAtlas) {
				t.Errorf("%s/%s: features %+v", team, source, f)
			}
			if (len(data.Tickets) > 0) != f.Tickets || (len(data.Projects) > 0) != f.Projects {
				t.Errorf("%s/%s: %d tickets, %d projects", team, source, len(data.Tickets), len(data.Projects))
			}
			if source == SourceTracker && (data.Team.Tracker.Kind != "jira" || len(data.Tickets) == 0 || !strings.HasPrefix(data.Tickets[0].Key, "ATL-")) {
				t.Errorf("%s/%s: tracker %+v", team, source, data.Team.Tracker)
			}
			if source == SourcePackages && data.Team.Tracker.Kind != model.PackagesKind {
				t.Errorf("%s/%s: tracker kind %q", team, source, data.Team.Tracker.Kind)
			}
			for _, issue := range validate.CheckTeam(data, today) {
				if issue.Level == validate.Error {
					t.Errorf("%s/%s: %s: %s", team, source, issue.Where, issue.Message)
				}
			}
		}
	}
	if err := WriteWith(t.TempDir(), today, "en", Options{Team: "big"}); err == nil {
		t.Error("an unknown variant must be refused")
	}
}
