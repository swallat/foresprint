package calendar_test

import (
	"errors"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/coretest"
	"github.com/swallat/foresprint/internal/coretypes"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/msg"
)

func date(t *testing.T, s string) time.Time {
	t.Helper()
	d, err := coretypes.ParseDate(s)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func sorted(days []int) []int {
	if days == nil {
		return []int{}
	}
	return days
}

type workdaysRef struct {
	Workdays []struct {
		Start   string   `json:"start"`
		End     string   `json:"end"`
		Weekend string   `json:"weekend"`
		Days    []string `json:"days"`
	} `json:"workdays"`
	WorkweekValues map[string]any    `json:"workweek_values"`
	TeamWeekend    map[string][]int  `json:"team_weekend"`
	Labels         map[string]string `json:"labels"`
}

func TestWorkdaysMatchPython(t *testing.T) {
	var ref workdaysRef
	golden.Load(t, &ref, "calendar", "workdays.json")
	weekends := map[string]calendar.Weekend{"default": calendar.DefaultWeekend, "sa": calendar.CountryWeekend("SA")}
	for name, w := range calendar.Workweeks {
		weekends[name] = w
	}
	four, _, err := calendar.WeekendFromWorkweek("mon,tue,wed,thu")
	if err != nil {
		t.Fatal(err)
	}
	weekends["4-day"] = four
	for _, row := range ref.Workdays {
		w, ok := weekends[row.Weekend]
		if !ok {
			t.Fatalf("unknown weekend %q in the reference", row.Weekend)
		}
		got := []string{}
		for _, d := range calendar.Workdays(date(t, row.Start), date(t, row.End), w) {
			got = append(got, d.Format("2006-01-02"))
		}
		golden.Compare(t, toAny(row.Days), toAny(got))
	}

	inputs := map[string]*string{
		"None": nil, "''": ptr(""), "'auto'": ptr("auto"), "'mon-fri'": ptr("mon-fri"), "'sun-thu'": ptr("sun-thu"),
		"'mon-sat'": ptr("mon-sat"), "'mon,tue,wed,thu'": ptr("mon,tue,wed,thu"), "'tue;wed;thu'": ptr("tue;wed;thu"),
		"'mon wed fri'": ptr("mon wed fri"), "'xyz'": ptr("xyz"), "'mon,foo'": ptr("mon,foo"),
	}
	if len(inputs) != len(ref.WorkweekValues) {
		t.Fatalf("the reference has %d workweek values, the test %d", len(ref.WorkweekValues), len(inputs))
	}
	for key, want := range ref.WorkweekValues {
		value := ""
		if in := inputs[key]; in != nil {
			value = *in
		}
		w, ok, err := calendar.WeekendFromWorkweek(value)
		switch want {
		case "error":
			if err == nil {
				t.Errorf("%s: want an error", key)
			}
		case nil:
			if err != nil || ok {
				t.Errorf("%s: want no weekend, got %v %v %v", key, w, ok, err)
			}
		default:
			if err != nil || !ok {
				t.Errorf("%s: want a weekend, got %v", key, err)
				continue
			}
			golden.Compare(t, want, coretest.JSON(t, sorted(w.Days())))
		}
	}

	for key, want := range ref.TeamWeekend {
		team := teamFor(t, key)
		golden.Compare(t, toAny(want), toAny(sorted(calendar.TeamWeekend(team).Days())))
		if got := calendar.WorkweekLabel(msg.English, team); got != ref.Labels[key] {
			t.Errorf("%s: label %q, Python %q", key, got, ref.Labels[key])
		}
	}
}

func ptr(s string) *string { return &s }

func teamFor(t *testing.T, key string) *coretypes.Team {
	t.Helper()
	var country, workweek string
	for i := range key {
		if key[i] == '/' {
			country, workweek = key[:i], key[i+1:]
		}
	}
	team := coretypes.NewTeam("x", "x")
	team.Capacity.Country = country
	team.Capacity.Workweek = workweek
	return team
}

func toAny(v any) any {
	out, err := coretest.ToAny(v)
	if err != nil {
		panic(err)
	}
	return out
}

type sprintsRef struct {
	Series []struct {
		Numbering  string `json:"numbering"`
		LengthDays int    `json:"length_days"`
		Sprints    []struct {
			ID    string `json:"id"`
			Start string `json:"start"`
			End   string `json:"end"`
		} `json:"sprints"`
	} `json:"series"`
	NextID []struct {
		Previous  string  `json:"previous"`
		Start     string  `json:"start"`
		Numbering string  `json:"numbering"`
		ID        *string `json:"id"`
	} `json:"next_id"`
	Fits []struct {
		Previous  string `json:"previous"`
		Start     string `json:"start"`
		Numbering string `json:"numbering"`
		Fits      bool   `json:"fits"`
	} `json:"fits"`
}

func TestSprintSeriesMatchesPython(t *testing.T) {
	var ref sprintsRef
	golden.Load(t, &ref, "calendar", "sprints.json")
	// The generator's series: numbering, first ID, first start, length.
	setups := []struct {
		first string
		start string
	}{{"2026.20", "2026-11-04"}, {"2026.1", "2026-12-02"}, {"21", "2026-03-02"}, {"2026.5", "2025-12-17"}}
	for i, s := range ref.Series {
		team := coretypes.NewTeam("t", "t")
		team.Sprint.Numbering = coretypes.Numbering(s.Numbering)
		team.Sprint.LengthDays = s.LengthDays
		team.Sprint.FirstID = setups[i].first
		start := date(t, setups[i].start)
		team.Sprint.FirstStart = &start
		var previous *coretypes.Sprint
		for k, want := range s.Sprints {
			next, err := calendar.FollowingSprint(team, previous)
			if err != nil {
				t.Fatal(err)
			}
			previous = &next
			got := [3]string{next.ID, next.Start.Format("2006-01-02"), next.End.Format("2006-01-02")}
			if got != [3]string{want.ID, want.Start, want.End} {
				t.Errorf("series %d sprint %d: got %v, Python %v", i, k, got, want)
			}
		}
	}
	for _, c := range ref.NextID {
		got, err := calendar.NextID(c.Previous, date(t, c.Start), coretypes.Numbering(c.Numbering))
		switch {
		case c.ID == nil && err == nil:
			t.Errorf("NextID(%q, %s, %s) = %q, Python fails", c.Previous, c.Start, c.Numbering, got)
		case c.ID != nil && (err != nil || got != *c.ID):
			t.Errorf("NextID(%q, %s, %s) = %q, %v; Python %q", c.Previous, c.Start, c.Numbering, got, err, *c.ID)
		}
	}
	for _, c := range ref.Fits {
		if got := calendar.IDFitsNumbering(c.Previous, date(t, c.Start), coretypes.Numbering(c.Numbering)); got != c.Fits {
			t.Errorf("IDFitsNumbering(%q, %s, %s) = %v, Python %v", c.Previous, c.Start, c.Numbering, got, c.Fits)
		}
	}
}

func TestCountriesMatchPython(t *testing.T) {
	var ref map[string]struct {
		Name         string   `json:"name"`
		Subdivisions []string `json:"subdivisions"`
		Weekend      []int    `json:"weekend"`
	}
	golden.Load(t, &ref, "calendar", "countries.json")
	countries := calendar.Countries()
	if len(countries) != len(ref) {
		t.Fatalf("%d countries, Python %d", len(countries), len(ref))
	}
	for _, c := range countries {
		want, ok := ref[c.Code]
		if !ok {
			t.Errorf("%s: not in the Python list", c.Code)
			continue
		}
		if c.Name != want.Name {
			t.Errorf("%s: name %q, Python %q", c.Code, c.Name, want.Name)
		}
		golden.Compare(t, toAny(orNone(want.Subdivisions)), toAny(orNone(calendar.Subdivisions(c.Code))))
		golden.Compare(t, toAny(want.Weekend), toAny(sorted(calendar.CountryWeekend(c.Code).Days())))
	}
}

func orNone(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

func TestDayLabel(t *testing.T) {
	d := date(t, "2026-10-28")
	if got := calendar.DayLabel(msg.English, d); got != "Wed 28.10.2026" {
		t.Errorf("English: %q", got)
	}
	if got := calendar.DayLabel(msg.Lang{Code: "de"}, d); got != "Mi 28.10.2026" {
		t.Errorf("German: %q", got)
	}
}

type holidaySample struct {
	Country string `json:"country"`
	Region  string `json:"region"`
	Years   map[string]struct {
		De        map[string]string `json:"de"`
		En        map[string]string `json:"en"`
		IsHoliday []string          `json:"is_holiday"`
	} `json:"years"`
}

// The holiday lookups of the calendar (is_holiday, holiday_name in both languages) equal the
// Python ones for the sample countries and regions of the reference.
func TestHolidaysMatchPython(t *testing.T) {
	var ref map[string]holidaySample
	golden.Load(t, &ref, "calendar", "holidays-sample.json")
	german := msg.Lang{Code: "de"}
	for key, s := range ref {
		for year, y := range s.Years {
			holiday := map[string]bool{}
			for _, d := range y.IsHoliday {
				holiday[d] = true
			}
			start := date(t, year+"-01-01")
			for day := start; day.Year() == start.Year(); day = day.AddDate(0, 0, 1) {
				iso := day.Format("2006-01-02")
				if got := calendar.IsHoliday(day, s.Region, s.Country); got != holiday[iso] {
					t.Fatalf("%s %s: IsHoliday %v, Python %v", key, iso, got, holiday[iso])
				}
				if got := calendar.HolidayName(msg.English, day, s.Region, s.Country); got != y.En[iso] {
					t.Fatalf("%s %s: English name %q, Python %q", key, iso, got, y.En[iso])
				}
				if got := calendar.HolidayName(german, day, s.Region, s.Country); got != y.De[iso] {
					t.Fatalf("%s %s: German name %q, Python %q", key, iso, got, y.De[iso])
				}
			}
		}
	}
}

// The messages of the calendar (English and German) equal the Python ones.
func TestMessagesMatchPython(t *testing.T) {
	var german map[string]string
	golden.Load(t, &german, "formulas-de", "calendar.json")
	de := coretest.German(t)
	team := coretypes.NewTeam("t", "t")
	_, err := calendar.FollowingSprint(team, nil)
	var first *calendar.NoFirstSprintError
	if !errors.As(err, &first) {
		t.Fatalf("error %T", err)
	}
	if got := first.Message(de); got != german["no_first"] {
		t.Errorf("no first sprint:\n got %q\nwant %q", got, german["no_first"])
	}
	_, err = calendar.NextID("22b", date(t, "2026-03-01"), coretypes.Sequential)
	var numbering *calendar.NumberingError
	if !errors.As(err, &numbering) {
		t.Fatalf("error %T", err)
	}
	if got := numbering.Message(de); got != german["sequential"] {
		t.Errorf("numbering:\n got %q\nwant %q", got, german["sequential"])
	}
	if got := calendar.ExpectedIDForm(de, coretypes.Yearly); got != german["yearly_form"] {
		t.Errorf("yearly form %q, Python %q", got, german["yearly_form"])
	}
	if got := calendar.ExpectedIDForm(de, coretypes.Sequential); got != german["sequential_form"] {
		t.Errorf("sequential form %q, Python %q", got, german["sequential_form"])
	}
	if got := calendar.DayLabel(de, date(t, "2026-10-28")); got != german["day_label"] {
		t.Errorf("day label %q, Python %q", got, german["day_label"])
	}
}

// Odd sprint IDs: every spelling of a number that Python accepts or refuses.
func TestOddIDsMatchPython(t *testing.T) {
	var rows []struct {
		Previous  string  `json:"previous"`
		Start     string  `json:"start"`
		Numbering string  `json:"numbering"`
		ID        *string `json:"id"`
		Fits      bool    `json:"fits"`
	}
	golden.Load(t, &rows, "calendar", "ids.json")
	if len(rows) < 100 {
		t.Fatalf("only %d rows", len(rows))
	}
	for _, r := range rows {
		start := date(t, r.Start)
		n := coretypes.Numbering(r.Numbering)
		got, err := calendar.NextID(r.Previous, start, n)
		switch {
		case r.ID == nil && err == nil:
			t.Errorf("NextID(%q, %s, %s) = %q, Python fails", r.Previous, r.Start, r.Numbering, got)
		case r.ID != nil && (err != nil || got != *r.ID):
			t.Errorf("NextID(%q, %s, %s) = %q, %v; Python %q", r.Previous, r.Start, r.Numbering, got, err, *r.ID)
		}
		if fits := calendar.IDFitsNumbering(r.Previous, start, n); fits != r.Fits {
			t.Errorf("IDFitsNumbering(%q, %s, %s) = %v, Python %v", r.Previous, r.Start, r.Numbering, fits, r.Fits)
		}
	}
}

// Workweek values in every spelling, and the weekend of a team and of a person from them.
func TestWorkweeksMatchPython(t *testing.T) {
	var rows []map[string]any
	golden.Load(t, &rows, "calendar", "workweeks.json")
	for _, r := range rows {
		value := r["value"].(string)
		w, ok, err := calendar.WeekendFromWorkweek(value)
		switch want := r["weekend"].(type) {
		case string:
			if err == nil {
				t.Errorf("%q: want an error, got %v", value, w.Days())
			}
		case nil:
			if err != nil || ok {
				t.Errorf("%q: want no weekend, got %v %v %v", value, w.Days(), ok, err)
			}
		default:
			if err != nil || !ok {
				t.Errorf("%q: %v", value, err)
				continue
			}
			golden.Compare(t, want, toAny(sorted(w.Days())))
		}
		for _, country := range []string{"DE", "SA", "XX"} {
			team := coretypes.NewTeam("x", "x")
			team.Capacity.Country = country
			team.Capacity.Workweek = value
			golden.Compare(t, r["team_"+country], toAny(sorted(calendar.TeamWeekend(team).Days())))
			base := coretypes.NewTeam("x", "x")
			base.Capacity.Country = country
			for _, own := range []string{"SA", "IL", ""} {
				person := coretypes.Person{ID: "p", Name: "p", Country: own, Workweek: value}
				key := "person_" + country + "_" + own
				if own == "" {
					key = "person_" + country + "_None"
				}
				golden.Compare(t, r[key], toAny(sorted(calendar.PersonWeekend(base, person).Days())))
			}
		}
	}
}
