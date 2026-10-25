// Package settings describes the settings of a team for the command line and the window: label,
// explanation, kind, allowed values, reading, parsing and writing (port of settings.py). A new
// setting needs only an entry in All.
package settings

import (
	"errors"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/pymath"
	"github.com/swallat/foresprint/internal/storage"
)

// Kind of a setting.
type Kind string

// The kinds.
const (
	Text   Kind = "text"
	Choice Kind = "choice"
	Int    Kind = "int"
	Number Kind = "number"
	// Percent is a share 0-1, entered and shown as a percentage.
	Percent Kind = "percent"
	Date    Kind = "date"
)

// Option is an allowed value of a choice with its description (an English source text; the
// names of the countries are not translated).
type Option struct{ Key, Label string }

// Value is the value of a setting: nil, string, int, float64 or time.Time.
type Value = any

// Setting is one setting. Label, Help and the option labels are English source texts, translated
// on display.
type Setting struct {
	Key     string
	Label   string
	Help    string
	Kind    Kind
	Options []Option
	// Min and Max limit numbers (as entered, percentages in %).
	Min, Max *float64
	Optional bool
	// OnlyWithoutSprints: only relevant as long as no sprint file exists.
	OnlyWithoutSprints bool
	// Retroactive: the change affects all calculated sprints.
	Retroactive bool
	// Step is the step of the input field in the window (0 = by kind).
	Step float64

	get func(*model.Team) Value
	set func(*model.Team, Value)
	// switchOf is set for the on/off settings.
	switchOf bool
	country  bool
}

// Title is the label in the language in use.
func (s Setting) Title() string { return i18n.T(s.Label) }

// Text is the explanation in the language in use.
func (s Setting) Text() string { return i18n.T(s.Help) }

// Choices are the allowed values with translated descriptions (nil if not a choice).
func (s Setting) Choices() []Option {
	if s.Kind != Choice {
		return nil
	}
	out := make([]Option, len(s.Options))
	for i, o := range s.Options {
		out[i] = Option{o.Key, o.Label}
		if !s.country {
			out[i].Label = i18n.T(o.Label)
		}
	}
	return out
}

func (s Setting) has(key string) bool {
	for _, o := range s.Options {
		if o.Key == key {
			return true
		}
	}
	return false
}

// Get is the current value (nil if not set).
func (s Setting) Get(t *model.Team) Value { return s.get(t) }

// Set writes a value (as returned by Parse) into the team.
func (s Setting) Set(t *model.Team, v Value) { s.set(t, v) }

// Parse converts an input into the value; the error message is translated. An empty input gives
// nil for an optional setting.
func (s Setting) Parse(raw string) (Value, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		if s.Optional {
			return nil, nil
		}
		return nil, errors.New(i18n.T("Please enter a value."))
	}
	switch s.Kind {
	case Text:
		switch s.Key {
		case "capacity.region":
			raw = strings.ToUpper(raw)
			if !knownRegion(raw) {
				return nil, errors.New(i18n.T("Unknown region code: {value}", "value", raw))
			}
		case "sprint.first_id":
			// The ID becomes the file name; what the load path rejects must not be savable here.
			if problem := storage.FileNameProblem(raw, false); problem != "" {
				return nil, errors.New(i18n.T("ID not allowed as a file name ({problem}).", "problem", problem))
			}
		}
		return raw, nil
	case Choice:
		value := raw
		if upper := strings.ToUpper(raw); s.has(upper) {
			value = upper
		}
		if s.switchOf {
			switch strings.ToLower(value) { // an/aus: German UI
			case "an":
				value = "on"
			case "aus":
				value = "off"
			}
		}
		if !s.has(value) {
			keys := make([]string, len(s.Options))
			for i, o := range s.Options {
				keys[i] = o.Key
			}
			return nil, errors.New(i18n.T("Allowed: {values}", "values", strings.Join(keys, ", ")))
		}
		return value, nil
	case Date:
		day, err := time.Parse("2006-01-02", raw)
		if err != nil {
			return nil, errors.New(i18n.T("Enter the date as YYYY-MM-DD."))
		}
		return day, nil
	default: // Int, Number, Percent
		text, ok := pythonDigits(strings.TrimSpace(strings.TrimSuffix(strings.ReplaceAll(raw, ",", "."), "%")))
		number, err := strconv.ParseFloat(text, 64)
		if !ok || err != nil || isWord(raw) {
			return nil, errors.New(i18n.T("Please enter a number."))
		}
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return nil, errors.New(i18n.T("Please enter a finite number."))
		}
		if s.Kind == Int && number != math.Trunc(number) {
			return nil, errors.New(i18n.T("Please enter a whole number."))
		}
		if err := s.CheckRange(number); err != nil {
			return nil, err
		}
		switch s.Kind {
		case Int:
			return int(number), nil
		case Percent:
			return number / 100, nil
		}
		return number, nil
	}
}

