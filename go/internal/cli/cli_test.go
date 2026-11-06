package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/config"
)

func run(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var out, errOut bytes.Buffer
	code := Execute(args, strings.NewReader(""), &out, &errOut)
	return code, out.String(), errOut.String()
}

func isolate(t *testing.T) {
	t.Helper()
	base := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", base)
	t.Setenv("HOME", base)
	t.Setenv("APPDATA", "")
	t.Setenv("FORESPRINT_LANG", "")
	t.Setenv(DataEnv, "")
	t.Setenv(AsOfEnv, "")
}

func TestLanguageCommand(t *testing.T) {
	isolate(t)
	if code, out, _ := run(t, "language"); code != 0 || out != "en (English)\n" {
		t.Errorf("show: %d %q", code, out)
	}
	if code, out, _ := run(t, "language", "de"); code != 0 || out != "Sprache: Deutsch\n" {
		t.Errorf("set: %d %q", code, out)
	}
	// The next start reads the saved language.
	if code, out, _ := run(t, "language"); code != 0 || out != "de (Deutsch)\n" {
		t.Errorf("saved: %d %q", code, out)
	}
	t.Setenv("FORESPRINT_LANG", "en")
	if _, out, _ := run(t, "language"); out != "en (English)\n" {
		t.Errorf("env wins: %q", out)
	}
	if code, _, errOut := run(t, "language", "fr"); code != 1 || errOut != "Allowed: de, en\n" {
		t.Errorf("invalid: %d %q", code, errOut)
	}
}

func TestVersionFlagAndBadDate(t *testing.T) {
	isolate(t)
	Version = "1.2.3"
	t.Cleanup(func() { Version = "dev" })
	if code, out, _ := run(t, "--version"); code != 0 || out != "1.2.3\n" {
		t.Errorf("version: %d %q", code, out)
	}
	if code, _, errOut := run(t, "--as-of", "21.10.2026", "language"); code != 2 || !strings.Contains(errOut, "YYYY-MM-DD") {
		t.Errorf("bad date: %d %q", code, errOut)
	}
	t.Setenv(AsOfEnv, "nonsense")
	if code, _, _ := run(t, "language"); code != 2 {
		t.Errorf("bad env date: %d", code)
	}
}

// A double click starts the program with Explorer as parent; cobra must not end it then (#368).
func TestNoMousetrap(t *testing.T) {
	if cobra.MousetrapHelpText != "" {
		t.Errorf("cobra mousetrap is on: %q", cobra.MousetrapHelpText)
	}
}

func TestCompletionScripts(t *testing.T) {
	isolate(t)
	for _, shell := range shells {
		code, out, errOut := run(t, "completion", shell, "--prog-name", "fs")
		if code != 0 || errOut != "" || !strings.Contains(out, "fs") {
			t.Errorf("%s: %d %q", shell, code, errOut)
		}
	}
	if code, _, _ := run(t, "completion", "tcsh"); code == 0 {
		t.Error("unknown shell accepted")
	}
}

func TestCompleteCommandNames(t *testing.T) {
	isolate(t)
	_, out, _ := run(t, "__complete", "lang")
	if !strings.HasPrefix(out, "language\t") {
		t.Errorf("complete = %q", out)
	}
}

func TestDataDirOrder(t *testing.T) {
	isolate(t)
	cwd := t.TempDir()
	teams := filepath.Join(cwd, "teams", "alpha")
	if err := os.MkdirAll(teams, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(teams, "team.yaml"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	t.Chdir(cwd)
	e := &Env{}
	if got := e.DataDir(); got != filepath.Join(".", "teams") {
		t.Errorf("repository layout: %q", got)
	}
	t.Setenv(DataEnv, "/elsewhere")
	if got := e.DataDir(); got != "/elsewhere" {
		t.Errorf("env: %q", got)
	}
	e.Data = "given"
	if got := e.DataDir(); got != "given" {
		t.Errorf("flag: %q", got)
	}
}

func TestFreshStartsWindowWithEmptySettings(t *testing.T) {
	isolate(t)
	saved := t.TempDir()
	if err := config.SaveDataDir(saved); err != nil {
		t.Fatal(err)
	}
	t.Setenv(DataEnv, "/should/be/ignored")
	var gotData, gotConfig string
	var remembered bool
	old := GUI
	defer func() { GUI = old }()
	GUI = func(dir string) error {
		gotData = dir
		gotConfig = os.Getenv("XDG_CONFIG_HOME")
		_, remembered = config.DataDir()
		return nil
	}
	origConfig := os.Getenv("XDG_CONFIG_HOME")
	os.Unsetenv("APPDATA") //nolint:errcheck
	if code, _, e := run(t, "--fresh"); code != 0 {
		t.Fatalf("exit %d: %s", code, e)
	}
	if gotData != "" || remembered {
		t.Errorf("data %q remembered %v: want an empty start", gotData, remembered)
	}
	if gotConfig == origConfig {
		t.Error("settings folder was not redirected")
	}
	if v, ok := os.LookupEnv("APPDATA"); ok {
		t.Errorf("APPDATA not unset again: %q", v)
	}
	if _, err := os.Stat(gotConfig); err == nil {
		t.Error("temporary settings folder was not removed")
	}
	want, _ := filepath.EvalSymlinks(saved) // macOS: /var -> /private/var
	if got, ok := config.DataDir(); !ok || (got != saved && got != want) {
		t.Errorf("saved settings changed: %q %v", got, ok)
	}
}

// A double click starts the program in some folder; the window must not take it for the data
// folder, especially not when the remembered one is gone.
func TestWindowDataDirIgnoresTheCurrentFolder(t *testing.T) {
	isolate(t)
	cwd := t.TempDir()
	team := filepath.Join(cwd, "teams", "alpha")
	if err := os.MkdirAll(team, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(team, "team.yaml"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	t.Chdir(cwd)
	e := &Env{}
	if got := e.WindowDataDir(); got != "" {
		t.Errorf("nothing remembered: %q", got)
	}
	gone := filepath.Join(t.TempDir(), "gone")
	if err := config.SaveDataDir(gone); err != nil {
		t.Fatal(err)
	}
	if got := e.WindowDataDir(); got == "" || got == "." || got == filepath.Join(".", "teams") {
		t.Errorf("remembered folder that is gone must stay named: %q", got)
	}
	t.Setenv(DataEnv, "/elsewhere")
	if got := e.WindowDataDir(); got != "/elsewhere" {
		t.Errorf("env: %q", got)
	}
	e.Data = "given"
	if got := e.WindowDataDir(); got != "given" {
		t.Errorf("flag: %q", got)
	}
}
