package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// as_of in team.yaml is the "today" of the team; --as-of still wins.
func TestTeamAsOfInTeamYaml(t *testing.T) {
	isolate(t)
	dir := t.TempDir()
	team := filepath.Join(dir, "demo")
	if err := os.CopyFS(team, os.DirFS(filepath.Join(demoTeams, "demo"))); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(team, "team.yaml")
	text, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	_, want, _ := run(t, "--data", dir, "--as-of", "2026-03-10", "forecast", "demo")
	_, other, _ := run(t, "--data", dir, "--as-of", "2026-08-12", "forecast", "demo")
	if want == other {
		t.Fatal("the forecast does not depend on the date; the test would prove nothing")
	}
	if err := os.WriteFile(file, append(text, []byte("as_of: 2026-03-10\n")...), 0o644); err != nil {
		t.Fatal(err)
	}
	code, got, errOut := run(t, "--data", dir, "forecast", "demo")
	if code != 0 || got != want {
		t.Errorf("without --as-of: code %d err %q\nwant the output of 2026-03-10:\n%s\ngot:\n%s", code, errOut, want, got)
	}
	if _, got, _ = run(t, "--data", dir, "--as-of", "2026-08-12", "forecast", "demo"); got != other {
		t.Errorf("--as-of must win over team.yaml:\n%s", got)
	}
	if code, _, errOut = run(t, "--data", dir, "check"); code != 0 || strings.Contains(errOut, "as_of") {
		t.Errorf("check: %d %q", code, errOut)
	}
}
