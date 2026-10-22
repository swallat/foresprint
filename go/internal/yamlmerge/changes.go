package yamlmerge

import (
	"sort"
	"strings"

	"github.com/swallat/foresprint/internal/yamlx"
)

// Change is one value that differs between two versions of a file: the path (the same form the
// merge uses), and the value before and after (Missing = not there).
type Change struct {
	Path   Path
	Before any
	After  any
}

// Label is the path for display; "." for the whole file.
func (c Change) Label() string {
	if len(c.Path) == 0 {
		return "."
	}
	return strings.Join(c.Path, ".")
}

// Changes lists the values that differ, one entry per value: keys of a mapping, entries of a
// list with ids (the fields inside them), forecasts by their timestamp. Anything else counts as
// one value.
func Changes(before, after any) []Change {
	var out []Change
	walkChanges(before, after, nil, &out)
	return out
}

func walkChanges(before, after any, path Path, out *[]Change) {
	if Same(before, after) {
		return
	}
	if b, ok := before.(*yamlx.Map); ok {
		if a, ok := after.(*yamlx.Map); ok {
			walkMaps(b, a, path, false, out)
			return
		}
	}
	if len(path) > 0 && path[len(path)-1] == Prognoses {
		if walkPrognoses(before, after, path, out) {
			return
		}
	}
	ka, kb := Keyed(after), Keyed(before)
	if ka != nil && (kb != nil || emptyList(before)) {
		if kb == nil {
			kb = &yamlx.Map{}
		}
		walkMaps(kb, ka, path, true, out)
		return
	}
	if kb != nil && emptyList(after) {
		walkMaps(kb, &yamlx.Map{}, path, true, out)
		return
	}
	*out = append(*out, Change{append(Path(nil), path...), before, after})
}

func emptyList(v any) bool {
	if IsMissing(v) {
		return true
	}
	l, ok := v.([]any)
	return ok && len(l) == 0
}

func walkMaps(before, after *yamlx.Map, path Path, item bool, out *[]Change) {
	keys := mapKeys(after)
	for _, k := range mapKeys(before) {
		if !mapHas(after, k) {
			keys = append(keys, k)
		}
	}
	for _, key := range keys {
		name := yamlx.PyStr(key)
		if item {
			name = "[" + name + "]"
		}
		walkChanges(getOr(before, key), getOr(after, key), append(append(Path(nil), path...), name), out)
	}
}

func walkPrognoses(before, after any, path Path, out *[]Change) bool {
	if _, ok := after.([]any); !ok {
		return false
	}
	var idxB *stampIndex
	switch {
	case emptyList(before) || before == nil:
		idxB = &stampIndex{entries: map[string]stamped{}}
	default:
		var ok bool
		if idxB, ok = byStamp(before); !ok {
			return false
		}
	}
	idxA, ok := byStamp(after)
	if !ok {
		return false
	}
	keys := append([]string(nil), idxA.keys...)
	for _, k := range idxB.keys {
		if _, in := idxA.get(k); !in {
			keys = append(keys, k)
		}
	}
	for _, key := range keys {
		b, hasB := idxB.get(key)
		a, hasA := idxA.get(key)
		if Same(content(a, hasA), content(b, hasB)) {
			continue
		}
		c := Change{Path: append(append(Path(nil), path...), "["+key+"]"), Before: Missing, After: Missing}
		if hasB {
			c.Before = b.item
		}
		if hasA {
			c.After = a.item
		}
		*out = append(*out, c)
	}
	return true
}

// Apply returns the tree with the value at path set to value (Missing removes it). A missing
// parent mapping is created. ok is false when the path does not fit the tree.
func Apply(tree any, path Path, value any) (result any, ok bool) {
	if len(path) == 0 {
		return value, true
	}
	part := path[0]
	if strings.HasPrefix(part, "[") && strings.HasSuffix(part, "]") {
		return applyListItem(tree, part[1:len(part)-1], path[1:], value)
	}
	m, isMap := tree.(*yamlx.Map)
	if !isMap {
		return nil, false
	}
	// A key is found by its text, as the path shows it.
	for i, e := range m.Entries {
		if yamlx.PyStr(e.Key) != part {
			continue
		}
		child := e.Value
		if len(path) == 1 {
			if IsMissing(value) {
				m.Entries = append(m.Entries[:i:i], m.Entries[i+1:]...)
				return m, true
			}
			m.Entries[i].Value = value
			return m, true
		}
		sub, ok := Apply(child, path[1:], value)
		if !ok {
			return nil, false
		}
		m.Entries[i].Value = sub
		return m, true
	}
	if IsMissing(value) {
		return m, true
	}
	child := value
	if len(path) > 1 {
		var ok bool
		var parent any = &yamlx.Map{}
		if next := path[1]; strings.HasPrefix(next, "[") && strings.HasSuffix(next, "]") {
			parent = []any{}
		}
		if child, ok = Apply(parent, path[1:], value); !ok {
			return nil, false
		}
	}
	m.Entries = append(m.Entries, yamlx.MapEntry{Key: part, Value: child})
	return m, true
}

func applyListItem(tree any, id string, rest Path, value any) (any, bool) {
	list, isList := tree.([]any)
	if !isList && !IsMissing(tree) && tree != nil {
		return nil, false
	}
	position := -1
	byStampKey := false
	if keyed := Keyed(list); keyed != nil || len(list) == 0 {
		for i, item := range list {
			if v, _ := mapGet(item.(*yamlx.Map), "id"); yamlx.PyStr(v) == id {
				position = i
			}
		}
	} else if _, ok := byStamp(list); ok {
		byStampKey = true
		for i, item := range list {
			if at, _ := mapGet(item.(*yamlx.Map), "at"); stampKeyOf(at) == id {
				position = i
			}
		}
	} else {
		return nil, false
	}
	if position < 0 {
		if IsMissing(value) {
			return list, true
		}
		item := value
		if len(rest) > 0 {
			var ok bool
			if item, ok = Apply(&yamlx.Map{}, rest, value); !ok {
				return nil, false
			}
		}
		list = append(list, item)
		if byStampKey {
			sortByStamp(list)
		}
		return list, true
	}
	if len(rest) == 0 {
		if IsMissing(value) {
			return append(list[:position:position], list[position+1:]...), true
		}
		list[position] = value
		return list, true
	}
	sub, ok := Apply(list[position], rest, value)
	if !ok {
		return nil, false
	}
	list[position] = sub
	return list, true
}

func stampKeyOf(at any) string {
	d, ok := stampOf(at)
	if !ok {
		return ""
	}
	return stampKey(d)
}

func sortByStamp(list []any) {
	sort.SliceStable(list, func(i, j int) bool {
		a, _ := mapGet(list[i].(*yamlx.Map), "at")
		b, _ := mapGet(list[j].(*yamlx.Map), "at")
		da, _ := stampOf(a)
		db, _ := stampOf(b)
		return order(da).Time.Before(order(db).Time)
	})
}
