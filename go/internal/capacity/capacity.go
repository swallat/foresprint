// Package capacity calculates a sprint's capacity from the list of people, holidays and
// absences. It ports src/foresprint/capacity.py.
package capacity

import (
	"math"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/engine"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
)

// PersonCapacity is the capacity of one person in a sprint, in PD.
type PersonCapacity struct {
	Person      model.Person `json:"person"`
	Workdays    int          `json:"workdays"`
	Holidays    int          `json:"holidays"`
	AbsenceDays float64      `json:"absence_days"`
	// Capacity is the available time after holidays and absences (before the deductions for
	// Scrum events).
	Capacity float64 `json:"capacity"`
	MeanFTE  float64 `json:"mean_fte"`
	// FTEChanges: the FTE changes during the sprint; absences are weighted with the mean FTE
	// (approximation).
	FTEChanges bool `json:"fte_changes"`
	// Overhead is the fixed deduction for Scrum events: PD per person × FTE, at most the
	// capacity.
	Overhead float64 `json:"overhead"`
}

// Breakdown is the capacity of a sprint with its parts.
type Breakdown struct {
	People []PersonCapacity `json:"people"`
	Gross  float64          `json:"gross"`
	// Overhead is the total deduction for Scrum events: share plus fixed PD.
	Overhead          float64 `json:"overhead"`
	OverheadSharePart float64 `json:"overhead_share_part"`
	OverheadDaysPart  float64 `json:"overhead_days_part"`
	// Capacity is unrounded: the forecast keeps calculating with it (no rounding error in the
	// denominator of the normalized velocity). Rounding happens only on display and freezing
	// (Rounded).
	Capacity float64 `json:"capacity"`
	Rounding int     `json:"rounding"`
}

// Rounded is the capacity for display and storage (rounded half up).
func (b Breakdown) Rounded() float64 { return engine.RoundHalfUp(b.Capacity, b.Rounding) }

// Approximated are the people whose FTE changes during the sprint (absences weighted only
// approximately) and who have absences.
func (b Breakdown) Approximated() []PersonCapacity {
	out := []PersonCapacity{}
	for _, p := range b.People {
		if p.FTEChanges && p.AbsenceDays != 0 {
			out = append(out, p)
		}
	}
	return out
}

// PersonOf is the capacity of one person in the sprint, in PD; ok is false if the person has no
// working day in the sprint.
//
// FTE is the share of the person's working days (see Person.Workweek): someone who works four
// days a week and enters that as workweek "mon,tue,wed,thu" has FTE 1; fte 0.8 with a full
// working week (Mon-Fri) gives the same capacity. Using both (four days and 0.8) would deduct
// twice.
//
// absenceRate reduces the capacity by an expected share of unknown absences (estimated from
// history); entered absences apply in addition.
func PersonOf(team *model.Team, person model.Person, sprint model.Sprint, absenceRate float64) (PersonCapacity, bool) {
	country := text(person.Country)
	if country == "" {
		country = team.Capacity.Country
	}
	// If the person has their own country, the team's region does not apply.
	region := text(person.Region)
	if region == "" && text(person.Country) == "" {
		region = text(team.Capacity.Region)
	}
	weekend := calendar.PersonWeekend(team, person)
	var days []time.Time
	for _, d := range calendar.Workdays(sprint.Start, sprint.End, weekend) {
		if person.FTEOn(d) > 0 {
			days = append(days, d)
		}
	}
	if len(days) == 0 {
		return PersonCapacity{}, false
	}
	var working []time.Time
	for _, d := range days {
		if !calendar.IsHoliday(d, region, country) {
			working = append(working, d)
		}
	}
	absence := math.Min(sprint.Absences[person.ID], float64(len(working)))
	ftes := make([]float64, len(working))
	distinct := map[float64]bool{}
	for i, d := range working {
		ftes[i] = person.FTEOn(d)
		distinct[ftes[i]] = true
	}
	available := pymath.Sum(ftes)
	meanFTE := 0.0
	if len(working) > 0 {
		meanFTE = available / float64(len(working))
	}
	capacity := math.Max(available-float64(absence*meanFTE), 0) * (1 - absenceRate)
	return PersonCapacity{
		Person:      person,
		Workdays:    len(days),
		Holidays:    len(days) - len(working),
		AbsenceDays: absence,
		Capacity:    capacity,
		MeanFTE:     meanFTE,
		FTEChanges:  len(distinct) > 1,
		Overhead:    math.Min(capacity, float64(team.Capacity.OverheadDays*meanFTE)),
	}, true
}

