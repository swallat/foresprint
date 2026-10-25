// Package holidays answers holiday and weekend questions from data that scripts/gen_holidays.py
// generates from the Python "holidays" library: every country and region of the library,
// 2001-2050, names in German and English. The data is embedded in the program; there is no
// runtime dependency on Python or on the network.
//
// The lookups follow the Python core (calendar.py) exactly: country codes are case-insensitive
// (and may be the alternative codes of the library, e.g. "UK"); an unknown region falls back to
// the nationwide holidays; an unknown country has no holidays at all.
package holidays

import (
	"archive/zip"
	"bytes"
	_ "embed" // the data file
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"
	"sync"
	"time"
)

//go:embed data/holidays.zip
var embedded []byte

// supportedFormat is the only data format this code reads.
const supportedFormat = 1

var epoch = time.Date(2001, 1, 1, 0, 0, 0, 0, time.UTC)

// Source says where the data comes from; shown in the about dialog and in bug reports.
type Source struct {
	HolidaysVersion string
	FirstYear       int
	LastYear        int
	Languages       []string
}

// meta is meta.json of the archive.
type meta struct {
	Format          int               `json:"format"`
	HolidaysVersion string            `json:"holidays_version"`
	FirstYear       int               `json:"first_year"`
	LastYear        int               `json:"last_year"`
	Languages       []string          `json:"languages"`
	Aliases         map[string]string `json:"aliases"`
	Countries       map[string]string `json:"countries"`
}

type rawCountry struct {
	Weekend      []int                  `json:"weekend"`
	Subdivisions []string               `json:"subdivisions"`
	Names        [][]string             `json:"names"`
	Aliases      map[string]string      `json:"subdivision_aliases"`
	Calendars    map[string]rawCalendar `json:"calendars"`
}

type rawCalendar struct {
	Days  []int `json:"days"`
	Names []int `json:"names"`
}

// calendar is one country or region: sorted day numbers (days since the epoch) and the index of
// the name of each.
type calendar struct {
	days  []int32
	names []int32
}

type country struct {
	aliases      map[string]string
	names        [][]string
	name         string
	weekend      []time.Weekday
	subdivisions []string
	calendars    map[string]*calendar
}

var (
	loadOnce sync.Once
	loadErr  error
	archive  *zip.Reader
	doc      *meta
	langCol  map[string]int

	cacheMu sync.Mutex
	cache   = map[string]*country{}
)

func readFile(path string) ([]byte, error) {
	for _, f := range archive.File {
		if f.Name == path {
			rc, err := f.Open()
			if err != nil {
				return nil, err
			}
			defer func() { _ = rc.Close() }()
			return io.ReadAll(rc)
		}
	}
	return nil, fmt.Errorf("holidays: %s missing in the data file", path)
}

func readJSON(path string, out any) error {
	raw, err := readFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("holidays: %s: %w", path, err)
	}
	return nil
}

// load opens the archive and reads the small shared parts; countries follow on demand.
func load() error {
	loadOnce.Do(func() {
		r, err := zip.NewReader(bytes.NewReader(embedded), int64(len(embedded)))
		if err != nil {
			loadErr = err
			return
		}
		archive = r
		var m meta
		if loadErr = readJSON("meta.json", &m); loadErr != nil {
			return
		}
		if m.Format != supportedFormat {
			loadErr = fmt.Errorf("holidays: data format %d not supported", m.Format)
			return
		}
		doc = &m
		langCol = map[string]int{}
		for i, l := range m.Languages {
			langCol[l] = i
		}
	})
	return loadErr
}

// mustLoad panics on a damaged embedded file: that is a build error, caught by the tests.
func mustLoad() {
	if err := load(); err != nil {
		panic(err)
	}
}

// Info describes the embedded data.
func Info() Source {
	mustLoad()
	return Source{
		HolidaysVersion: doc.HolidaysVersion,
		FirstYear:       doc.FirstYear,
		LastYear:        doc.LastYear,
		Languages:       append([]string(nil), doc.Languages...),
	}
}

// canonical maps a country code (any case, alternative codes included) to the code of the data;
// "" if unknown.
func canonical(code string) string {
	code = strings.ToUpper(code)
	if _, ok := doc.Countries[code]; ok {
		return code
	}
	return doc.Aliases[code]
}

