// Package coretest loads the team folders of the golden cases into the types of the calculation
// packages, for their tests. It reads only what the calculation needs and trusts the files (the
// complete reader with validation is the storage of the port).
package coretest

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/storage"
)

// Load reads the team folder of a golden case with the storage of the port.
func Load(tb testing.TB, c golden.Case) *storage.TeamData {
	tb.Helper()
	dir := c.TeamDir(tb)
	data, err := storage.NewRepository(filepath.Dir(dir)).Load(filepath.Base(dir))
	if err != nil {
		tb.Fatalf("%s: %v", dir, err)
	}
	return data
}

// Today is the date the case's references were calculated for.
func Today(tb testing.TB, c golden.Case) time.Time {
	tb.Helper()
	d, err := time.Parse("2006-01-02", c.Today)
	if err != nil {
		tb.Fatal(err)
	}
	return d
}

var dateTime = regexp.MustCompile(`^(\d{4}-\d{2}-\d{2})T00:00:00Z$`)

// emptyIsNull are the keys whose empty text is None in Python.
var emptyIsNull = map[string]bool{"region": true, "country": true, "workweek": true}

// JSON is v as the generic JSON value the golden comparison reads, in the form of the Python
// references: dates as YYYY-MM-DD, empty region, country and workweek as null.
func JSON(tb testing.TB, v any) any {
	tb.Helper()
	out, err := ToAny(v)
	if err != nil {
		tb.Fatal(err)
	}
	return out
}

// ToAny is JSON without a test, for helpers of table tests.
func ToAny(v any) (any, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var out any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&out); err != nil {
		return nil, err
	}
	return normalize("", out), nil
}

func normalize(key string, v any) any {
	switch x := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(x))
		_, isSprint := x["Absences"]
		if !isSprint {
			_, isSprint = x["absences"]
		}
		for k, e := range x {
			k = snake(k)
			if isSprint && unmodelledKey[k] {
				continue
			}
			out[k] = normalize(k, e)
		}
		return out
	case []any:
		for i, e := range x {
			x[i] = normalize("", e)
		}
	case string:
		if m := dateTime.FindStringSubmatch(x); m != nil {
			return m[1]
		}
		if x == "" && emptyIsNull[key] {
			return nil
		}
	}
	return v
}

// snake turns a Go field name (ForecastPlan, FTE, ID) into the key of the Python references
// (forecast_plan, fte, id); keys that are already lower case stay.
func snake(name string) string {
	if name == "" || name[0] < 'A' || name[0] > 'Z' {
		return name
	}
	var b strings.Builder
	for i, r := range name {
		if r >= 'A' && r <= 'Z' {
			if i > 0 {
				prev := name[i-1]
				nextLower := i+1 < len(name) && name[i+1] >= 'a' && name[i+1] <= 'z'
				if (prev >= 'a' && prev <= 'z') || (prev >= '0' && prev <= '9') ||
					(prev >= 'A' && prev <= 'Z' && nextLower) {
					b.WriteByte('_')
				}
			}
			r += 'a' - 'A'
		}
		b.WriteRune(r)
	}
	return b.String()
}

// unmodelled are the fields of the Python sprint that the calculation types do not have.
var unmodelled = []string{"products", "note", "production_planned", "production_done", "not_done", "additional_done", "prognoses"}

var unmodelledKey = func() map[string]bool {
	m := map[string]bool{}
	for _, k := range unmodelled {
		m[k] = true
	}
	return m
}()

// Prune removes the keys of the Python sprint that the calculation does not compare from a
// reference, so that it can be compared with a Go result (which ToAny prunes the same way).
func Prune(want any) any {
	switch x := want.(type) {
	case map[string]any:
		if _, ok := x["absences"]; ok {
			for _, k := range unmodelled {
				delete(x, k)
			}
		}
		for k, e := range x {
			x[k] = Prune(e)
		}
	case []any:
		for i, e := range x {
			x[i] = Prune(e)
		}
	}
	return want
}

// German is the code of the German language; its texts come from the catalog of internal/i18n.
func German(tb testing.TB) string {
	tb.Helper()
	return "de"
}
