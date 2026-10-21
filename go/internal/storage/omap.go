package storage

import "github.com/swallat/foresprint/internal/yamlx"

// omap builds an ordered mapping from alternating keys and values.
func omap(kv ...any) *yamlx.Map {
	m := &yamlx.Map{}
	for i := 0; i+1 < len(kv); i += 2 {
		m.Entries = append(m.Entries, yamlx.MapEntry{Key: kv[i], Value: kv[i+1]})
	}
	return m
}

// put appends a key and value.
func put(m *yamlx.Map, key string, value any) {
	m.Entries = append(m.Entries, yamlx.MapEntry{Key: key, Value: value})
}

// strs turns texts into a YAML list.
func strs(list []string) []any {
	out := make([]any, len(list))
	for i, s := range list {
		out[i] = s
	}
	return out
}

func strPtr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}
