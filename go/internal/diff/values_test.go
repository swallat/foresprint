package diff_test

import (
	"fmt"
	"math/big"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/diff"
	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/yamlx"
)

type refChange struct {
	Path    []string `json:"path"`
	Kind    string   `json:"kind"`
	Label   string   `json:"label"`
	Old     any      `json:"old"`
	New     any      `json:"new"`
	OldSlim any      `json:"old_slim"`
	NewSlim any      `json:"new_slim"`
}

type refs struct {
	Cases []struct {
		Name    string      `json:"name"`
		Old     string      `json:"old"`
		New     string      `json:"new"`
		Changes []refChange `json:"changes"`
	} `json:"cases"`
	Keyed []struct {
		Text  string   `json:"text"`
		Keyed []string `json:"keyed"`
	} `json:"keyed"`
}

// jsonable is the structure the reference writes for a value (see jsonable in scripts/golden.py).
func jsonable(v any) any {
	switch x := v.(type) {
	case nil, bool, string, float64:
		return x
	case int64:
		return float64(x)
	case *big.Int:
		f, _ := new(big.Float).SetInt(x).Float64()
		return f
	case yamlx.Date:
		return time.Time(x).Format("2006-01-02")
	case time.Time:
		s := x.Format("2006-01-02T15:04:05.999999")
		if x.Location() != time.UTC {
			s = x.Format("2006-01-02T15:04:05.999999-07:00")
		}
		return s
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = jsonable(e)
		}
		return out
	case *yamlx.Map:
		out := map[string]any{}
		for _, e := range x.Entries {
			k := e.Key
			if k == nil {
				out["(none)"] = jsonable(e.Value)
				continue
			}
			out[yamlx.PyStr(jsonable2key(k))] = jsonable(e.Value)
		}
		return out
	}
	panic(fmt.Sprintf("jsonable: %T", v))
}

func jsonable2key(k any) any {
	if d, ok := k.(yamlx.Date); ok {
		return time.Time(d).Format("2006-01-02")
	}
	return k
}

func value(v any) any {
	if v == diff.Missing {
		return map[string]any{"missing": true}
	}
	return jsonable(v)
}

func load(t *testing.T, text string) any {
	if text == "" {
		return diff.Missing
	}
	v, err := yamlx.Load(text)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestGolden(t *testing.T) {
	var ref refs
	golden.Load(t, &ref, "diff", "cases.json")
	for _, c := range ref.Cases {
		t.Run(c.Name, func(t *testing.T) {
			old, new := load(t, c.Old), load(t, c.New)
			var changes []diff.ValueChange
			if old == diff.Missing || new == diff.Missing {
				changes = []diff.ValueChange{{Old: old, New: new}}
			} else {
				var err error
				if changes, err = diff.Values(old, new); err != nil {
					t.Fatal(err)
				}
			}
			var got []refChange
			for _, ch := range changes {
				rc := refChange{Path: append([]string{}, ch.Path...), Kind: ch.Kind(), Label: ch.Label(), Old: value(ch.Old), New: value(ch.New)}
				if ch.Old != diff.Missing {
					rc.OldSlim = value(diff.Slim(ch.Old))
				}
				if ch.New != diff.Missing {
					rc.NewSlim = value(diff.Slim(ch.New))
				}
				got = append(got, rc)
			}
			if got == nil {
				got = []refChange{}
			}
			want := c.Changes
			if want == nil {
				want = []refChange{}
			}
			golden.Compare(t, want, got)
		})
	}
	for _, k := range ref.Keyed {
		v, err := yamlx.Load(k.Text)
		if err != nil {
			t.Fatal(err)
		}
		m := diff.Keyed(v)
		if (m == nil) != (k.Keyed == nil) {
			t.Errorf("%q: keyed %v, want %v", k.Text, m != nil, k.Keyed != nil)
			continue
		}
		if m != nil {
			for i, e := range m.Entries {
				if e.Key != k.Keyed[i] {
					t.Errorf("%q: key %d %v, want %v", k.Text, i, e.Key, k.Keyed[i])
				}
			}
		}
	}
}