func lookup(code string) *country {
	mustLoad()
	key := canonical(code)
	if key == "" {
		return nil
	}
	cacheMu.Lock()
	defer cacheMu.Unlock()
	if c, ok := cache[key]; ok {
		return c
	}
	var rc rawCountry
	if err := readJSON("countries/"+key+".json", &rc); err != nil {
		panic(err)
	}
	c := &country{name: doc.Countries[key], names: rc.Names, aliases: rc.Aliases, subdivisions: rc.Subdivisions, calendars: map[string]*calendar{}}
	for _, d := range rc.Weekend {
		// The data counts Monday as 0 (Python); time.Weekday counts Sunday as 0.
		c.weekend = append(c.weekend, time.Weekday((d+1)%7))
	}
	for region, rcal := range rc.Calendars {
		cal := &calendar{days: make([]int32, len(rcal.Days)), names: make([]int32, len(rcal.Names))}
		day := 0
		for i, delta := range rcal.Days {
			day += delta
			cal.days[i] = int32(day)
		}
		for i, n := range rcal.Names {
			cal.names[i] = int32(n)
		}
		c.calendars[region] = cal
	}
	cache[key] = c
	return c
}

// Country is an entry of the country list.
type Country struct {
	Code string
	Name string
}

// Countries lists all supported countries by code (alternative codes are not listed, but
// accepted everywhere).
func Countries() []Country {
	mustLoad()
	out := make([]Country, 0, len(doc.Countries))
	for code, name := range doc.Countries {
		out = append(out, Country{Code: code, Name: name})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Code < out[j].Code })
	return out
}

// Subdivisions lists the valid region codes of a country (nil for an unknown country).
func Subdivisions(countryCode string) []string {
	c := lookup(countryCode)
	if c == nil {
		return nil
	}
	return append([]string(nil), c.subdivisions...)
}

// Weekend returns the days off of the country; Saturday and Sunday for an unknown country, as
// the Python core does.
func Weekend(countryCode string) []time.Weekday {
	if c := lookup(countryCode); c != nil {
		return append([]time.Weekday(nil), c.weekend...)
	}
	return []time.Weekday{time.Saturday, time.Sunday}
}

// Covers reports whether the data includes the year. Outside the range IsHoliday is false.
func Covers(year int) bool {
	mustLoad()
	return year >= doc.FirstYear && year <= doc.LastYear
}

func dayNumber(day time.Time) int {
	y, m, d := day.Date()
	return int(time.Date(y, m, d, 0, 0, 0, 0, time.UTC).Sub(epoch) / (24 * time.Hour))
}

// find returns the index of the day in the calendar of country and region (an unknown or empty
// region means the nationwide holidays), or -1.
func find(countryCode, region string, day time.Time) (*country, *calendar, int) {
	c := lookup(countryCode)
	if c == nil || !Covers(day.Year()) {
		return nil, nil, -1
	}
	cal := c.region(region)
	if cal == nil {
		return c, nil, -1
	}
	n := int32(dayNumber(day))
	i := sort.Search(len(cal.days), func(i int) bool { return cal.days[i] >= n })
	if i < len(cal.days) && cal.days[i] == n {
		return c, cal, i
	}
	return c, cal, -1
}

// IsHoliday reports whether the day is a public holiday in the country and region.
func IsHoliday(countryCode, region string, day time.Time) bool {
	_, _, i := find(countryCode, region, day)
	return i >= 0
}

// Name is the name of the holiday in the language ("de", "en"), or "" if the day is none. An
// unknown language gives the English name.
func Name(countryCode, region string, day time.Time, lang string) string {
	c, cal, i := find(countryCode, region, day)
	if i < 0 {
		return ""
	}
	col, ok := langCol[lang]
	if !ok {
		col = langCol["en"]
	}
	return c.names[cal.names[i]][col]
}

// Holiday is one public holiday.
type Holiday struct {
	Date time.Time // midnight UTC
	Name string
}

// List returns all holidays of the country and region in the years first..last (clamped to the
// covered years), oldest first, with the names in the language.
func List(countryCode, region, lang string, first, last int) []Holiday {
	c := lookup(countryCode)
	if c == nil {
		return nil
	}
	cal := c.region(region)
	if cal == nil {
		return nil
	}
	col, ok := langCol[lang]
	if !ok {
		col = langCol["en"]
	}
	var out []Holiday
	for i, n := range cal.days {
		day := epoch.AddDate(0, 0, int(n))
		if day.Year() < first || day.Year() > last {
			continue
		}
		out = append(out, Holiday{Date: day, Name: c.names[cal.names[i]][col]})
	}
	return out
}

// region returns the calendar for a region code or alias; the nationwide one for an unknown
// region (nil if the country has none).
func (c *country) region(code string) *calendar {
	if cal := c.calendars[code]; cal != nil {
		return cal
	}
	if target, ok := c.aliases[code]; ok {
		if cal := c.calendars[target]; cal != nil {
			return cal
		}
	}
	return c.calendars[""]
}
