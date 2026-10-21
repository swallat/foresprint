// Package diff compares loaded YAML values and reports the changed values with their path
// (port of diff.py, the part that does not need Git).
//
// Lists of objects with an "id" (people, products) are compared per entry, all other lists as
// one value, as in merging; the "prognoses" list counts as one value too.
package diff

import (
	"errors"
	"math"
	"math/big"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/yamlx"
)

// MaxNodes is the upper limit of compared nodes per file: two separately loaded trees made of
// YAML aliases (small file, huge tree) would otherwise compute for an arbitrarily long time.
const MaxNodes = 200_000

// ErrTooComplex means the file is too nested or too large to compare.
var ErrTooComplex = errors.New("too many nodes")

type missing struct{}

// Missing stands for "not present" (a value that was added or removed).
var Missing any = &missing{}

// Kinds of a change.
const (
	Added   = "added"
	Removed = "removed"
	Changed = "changed"
)

// ValueChange is a value under Path; Missing as Old or New means "not present".
type ValueChange struct {
	Path []string
	Old  any
	New  any
}

// Kind is Added, Removed or Changed.
func (c ValueChange) Kind() string {
	switch {
	case c.Old == Missing:
		return Added
	case c.New == Missing:
		return Removed
	}
	return Changed
}

// Label is the path as text ("." for the whole file).
func (c ValueChange) Label() string {
	if len(c.Path) == 0 {
		return "."
	}
	return strings.Join(c.Path, ".")
}

type budget struct{ left int }

func (b *budget) spend() error {
	b.left--
	if b.left < 0 {
		return ErrTooComplex
	}
	return nil
}

// same is the equality of the comparison: True is not 1 (Python treats them as equal, but in YAML
// they are different values), also not inside lists and objects; 1 and 1.0 are equal.
func same(a, b any, bg *budget) (bool, error) {
	if err := bg.spend(); err != nil {
		return false, err
	}
	if a == Missing || b == Missing {
		return a == b, nil
	}
	ab, aIsBool := a.(bool)
	bb, bIsBool := b.(bool)
	if aIsBool || bIsBool {
		return aIsBool && bIsBool && ab == bb, nil
	}
	switch x := a.(type) {
	case *yamlx.Map:
		y, ok := b.(*yamlx.Map)
		if !ok || x.Len() != y.Len() {
			return false, nil
		}
		index := keyIndex(y)
		for _, e := range x.Entries {
			j, ok := index[yamlx.CanonicalKey(e.Key)]
			if !ok {
				return false, nil
			}
			eq, err := same(e.Value, y.Entries[j].Value, bg)
			if err != nil || !eq {
				return false, err
			}
		}
		return true, nil
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false, nil
		}
		for i := range x {
			eq, err := same(x[i], y[i], bg)
			if err != nil || !eq {
				return false, err
			}
		}
		return true, nil
	case float64:
		if y, ok := b.(float64); ok && math.IsNaN(x) && math.IsNaN(y) {
			return true, nil
		}
	}
	return scalarEqual(a, b), nil
}

func keyIndex(m *yamlx.Map) map[string]int {
	index := make(map[string]int, len(m.Entries))
	for i, e := range m.Entries {
		index[yamlx.CanonicalKey(e.Key)] = i
	}
	return index
}

// scalarEqual is Python's == for scalars: numbers compare by value across int and float,
// timestamps by instant (a timestamp with a zone never equals one without).
func scalarEqual(a, b any) bool {
	switch x := a.(type) {
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case yamlx.Date:
		y, ok := b.(yamlx.Date)
		return ok && time.Time(x).Equal(time.Time(y))
	case time.Time:
		y, ok := b.(time.Time)
		return ok && x.Equal(y) && (x.Location() == time.UTC) == (y.Location() == time.UTC)
	}
	if na, ok := number(a); ok {
		if nb, ok := number(b); ok {
			return na.Cmp(nb) == 0
		}
	}
	return false
}

func number(v any) (*big.Float, bool) {
	switch x := v.(type) {
	case int64:
		return new(big.Float).SetInt64(x), true
	case *big.Int:
		return new(big.Float).SetInt(x), true
	case float64:
		if math.IsNaN(x) {
			return nil, false
		}
		return new(big.Float).SetFloat64(x), true // infinities compare too
	}
	return nil, false
}

// Keyed turns a list of objects with a unique id into a mapping from the id's text to the object
// (in list order); nil if the value is not such a list.
func Keyed(items any) *yamlx.Map {
	list, ok := items.([]any)
	if !ok || len(list) == 0 {
		return nil
	}
	m := &yamlx.Map{}
	seen := map[string]bool{}
	for _, item := range list {
		obj, ok := item.(*yamlx.Map)
		if !ok {
			return nil
		}
		id, ok := get(obj, "id")
		if !ok {
			return nil
		}
		key := yamlx.PyStr(id)
		if seen[key] {
			return nil
		}
		seen[key] = true
		m.Entries = append(m.Entries, yamlx.MapEntry{Key: key, Value: item})
	}
	return m
}

func get(m *yamlx.Map, key string) (any, bool) {
	for _, e := range m.Entries {
		if s, ok := e.Key.(string); ok && s == key {
			return e.Value, true
		}
	}
	return nil, false
}

