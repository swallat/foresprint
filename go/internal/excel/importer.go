package excel

import (
	"fmt"
	"math"
	"math/big"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/yamlx"
)

// LegacySheets are the sheet names older versions wrote (German); the import renames them to
// the current ones.
var LegacySheets = [][2]string{
	{"Einstellungen", SheetSettings},
	{"Fehltage", SheetAbsences},
	{"Personen", SheetPeople},
	{"Sprintdaten", SheetSprints},
	{"Produktliste", SheetProducts},
	{"Produktwerte", SheetValues},
	{"Prognosen", SheetPrognose},
}

var (
	trueWords  = []string{"true", "wahr", "ja", "an", "yes", "on", "1", "x"}
	falseWords = []string{"false", "falsch", "nein", "aus", "no", "off", "0"}
)

// Plausible limits: quantities and days are far below them, dates fall in a sensible period.
const (
	MaxNumber = 1e9
	MinYear   = 1990
	MaxYear   = 2100
)

func dataErr(template string, kv ...any) error {
	return &storage.DataError{Msg: i18n.T(template, kv...)}
}

// CheckSprintID checks that a sprint id can become a file name.
func CheckSprintID(id, where string) (string, error) {
	if problem := storage.FileNameProblem(id, true); problem != "" {
		return "", dataErr("{where}: sprint ID {id} is not allowed ({problem})", "where", where, "id", yamlx.PyRepr(id), "problem", problem)
	}
	return id, nil
}

func columnLetters(col int) string {
	name := ""
	for col++; col > 0; col = (col - 1) / 26 {
		name = string(rune('A'+(col-1)%26)) + name
	}
	return name
}

func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}

// reprValue is repr() of a cell value as openpyxl would have returned it.
func reprValue(v any) string {
	switch x := v.(type) {
	case timeOfDay:
		parts := []int{x.Hour, x.Minute}
		if x.Second != 0 || x.Micro != 0 {
			parts = append(parts, x.Second)
		}
		if x.Micro != 0 {
			parts = append(parts, x.Micro)
		}
		return "datetime.time(" + joinInts(parts) + ")"
	case duration:
		var parts []string
		if x.Days != 0 {
			parts = append(parts, fmt.Sprintf("days=%d", x.Days))
		}
		if x.Seconds != 0 {
			parts = append(parts, fmt.Sprintf("seconds=%d", x.Seconds))
		}
		if x.Micro != 0 {
			parts = append(parts, fmt.Sprintf("microseconds=%d", x.Micro))
		}
		if len(parts) == 0 {
			return "datetime.timedelta(0)"
		}
		return "datetime.timedelta(" + strings.Join(parts, ", ") + ")"
	}
	return yamlx.PyRepr(v)
}

func joinInts(parts []int) string {
	s := make([]string, len(parts))
	for i, p := range parts {
		s[i] = strconv.Itoa(p)
	}
	return strings.Join(s, ", ")
}

// pyStr is str() of a cell value.
func pyStr(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return yamlx.PyFloatRepr(x)
	case bool:
		if x {
			return "True"
		}
		return "False"
	case time.Time:
		return x.Format("2006-01-02 15:04:05")
	case timeOfDay:
		s := fmt.Sprintf("%02d:%02d:%02d", x.Hour, x.Minute, x.Second)
		if x.Micro != 0 {
			s += fmt.Sprintf(".%06d", x.Micro)
		}
		return s
	case duration:
		s := ""
		if x.Days != 0 {
			s = fmt.Sprintf("%d day", x.Days)
			if x.Days != 1 && x.Days != -1 {
				s += "s"
			}
			s += ", "
		}
		s += fmt.Sprintf("%d:%02d:%02d", x.Seconds/3600, x.Seconds%3600/60, x.Seconds%60)
		if x.Micro != 0 {
			s += fmt.Sprintf(".%06d", x.Micro)
		}
		return s
	}
	return fmt.Sprint(v)
}

