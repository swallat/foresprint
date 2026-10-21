// Package calendar is the sprint calendar of the core: the IDs and dates of the following
// sprints, workweeks and workdays, and the holidays of a country and region. It ports
// src/foresprint/calendar.py; weekdays are numbered like in Python (Monday = 0).
package calendar

import (
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/msg"
)

// Weekend is a set of weekdays (Monday = 0 ... Sunday = 6) as a bit mask: the days off.
type Weekend uint8

// Has reports whether the weekday (Monday = 0) is a day off.
func (w Weekend) Has(weekday int) bool { return w&(1<<uint(weekday)) != 0 }

// Days lists the days off in ascending order.
func (w Weekend) Days() []int {
	days := []int{}
	for d := 0; d < 7; d++ {
		if w.Has(d) {
			days = append(days, d)
		}
	}
	return days
}

// WeekendOf builds a Weekend from weekday numbers.
func WeekendOf(days ...int) Weekend {
	var w Weekend
	for _, d := range days {
		w |= 1 << uint(d)
	}
	return w
}

// Weekday is the weekday of a date, Monday = 0 as in Python.
func Weekday(d time.Time) int { return (int(d.Weekday()) + 6) % 7 }

// DefaultWeekend is Saturday and Sunday.
var DefaultWeekend = WeekendOf(5, 6)

// DefaultCountry is the country of a team that sets none.
const DefaultCountry = "DE"

// Workweeks that can be set independently of the country (value = weekend).
var Workweeks = map[string]Weekend{
	"mon-fri": WeekendOf(5, 6),
	"sun-thu": WeekendOf(4, 5),
	"mon-sat": WeekendOf(6),
}

// WeekdayCodes are the codes of the weekdays in a workweek list.
var WeekdayCodes = []string{"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

// NumberingError says that a sprint ID does not fit the numbering, so the ID of the following
// sprint cannot be formed.
type NumberingError struct {
	ID        string
	Numbering coretypes.Numbering
}

// Message is the text for the user (the catalog of the language fills it in).
func (e *NumberingError) Message(l msg.Lang) string {
	return l.T(
		"Sprint ID '{id}' does not match the numbering (expected {expected}); the "+
			"ID of the following sprint cannot be formed. Please correct the ID: with "+
			"foresprint rename-sprint or under Settings (without sprint files: the "+
			"ID of the first sprint there).",
		msg.Values{"id": e.ID, "expected": ExpectedIDForm(l, e.Numbering)},
	)
}

func (e *NumberingError) Error() string { return e.Message(msg.English) }

// NoFirstSprintError says that no sprint exists and the team has no first sprint either.
type NoFirstSprintError struct{ Team string }

// Message is the text for the user.
func (e *NoFirstSprintError) Message(l msg.Lang) string {
	return l.T(
		"Team {team}: No sprint has been recorded yet. Please enter the start "+
			"and ID of the first sprint under Settings (in team.yaml: "+
			"sprint.first.id and sprint.first.start).",
		msg.Values{"team": e.Team},
	)
}

func (e *NoFirstSprintError) Error() string { return e.Message(msg.English) }

// ExpectedIDForm is the form of the sprint IDs that NextID can continue (for messages).
func ExpectedIDForm(l msg.Lang, numbering coretypes.Numbering) string {
	if numbering == coretypes.Sequential {
		return l.T("a number, e.g. 22", nil)
	}
	return l.T("YYYY.N, e.g. 2026.22", nil)
}

// pyFloat matches what Python's float() accepts as a decimal number.
var pyFloat = regexp.MustCompile(`^[+-]?(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[eE][+-]?\d+(?:_\d+)*)?$`)

// pyInt matches what Python's int() accepts for ASCII digits.
var pyInt = regexp.MustCompile(`^[+-]?\d+(?:_\d+)*$`)

// pyTrim removes the whitespace Python's float() and int() ignore around a number.
func pyTrim(s string) string { return strings.TrimFunc(s, isPySpace) }

func isPySpace(r rune) bool {
	switch r {
	case ' ', '\t', '\n', '\v', '\f', '\r', 0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xa0, 0x1680, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000:
		return true
	}
	return r >= 0x2000 && r <= 0x200a
}

// intOfFloatText is int(float(s)) of Python; false where Python raises (not a number, NaN,
// infinity). The text is rounded to a double first, so "99999999999999999999" is 1e20.
func intOfFloatText(s string) (*big.Int, bool) {
	s = pyTrim(s)
	if !pyFloat.MatchString(s) {
		return nil, false
	}
	f, err := strconv.ParseFloat(strings.ReplaceAll(s, "_", ""), 64)
	if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
		return nil, false
	}
	n, _ := new(big.Float).SetFloat64(f).Int(nil) // truncates toward zero
	return n, true
}

