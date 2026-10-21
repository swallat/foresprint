package pymath_test

import (
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/pymath"
)

type reference struct {
	Sums []struct {
		Values []float64 `json:"values"`
		Sum    float64   `json:"sum"`
		Fsum   float64   `json:"fsum"`
		Median float64   `json:"median"`
		FMean  float64   `json:"fmean"`
	} `json:"sums"`
	Formats []map[string]json.RawMessage `json:"formats"`
}

func load(t *testing.T) reference {
	t.Helper()
	var ref reference
	golden.Load(t, &ref, "pymath", "cases.json")
	if len(ref.Sums) == 0 || len(ref.Formats) == 0 {
		t.Fatal("empty reference")
	}
	return ref
}

// The sums are the exact ones of Python: not Close, equal in every bit.
func TestSumsMatchPython(t *testing.T) {
	for _, c := range load(t).Sums {
		if got := pymath.Sum(c.Values); got != c.Sum {
			t.Errorf("Sum(%v) = %v, Python sum() %v", c.Values, got, c.Sum)
		}
		if got := pymath.Fsum(c.Values); got != c.Fsum {
			t.Errorf("Fsum(%v) = %v, Python %v", c.Values, got, c.Fsum)
		}
		if got := pymath.Median(c.Values); got != c.Median {
			t.Errorf("Median(%v) = %v, Python %v", c.Values, got, c.Median)
		}
		if got := pymath.FMean(c.Values); got != c.FMean {
			t.Errorf("FMean(%v) = %v, Python %v", c.Values, got, c.FMean)
		}
	}
}

func TestFormatsMatchPython(t *testing.T) {
	for _, row := range load(t).Formats {
		var x float64
		if err := json.Unmarshal(row["value"], &x); err != nil {
			t.Fatal(err)
		}
		str := func(key string) string {
			var s string
			if err := json.Unmarshal(row[key], &s); err != nil {
				t.Fatalf("%s: %v", key, err)
			}
			return s
		}
		num := func(key string) float64 {
			var f float64
			if err := json.Unmarshal(row[key], &f); err != nil {
				t.Fatalf("%s: %v", key, err)
			}
			return f
		}
		if got, want := pymath.General(x), str("g"); got != want {
			t.Errorf("General(%v) = %q, Python %q", x, got, want)
		}
		for digits := 0; digits <= 4; digits++ {
			if got, want := pymath.Fixed(x, digits, false), str(fmt.Sprintf("fixed%d", digits)); got != want {
				t.Errorf("Fixed(%v, %d) = %q, Python %q", x, digits, got, want)
			}
			if got, want := pymath.Fixed(x, digits, true), str(fmt.Sprintf("grouped%d", digits)); got != want {
				t.Errorf("Fixed(%v, %d, grouped) = %q, Python %q", x, digits, got, want)
			}
		}
		for digits := 0; digits <= 3; digits++ {
			key := "round" + strconv.Itoa(digits)
			if got, want := pymath.Round(x, digits), num(key); got != want && !(math.IsNaN(got) && math.IsNaN(want)) {
				t.Errorf("Round(%v, %d) = %v, Python %v", x, digits, got, want)
			}
		}
	}
}