// parseFloat is Python's float(): finite numbers, and "inf" or "nan" in their spellings.
func parseFloat(text string) (float64, bool) {
	if v, ok := sources.PyFloat(text); ok {
		return v, true
	}
	switch strings.ToLower(pytext.Strip(text)) {
	case "inf", "+inf", "infinity", "+infinity":
		return math.Inf(1), true
	case "-inf", "-infinity":
		return math.Inf(-1), true
	case "nan", "+nan", "-nan":
		return math.NaN(), true
	}
	return 0, false
}

// sheet is a sheet with cell access and error messages that name the sheet and the cell.
type sheet0 struct {
	ws   *worksheet
	name string
}

type sheetRow struct {
	number int
	cells  map[int]any
}

func (s sheet0) rows(first int) []sheetRow {
	var out []sheetRow
	for n := first; n <= s.ws.last; n++ {
		cells := s.ws.rows[n]
		filled := false
		for _, v := range cells {
			if str, ok := v.(string); !ok || str != "" {
				filled = true
				break
			}
		}
		if filled {
			out = append(out, sheetRow{n, cells})
		}
	}
	return out
}

func (s sheet0) where(row, col int) string {
	return fmt.Sprintf("%s!%s%d", s.name, columnLetters(col), row)
}

func (s sheet0) get(r sheetRow, col int) any {
	v := r.cells[col]
	if str, ok := v.(string); ok {
		str = pytext.Strip(str)
		if str == "" {
			return nil
		}
		return str
	}
	return v
}

// number is the numeric value of a cell, nil for an empty cell.
func (s sheet0) number(r sheetRow, col int) (*float64, error) {
	v := s.get(r, col)
	if v == nil {
		return nil, nil
	}
	result := math.NaN()
	switch x := v.(type) {
	case int64:
		result = float64(x)
	case float64:
		result = x
	case bool:
	default:
		if f, ok := parseFloat(strings.ReplaceAll(pyStr(v), ",", ".")); ok {
			result = f
		}
	}
	if _, isBool := v.(bool); isBool || math.IsNaN(result) || math.IsInf(result, 0) {
		// Text, boolean, NaN or infinite: not a number that may be calculated with.
		return nil, dataErr("{where}: a finite number expected, found: {value}", "where", s.where(r.number, col), "value", truncate(reprValue(v), 60))
	}
	if math.Abs(result) > MaxNumber {
		return nil, dataErr("{where}: number outside the allowed range (at most {limit}): {value}",
			"where", s.where(r.number, col), "limit", pyG(MaxNumber), "value", truncate(reprValue(v), 60))
	}
	return &result, nil
}

// flag is the boolean value of a cell: Excel boolean or yes/no text; empty = no. Anything else
// is an error.
func (s sheet0) flag(r sheetRow, col int) (bool, error) {
	v := s.get(r, col)
	if v == nil {
		return false, nil
	}
	if b, ok := v.(bool); ok {
		return b, nil
	}
	word := strings.ToLower(pytext.Strip(pyStr(v)))
	if slices.Contains(trueWords, word) {
		return true, nil
	}
	if slices.Contains(falseWords, word) {
		return false, nil
	}
	return false, dataErr("{where}: yes or no (TRUE or FALSE) expected, found: {value}", "where", s.where(r.number, col), "value", reprValue(v))
}

// text is the text of a cell, nil for an empty cell.
func (s sheet0) text(r sheetRow, col int) (*string, error) {
	v := s.get(r, col)
	if v == nil {
		return nil, nil
	}
	switch x := v.(type) {
	case float64:
		if math.IsInf(x, 0) || math.IsNaN(x) || x != math.Trunc(x) {
			return nil, s.textError(r, col)
		}
		str := new(big.Float).SetFloat64(x)
		i, _ := str.Int(nil)
		out := i.String()
		return &out, nil
	case time.Time:
		return nil, s.textError(r, col)
	}
	out := pyStr(v)
	return &out, nil
}

func (s sheet0) textError(r sheetRow, col int) error {
	return dataErr("{where}: text expected (enter numbers and dates as text, e.g. 2026.20 in quotes or with a leading ' )", "where", s.where(r.number, col))
}

