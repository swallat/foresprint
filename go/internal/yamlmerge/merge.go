// Package yamlmerge is the three-way merge at key level for YAML data (port of yamlmerge.py).
//
// Different keys of the same file are combined; only if both sides changed the same value in
// different ways does a KeyConflict arise, which a human decides ("mine" or "theirs" change).
// Lists of objects with an `id` (people, products) are merged entry by entry. The forecasts of
// a sprint (list `prognoses`, without `id`) are combined by their timestamp `at` and then sorted
// ascending by `at`: if two people each append a forecast, both stay. All other lists count as a
// single value.
//
// The merge works on the value tree described in value.go, not on text; the caller parses the
// three file versions and writes the result.
package yamlmerge

import (
	"math"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/yamlx"
)

type missingType struct{}

// Missing marks a value that is not there (a key that does not exist in a version).
var Missing any = missingType{}

// IsMissing says whether v is the Missing marker.
func IsMissing(v any) bool {
	_, ok := v.(missingType)
	return ok
}

// The two sides of a conflict.
const (
	Ours   = "ours"
	Theirs = "theirs"
)

// Prognoses is the key of the list without `id`, combined by the timestamp `at`.
const Prognoses = "prognoses"

// Path is the way to a value: mapping keys, and `[id]` for the entry of a list with ids.
type Path []string

// Key is the form of the path used as the key of Choices.
func (p Path) Key() string {
	var b strings.Builder
	for _, part := range p {
		b.WriteByte(0)
		b.WriteString(part)
	}
	return b.String()
}

// Choices holds the decisions for conflicts: the key of the path (Path.Key) to "ours" or "theirs".
type Choices map[string]string

// Choose records the decision for the path.
func (c Choices) Choose(p Path, side string) { c[p.Key()] = side }

// KeyConflict means both sides changed the value at Path in different ways.
type KeyConflict struct {
	Path   Path
	Ours   any // Missing = removed by me
	Theirs any // Missing = removed by others
}

// Label is the path for display; "." for the whole file.
func (k KeyConflict) Label() string {
	if len(k.Path) == 0 {
		return "."
	}
	return strings.Join(k.Path, ".")
}

// Keyed returns a list of objects with a unique `id` as a mapping from the id (as text) to the
// object, or nil.
func Keyed(items any) *yamlx.Map {
	list, ok := items.([]any)
	if !ok || len(list) == 0 {
		return nil
	}
	out := &yamlx.Map{}
	for _, item := range list {
		obj, ok := item.(*yamlx.Map)
		if !ok {
			return nil
		}
		id, ok := mapGet(obj, "id")
		if !ok {
			return nil
		}
		name := yamlx.PyStr(id)
		if mapHas(out, name) {
			return nil
		}
		mapSet(out, name, item)
	}
	return out
}

// Merge3 merges ours and theirs on the basis of base (Missing = not present). Conflicts are
// resolved by choices; without a choice, our side stays in the result and the conflict is
// reported.
func Merge3(base, ours, theirs any, choices Choices) (merged any, conflicts []KeyConflict) {
	m := merger{choices: choices}
	merged = m.merge(base, ours, theirs, nil)
	return merged, m.conflicts
}

type merger struct {
	choices   Choices
	conflicts []KeyConflict
}

// Same reports equal value and equal type: true is not 1 (Python treats them as equal, but in
// YAML they are different values), also not inside lists and objects.
func Same(a, b any) bool {
	am, bm := IsMissing(a), IsMissing(b)
	if am || bm {
		return am && bm
	}
	ab, aBool := a.(bool)
	bb, bBool := b.(bool)
	if aBool || bBool {
		return aBool && bBool && ab == bb
	}
	switch x := a.(type) {
	case *yamlx.Map:
		y, ok := b.(*yamlx.Map)
		if !ok || x.Len() != y.Len() {
			return false
		}
		for _, p := range x.Entries {
			other, ok := mapGet(y, p.Key)
			if !ok || !Same(p.Value, other) {
				return false
			}
		}
		return true
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !Same(x[i], y[i]) {
				return false
			}
		}
		return true
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case int64:
		switch y := b.(type) {
		case int64:
			return x == y
		case float64:
			return float64(x) == y
		}
		return false
	case float64:
		switch y := b.(type) {
		case int64:
			return x == float64(y)
		case float64:
			return x == y || (math.IsNaN(x) && math.IsNaN(y)) // .nan is a value in YAML
		}
		return false
	case yamlx.Date:
		y, ok := b.(yamlx.Date)
		return ok && time.Time(x).Equal(time.Time(y))
	case time.Time:
		y, ok := b.(time.Time)
		if !ok || (x.Location() != time.UTC) != (y.Location() != time.UTC) {
			return false
		}
		return x.Equal(y)
	}
	return false
}

