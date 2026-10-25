package pytext

import (
	"reflect"
	"testing"
)

func TestSplitLines(t *testing.T) {
	cases := []struct {
		in       string
		keepends bool
		want     []string
	}{
		{"", false, nil},
		{"a", false, []string{"a"}},
		{"a\nb\n", false, []string{"a", "b"}},
		{"a\nb\n", true, []string{"a\n", "b\n"}},
		{"a\r\nb\rc", true, []string{"a\r\n", "b\r", "c"}},
		{"a\n\nb", false, []string{"a", "", "b"}},
		{"a b\x0cc\u0085d", false, []string{"a", "b", "c", "d"}},
		{"\n", false, []string{""}},
	}
	for _, c := range cases {
		if got := SplitLines(c.in, c.keepends); !reflect.DeepEqual(got, c.want) {
			t.Errorf("SplitLines(%q, %v) = %q, want %q", c.in, c.keepends, got, c.want)
		}
	}
}

func TestCasefold(t *testing.T) {
	for in, want := range map[string]string{
		"Straße": "strasse", "ς": "σ", "µ": "μ", "İ": "i̇", "ﬁ": "fi", "ſ": "s", "ẞ": "ss", "ABC": "abc",
	} {
		if got := Casefold(in); got != want {
			t.Errorf("Casefold(%q) = %q, want %q", in, got, want)
		}
	}
}
