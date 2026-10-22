package config

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// Themes of the window: "system" follows the setting of the operating system. The labels are
// English source texts, translated on display.
var Themes = []struct{ Code, Label string }{
	{"system", "As system"},
	{"light", "Light"},
	{"dark", "Dark"},
}

// DefaultTheme is the theme without a saved choice.
const DefaultTheme = "system"

// MaxRecent is the length of the list of recently used data folders.
const MaxRecent = 8

// Language is the saved interface language ("" if none).
func Language() string { return i18n.Normalize(String("language")) }

// SaveLanguage saves the interface language.
func SaveLanguage(code string) error {
	if code == "" || i18n.Normalize(code) != code {
		var codes []string
		for _, l := range i18n.Languages() {
			codes = append(codes, l.Code)
		}
		return &Error{msg: i18n.T("Allowed: {values}", "values", strings.Join(codes, ", "))}
	}
	return Update(map[string]any{"language": code})
}

// Theme is the saved theme or the default.
func Theme() string {
	value := String("theme")
	for _, t := range Themes {
		if t.Code == value {
			return value
		}
	}
	return DefaultTheme
}

// SaveTheme saves the theme.
func SaveTheme(code string) error {
	for _, t := range Themes {
		if t.Code == code {
			return Update(map[string]any{"theme": code})
		}
	}
	var codes []string
	for _, t := range Themes {
		codes = append(codes, t.Code)
	}
	return &Error{msg: i18n.T("Allowed: {values}", "values", strings.Join(codes, ", "))}
}

// Densities of tables (personal setting of the window). The codes are fixed, the window
// translates the labels.
var (
	Densities = []string{"compact", "normal", "roomy"}
)

// Defaults of the two choices.
const DefaultDensity = "normal"

func choiceOf(key string, allowed []string, def string) string {
	value := String(key)
	for _, a := range allowed {
		if a == value {
			return value
		}
	}
	return def
}

func saveChoice(key string, allowed []string, code string) error {
	for _, a := range allowed {
		if a == code {
			return Update(map[string]any{key: code})
		}
	}
	return &Error{msg: i18n.T("Allowed: {values}", "values", strings.Join(allowed, ", "))}
}

// Density is the saved density of tables.
func Density() string { return choiceOf("density", Densities, DefaultDensity) }

// SaveDensity saves the density of tables.
func SaveDensity(code string) error { return saveChoice("density", Densities, code) }

// DataDir is the remembered data folder, if it still exists.
func DataDir() (string, bool) {
	dir := String("data_dir")
	if dir == "" {
		return "", false
	}
	info, err := os.Stat(dir)
	return dir, err == nil && info.IsDir()
}

// RecentDataDirs lists recently used data folders, newest first (also ones that no longer
// exist: the window marks them).
func RecentDataDirs() []string { return Strings("recent_data_dirs") }

// SaveDataDir remembers a data folder as the current one and puts it first in the recent list.
func SaveDataDir(path string) error {
	here, err := filepath.Abs(path)
	if err != nil {
		here = path
	}
	if resolved, err := filepath.EvalSymlinks(here); err == nil {
		here = resolved
	}
	recent := []string{here}
	for _, p := range RecentDataDirs() {
		if p != here {
			recent = append(recent, p)
		}
	}
	if len(recent) > MaxRecent {
		recent = recent[:MaxRecent]
	}
	return Update(map[string]any{"data_dir": here, "recent_data_dirs": recent})
}

// Install hooks the saved language into the translation, so that texts follow the setting.
func Install() { i18n.SetSaved(func() string { return String("language") }) }
