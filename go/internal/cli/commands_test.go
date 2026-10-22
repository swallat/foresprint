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

func TestForecastDemo(t *testing.T) {
	isolate(t)
	code, out, errOut := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "forecast", "demo", "--history", "1", "--explain", "-")
	if code != 0 || errOut != "" {
		t.Fatalf("forecast: %d %q", code, errOut)
	}
	for _, want := range []string{
		"Sprint forecast Demo-Team (as of 10.03.2026)",
		"2026.4  18.02. – 04.03.2026  finished",
		"2026.6  18.03. – 01.04.2026  planned   40.0 (recorded)",
		"Calculation sprint 2026.22",
		"16.8433 / 45 × 30 = 11.229 → 11.2 PT",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "2026.3 ") {
		t.Error("--history 1 shows more than one past sprint")
	}
	if code, _, errOut := run(t, "--data", demoTeams, "forecast", "demo", "--explain", "1999.1"); code != 1 || errOut != "Sprint 1999.1 is not in the forecast.\n" {
		t.Errorf("unknown sprint: %d %q", code, errOut)
	}
}

func TestReportDemo(t *testing.T) {
	isolate(t)
	code, out, _ := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "report", "demo", "-o", "-")
	if code != 0 || !strings.HasPrefix(out, "# Sprint-Forecast Demo-Team\n") {
		t.Errorf("stdout: %d %q", code, out[:min(len(out), 80)])
	}
	dir := t.TempDir()
	copyTree(t, filepath.Join(demoTeams, "demo"), filepath.Join(dir, "demo"))
	if code, out, _ := run(t, "--data", dir, "--as-of", "2026-03-10", "report"); code != 0 || out != filepath.Join(dir, "demo", "FORECAST.md")+"\n" {
		t.Errorf("file: %d %q", code, out)
	}
	written, err := os.ReadFile(filepath.Join(dir, "demo", "FORECAST.md"))
	if err != nil || !strings.HasPrefix(string(written), "# Sprint-Forecast Demo-Team") {
		t.Errorf("file content: %v", err)
	}
}

func copyTree(t *testing.T, from, to string) {
	t.Helper()
	err := filepath.WalkDir(from, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(from, path)
		if d.IsDir() {
			return os.MkdirAll(filepath.Join(to, rel), 0o755)
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(to, rel), data, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestAnalysisDemo(t *testing.T) {
	isolate(t)
	code, out, errOut := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "analysis", "demo", "--remaining", "80", "--share", "50")
	if code != 0 || errOut != "" {
		t.Fatalf("analysis: %d %q", code, errOut)
	}
	for _, want := range []string{
		"2026.5              11.7           8.8    10.5        13.2",
		"Ø               0.34",
		"Buffer: Ø scope creep 9 % of the commitment = 9 % of the Forecast PLAN (4 sprints), small-items share 20 % – fine",
		"in 50 % of the simulations by 2026.24, in 85 % by 2026.24 (model-dependent frequency, sample of 5 sprints; ≈ 4.0 PT per sprint).",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
	if code, _, _ := run(t, "--data", demoTeams, "analysis", "demo", "--share", "0"); code != 1 {
		t.Errorf("share 0: %d", code)
	}
}