// intText is int(s) of Python for ASCII digits (non-ASCII digits are not read: IDs are ASCII).
func intText(s string) (*big.Int, bool) {
	s = pyTrim(s)
	if !pyInt.MatchString(s) {
		return nil, false
	}
	n, ok := new(big.Int).SetString(strings.ReplaceAll(s, "_", ""), 10)
	return n, ok
}

func isDigitText(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// successor is the ID of the following sprint; false where the ID does not fit the numbering.
func successor(previousID string, startYear int, numbering coretypes.Numbering) (string, bool) {
	if numbering == coretypes.Sequential {
		n, ok := intOfFloatText(previousID)
		if !ok {
			return "", false
		}
		return new(big.Int).Add(n, big.NewInt(1)).String(), true
	}
	year, counter, sep := strings.Cut(previousID, ".")
	if sep && isDigitText(year) {
		y, ok := intText(year)
		if !ok {
			return "", false
		}
		if y.Cmp(big.NewInt(int64(startYear))) == 0 {
			c, ok := intText(counter)
			if !ok {
				return "", false
			}
			return year + "." + new(big.Int).Add(c, big.NewInt(1)).String(), true
		}
	}
	return fmt.Sprintf("%d.1", startYear), true
}

// NextID is the ID of the following sprint. It fails with a *NumberingError if previousID does
// not fit the numbering.
func NextID(previousID string, nextStart time.Time, numbering coretypes.Numbering) (string, error) {
	id, ok := successor(previousID, nextStart.Year(), numbering)
	if !ok {
		return "", &NumberingError{ID: previousID, Numbering: numbering}
	}
	return id, nil
}

// IDFitsNumbering reports whether the ID of the following sprint starting at nextStart can be
// derived from sprintID: exactly the condition under which NextID does not fail. With yearly
// numbering the counter only continues within the same year (a counter like "22b" is harmless
// at a year change); IDs without a leading year restart the yearly numbering.
func IDFitsNumbering(sprintID string, nextStart time.Time, numbering coretypes.Numbering) bool {
	_, ok := successor(sprintID, nextStart.Year(), numbering)
	return ok
}

// FollowingSprint creates the sprint that follows previous (nil: the team's first sprint).
func FollowingSprint(team *coretypes.Team, previous *coretypes.Sprint) (coretypes.Sprint, error) {
	length := time.Duration(team.Sprint.LengthDays) * 24 * time.Hour
	if previous == nil {
		if team.Sprint.FirstID == "" || team.Sprint.FirstStart == nil {
			return coretypes.Sprint{}, &NoFirstSprintError{Team: team.Key}
		}
		start := *team.Sprint.FirstStart
		return newSprint(team.Sprint.FirstID, start, start.Add(length)), nil
	}
	start := previous.End
	id, err := NextID(previous.ID, start, team.Sprint.Numbering)
	if err != nil {
		return coretypes.Sprint{}, err
	}
	return newSprint(id, start, start.Add(length)), nil
}

func newSprint(id string, start, end time.Time) coretypes.Sprint {
	unknown := coretypes.Unknown
	return coretypes.Sprint{
		ID: id, Start: start, End: end, AbsenceState: &unknown,
		Absences: map[string]float64{}, ExpectedAbsences: map[string]float64{},
	}
}

var weekdayNames = map[string][]string{
	"de": {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"},
	"en": {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"},
}

func weekdayNamesOf(l msg.Lang) []string {
	if l.IsEnglish() {
		return weekdayNames["en"]
	}
	if names, ok := weekdayNames[l.Code]; ok {
		return names
	}
	return weekdayNames["en"]
}

// DayLabel is the day for texts: German "Mi 28.10.2026", English "Wed 28.10.2026".
func DayLabel(l msg.Lang, d time.Time) string {
	return fmt.Sprintf("%s %s", weekdayNamesOf(l)[Weekday(d)], d.Format("02.01.2006"))
}

// Country is an entry of the country list.
type Country struct {
	Code string
	Name string
}

// Countries lists the supported countries (ISO code and name), sorted by code.
func Countries() []Country {
	var out []Country
	for _, c := range holidays.Countries() {
		out = append(out, Country{Code: c.Code, Name: c.Name})
	}
	return out
}

// Subdivisions lists the valid region codes of a country.
func Subdivisions(country string) []string { return holidays.Subdivisions(country) }

// CountryWeekend is the weekend of the country according to the holidays data (Friday and
// Saturday in Saudi Arabia); Saturday and Sunday for an unknown country.
func CountryWeekend(country string) Weekend {
	var w Weekend
	for _, d := range holidays.Weekend(country) {
		w |= 1 << uint((int(d)+6)%7)
	}
	return w
}

// WeekendFromWorkweek gives the days off for a workweek: a name (mon-fri, sun-thu, mon-sat) or
// a list of the workdays like "mon,tue,wed,thu" (4-day week). ok is false for "auto" and the
// empty value (the weekend is then not set); err is non-nil for an unknown value.
func WeekendFromWorkweek(value string) (w Weekend, ok bool, err error) {
	value = strings.ToLower(pyTrim(value))
	if value == "" || value == "auto" {
		return 0, false, nil
	}
	if w, found := Workweeks[value]; found {
		return w, true, nil
	}
	fields := strings.FieldsFunc(strings.NewReplacer(";", ",", " ", ",").Replace(value), func(r rune) bool { return r == ',' })
	var worked Weekend
	for _, f := range fields {
		f = pyTrim(f)
		if f == "" {
			continue
		}
		i := indexOf(WeekdayCodes, f)
		if i < 0 {
			return 0, false, fmt.Errorf("unknown workweek %q", value)
		}
		worked |= 1 << uint(i)
	}
	if worked == 0 {
		return 0, false, fmt.Errorf("unknown workweek %q", value)
	}
	return ^worked & 0x7f, true, nil
}

func indexOf(list []string, s string) int {
	for i, v := range list {
		if v == s {
			return i
		}
	}
	return -1
}

// TeamWeekend is the weekend of the team: the configured workweek, otherwise that of the
// country.
func TeamWeekend(team *coretypes.Team) Weekend {
	if w, ok, err := WeekendFromWorkweek(team.Capacity.Workweek); err == nil && ok && w != 0 {
		return w
	}
	return CountryWeekend(team.Capacity.Country)
}

// PersonWeekend is the days off of a person: their own workweek, otherwise the weekend of their
// country, otherwise that of the team.
func PersonWeekend(team *coretypes.Team, person coretypes.Person) Weekend {
	if w, ok, err := WeekendFromWorkweek(person.Workweek); err == nil && ok {
		return w
	}
	if person.Country != "" {
		return CountryWeekend(person.Country)
	}
	return TeamWeekend(team)
}

// Workdays are the workdays in the half-open interval [start, end); weekend = days off.
func Workdays(start, end time.Time, weekend Weekend) []time.Time {
	var days []time.Time
	for day := start; day.Before(end); day = day.AddDate(0, 0, 1) {
		if !weekend.Has(Weekday(day)) {
			days = append(days, day)
		}
	}
	return days
}

// TeamWorkdays are the team's workdays in [start, end).
func TeamWorkdays(team *coretypes.Team, start, end time.Time) []time.Time {
	return Workdays(start, end, TeamWeekend(team))
}

// WorkweekLabel is the workweek of the team for texts: "Mon–Fri" for consecutive days,
// otherwise the list ("Mon, Tue, Wed, Thu").
func WorkweekLabel(l msg.Lang, team *coretypes.Team) string {
	names := weekdayNamesOf(l)
	weekend := TeamWeekend(team)
	var worked []int
	for i := 0; i < 7; i++ {
		if !weekend.Has(i) {
			worked = append(worked, i)
		}
	}
	if len(worked) == 0 {
		return "–"
	}
	// Consecutive (also across the weekend, e.g. Sun–Thu): from the first day after a day off
	// to the last workday.
	start := -1
	for _, i := range worked {
		if weekend.Has((i + 6) % 7) {
			start = i
			break
		}
	}
	if start >= 0 && len(worked) > 2 {
		consecutive := true
		for k := range worked {
			if weekend.Has((start + k) % 7) {
				consecutive = false
			}
		}
		if consecutive {
			return names[start] + "–" + names[(start+len(worked)-1)%7]
		}
	}
	parts := make([]string, len(worked))
	for i, d := range worked {
		parts[i] = names[d]
	}
	return strings.Join(parts, ", ")
}

// IsHoliday reports whether the day is a public holiday in the country and region ("" region =
// nationwide only). An unknown country or region does not fail: only the nationwide holidays
// apply, or none.
func IsHoliday(day time.Time, region, country string) bool {
	return holidays.IsHoliday(country, region, day)
}

// HolidayName is the name of the holiday in the language, or "" if the day is none.
func HolidayName(l msg.Lang, day time.Time, region, country string) string {
	code := "de"
	if l.IsEnglish() {
		code = "en"
	} else if l.Code != "" {
		code = l.Code
	}
	return holidays.Name(country, region, day, code)
}
