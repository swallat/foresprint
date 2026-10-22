package cli

import (
	"bytes"
	"strings"
	"testing"
	"time"
)

func promptEnv(input string) (*Env, *bytes.Buffer) {
	var out bytes.Buffer
	return &Env{In: strings.NewReader(input), Out: &out, Err: &out}, &out
}

func TestAskNumberRetriesUntilValid(t *testing.T) {
	isolate(t)
	t.Setenv("FORESPRINT_LANG", "en")
	env, out := promptEnv("abc\n-1\ninf\n2,5\n")
	got, err := env.AskNumber("Days", nil, false, 0)
	if err != nil || got == nil || *got != 2.5 {
		t.Fatalf("got %v, %v", got, err)
	}
	for _, want := range []string{"Please enter a number", "The value must be ≥ 0", "Please enter a finite number."} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("output lacks %q:\n%s", want, out.String())
		}
	}
}

func TestAskDefaultsAndEmpty(t *testing.T) {
	isolate(t)
	t.Setenv("FORESPRINT_LANG", "en")
	env, _ := promptEnv("\n\n")
	def := 3.0
	if got, err := env.AskNumber("N", &def, true, 0); err != nil || got == nil || *got != 3 {
		t.Errorf("default: %v %v", got, err)
	}
	if got, err := env.AskNumber("N", nil, true, 0); err != nil || got != nil {
		t.Errorf("empty: %v %v", got, err)
	}
}

func TestAskDateNumbersConfirmAndEOF(t *testing.T) {
	isolate(t)
	t.Setenv("FORESPRINT_LANG", "en")
	env, _ := promptEnv("31.12.2026\n2026-12-31\n1 2,5 x\n1 2,5\nmaybe\nj\n")
	if d, err := env.AskDate("Day", nil); err != nil || !d.Equal(time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("date: %v %v", d, err)
	}
	if v, err := env.AskNumbers("List", nil); err != nil || len(v) != 2 || v[1] != 2.5 {
		t.Errorf("numbers: %v %v", v, err)
	}
	if ok, err := env.Confirm("Sure?", false); err != nil || !ok {
		t.Errorf("confirm: %v %v", ok, err)
	}
	if _, err := env.Ask("More", ""); err == nil {
		t.Error("closed input must abort")
	}
}
