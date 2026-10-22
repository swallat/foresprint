package tutorial

import (
	"testing"
	"time"

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