// Sprint is the capacity of the sprint. One shared calculation for confirmed, announced and
// expected absences: first holidays and absences (or the expected rate) per person, then the
// deduction for Scrum events. The result (Capacity) stays unrounded; rounding happens only for
// display and freezing (Breakdown.Rounded, half up).
//
// The deduction: fixed PD per person (OverheadDays × FTE, at most the person's capacity)
// replace the percentage deduction (OverheadShare); both are the same deduction in two units
// and are not added.
func Sprint(team *model.Team, people []model.Person, sprint model.Sprint, absenceRate float64) Breakdown {
	rows := []PersonCapacity{}
	gross := make([]float64, 0, len(people))
	overheads := make([]float64, 0, len(people))
	for _, p := range people {
		if pc, ok := PersonOf(team, p, sprint, absenceRate); ok {
			rows = append(rows, pc)
			gross = append(gross, pc.Capacity)
			overheads = append(overheads, pc.Overhead)
		}
	}
	grossSum := pymath.Sum(gross)
	daysPart := pymath.Sum(overheads)
	sharePart := 0.0
	if team.Capacity.OverheadDays == 0 {
		sharePart = float64(grossSum * team.Capacity.OverheadShare)
	}
	overhead := sharePart + daysPart
	return Breakdown{
		People:            rows,
		Gross:             grossSum,
		Overhead:          overhead,
		OverheadSharePart: sharePart,
		OverheadDaysPart:  daysPart,
		Capacity:          math.Max(grossSum-overhead, 0),
		Rounding:          team.Capacity.Rounding,
	}
}

// ProductionShare is the share of the sprint capacity held by people with production access
// (0-1); ok is false if nobody has production access.
func ProductionShare(team *model.Team, people []model.Person, sprint model.Sprint) (share float64, ok bool) {
	var group []model.Person
	for _, p := range people {
		if p.ProductionAccess {
			group = append(group, p)
		}
	}
	if len(group) == 0 {
		return 0, false
	}
	total := Sprint(team, people, sprint, 0).Gross
	if total == 0 {
		return 0, true
	}
	return Sprint(team, group, sprint, 0).Gross / total, true
}

// AbsenceHistory is the average share of capacity lost to absences in past sprints.
type AbsenceHistory struct {
	Rate *float64 `json:"rate"`
	// Sprints are the sprints actually used (IDs, older first) and Rates their rates.
	Sprints []string  `json:"sprints"`
	Rates   []float64 `json:"rates"`
	// Derived are those of the sprints that only count as confirmed because of other fields
	// (older files without a stored state) and have no absences: they count as "0 % loss",
	// which makes the rate uncertain. Changes no number.
	Derived []string `json:"derived"`
}

// History is the average loss to absences over the last count sprints.
//
// Only completed sprints whose absences are confirmed are considered, using the same definition
// as for the capacity (AbsenceStatus). Confirmed sprints without absences count with a rate of
// 0, otherwise the rate would be too high. Unknown and merely announced sprints are left out.
func History(team *model.Team, people []model.Person, past []model.Sprint, count int) AbsenceHistory {
	empty := AbsenceHistory{Sprints: []string{}, Rates: []float64{}, Derived: []string{}}
	if count <= 0 {
		return empty
	}
	type used struct {
		id   string
		rate float64
	}
	var rows []used
	derived := map[string]bool{}
	for _, sprint := range past {
		if sprint.AbsenceStatus() != model.AbsencesConfirmed {
			continue
		}
		if len(sprint.Absences) == 0 && sprint.AbsenceState == nil && sprint.AbsenceStatus() != model.AbsencesUnknown {
			derived[sprint.ID] = true
		}
		without := sprint.Clone()
		without.Absences = map[string]float64{}
		full := Sprint(team, people, without, 0).Gross
		if full <= 0 {
			continue
		}
		rows = append(rows, used{sprint.ID, 1 - Sprint(team, people, sprint, 0).Gross/full})
	}
	if len(rows) > count {
		rows = rows[len(rows)-count:]
	}
	out := empty
	for _, r := range rows {
		out.Sprints = append(out.Sprints, r.id)
		out.Rates = append(out.Rates, r.rate)
		if derived[r.id] {
			out.Derived = append(out.Derived, r.id)
		}
	}
	if len(out.Rates) > 0 {
		out.Rate = model.Ptr(pymath.Sum(out.Rates) / float64(len(out.Rates)))
	}
	return out
}

