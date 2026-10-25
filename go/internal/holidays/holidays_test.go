package holidays_test

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/holidays"
)

type sampleYear struct {
	DE        map[string]string `json:"de"`
	EN        map[string]string `json:"en"`
	IsHoliday []string          `json:"is_holiday"`
}

type sample struct {
	Country string                `json:"country"`
	Region  *string               `json:"region"`
	Years   map[string]sampleYear `json:"years"`
}

func parse(t *testing.T, s string) time.Time {
	t.Helper()
	d, err := time.Parse("2006-01-02", s)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

// The names and the holiday flags of a sample of countries and regions equal what the Python
// core answers for the same calls.
func TestSample(t *testing.T) {
	var samples map[string]sample
	golden.Load(t, &samples, "calendar", "holidays-sample.json")
	if len(samples) < 20 {
		t.Fatalf("only %d samples in the reference", len(samples))
	}
	for key, s := range samples {
		region := ""
		if s.Region != nil {
			region = *s.Region
		}
		for year, want := range s.Years {
			wantDays := map[string]bool{}
			for _, d := range want.IsHoliday {
				wantDays[d] = true
			}
			start := parse(t, year+"-01-01")
			for day := start; day.Year() == start.Year(); day = day.AddDate(0, 0, 1) {
				iso := day.Format("2006-01-02")
				if got := holidays.IsHoliday(s.Country, region, day); got != wantDays[iso] {
					t.Fatalf("%s %s: IsHoliday = %v, Python %v", key, iso, got, wantDays[iso])
				}
				for lang, names := range map[string]map[string]string{"de": want.DE, "en": want.EN} {
					if got := holidays.Name(s.Country, region, day, lang); got != names[iso] {
						t.Fatalf("%s %s (%s): name %q, Python %q", key, iso, lang, got, names[iso])
					}
				}
			}
		}
	}
}

type countryInfo struct {
	Name         string   `json:"name"`
	Subdivisions []string `json:"subdivisions"`
	Weekend      []int    `json:"weekend"`
}

func TestCountries(t *testing.T) {
	var want map[string]countryInfo
	golden.Load(t, &want, "calendar", "countries.json")
	got := holidays.Countries()
	if len(got) != len(want) {
		t.Fatalf("%d countries, Python %d", len(got), len(want))
	}
	for _, c := range got {
		w, ok := want[c.Code]
		if !ok {
			t.Fatalf("country %s is not in the Python list", c.Code)
		}
		if c.Name != w.Name {
			t.Errorf("%s: name %q, Python %q", c.Code, c.Name, w.Name)
		}
		gotSub := holidays.Subdivisions(c.Code)
		sort.Strings(gotSub)
		wantSub := append([]string(nil), w.Subdivisions...)
		sort.Strings(wantSub)
		if strings.Join(gotSub, ",") != strings.Join(wantSub, ",") {
			t.Errorf("%s: subdivisions %v, Python %v", c.Code, gotSub, wantSub)
		}
		var weekend []int
		for _, d := range holidays.Weekend(c.Code) {
			weekend = append(weekend, (int(d)+6)%7) // back to Python's Monday = 0
		}
		sort.Ints(weekend)
		if fmt.Sprint(weekend) != fmt.Sprint(w.Weekend) {
			t.Errorf("%s: weekend %v, Python %v", c.Code, weekend, w.Weekend)
		}
	}
}

func TestFallbacks(t *testing.T) {
	d := parse(t, "2026-01-01")
	if !holidays.IsHoliday("de", "", d) || !holidays.IsHoliday("DEU", "", d) {
		t.Error("country codes are case-insensitive and accept the alternative codes")
	}
	if !holidays.IsHoliday("DE", "no-such-region", d) {
		t.Error("an unknown region falls back to the nationwide holidays")
	}
	if holidays.IsHoliday("ZZ", "", d) {
		t.Error("an unknown country has no holidays")
	}
	if holidays.IsHoliday("DE", "", parse(t, "2060-01-01")) {
		t.Error("outside the covered years nothing is a holiday")
	}
	if got := holidays.Name("DE", "", d, "xx"); got != "New Year's Day" {
		t.Errorf("an unknown language gives English, got %q", got)
	}
	if got := holidays.Weekend("ZZ"); len(got) != 2 {
		t.Errorf("unknown country: Saturday and Sunday, got %v", got)
	}
}

func TestInfo(t *testing.T) {
	info := holidays.Info()
	if info.FirstYear != 2001 || info.LastYear != 2050 || info.HolidaysVersion == "" {
		t.Errorf("unexpected data description: %+v", info)
	}
	if strings.Join(info.Languages, ",") != "de,en" {
		t.Errorf("languages %v", info.Languages)
	}
}

type digests struct {
	FirstYear int                          `json:"first_year"`
	LastYear  int                          `json:"last_year"`
	Digests   map[string]map[string]string `json:"digests"`
	Aliases   map[string]string            `json:"aliases"`
}

func digest(list []holidays.Holiday) string {
	var b strings.Builder
	for _, h := range list {
		b.WriteString(h.Date.Format("2006-01-02") + "\t" + h.Name + "\n")
	}
	sum := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(sum[:])[:24]
}

// Every calendar of the library (all countries and regions, 2001-2050, both languages) is in
// the data and equals the Python result; checked by a digest per calendar.
func TestAllCalendars(t *testing.T) {
	var want digests
	golden.Load(t, &want, "calendar", "holidays-digest.json")
	if len(want.Digests) < 800 {
		t.Fatalf("only %d calendars in the reference", len(want.Digests))
	}
	for key, byLang := range want.Digests {
		country, region, _ := strings.Cut(key, "/")
		for lang, sum := range byLang {
			if got := digest(holidays.List(country, region, lang, want.FirstYear, want.LastYear)); got != sum {
				t.Errorf("%s (%s): digest %s, Python %s", key, lang, got, sum)
			}
		}
	}
	for alias, code := range want.Aliases {
		if a, b := holidays.Subdivisions(alias), holidays.Subdivisions(code); fmt.Sprint(a) != fmt.Sprint(b) {
			t.Errorf("alias %s does not lead to %s", alias, code)
		}
	}
}

// Alias spellings and deprecated codes of a region give the regional calendar, as in Python.
func TestSubdivisionAliases(t *testing.T) {
	cases := []struct{ country, alias, region string }{
		{"DE", "Bayern", "BY"},
		{"DE", "BYP", "BY"},
	}
	for _, c := range cases {
		for year := 2024; year <= 2027; year++ {
			a := holidays.List(c.country, c.alias, "en", year, year)
			b := holidays.List(c.country, c.region, "en", year, year)
			if len(a) == 0 || fmt.Sprint(a) != fmt.Sprint(b) {
				t.Errorf("%s/%s %d differs from %s", c.country, c.alias, year, c.region)
			}
		}
	}
	// US/Arkansas has no Columbus Day in 2026 (the nationwide list has one).
	if got, nat := len(holidays.List("US", "Arkansas", "en", 2026, 2026)), len(holidays.List("US", "", "en", 2026, 2026)); got == nat {
		t.Errorf("US/Arkansas should differ from the nationwide list (%d)", got)
	}
}
