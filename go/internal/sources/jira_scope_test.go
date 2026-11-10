package sources

import "testing"

func TestStripOrderBy(t *testing.T) {
	for in, want := range map[string]string{
		"project = A ORDER BY Rank":            "project = A",
		"project = A order by Rank ASC":        "project = A",
		`summary ~ "order by x" ORDER BY Rank`: `summary ~ "order by x"`,
		`summary ~ "order by x"`:               `summary ~ "order by x"`,
		"project = A":                          "project = A",
	} {
		if got := stripOrderBy(in); got != want {
			t.Errorf("stripOrderBy(%q) = %q, want %q", in, got, want)
		}
	}
}