// ExpectedAbsenceRate is the average share of capacity lost to absences (0-1); nil without
// history.
func ExpectedAbsenceRate(team *model.Team, people []model.Person, past []model.Sprint, count int) *float64 {
	return History(team, people, past, count).Rate
}

// Estimated is the capacity of a sprint without known absences, reduced by the expected rate.
func Estimated(team *model.Team, people []model.Person, sprint model.Sprint, rate float64) float64 {
	return Sprint(team, people, sprint, rate).Capacity
}

// WithExpectedAbsences is the capacity of a sprint with its announced absences (PO
// pre-planning).
func WithExpectedAbsences(team *model.Team, people []model.Person, sprint model.Sprint) float64 {
	probe := sprint.Clone()
	probe.Absences = map[string]float64{}
	for k, v := range sprint.ExpectedAbsences {
		probe.Absences[k] = v
	}
	return Sprint(team, people, probe, 0).Capacity
}

// text is an optional text: nil is the empty text.
func text(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// ProductionTime is the time of the people with production access in the sprint, in PD: per
// person the capacity after holidays and absences (max(0, share of the sprint's PD − absence),
// before the deduction for Scrum events), summed, times capPercent/100. capPercent is the team
// setting "at most X % of the time of people with production access"; 100 means no cap.
type ProductionTime struct {
	People []PersonCapacity `json:"people"`
	// Time is the time of the group before the cap.
	Time float64 `json:"time"`
	// CapPercent is the cap in percent (100 = none).
	CapPercent float64 `json:"cap_percent"`
	// Available is Time × CapPercent / 100: what can be planned for production work.
	Available float64 `json:"available"`
}

// ProductionTimeOf calculates the ProductionTime of a sprint. absenceRate is the expected share
// of unknown absences, like in Sprint. A negative capPercent counts as 0.
func ProductionTimeOf(team *model.Team, people []model.Person, sprint model.Sprint, absenceRate, capPercent float64) ProductionTime {
	rows := []PersonCapacity{}
	times := []float64{}
	for _, p := range people {
		if !p.ProductionAccess {
			continue
		}
		if pc, ok := PersonOf(team, p, sprint, absenceRate); ok {
			rows = append(rows, pc)
			times = append(times, pc.Capacity)
		}
	}
	capPercent = math.Max(capPercent, 0)
	total := pymath.Sum(times)
	return ProductionTime{
		People:     rows,
		Time:       total,
		CapPercent: capPercent,
		Available:  float64(total*capPercent) / 100,
	}
}

// PeriodDays are the working days of a planned absence period [from, to] (both included) per
// sprint, for the sprints that overlap it. Weekend, holidays, region and country are those of
// the person (see PersonOf); only whole days count, and a person who is not in the team on a day
// does not have a working day on it. Sprints without a working day in the period are left out.
func PeriodDays(team *model.Team, person model.Person, from, to time.Time, sprints []model.Sprint) map[string]float64 {
	result := map[string]float64{}
	if to.Before(from) {
		return result
	}
	country := text(person.Country)
	if country == "" {
		country = team.Capacity.Country
	}
	region := text(person.Region)
	if region == "" && text(person.Country) == "" {
		region = text(team.Capacity.Region)
	}
	weekend := calendar.PersonWeekend(team, person)
	for _, s := range sprints {
		count := 0
		for _, d := range calendar.Workdays(s.Start, s.End, weekend) {
			if d.Before(from) || d.After(to) || person.FTEOn(d) <= 0 {
				continue
			}
			if !calendar.IsHoliday(d, region, country) {
				count++
			}
		}
		if count > 0 {
			result[s.ID] = float64(count)
		}
	}
	return result
}
