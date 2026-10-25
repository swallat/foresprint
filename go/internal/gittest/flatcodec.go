package gittest

import (
	"errors"
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/yamlx"
)

// FlatCodec reads and writes flat "key: value" files (numbers and text), enough for the tests of
// the merge: the real codec belongs to the storage layer.
type FlatCodec struct{}

// Parse reads a flat mapping; an empty document gives nil.
func (FlatCodec) Parse(text string) (any, error) {
	m := &yamlx.Map{}
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, ":")
		if !ok || strings.HasPrefix(line, " ") || strings.HasPrefix(line, "-") {
			return nil, errors.New("not a flat mapping")
		}
		value = strings.TrimSpace(value)
		if value == "" {
			m.Set(key, nil)
		} else if n, err := strconv.ParseInt(value, 10, 64); err == nil {
			m.Set(key, n)
		} else if f, err := strconv.ParseFloat(value, 64); err == nil {
			m.Set(key, f)
		} else {
			m.Set(key, value)
		}
	}
	if m.Len() == 0 {
		return nil, nil
	}
	return m, nil
}

// Dump writes a flat mapping.
func (FlatCodec) Dump(tree any) (string, error) {
	m, ok := tree.(*yamlx.Map)
	if !ok {
		if tree == nil {
			return "", nil
		}
		return "", errors.New("not a flat mapping")
	}
	var sb strings.Builder
	for _, p := range m.Entries {
		sb.WriteString(yamlx.PyStr(p.Key))
		if p.Value == nil {
			sb.WriteString(":\n")
			continue
		}
		sb.WriteString(": " + yamlx.PyStr(p.Value) + "\n")
	}
	return sb.String(), nil
}
