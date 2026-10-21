package yamlx

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"strconv"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
)

// decode builds the Go value of a case from the typed JSON of scripts/golden_ext/yamlemit.py.
func decode(t *testing.T, raw json.RawMessage) any {
	t.Helper()
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	for kind, v := range m {
		switch kind {
		case "null":
			return nil
		case "bool":
			var b bool
			must(t, json.Unmarshal(v, &b))
			return b
		case "int":
			var s string
			must(t, json.Unmarshal(v, &s))
			n, ok := new(big.Int).SetString(s, 10)
			if !ok {
				t.Fatalf("int %q", s)
			}
			if n.IsInt64() {
				return n.Int64()
			}
			return n
		case "float":
			var s string
			must(t, json.Unmarshal(v, &s))
			switch s {
			case "inf":
				return math.Inf(1)
			case "-inf":
				return math.Inf(-1)
			case "nan":
				return math.NaN()
			}
			f, err := strconv.ParseFloat(s, 64)
			must(t, err)
			return f
		case "str":
			var s string
			must(t, json.Unmarshal(v, &s))
			return s
		case "date":
			var s string
			must(t, json.Unmarshal(v, &s))
			d, err := time.Parse("2006-01-02", s)
			must(t, err)
			return Date(d)
		case "datetime":
			var s string
			must(t, json.Unmarshal(v, &s))
			for _, layout := range []string{"2006-01-02 15:04:05.999999", "2006-01-02 15:04:05-07:00", "2006-01-02 15:04:05.999999-07:00"} {
				if d, err := time.Parse(layout, s); err == nil {
					return d
				}
			}
			t.Fatalf("datetime %q", s)
		case "list":
			var items []json.RawMessage
			must(t, json.Unmarshal(v, &items))
			out := make([]any, len(items))
			for i, it := range items {
				out[i] = decode(t, it)
			}
			return out
		case "map":
			var pairs [][2]json.RawMessage
			must(t, json.Unmarshal(v, &pairs))
			m := &Map{}
			for _, p := range pairs {
				m.Entries = append(m.Entries, MapEntry{decode(t, p[0]), decode(t, p[1])})
			}
			return m
		}
	}
	t.Fatalf("unknown value %s", raw)
	return nil
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func TestDumpGolden(t *testing.T) {
	var cases []struct {
		Name  string          `json:"name"`
		Value json.RawMessage `json:"value"`
		YAML  string          `json:"yaml"`
	}
	golden.Load(t, &cases, "yamlemit", "cases.json")
	if len(cases) < 500 {
		t.Fatalf("only %d cases", len(cases))
	}
	failed := 0
	for _, c := range cases {
		got, err := Dump(decode(t, c.Value))
		if err != nil {
			t.Errorf("%s: %v", c.Name, err)
			continue
		}
		if got != c.YAML {
			failed++
			if failed <= 10 {
				t.Errorf("%s:\n--- python\n%s\n--- go\n%s", c.Name, c.YAML, got)
			}
		}
	}
	if failed > 0 {
		t.Errorf("%d of %d cases differ", failed, len(cases))
	}
}

func TestFloatText(t *testing.T) {
	for in, want := range map[float64]string{
		1e16: "1.0e+16", 1e15: "1000000000000000.0", 1e-5: "1.0e-05", 0.0001: "0.0001", 41.5: "41.5",
	} {
		if got := floatText(in); got != want {
			t.Errorf("%v: got %s want %s", in, got, want)
		}
	}
	_ = fmt.Sprint
}
