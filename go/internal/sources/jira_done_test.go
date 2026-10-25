package sources

import "testing"

func TestStatusDone(t *testing.T) {
	status := func(key string) any {
		return map[string]any{"name": "x", "statusCategory": map[string]any{"key": key}}
	}
	cases := []struct {
		name   string
		status any
		want   bool
	}{
		{"done category", status("done"), true},
		{"open category", status("indeterminate"), false},
		{"no category", map[string]any{"name": "Closed"}, false},
		{"no status", nil, false},
	}
	for _, c := range cases {
		if got := statusDone(c.status); got != c.want {
			t.Errorf("%s: statusDone = %v, want %v", c.name, got, c.want)
		}
	}
}
