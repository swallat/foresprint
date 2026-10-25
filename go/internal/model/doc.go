// Package model has the data types of Foresprint: team settings, people, products, sprints and
// the ticket pre-planning. It is the Go port of src/foresprint/model.py and holds no logic
// beyond small queries on the types themselves; reading and writing the YAML files is the
// package storage, the calculations are in their own packages.
//
// Conventions:
//
//   - A value that can be missing is a pointer (*float64, *string, *time.Time); nil is Python's
//     None. Ptr makes one from a value.
//   - Dates are calendar dates as time.Time at UTC midnight (see Date); no time zone arithmetic.
//   - Enumerations are string types with the values of the files (TrendMode "flat").
//   - A map whose order is part of the file is an OrderedMap; the other maps are written sorted
//     by the storage, like Python does.
package model

import (
	"time"
)

// Ptr returns a pointer to v, for the optional fields.
func Ptr[T any](v T) *T { return &v }

// Date returns the calendar date year-month-day as UTC midnight.
func Date(year int, month time.Month, day int) time.Time {
	return time.Date(year, month, day, 0, 0, 0, 0, time.UTC)
}

// Entry is one key and value of an OrderedMap.
type Entry[V any] struct {
	Key   string
	Value V
}

// OrderedMap is a map that keeps the order in which the keys were added, because the order is
// part of the file (Python dictionaries do the same). The zero value is an empty map.
type OrderedMap[V any] struct {
	Entries []Entry[V]
}

// Len is the number of entries.
func (m OrderedMap[V]) Len() int { return len(m.Entries) }

// Get returns the value of key.
func (m OrderedMap[V]) Get(key string) (V, bool) {
	for _, e := range m.Entries {
		if e.Key == key {
			return e.Value, true
		}
	}
	var zero V
	return zero, false
}

// Set replaces the value of key, or appends the key at the end.
func (m *OrderedMap[V]) Set(key string, value V) {
	for i := range m.Entries {
		if m.Entries[i].Key == key {
			m.Entries[i].Value = value
			return
		}
	}
	m.Entries = append(m.Entries, Entry[V]{key, value})
}

// Keys returns the keys in order.
func (m OrderedMap[V]) Keys() []string {
	keys := make([]string, len(m.Entries))
	for i, e := range m.Entries {
		keys[i] = e.Key
	}
	return keys
}

// Clone returns a copy of the entries (values that are slices stay shared).
func (m OrderedMap[V]) Clone() OrderedMap[V] {
	return OrderedMap[V]{Entries: append([]Entry[V](nil), m.Entries...)}
}

// NewOrderedMap builds a map from alternating keys and values given as entries.
func NewOrderedMap[V any](entries ...Entry[V]) OrderedMap[V] {
	return OrderedMap[V]{Entries: append([]Entry[V](nil), entries...)}
}
