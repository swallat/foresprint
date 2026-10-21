package config

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func isolate(t *testing.T) string {
	t.Helper()
	base := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", base)
	t.Setenv("APPDATA", base)
	t.Setenv("HOME", base)
	t.Setenv("USERPROFILE", base)
	if runtime.GOOS != "windows" {
		t.Setenv("APPDATA", "")
	}
	return base
}

func TestMarshalLikePython(t *testing.T) {
	got, err := Marshal(map[string]any{"b": []any{"x", "<&>"}, "a": "Zoë 😀", "c": map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	want := "{\n  \"a\": \"Zo\\u00eb \\ud83d\\ude00\",\n  \"b\": [\n    \"x\",\n    \"<&>\"\n  ],\n  \"c\": {}\n}"
	if string(got) != want {
		t.Errorf("got\n%s\nwant\n%s", got, want)
	}
}

func TestUpdateMergesAndKeepsDamaged(t *testing.T) {
	base := isolate(t)
	if err := Update(map[string]any{"language": "de"}); err != nil {
		t.Fatal(err)
	}
	if err := Update(map[string]any{"theme": "dark"}); err != nil {
		t.Fatal(err)
	}
	if Language() != "de" || Theme() != "dark" {
		t.Errorf("language %q theme %q", Language(), Theme())
	}
	path := filepath.Join(base, "foresprint", "settings.json")
	if err := os.WriteFile(path, []byte("{broken"), 0o644); err != nil {
		t.Fatal(err)
	}
	if len(Load()) != 0 {
		t.Error("damaged file should load as empty")
	}
	if err := Update(map[string]any{"theme": "light"}); err != nil {
		t.Fatal(err)
	}
	backup, err := os.ReadFile(path + ".defekt")
	if err != nil || string(backup) != "{broken" {
		t.Errorf("backup = %q, %v", backup, err)
	}
	if Theme() != "light" {
		t.Error("theme not saved")
	}
}

func TestUnwritable(t *testing.T) {
	base := isolate(t)
	if err := os.WriteFile(filepath.Join(base, "foresprint"), []byte("a file"), 0o644); err != nil {
		t.Fatal(err)
	}
	err := Update(map[string]any{"theme": "dark"})
	var ce *Error
	if err == nil || !strings.HasPrefix(err.Error(), "The settings could not be saved (") {
		t.Fatalf("error = %v", err)
	}
	_ = ce
}

func TestLegacyFolderIsCopied(t *testing.T) {
	base := isolate(t)
	old := filepath.Join(base, "sprintforecast")
	if err := os.MkdirAll(filepath.Join(old, "sperren"), 0o755); err != nil {
		t.Fatal(err)
	}
	for name, text := range map[string]string{"settings.json": `{"language": "de"}`, "sperren/lock": "x"} {
		if err := os.WriteFile(filepath.Join(old, name), []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if Language() != "de" {
		t.Error("legacy settings not used")
	}
	dir := filepath.Join(base, "foresprint")
	for _, want := range []string{"settings.json", ".migrated"} {
		if !exists(filepath.Join(dir, want)) {
			t.Errorf("%s missing", want)
		}
	}
	if exists(filepath.Join(dir, "sperren")) || !exists(filepath.Join(old, "settings.json")) {
		t.Error("lock copied or old folder removed")
	}
}

func TestDataDirs(t *testing.T) {
	isolate(t)
	var dirs []string
	for i := 0; i < MaxRecent+2; i++ {
		d := t.TempDir()
		dirs = append(dirs, d)
		if err := SaveDataDir(d); err != nil {
			t.Fatal(err)
		}
	}
	if err := SaveDataDir(dirs[5]); err != nil {
		t.Fatal(err)
	}
	recent := RecentDataDirs()
	if len(recent) != MaxRecent || recent[0] != dirs[5] || recent[1] != dirs[len(dirs)-1] {
		t.Errorf("recent = %v", recent)
	}
	if d, ok := DataDir(); !ok || d != dirs[5] {
		t.Errorf("DataDir = %q %v", d, ok)
	}
}

func TestSaveValidation(t *testing.T) {
	isolate(t)
	if SaveLanguage("fr") == nil || SaveLanguage("") == nil || SaveTheme("pink") == nil {
		t.Error("invalid values accepted")
	}
	if SaveLanguage("en") != nil || SaveTheme("dark") != nil {
		t.Error("valid values refused")
	}
}
