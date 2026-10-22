package cli

import (
	"bytes"
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

func TestExcelDemo(t *testing.T) {
	isolate(t)
	target := filepath.Join(t.TempDir(), "demo.xlsx")
	code, out, errOut := run(t, "--data", demoTeams, "--as-of", "2026-03-10", "excel", "demo", "-o", target)
	if code != 0 || strings.TrimSpace(out) != target || errOut != "" {
		t.Fatalf("excel: %d %q %q", code, out, errOut)
	}
	content, err := os.ReadFile(target)
	if err != nil || !strings.HasPrefix(string(content), "PK") {
		t.Errorf("not a workbook: %v", err)
	}
	if code, _, errOut := run(t, "--data", demoTeams, "excel", "nope"); code != 1 || !strings.Contains(errOut, "not found") {
		t.Errorf("unknown team: %d %q", code, errOut)
	}
}

func TestExcelRoundTrip(t *testing.T) {
	isolate(t)
	data := t.TempDir()
	copyTree(t, demoTeams, data)
	book := filepath.Join(t.TempDir(), "demo.xlsx")
	if code, _, errOut := run(t, "--data", data, "--as-of", "2026-10-15", "excel", "demo", "-o", book); code != 0 {
		t.Fatalf("export: %d %q", code, errOut)
	}
	code, out, errOut := run(t, "--data", data, "--as-of", "2026-10-15", "excel-import", "demo", book)
	if code != 0 || out != "No changes compared to the existing files.\n" || errOut != "" {
		t.Fatalf("import of the unchanged workbook: %d %q %q", code, out, errOut)
	}
	// A change in the files shows in the preview and the import takes it back.
	path := filepath.Join(data, "demo", "team.yaml")
	text, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	changed := strings.Replace(string(text), "window: 5", "window: 4", 1)
	if changed == string(text) {
		t.Fatal("window not found in team.yaml")
	}
	if err := os.WriteFile(path, []byte(changed), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, _ = run(t, "--data", data, "--as-of", "2026-10-15", "excel-import", "demo", book)
	if code != 0 || !strings.Contains(out, "forecast.window") || !strings.Contains(out, "Preview only") {
		t.Fatalf("preview: %d %q", code, out)
	}
	if after, _ := os.ReadFile(path); string(after) != changed {
		t.Error("the preview wrote a file")
	}
	if code, _, errOut := run(t, "--data", data, "--as-of", "2026-10-15", "excel-import", "demo", book, "--apply"); code != 0 {
		t.Fatalf("apply: %d %q", code, errOut)
	}
	if after, _ := os.ReadFile(path); string(after) != string(text) {
		t.Errorf("team.yaml not restored:\n%s", after)
	}
	if code, _, errOut := run(t, "--data", data, "excel-import", "demo", filepath.Join(data, "nope.xlsx")); code != 1 || errOut == "" {
		t.Errorf("missing file: %d %q", code, errOut)
	}
}

func TestPeopleKinds(t *testing.T) {
	isolate(t)
	data := t.TempDir()
	copyTree(t, demoTeams, data)
	var out, errOut bytes.Buffer
	in := strings.NewReader("n\nFrieda Extern\n\n2026-10-15\n1\n2026-12-18\nq\n")
	args := []string{"--data", data, "--as-of", "2026-10-15", "people", "demo", "--kind", "external"}
	if code := Execute(args, in, &out, &errOut); code != 0 {
		t.Fatalf("people: %d %q", code, errOut.String())
	}
	if !strings.Contains(out.String(), "Last day in the team") {
		t.Errorf("external people must be asked for an end date:\n%s", out.String())
	}
	raw, err := os.ReadFile(filepath.Join(data, "demo", "people.yaml"))
	if err != nil || !strings.Contains(string(raw), "kind: external") || !strings.Contains(string(raw), "2026-12-18") {
		t.Errorf("people.yaml: %v\n%s", err, raw)
	}
	_, table, _ := run(t, "--data", data, "--as-of", "2026-10-15", "people", "demo")
	if !strings.Contains(table, "external") {
		t.Errorf("kind column missing:\n%s", table)
	}
	if code, _, errOut := run(t, "--data", data, "people", "demo", "--kind", "boss"); code == 0 || !strings.Contains(errOut, "--kind") {
		t.Errorf("bad kind: %d %q", code, errOut)
	}
}

func TestAbsencePeriods(t *testing.T) {
	isolate(t)
	data := t.TempDir()
	copyTree(t, demoTeams, data)
	base := []string{"--data", data, "--as-of", "2026-10-15", "absences", "demo"}
	with := func(extra ...string) (int, string, string) {
		return run(t, append(append([]string{}, base...), extra...)...)
	}

	code, out, errOut := with("--person", "anna", "--from", "2026-10-26", "--to", "2026-10-30")
	if code != 0 || !strings.Contains(out, "Working days of Anna") {
		t.Fatalf("add: %d %q %q", code, out, errOut)
	}
	raw, err := os.ReadFile(filepath.Join(data, "demo", "abwesenheiten.yaml"))
	if err != nil || !strings.Contains(string(raw), "2026-10-26") {
		t.Fatalf("abwesenheiten.yaml: %v\n%s", err, raw)
	}
	// An adjoining period is joined with the first one.
	if code, _, errOut := with("--person", "Anna", "--from", "2026-10-31", "--to", "2026-11-02", "--confirmed"); code != 0 {
		t.Fatalf("join: %d %q", code, errOut)
	}
	_, list, _ := with("--periods")
	if !strings.Contains(list, "26.10.2026") || !strings.Contains(list, "02.11.2026") || strings.Count(list, "Anna") != 1 {
		t.Errorf("list:\n%s", list)
	}
	if code, _, errOut := with("--person", "anna", "--from", "2026-10-26", "--remove"); code != 0 {
		t.Fatalf("remove: %d %q", code, errOut)
	}
	if _, list, _ := with("--periods"); !strings.Contains(list, "No absence periods") {
		t.Errorf("after remove:\n%s", list)
	}
	for _, bad := range [][]string{
		{"--person", "nobody", "--from", "2026-10-26"},
		{"--person", "anna", "--from", "26.10.2026"},
		{"--person", "anna", "--from", "2026-10-30", "--to", "2026-10-26"},
		{"--person", "anna"},
	} {
		if code, _, _ := with(bad...); code == 0 {
			t.Errorf("%v must fail", bad)
		}
	}
}

func TestSprintNaming(t *testing.T) {
	isolate(t)
	data := t.TempDir()
	copyTree(t, demoTeams, data)
	base := []string{"--data", data, "--as-of", "2026-10-15", "sprint-naming", "demo"}
	with := func(extra ...string) (int, string, string) { return run(t, append(append([]string{}, base...), extra...)...) }

	if code, out, _ := with(); code != 0 || !strings.Contains(out, "named by their ID") {
		t.Fatalf("show: %d %q", code, out)
	}
	code, out, errOut := with("--pattern", "S{JJ}-{NN}")
	if code != 0 || !strings.Contains(out, "S26-") {
		t.Fatalf("set: %d %q %q", code, out, errOut)
	}
	raw, err := os.ReadFile(filepath.Join(data, "demo", "team.yaml"))
	if err != nil || !strings.Contains(string(raw), "S{JJ}-{NN}") {
		t.Errorf("team.yaml: %v\n%s", err, raw)
	}
	if code, out, _ := with("--pattern", "X"); code != 0 || strings.Count(out, "(twice)") == 0 {
		t.Errorf("duplicate names must be marked: %d\n%s", code, out)
	}
	if code, _, errOut := with("--pattern", "{XX}"); code == 0 || !strings.Contains(errOut, "{XX}") {
		t.Errorf("unknown placeholder: %d %q", code, errOut)
	}
	if code, _, errOut := with("--pattern", "A", "--from", "9999.9"); code == 0 || !strings.Contains(errOut, "9999.9") {
		t.Errorf("unknown sprint: %d %q", code, errOut)
	}
	if code, out, _ := with("--clear"); code != 0 || !strings.Contains(out, "named by their ID") {
		t.Errorf("clear: %d %q", code, out)
	}
}