// Values returns all differences between old and new in key order. If only the order of the
// entries changes in lists with an id, one change is reported under the path of the list, with
// the ids before and after. Trees with more than MaxNodes nodes to compare give ErrTooComplex.
// Missing stands for "not present" on either side.
func Values(old, new any) ([]ValueChange, error) {
	return values(old, new, nil, &budget{MaxNodes})
}

func values(old, new any, path []string, bg *budget) ([]ValueChange, error) {
	eq, err := same(old, new, bg)
	if err != nil || eq {
		return nil, err
	}
	om, oldIsMap := old.(*yamlx.Map)
	nm, newIsMap := new.(*yamlx.Map)
	if oldIsMap && newIsMap {
		return diffMapping(om, nm, path, false, bg)
	}
	keyedOld, keyedNew := Keyed(old), Keyed(new)
	// An empty list is the empty mapping if the other side contains objects with an id (first
	// object added, last removed): that keeps the path [id].
	if keyedOld == nil && isEmptyList(old) && keyedNew != nil {
		keyedOld = &yamlx.Map{}
	}
	if keyedNew == nil && isEmptyList(new) && keyedOld != nil {
		keyedNew = &yamlx.Map{}
	}
	if keyedOld != nil && keyedNew != nil {
		changes, err := diffMapping(keyedOld, keyedNew, path, true, bg)
		if err != nil {
			return nil, err
		}
		oldIdx, newIdx := keyIndex(keyedOld), keyIndex(keyedNew)
		var orderOld, orderNew []any
		for _, e := range keyedOld.Entries {
			if _, ok := newIdx[yamlx.CanonicalKey(e.Key)]; ok {
				orderOld = append(orderOld, e.Key)
			}
		}
		for _, e := range keyedNew.Entries {
			if _, ok := oldIdx[yamlx.CanonicalKey(e.Key)]; ok {
				orderNew = append(orderNew, e.Key)
			}
		}
		if !equalLists(orderOld, orderNew) {
			changes = append(changes, ValueChange{path, keys(keyedOld), keys(keyedNew)})
		}
		return changes, nil
	}
	return []ValueChange{{path, old, new}}, nil
}

func isEmptyList(v any) bool {
	l, ok := v.([]any)
	return ok && len(l) == 0
}

func equalLists(a, b []any) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func keys(m *yamlx.Map) []any {
	out := make([]any, len(m.Entries))
	for i, e := range m.Entries {
		out[i] = e.Key
	}
	return out
}

// KeyText is a key in the file's spelling (null, true), not Python's.
func KeyText(key any) string {
	switch k := key.(type) {
	case nil:
		return "null"
	case bool:
		if k {
			return "true"
		}
		return "false"
	}
	return yamlx.PyStr(key)
}

func diffMapping(old, new *yamlx.Map, path []string, item bool, bg *budget) ([]ValueChange, error) {
	oldIdx, newIdx := keyIndex(old), keyIndex(new)
	var changes []ValueChange
	order := make([]any, 0, len(old.Entries)+len(new.Entries))
	for _, e := range old.Entries {
		order = append(order, e.Key)
	}
	for _, e := range new.Entries {
		if _, ok := oldIdx[yamlx.CanonicalKey(e.Key)]; !ok {
			order = append(order, e.Key)
		}
	}
	for _, key := range order {
		c := yamlx.CanonicalKey(key)
		text := KeyText(key)
		if item {
			text = "[" + text + "]"
		}
		sub := append(append([]string{}, path...), text)
		var o, n any = Missing, Missing
		if i, ok := oldIdx[c]; ok {
			o = old.Entries[i].Value
		}
		if i, ok := newIdx[c]; ok {
			n = new.Entries[i].Value
		}
		part, err := values(o, n, sub, bg)
		if err != nil {
			return nil, err
		}
		changes = append(changes, part...)
	}
	return changes, nil
}

// Slim limits for kept values: slightly above the display limits of the UI, so that an excerpt
// shows the same as the whole value would, and a cache holds no large subtrees.
const (
	slimItems = 1001
	slimNodes = 6000
	slimDepth = 9
)

// Slim shortens a value to an excerpt (strings, lists and mappings to 1001 elements, 6000 nodes,
// depth 9; what is cut off becomes "…").
func Slim(v any) any {
	left := slimNodes
	return slim(v, &left, 0)
}

func slim(v any, left *int, depth int) any {
	*left--
	if *left < 0 || depth > slimDepth {
		return "…"
	}
	switch x := v.(type) {
	case string:
		return truncate(x)
	case *yamlx.Map:
		out := &yamlx.Map{}
		for i, e := range x.Entries {
			if i == slimItems {
				break
			}
			key := e.Key
			if s, ok := key.(string); ok {
				key = truncate(s)
			}
			out.Entries = append(out.Entries, yamlx.MapEntry{Key: key, Value: slim(e.Value, left, depth+1)})
		}
		return out
	case []any:
		n := len(x)
		if n > slimItems {
			n = slimItems
		}
		out := make([]any, n)
		for i := 0; i < n; i++ {
			out[i] = slim(x[i], left, depth+1)
		}
		return out
	}
	return v
}

func truncate(s string) string {
	if utf8.RuneCountInString(s) <= slimItems {
		return s
	}
	return string([]rune(s)[:slimItems])
}
