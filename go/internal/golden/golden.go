// Package golden compares the results of the Go core with the reference files that the Python
// core wrote (repository folder golden/, produced by scripts/golden.py).
//
// Tests load a reference with Load, build the same structure from the Go result (as a value that
// encodes to the same JSON) and hand both to Compare. Numbers are compared with a small relative
// tolerance (Tolerance) because both cores may sum floating point numbers in a different
// order; everything else, in particular strings, must match exactly.
package golden

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// Tolerance is the relative (and, near zero, absolute) difference at which two numbers still
// count as equal. The Python core and the Go core run the same IEEE 754 double arithmetic, so
// this only absorbs a different order of additions.
const Tolerance = 1e-9

// Dir returns the golden folder of the repository.
func Dir(tb testing.TB) string {
	tb.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		tb.Fatal("golden: cannot locate the source file")
	}
	dir := filepath.Dir(file)
	for {
		candidate := filepath.Join(dir, "golden")
		if info, err := os.Stat(filepath.Join(candidate, "expected")); err == nil && info.IsDir() {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			tb.Fatal("golden: no golden/expected folder above " + filepath.Dir(file))
		}
		dir = parent
	}
}

// Path is the file below golden/expected.
func Path(tb testing.TB, elem ...string) string {
	tb.Helper()
	return filepath.Join(append([]string{Dir(tb), "expected"}, elem...)...)
}

// Load reads a JSON reference into out (a pointer). Numbers stay exact when out holds
// json.Number or any.
func Load(tb testing.TB, out any, elem ...string) {
	tb.Helper()
	raw, err := os.ReadFile(Path(tb, elem...))
	if err != nil {
		tb.Fatal(err)
	}
	if err := decode(raw, out); err != nil {
		tb.Fatalf("%s: %v", filepath.Join(elem...), err)
	}
}

func decode(raw []byte, out any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	return dec.Decode(out)
}

// Compare fails the test for every difference between want (usually a reference loaded with
// Load into an any) and got (any value; it is encoded to JSON first). At most 20 differences
// are reported, each with the path of the value.
func Compare(tb testing.TB, want, got any) {
	tb.Helper()
	diffs, err := Diff(want, got)
	if err != nil {
		tb.Fatal(err)
	}
	if len(diffs) == 0 {
		return
	}
	more := ""
	if len(diffs) > 20 {
		more = fmt.Sprintf("\n... and %d more", len(diffs)-20)
		diffs = diffs[:20]
	}
	tb.Fatalf("difference(s) from the Python reference:\n%s%s", strings.Join(diffs, "\n"), more)
}

// Diff lists the differences between want and got, one line each, with the path of the value.
func Diff(want, got any) ([]string, error) {
	var wantAny, gotAny any
	for _, pair := range []struct {
		in  any
		out *any
	}{{want, &wantAny}, {got, &gotAny}} {
		raw, err := json.Marshal(pair.in)
		if err != nil {
			return nil, err
		}
		if err := decode(raw, pair.out); err != nil {
			return nil, err
		}
	}
	var diffs []string
	diff(&diffs, "$", wantAny, gotAny)
	return diffs, nil
}

func diff(out *[]string, path string, want, got any) {
	add := func(format string, args ...any) {
		*out = append(*out, path+": "+fmt.Sprintf(format, args...))
	}
	switch w := want.(type) {
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			add("want an object, got %T", got)
			return
		}
		keys := make([]string, 0, len(w)+len(g))
		seen := map[string]bool{}
		for k := range w {
			keys = append(keys, k)
			seen[k] = true
		}
		for k := range g {
			if !seen[k] {
				keys = append(keys, k)
			}
		}
		sort.Strings(keys)
		for _, k := range keys {
			wv, wok := w[k]
			gv, gok := g[k]
			switch {
			case !gok:
				*out = append(*out, path+"."+k+": missing in the Go result")
			case !wok:
				*out = append(*out, path+"."+k+": not in the Python reference")
			default:
				diff(out, path+"."+k, wv, gv)
			}
		}
	case []any:
		g, ok := got.([]any)
		if !ok {
			add("want an array, got %T", got)
			return
		}
		if len(w) != len(g) {
			add("want %d elements, got %d", len(w), len(g))
			return
		}
		for i := range w {
			diff(out, fmt.Sprintf("%s[%d]", path, i), w[i], g[i])
		}
	case json.Number:
		g, ok := got.(json.Number)
		if !ok {
			add("want the number %s, got %v", w, got)
			return
		}
		if !numbersEqual(w, g) {
			add("want %s, got %s", w, g)
		}
	case nil:
		if got != nil {
			add("want null, got %v", got)
		}
	default: // string, bool
		if want != got {
			add("want %v, got %v", want, got)
		}
	}
}

func numbersEqual(want, got json.Number) bool {
	if want.String() == got.String() {
		return true
	}
	w, err1 := strconv.ParseFloat(want.String(), 64)
	g, err2 := strconv.ParseFloat(got.String(), 64)
	if err1 != nil || err2 != nil {
		return false
	}
	return Close(w, g)
}

// Close reports whether two numbers are equal within Tolerance.
func Close(a, b float64) bool {
	if a == b {
		return true
	}
	scale := math.Max(1, math.Max(math.Abs(a), math.Abs(b)))
	return math.Abs(a-b) <= Tolerance*scale
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