// isoDate is Python's date.fromisoformat.
func isoDate(text string) (time.Time, bool) {
	digits := func(s string) (int, bool) {
		if s == "" {
			return 0, false
		}
		n := 0
		for _, c := range []byte(s) {
			if c < '0' || c > '9' {
				return 0, false
			}
			n = n*10 + int(c-'0')
		}
		return n, true
	}
	build := func(y, m, d int) (time.Time, bool) {
		if y < 1 || y > 9999 || m < 1 || m > 12 || d < 1 {
			return time.Time{}, false
		}
		t := time.Date(y, time.Month(m), d, 0, 0, 0, 0, time.UTC)
		if t.Day() != d {
			return time.Time{}, false
		}
		return t, true
	}
	week := func(y, w, d int) (time.Time, bool) {
		if y < 1 || y > 9999 || d < 1 || d > 7 || w < 1 || w > 53 {
			return time.Time{}, false
		}
		jan4 := time.Date(y, 1, 4, 0, 0, 0, 0, time.UTC)
		monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
		t := monday.AddDate(0, 0, (w-1)*7+d-1)
		if w == 53 {
			if _, lastWeek := time.Date(y, 12, 28, 0, 0, 0, 0, time.UTC).ISOWeek(); lastWeek != 53 {
				return time.Time{}, false
			}
		}
		return t, true
	}
	switch len(text) {
	case 10:
		if text[4] == '-' && text[7] == '-' {
			y, ok1 := digits(text[0:4])
			m, ok2 := digits(text[5:7])
			d, ok3 := digits(text[8:10])
			if ok1 && ok2 && ok3 {
				return build(y, m, d)
			}
		}
		if text[4] == '-' && text[5] == 'W' && text[8] == '-' {
			y, ok1 := digits(text[0:4])
			w, ok2 := digits(text[6:8])
			d, ok3 := digits(text[9:10])
			if ok1 && ok2 && ok3 {
				return week(y, w, d)
			}
		}
	case 8:
		if y, ok := digits(text[0:4]); ok {
			if m, ok2 := digits(text[4:6]); ok2 {
				if d, ok3 := digits(text[6:8]); ok3 {
					return build(y, m, d)
				}
			}
			if text[4] == 'W' {
				if w, ok2 := digits(text[5:7]); ok2 {
					if d, ok3 := digits(text[7:8]); ok3 {
						return week(y, w, d)
					}
				}
			}
			if text[4] == '-' && text[5] == 'W' {
				if w, ok2 := digits(text[6:8]); ok2 {
					return week(y, w, 1)
				}
			}
		}
	case 7:
		if y, ok := digits(text[0:4]); ok && text[4] == 'W' {
			if w, ok2 := digits(text[5:7]); ok2 {
				return week(y, w, 1)
			}
		}
	}
	return time.Time{}, false
}

// day is the date of a cell, nil for an empty cell.
func (s sheet0) day(r sheetRow, col int) (*time.Time, error) {
	v := s.get(r, col)
	if v == nil {
		return nil, nil
	}
	var day time.Time
	if t, ok := v.(time.Time); ok {
		day = time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	} else {
		t, ok := isoDate(pyStr(v))
		if !ok {
			return nil, dataErr("{where}: date expected, found: {value}", "where", s.where(r.number, col), "value", truncate(reprValue(v), 60))
		}
		day = t
	}
	if day.Year() < MinYear || day.Year() > MaxYear {
		return nil, dataErr("{where}: date outside {first} to {last}: {value}",
			"where", s.where(r.number, col), "first", MinYear, "last", MaxYear, "value", day.Format("2006-01-02"))
	}
	return &day, nil
}

func strOf(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// timestamp is the value of a prognosis cell: only a date with a time counts.
func (s sheet0) timestamp(r sheetRow, col int) (time.Time, bool) {
	t, ok := s.get(r, col).(time.Time)
	return t, ok
}
