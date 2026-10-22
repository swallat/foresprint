package yamlx_test

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/yamlx"
)

type enc struct {
	T       string  `json:"t"`
	V       any     `json:"v"`
	Entries [][]enc `json:"entries"`
	Items   []enc   `json:"items"`
}

type result struct {
	Value *enc   `json:"value"`
	Error string `json:"error"`
}

type refs struct {
	Scalars []struct {
		Text  string  `json:"text"`
		Plain *result `json:"plain"`
		Tag   *string `json:"tag"`
	} `json:"scalars"`
	Docs []struct {
		Name string `json:"name"`
		Text string `json:"text"`
		result
	} `json:"docs"`
}

// same compares a loaded value with the reference; it returns a description of the first
// difference or "".
func same(got any, want enc) string {
	switch want.T {
	case "null":
		if got != nil {
			return fmt.Sprintf("want null, got %#v", got)
		}
	case "bool":
		if b, ok := got.(bool); !ok || b != want.V.(bool) {
			return fmt.Sprintf("want bool %v, got %#v", want.V, got)
		}
	case "int":
		w, _ := new(big.Int).SetString(want.V.(string), 10)
		var g *big.Int
		switch v := got.(type) {
		case int64:
			g = big.NewInt(v)
		case *big.Int:
			g = v
		default:
			return fmt.Sprintf("want int %v, got %#v", want.V, got)
		}
		if g.Cmp(w) != 0 {
			return fmt.Sprintf("want int %v, got %v", w, g)
		}
	case "float":
		f, ok := got.(float64)
		if !ok {
			return fmt.Sprintf("want float %v, got %#v", want.V, got)
		}
		w, _ := strconv.ParseFloat(want.V.(string), 64)
		if math.IsNaN(w) != math.IsNaN(f) || (!math.IsNaN(w) && math.Float64bits(w) != math.Float64bits(f)) {
			return fmt.Sprintf("want float %v, got %v", want.V, f)
		}
	case "str":
		if s, ok := got.(string); !ok || s != want.V.(string) {
			return fmt.Sprintf("want str %q, got %#v", want.V, got)
		}
	case "date":
		d, ok := got.(yamlx.Date)
		if !ok || time.Time(d).Format("2006-01-02") != want.V.(string) {
			return fmt.Sprintf("want date %v, got %#v", want.V, got)
		}
	case "datetime":
		tm, ok := got.(time.Time)
		if !ok {
			return fmt.Sprintf("want datetime %v, got %#v", want.V, got)
		}
		text := want.V.(string)
		aware := len(text) > 19 && (text[len(text)-6] == '+' || text[len(text)-6] == '-')
		layout := "2006-01-02T15:04:05.999999"
		if aware {
			layout += "-07:00"
		}
		w, err := time.Parse(layout, text)
		if err != nil {
			return "bad reference " + text
		}
		if !w.Equal(tm) || aware != (tm.Location() != time.UTC) {
			return fmt.Sprintf("want datetime %v, got %v (%v)", text, tm, tm.Location())
		}
	case "seq":
		s, ok := got.([]any)
		if !ok || len(s) != len(want.Items) {
			return fmt.Sprintf("want seq of %d, got %#v", len(want.Items), got)
		}
		for i := range s {
			if d := same(s[i], want.Items[i]); d != "" {
				return fmt.Sprintf("[%d]: %s", i, d)
			}
		}
	case "map":
		m, ok := got.(*yamlx.Map)
		if !ok || m.Len() != len(want.Entries) {
			return fmt.Sprintf("want map of %d, got %#v", len(want.Entries), got)
		}
		for i, e := range want.Entries {
			if d := same(m.Entries[i].Key, e[0]); d != "" {
				return fmt.Sprintf("key %d: %s", i, d)
			}
			if d := same(m.Entries[i].Value, e[1]); d != "" {
				return fmt.Sprintf("value %d: %s", i, d)
			}
		}
	default:
		return "unsupported reference type " + want.T
	}
	return ""
}

func TestGolden(t *testing.T) {
	var ref refs
	golden.Load(t, &ref, "yamlx", "cases.json")
	check := func(name, text string, want result) {
		got, err := yamlx.Load(text)
		if want.Error != "" {
			if err == nil {
				t.Errorf("%s: want an error (%s), got %#v", name, want.Error, got)
			}
			return
		}
		if err != nil {
			t.Errorf("%s: %v", name, err)
			return
		}
		if d := same(got, *want.Value); d != "" {
			t.Errorf("%s: %s", name, d)
		}
	}
	for _, c := range ref.Scalars {
		if c.Plain != nil {
			check(fmt.Sprintf("scalar %q", c.Text), "x: "+c.Text+"\n", wrapMap(*c.Plain))
		}
		if c.Tag != nil && c.Plain != nil && c.Plain.Value != nil {
			if got := yamlx.ResolveTag(c.Text); "tag:yaml.org,2002:"+got[2:] != *c.Tag {
				t.Errorf("scalar %q: tag %s, want %s", c.Text, got, *c.Tag)
			}
		}
	}
	for _, d := range ref.Docs {
		check(d.Name, d.Text, d.result)
	}
}

// wrapMap turns the reference of "x: <text>" into the form check expects (it is already a map).
func wrapMap(r result) result { return r }
