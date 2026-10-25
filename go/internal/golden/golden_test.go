package golden

import "testing"

func TestDiff(t *testing.T) {
	var want any
	if err := decode([]byte(`{"a": [1, 2.5, "x", null, true], "b": {"c": 1.0}}`), &want); err != nil {
		t.Fatal(err)
	}
	same := map[string]any{"a": []any{1, 2.5000000000001, "x", nil, true}, "b": map[string]any{"c": 1}}
	if diffs, err := Diff(want, same); err != nil || len(diffs) != 0 {
		t.Errorf("equal values within the tolerance must not differ: %v %v", diffs, err)
	}
	cases := map[string]map[string]any{
		"number":  {"a": []any{1, 2.6, "x", nil, true}, "b": map[string]any{"c": 1}},
		"string":  {"a": []any{1, 2.5, "y", nil, true}, "b": map[string]any{"c": 1}},
		"length":  {"a": []any{1}, "b": map[string]any{"c": 1}},
		"missing": {"a": []any{1, 2.5, "x", nil, true}},
		"extra":   {"a": []any{1, 2.5, "x", nil, true}, "b": map[string]any{"c": 1}, "d": 1},
		"null":    {"a": []any{1, 2.5, "x", 0, true}, "b": map[string]any{"c": 1}},
	}
	for name, got := range cases {
		if diffs, err := Diff(want, got); err != nil || len(diffs) == 0 {
			t.Errorf("%s: the difference was not reported (%v)", name, err)
		}
	}
}

func TestClose(t *testing.T) {
	if !Close(1e12, 1e12+1) {
		t.Error("relative tolerance")
	}
	if Close(1, 1.001) {
		t.Error("1 and 1.001 are different")
	}
	if !Close(0, 1e-12) {
		t.Error("absolute tolerance near zero")
	}
}
