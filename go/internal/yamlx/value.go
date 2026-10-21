// Package yamlx reads and writes the YAML files of Foresprint the way PyYAML does: scalars are
// resolved with the YAML 1.1 rules of PyYAML's SafeLoader, and the writer produces the bytes of
// yaml.safe_dump(width=100, sort_keys=False, allow_unicode=True).
//
// The loaded values are:
//
//	nil, bool, int64 (*big.Int beyond the range), float64, string,
//	Date (a calendar day), time.Time (a timestamp), []any, *Map
package yamlx

import "time"

// Date is a calendar day (UTC midnight), the value of a YAML timestamp without a time. A plain
// time.Time is a timestamp with a time.
type Date time.Time

// MapEntry is one key and value of a Map.
type MapEntry struct {
	Key   any
	Value any
}

// Map is a YAML mapping that keeps the order of its keys (Python dictionaries do the same).
// Keys are usually strings; YAML allows any scalar.
type Map struct {
	Entries []MapEntry
}

// Len is the number of entries.
func (m *Map) Len() int { return len(m.Entries) }

// Get returns the value of key.
func (m *Map) Get(key any) (any, bool) {
	for _, e := range m.Entries {
		if e.Key == key {
			return e.Value, true
		}
	}
	return nil, false
}

// Set replaces the value of key, or appends the key at the end.
func (m *Map) Set(key, value any) {
	for i := range m.Entries {
		if m.Entries[i].Key == key {
			m.Entries[i].Value = value
			return
		}
	}
	m.Entries = append(m.Entries, MapEntry{key, value})
}
