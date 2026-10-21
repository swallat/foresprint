package yamlmerge_test

import (
	"encoding/json"
	"fmt"
	"strconv"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/yamlmerge"
)

// decode turns the tagged JSON of golden/expected/yamlmerge into a value tree.
func decode(t *testing.T, raw json.RawMessage) any {
	t.Helper()
	var parts []json.RawMessage
	if err := json.Unmarshal(raw, &parts); err != nil {
		t.Fatalf("bad tagged value %s: %v", raw, err)
	}
	var kind string
	if err := json.Unmarshal(parts[0], &kind); err != nil {
		t.Fatal(err)
	}
	str := func() string {
		var s string
		if err := json.Unmarshal(parts[1], &s); err != nil {
			t.Fatal(err)
		}
		return s
	}
	switch kind {
	case "missing":
		return yamlmerge.Missing
	case "null":
		return nil
	case "bool":
		var b bool
		if err := json.Unmarshal(parts[1], &b); err != nil {
			t.Fatal(err)
		}
		return b
	case "int":
		n, err := strconv.ParseInt(str(), 10, 64)
		if err != nil {
			t.Fatal(err)
		}
		return n
	case "float":
		switch s := str(); s {
		case "nan":
			return nan()
		case "inf":
			return inf(1)
		case "-inf":
			return inf(-1)
		default:
			f, err := strconv.ParseFloat(s, 64)
			if err != nil {
				t.Fatal(err)
			}
			return f
		}
	case "str":
		return str()
	case "date":
		d, err := time.Parse("2006-01-02", str())
		if err != nil {
			t.Fatal(err)
		}
		return yamlmerge.Date{Year: d.Year(), Month: d.Month(), Day: d.Day()}
	case "datetime":
		d, ok := yamlmerge.ParseISO(str())
		if !ok {
			t.Fatalf("datetime %q", str())
		}
		// microseconds are kept by the reference
		if frac := fraction(str()); frac > 0 {
			d.Time = d.Time.Add(time.Duration(frac) * time.Microsecond)
		}
		return d
	case "list":
		var items []json.RawMessage
		if err := json.Unmarshal(parts[1], &items); err != nil {
			t.Fatal(err)
		}
		out := make([]any, len(items))
		for i, item := range items {
			out[i] = decode(t, item)
		}
		return out
	case "map":
		var pairs [][]json.RawMessage
		if err := json.Unmarshal(parts[1], &pairs); err != nil {
			t.Fatal(err)
		}
		m := yamlmerge.NewMap()
		for _, p := range pairs {
			m.Set(decode(t, p[0]), decode(t, p[1]))
		}
		return m
	}
	t.Fatalf("unknown tag %q", kind)
	return nil
}

// fraction returns the microseconds of an ISO text (0 without a fraction).
func fraction(s string) int {
	for i := 0; i < len(s); i++ {
		if s[i] == '.' {
			digits := ""
			for j := i + 1; j < len(s) && s[j] >= '0' && s[j] <= '9'; j++ {
				digits += string(s[j])
			}
			for len(digits) < 6 {
				digits += "0"
			}
			n, _ := strconv.Atoi(digits[:6])
			return n
		}
	}
	return 0
}

// encode is the inverse of decode, with Python's repr for floats and ISO text for datetimes.
func encode(v any) any {
	switch x := v.(type) {
	case nil:
		return []any{"null"}
	case bool:
		return []any{"bool", x}
	case int64:
		return []any{"int", strconv.FormatInt(x, 10)}
	case float64:
		return []any{"float", yamlmerge.PyFloat(x)}
	case string:
		return []any{"str", x}
	case yamlmerge.Date:
		return []any{"date", x.String()}
	case yamlmerge.DateTime:
		return []any{"datetime", isoDateTime(x)}
	case []any:
		items := make([]any, len(x))
		for i, item := range x {
			items[i] = encode(item)
		}
		return []any{"list", items}
	case *yamlmerge.Map:
		pairs := make([]any, 0, x.Len())
		for _, p := range x.Pairs() {
			pairs = append(pairs, []any{encode(p.Key), encode(p.Value)})
		}
		return []any{"map", pairs}
	}
	if yamlmerge.IsMissing(v) {
		return []any{"missing"}
	}
	panic(fmt.Sprintf("cannot encode %T", v))
}

func isoDateTime(d yamlmerge.DateTime) string {
	text := d.Time.Format("2006-01-02T15:04:05")
	if micro := d.Time.Nanosecond() / 1000; micro != 0 {
		text += fmt.Sprintf(".%06d", micro)
	}
	if d.Aware {
		_, offset := d.Time.Zone()
		sign := "+"
		if offset < 0 {
			sign, offset = "-", -offset
		}
		text += fmt.Sprintf("%s%02d:%02d", sign, offset/3600, offset%3600/60)
	}
	return text
}

