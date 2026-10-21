package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const demoTeams = "../../../examples/teams"

func TestCheckDemo(t *testing.T) {
	isolate(t)
	code, out, errOut := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "check")
	if code != 0 || out != "✔ demo\n" || errOut != "" {
		t.Errorf("check: %d %q %q", code, out, errOut)
	}
}

func TestCheckFindsErrors(t *testing.T) {
	isolate(t)
	dir := t.TempDir()
	team := filepath.Join(dir, "broken")
	if err := os.MkdirAll(team, 0o755); err != nil {
		t.Fatal(err)
	}
	text, err := os.ReadFile(filepath.Join(demoTeams, "demo", "team.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(team, "team.yaml"), []byte(strings.Replace(string(text), "window:", "window: 0 #", 1)), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, _ := run(t, "--data", dir, "check")
	if code != 1 || !strings.HasPrefix(out, "broken\n  Error team.yaml: ") {
		t.Errorf("check: %d %q", code, out)
	}
	if code, _, errOut := run(t, "--data", t.TempDir(), "check"); code != 1 || !strings.HasPrefix(errOut, "No teams found in ") {
		t.Errorf("no teams: %d %q", code, errOut)
	}
}

func TestCapacityDemo(t *testing.T) {
	isolate(t)
	code, out, errOut := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "capacity", "demo")
	want := `Capacity sprint 2026.6 (18.03. – 01.04.2026)
Person  Working days  Holidays  Absences    PT
──────────────────────────────────────────────
Anna              10         0         2   8.0
Ben               10         0         5   5.0
Cem               10         0         1   9.0
Dana              10         0         0  10.0
Emil              10         0         0   8.0
Total                                     40.0
Recorded/frozen in the sprint file: 40.0 PT
`
	if code != 0 || out != want || errOut != "" {
		t.Errorf("capacity: %d\n%s\n%q", code, out, errOut)
	}
	if code, _, errOut := run(t, "--data", demoTeams, "capacity", "nope"); code != 1 || !strings.Contains(errOut, "not found") {
		t.Errorf("unknown team: %d %q", code, errOut)
	}
	if code, _, errOut := run(t, "--data", demoTeams, "capacity", "demo", "9999.99"); code != 1 || errOut != "Sprint 9999.99 is not part of the team's sprint sequence.\n" {
		t.Errorf("unknown sprint: %d %q", code, errOut)
	}
}
