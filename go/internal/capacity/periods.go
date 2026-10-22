package capacity

import (
	"sort"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/model"
)

// periodDaySet are the days of the period on which the person works and is therefore away: the
// working days of the person (weekend, holidays, membership) in [from, to] inside the sprint.
func periodDaySet(team *model.Team, person model.Person, period model.AbsencePeriod, sprint model.Sprint) map[time.Time]bool {
	days := map[time.Time]bool{}
	country := text(person.Country)
	if country == "" {
		country = team.Capacity.Country
	}
	region := text(person.Region)
	if region == "" && text(person.Country) == "" {
		region = text(team.Capacity.Region)
	}
	weekend := calendar.PersonWeekend(team, person)
	for _, d := range calendar.Workdays(sprint.Start, sprint.End, weekend) {
		if period.Covers(d) && person.FTEOn(d) > 0 && !calendar.IsHoliday(d, region, country) {
			days[d] = true
		}
	}
	return days
}

// PeriodsApplied is a sprint with the absences that come from planned absence periods.
type PeriodsApplied struct {
	Sprint model.Sprint
	// HandWins lists the people whose period days were not used because days were typed by hand
	// for the sprint (typed days win over a period).
	HandWins []string
}

// ApplyPeriods fills the absences of a sprint from the planned absence periods (decision 23):
// the working days of a person inside the sprint, each day counted once even if periods
// overlap. A confirmed period gives confirmed absences (Sprint.Absences), an announced one
// announced absences (Sprint.ExpectedAbsences).
//
// Days typed by hand win over a period (the person is listed in HandWins), and a sprint whose
// absences are already confirmed is not changed. The result is a copy for calculating; the
// sprint file keeps only what was typed.
func ApplyPeriods(team *model.Team, people []model.Person, periods model.Absences, sprint model.Sprint) PeriodsApplied {
	result := PeriodsApplied{Sprint: sprint}
	if periods.Len() == 0 || sprint.AbsenceStatus() == model.AbsencesConfirmed {
		return result
	}
	applied := sprint.Clone()
	if applied.Absences == nil {
		applied.Absences = map[string]float64{}
	}
	if applied.ExpectedAbsences == nil {
		applied.ExpectedAbsences = map[string]float64{}
	}
	changed := false
	for _, person := range people {
		list, ok := periods.Get(person.ID)
		if !ok {
			continue
		}
		confirmed := map[time.Time]bool{}
		announced := map[time.Time]bool{}
		for _, period := range list {
			target := announced
			if period.Confirmed {
				target = confirmed
			}
			for d := range periodDaySet(team, person, period, sprint) {
				target[d] = true
			}
		}
		for d := range confirmed {
			delete(announced, d)
		}
		if len(confirmed) > 0 {
			if _, typed := sprint.Absences[person.ID]; typed {
				result.HandWins = append(result.HandWins, person.ID)
			} else {
				applied.Absences[person.ID] = float64(len(confirmed))
				changed = true
			}
		}
		if len(announced) > 0 {
			if _, typed := sprint.ExpectedAbsences[person.ID]; typed {
				result.HandWins = append(result.HandWins, person.ID)
			} else {
				applied.ExpectedAbsences[person.ID] = float64(len(announced))
				changed = true
			}
		}
	}
	sort.Strings(result.HandWins)
	result.HandWins = dedupe(result.HandWins)
	if changed {
		result.Sprint = applied
	}
	return result
}

func dedupe(sorted []string) []string {
	out := sorted[:0]
	for i, s := range sorted {
		if i == 0 || s != sorted[i-1] {
			out = append(out, s)
		}
	}
	return out
}