type conflict struct {
	Path   []string        `json:"path"`
	Label  string          `json:"label"`
	Ours   json.RawMessage `json:"ours"`
	Theirs json.RawMessage `json:"theirs"`
}

type mergeCase struct {
	Name    string            `json:"name"`
	Base    json.RawMessage   `json:"base"`
	Ours    json.RawMessage   `json:"ours"`
	Theirs  json.RawMessage   `json:"theirs"`
	Choices [][]any           `json:"choices"`
	Merged  json.RawMessage   `json:"merged"`
	Conf    []conflict        `json:"conflicts"`
	Extra   map[string]string `json:"-"`
}

func TestMerge3MatchesPython(t *testing.T) {
	var ref struct {
		Cases []mergeCase `json:"cases"`
	}
	golden.Load(t, &ref, "yamlmerge", "merge3.json")
	if len(ref.Cases) == 0 {
		t.Fatal("no cases in the reference")
	}
	for _, c := range ref.Cases {
		t.Run(c.Name, func(t *testing.T) {
			choices := yamlmerge.Choices{}
			for _, ch := range c.Choices {
				var path yamlmerge.Path
				for _, part := range ch[0].([]any) {
					path = append(path, part.(string))
				}
				choices.Choose(path, ch[1].(string))
			}
			merged, conflicts := yamlmerge.Merge3(decode(t, c.Base), decode(t, c.Ours), decode(t, c.Theirs), choices)

			var wantMerged any
			if err := json.Unmarshal(c.Merged, &wantMerged); err != nil {
				t.Fatal(err)
			}
			golden.Compare(t, wantMerged, encode(merged))

			got := make([]any, 0, len(conflicts))
			for _, k := range conflicts {
				got = append(got, map[string]any{
					"path": append([]string{}, k.Path...), "label": k.Label(),
					"ours": encode(k.Ours), "theirs": encode(k.Theirs),
				})
			}
			var want []any
			for _, k := range c.Conf {
				var ours, theirs any
				_ = json.Unmarshal(k.Ours, &ours)
				_ = json.Unmarshal(k.Theirs, &theirs)
				want = append(want, map[string]any{
					"path": k.Path, "label": k.Label, "ours": ours, "theirs": theirs,
				})
			}
			if want == nil {
				want = []any{}
			}
			golden.Compare(t, want, got)
		})
	}
}

func TestHeaderOfMatchesPython(t *testing.T) {
	var ref []struct {
		Text   string `json:"text"`
		Header string `json:"header"`
	}
	golden.Load(t, &ref, "yamlmerge", "header.json")
	for _, c := range ref {
		if got := yamlmerge.HeaderOf(c.Text); got != c.Header {
			t.Errorf("HeaderOf(%q) = %q, want %q", c.Text, got, c.Header)
		}
	}
}

func TestParseISO(t *testing.T) {
	good := map[string]string{
		"2026-10-18":                "2026-10-18T00:00:00",
		"2026-10-18T09:10:00":       "2026-10-18T09:10:00",
		"2026-10-18 09:10:00":       "2026-10-18T09:10:00",
		"2026-10-18T09:10":          "2026-10-18T09:10:00",
		"2026-10-18T09:10:00Z":      "2026-10-18T09:10:00+00:00",
		"2026-10-18T09:10:00+02:00": "2026-10-18T09:10:00+02:00",
		"2026-10-18T09:10:00-0130":  "2026-10-18T09:10:00-01:30",
		"20261018T091000":           "2026-10-18T09:10:00",
		"2026-10-18T09:10:00.5":     "2026-10-18T09:10:00",
		"2026-10-18T09:10:00,25+01": "2026-10-18T09:10:00+01:00",
	}
	for in, want := range good {
		d, ok := yamlmerge.ParseISO(in)
		if !ok {
			t.Errorf("ParseISO(%q) failed", in)
			continue
		}
		if got := isoDateTime(d); got != want {
			t.Errorf("ParseISO(%q) = %s, want %s", in, got, want)
		}
	}
	for _, in := range []string{"", "kein Zeitpunkt", "2026-13-01", "2026-02-30", "2026-10-18T25:00:00", "2026-10-18T"} {
		if _, ok := yamlmerge.ParseISO(in); ok {
			t.Errorf("ParseISO(%q) should fail", in)
		}
	}
}