func (m *merger) merge(base, ours, theirs any, path Path) any {
	if Same(ours, theirs) {
		return ours
	}
	if Same(ours, base) {
		return theirs
	}
	if Same(theirs, base) {
		return ours
	}
	// Both changed it, in different ways.
	if o, ok := ours.(*yamlx.Map); ok {
		if t, ok := theirs.(*yamlx.Map); ok {
			b, ok := base.(*yamlx.Map)
			if !ok {
				b = &yamlx.Map{}
			}
			return m.mergeMaps(b, o, t, path, false)
		}
	}
	if len(path) > 0 && path[len(path)-1] == Prognoses {
		if union, ok := m.mergePrognoses(base, ours, theirs, path); ok {
			return union
		}
	}
	keyedO, keyedT := Keyed(ours), Keyed(theirs)
	if keyedO != nil && keyedT != nil {
		baseList, isList := base.([]any)
		if IsMissing(base) || isList {
			var keyedB *yamlx.Map
			if IsMissing(base) || len(baseList) == 0 {
				keyedB = &yamlx.Map{}
			} else {
				keyedB = Keyed(base)
			}
			if keyedB != nil {
				merged := m.mergeMaps(keyedB, keyedO, keyedT, path, true)
				values := make([]any, 0, merged.Len())
				for _, p := range merged.Entries {
					values = append(values, p.Value)
				}
				return values
			}
		}
	}
	switch m.choices[path.Key()] {
	case Theirs:
		return theirs
	case Ours:
		return ours
	}
	m.conflicts = append(m.conflicts, KeyConflict{append(Path(nil), path...), ours, theirs})
	return ours
}

func (m *merger) mergeMaps(base, ours, theirs *yamlx.Map, path Path, item bool) *yamlx.Map {
	keys := mapKeys(ours)
	for _, k := range mapKeys(theirs) {
		if !mapHas(ours, k) {
			keys = append(keys, k)
		}
	}
	merged := &yamlx.Map{}
	for _, key := range keys {
		name := yamlx.PyStr(key)
		if item {
			name = "[" + name + "]"
		}
		sub := append(append(Path(nil), path...), name)
		value := m.merge(getOr(base, key), getOr(ours, key), getOr(theirs, key), sub)
		if !IsMissing(value) {
			mapSet(merged, key, value)
		}
	}
	return merged
}

func getOr(m *yamlx.Map, key any) any {
	if v, ok := mapGet(m, key); ok {
		return v
	}
	return Missing
}

// stamped is a forecast entry with its timestamp.
type stamped struct {
	at   DateTime
	item *yamlx.Map
}

type stampIndex struct {
	keys    []string
	entries map[string]stamped
}

func (s *stampIndex) get(key string) (stamped, bool) {
	e, ok := s.entries[key]
	return e, ok
}

// stampOf is the timestamp of a forecast entry (a datetime or ISO text), to the second.
func stampOf(value any) (DateTime, bool) {
	switch v := value.(type) {
	case string:
		d, ok := ParseISO(v)
		if !ok {
			return DateTime{}, false
		}
		return truncateSecond(d), true
	case time.Time:
		return truncateSecond(FromTime(v)), true
	}
	return DateTime{}, false
}

func truncateSecond(d DateTime) DateTime {
	d.Time = d.Time.Truncate(1e9)
	return d
}

// order is the timestamp as an instant: converted to UTC if it has a time zone, and returned
// without a zone, so that different notations (+00:00 and +01:00) and timestamps without a zone
// can be compared and sorted.
func order(d DateTime) DateTime {
	if d.Aware {
		return DateTime{Time: d.Time.UTC()}
	}
	return d
}

// stampKey is the key of a timestamp: the instant, not the notation (ISO text without zone).
func stampKey(d DateTime) string {
	return order(d).Time.Format("2006-01-02T15:04:05")
}