// pythonDigits removes the underscores between digits that Python's float() allows ("1_000");
// ok is false for any other underscore.
func pythonDigits(text string) (string, bool) {
	if !strings.Contains(text, "_") {
		return text, true
	}
	isDigit := func(b byte) bool { return b >= '0' && b <= '9' }
	var b strings.Builder
	for i := 0; i < len(text); i++ {
		if text[i] != '_' {
			b.WriteByte(text[i])
			continue
		}
		if i == 0 || i+1 >= len(text) || !isDigit(text[i-1]) || !isDigit(text[i+1]) {
			return "", false
		}
	}
	return b.String(), true
}

// isWord reports the inputs Go's ParseFloat accepts but Python's float() does not ("0x10",
// "1e5" is fine in both): hexadecimal numbers.
func isWord(raw string) bool {
	r := strings.ToLower(strings.TrimLeft(raw, "+-"))
	return strings.HasPrefix(r, "0x") || strings.HasPrefix(r, "0p")
}

func knownRegion(code string) bool {
	for _, c := range calendar.Countries() {
		for _, r := range calendar.Subdivisions(c.Code) {
			if r == code {
				return true
			}
		}
	}
	return false
}

// CheckRange checks a number as entered against Min and Max.
func (s Setting) CheckRange(shown float64) error {
	if s.Min != nil && shown < *s.Min {
		return errors.New(i18n.T("The value must be ≥ {value}.", "value", plain(*s.Min)))
	}
	if s.Max != nil && shown > *s.Max {
		return errors.New(i18n.T("The value must be ≤ {value}.", "value", plain(*s.Max)))
	}
	return nil
}

// Display is the current value as text, the way it would be entered.
func (s Setting) Display(t *model.Team) string {
	switch v := s.get(t).(type) {
	case nil:
		return ""
	case time.Time:
		return v.Format("2006-01-02")
	case float64:
		if s.Kind == Percent {
			return plain(pymath.Round(v*100, 6))
		}
		return plain(v)
	case int:
		return strconv.Itoa(v)
	case string:
		return v
	}
	return ""
}

func plain(v float64) string {
	if v == math.Trunc(v) && !math.IsInf(v, 0) {
		return strconv.FormatInt(int64(v), 10)
	}
	return pymath.General(v)
}

// Applicable lists the settings that make sense for a team with or without recorded sprints.
func Applicable(hasSprints bool) []Setting {
	var out []Setting
	for _, s := range All {
		if !s.OnlyWithoutSprints || !hasSprints {
			out = append(out, s)
		}
	}
	return out
}

// ByKey returns the setting with the key.
func ByKey(key string) (Setting, bool) {
	for _, s := range All {
		if s.Key == key {
			return s, true
		}
	}
	return Setting{}, false
}

// FirstSprintKeys are asked for first when a team is created (in this order).
var FirstSprintKeys = []string{"sprint.numbering", "sprint.first_start", "sprint.first_id"}

// Change is a changed setting with the old and the new value as text.
type Change struct {
	Setting  Setting
	Old, New string
}

// Changes lists the settings that differ between two states of a team.
func Changes(before, after *model.Team) []Change {
	var out []Change
	for _, s := range All {
		if o, n := s.Display(before), s.Display(after); o != n {
			out = append(out, Change{s, o, n})
		}
	}
	return out
}
