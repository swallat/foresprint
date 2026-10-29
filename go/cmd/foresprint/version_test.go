package main

import "testing"

func TestWithCommit(t *testing.T) {
	for _, c := range []struct{ v, commit, want string }{
		{"dev", "abc1234", "dev (abc1234)"},
		{"dev", "", "dev"},
		{"1.1.0", "abc1234", "1.1.0"},
	} {
		if got := withCommit(c.v, c.commit); got != c.want {
			t.Errorf("withCommit(%q, %q) = %q, want %q", c.v, c.commit, got, c.want)
		}
	}
}
