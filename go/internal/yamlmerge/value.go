package yamlmerge

import (
	"time"

	"github.com/swallat/foresprint/internal/yamlx"
)

// The YAML value tree the merge works on is the one of package yamlx: nil, bool, int64,
// *big.Int, float64, string, yamlx.Date, time.Time, []any (a list) and *yamlx.Map (a mapping
// that keeps its key order).

// DateTime is a point in time as the merge compares it. Aware says whether the file gave a time
// zone; Time then carries it. Without a zone the wall clock time is kept in UTC and Aware is
// false. In the value tree this is a time.Time: one in a zone other than time.UTC is aware.
type DateTime struct {
	Time  time.Time
	Aware bool
}

// FromTime converts a timestamp of the value tree.
func FromTime(t time.Time) DateTime {
	return DateTime{Time: t, Aware: t.Location() != time.UTC}
}

// Value is the timestamp as a value of the tree (aware ones keep a fixed zone of their own,
// even when it is +00:00).
func (d DateTime) Value() time.Time {
	if !d.Aware {
		return time.Date(d.Time.Year(), d.Time.Month(), d.Time.Day(), d.Time.Hour(), d.Time.Minute(),
			d.Time.Second(), d.Time.Nanosecond(), time.UTC)
	}
	_, offset := d.Time.Zone()
	return d.Time.In(time.FixedZone("", offset))
}

// mapGet looks key up the way Python's dictionary does (1, True and 1.0 are one key).
func mapGet(m *yamlx.Map, key any) (any, bool) {
	if m == nil {
		return nil, false
	}
	if s, ok := key.(string); ok { // a string only equals a string
		for _, e := range m.Entries {
			if k, ok := e.Key.(string); ok && k == s {
				return e.Value, true
			}
		}
		return nil, false
	}
	want := yamlx.CanonicalKey(key)
	for _, e := range m.Entries {
		if yamlx.CanonicalKey(e.Key) == want {
			return e.Value, true
		}
	}
	return nil, false
}

// mapSet adds the entry or replaces the value of an existing key (which keeps its position).
func mapSet(m *yamlx.Map, key, value any) {
	if _, ok := mapGet(m, key); ok {
		if s, isStr := key.(string); isStr {
			for i := range m.Entries {
				if k, ok := m.Entries[i].Key.(string); ok && k == s {
					m.Entries[i].Value = value
				}
			}
			return
		}
		want := yamlx.CanonicalKey(key)
		for i := range m.Entries {
			if yamlx.CanonicalKey(m.Entries[i].Key) == want {
				m.Entries[i].Value = value
			}
		}
		return
	}
	m.Entries = append(m.Entries, yamlx.MapEntry{Key: key, Value: value})
}

func mapHas(m *yamlx.Map, key any) bool {
	_, ok := mapGet(m, key)
	return ok
}

func mapKeys(m *yamlx.Map) []any {
	keys := make([]any, len(m.Entries))
	for i, e := range m.Entries {
		keys[i] = e.Key
	}
	return keys
}
