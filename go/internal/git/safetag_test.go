package git

import "testing"

func TestSafeTagName(t *testing.T) {
	for in, want := range map[string]string{
		"atlas/Atlas - BV Sprint 2026.21": "atlas/Atlas-BV-Sprint-2026.21",
		"atlas/2026.21":                   "atlas/2026.21",
		"a b//c..d/.e/f.lock/g.":          "a-b/c.d/e/f/g",
		"x~y^z:w?*[v\\u@{n":               "x-y-z-w-v-u@-n",
	} {
		got := SafeTagName(in)
		if got != want {
			t.Errorf("SafeTagName(%q) = %q, want %q", in, got, want)
		}
		if err := ValidTagName(t.Context(), t.TempDir(), got); err != nil {
			t.Errorf("%q not valid: %v", got, err)
		}
	}
}