// byStamp indexes forecasts by timestamp; ok is false if an entry has no readable `at` or an
// `at` occurs twice.
func byStamp(items any) (*stampIndex, bool) {
	list, ok := items.([]any)
	if !ok {
		return nil, false
	}
	idx := &stampIndex{entries: map[string]stamped{}}
	for _, raw := range list {
		item, ok := raw.(*yamlx.Map)
		if !ok {
			return nil, false
		}
		at, _ := mapGet(item, "at")
		stamp, ok := stampOf(at)
		if !ok {
			return nil, false
		}
		key := stampKey(stamp)
		if _, dup := idx.entries[key]; dup {
			return nil, false
		}
		idx.keys = append(idx.keys, key)
		idx.entries[key] = stamped{stamp, item}
	}
	return idx, true
}

// content is the entry with `at` normalized, so that a datetime and text as well as different
// time zone notations of the same instant compare equal.
func content(e stamped, present bool) any {
	if !present {
		return Missing
	}
	out := &yamlx.Map{}
	for _, p := range e.item.Entries {
		mapSet(out, p.Key, p.Value)
	}
	mapSet(out, "at", stampKey(e.at))
	return out
}

// mergePrognoses combines forecasts by their timestamp `at` (entries carry no `id`): both sides
// may append without one getting lost. An entry counts as a whole; only the same `at` with
// different content causes a conflict (path `…[<at>]`). The result is sorted ascending by `at`.
// A base without forecasts (missing or empty key, i.e. nil) counts as an empty list. ok is false
// when this does not apply (no `at`, duplicate `at`, not a list): the list then counts as a single
// value, as with other lists.
func (m *merger) mergePrognoses(base, ours, theirs any, path Path) (union []any, ok bool) {
	if _, isList := ours.([]any); !isList {
		return nil, false
	}
	if _, isList := theirs.([]any); !isList {
		return nil, false
	}
	emptyBase := IsMissing(base) || base == nil
	if _, isList := base.([]any); !emptyBase && !isList {
		return nil, false
	}
	keyedB := &stampIndex{entries: map[string]stamped{}}
	if !emptyBase {
		if keyedB, ok = byStamp(base); !ok {
			return nil, false
		}
	}
	keyedO, okO := byStamp(ours)
	keyedT, okT := byStamp(theirs)
	if !okO || !okT {
		return nil, false
	}
	keys := append([]string(nil), keyedO.keys...)
	for _, k := range keyedT.keys {
		if _, in := keyedO.get(k); !in {
			keys = append(keys, k)
		}
	}
	var merged []stamped
	for _, key := range keys {
		b, hasB := keyedB.get(key)
		o, hasO := keyedO.get(key)
		t, hasT := keyedT.get(key)
		sub := append(append(Path(nil), path...), "["+key+"]")
		var chosen stamped
		var has bool
		switch {
		case Same(content(o, hasO), content(t, hasT)):
			chosen, has = o, hasO
		case Same(content(o, hasO), content(b, hasB)):
			chosen, has = t, hasT
		case Same(content(t, hasT), content(b, hasB)):
			chosen, has = o, hasO
		default:
			choice, decided := m.choices[sub.Key()]
			if !decided {
				c := KeyConflict{Path: sub, Ours: Missing, Theirs: Missing}
				if hasO {
					c.Ours = o.item
				}
				if hasT {
					c.Theirs = t.item
				}
				m.conflicts = append(m.conflicts, c)
			}
			if choice == Theirs {
				chosen, has = t, hasT
			} else {
				chosen, has = o, hasO
			}
		}
		if has {
			merged = append(merged, chosen)
		}
	}
	// Stable: equal timestamps keep their order.
	sort.SliceStable(merged, func(i, j int) bool {
		return order(merged[i].at).Time.Before(order(merged[j].at).Time)
	})
	union = make([]any, len(merged))
	for i, e := range merged {
		union[i] = e.item
	}
	return union, true
}

// HeaderOf is the leading comment block of a file (kept when merging): the lines that start with
// `#` or are blank, up to the first other line.
func HeaderOf(text string) string {
	var b strings.Builder
	for _, line := range pytext.SplitLines(text, true) {
		if strings.HasPrefix(line, "#") || pytext.Strip(line) == "" {
			b.WriteString(line)
			continue
		}
		break
	}
	return b.String()
}
