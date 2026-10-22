package app

import (
	"os"
	"path/filepath"
	"testing"
)

func demoDir(t *testing.T) string {
	t.Helper()
	dir, err := filepath.Abs(filepath.Join("..", "..", "..", "examples", "teams"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); err != nil {
		t.Skip("no examples/teams: " + err.Error())
	}
	return dir
}

func newAPI(t *testing.T, dataDir string) *API {
	t.Helper()
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("APPDATA", t.TempDir())
	t.Setenv("FORESPRINT_LANG", "")
	return New("test", dataDir)
}

func TestTeamsListsTheDemoTeam(t *testing.T) {
	api := newAPI(t, demoDir(t))
	teams := api.Teams()
	if len(teams) == 0 {
		t.Fatal("no teams")
	}
	for _, team := range teams {
		if team.Problem != "" {
			t.Errorf("team %s: %s", team.Key, team.Problem)
		}
		if team.Name == "" || team.People == 0 {
			t.Errorf("team %+v looks empty", team)
		}
	}
}

func TestPrefsRoundTrip(t *testing.T) {
	api := newAPI(t, "")
	if err := api.SetLanguage("de"); err != nil {
		t.Fatal(err)
	}
	if err := api.SetTheme("dark"); err != nil {
		t.Fatal(err)
	}
	p := api.Prefs()
	if p.Language != "de" || p.Theme != "dark" {
		t.Fatalf("prefs = %+v", p)
	}
	if len(p.Languages) < 2 || len(p.Themes) != 3 {
		t.Fatalf("choices = %+v %+v", p.Languages, p.Themes)
	}
	if err := api.SetTheme("neon"); err == nil {
		t.Error("an unknown theme must be refused")
	}
}

func TestSetDataDir(t *testing.T) {
	api := newAPI(t, "")
	if err := api.SetDataDir(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Error("a missing folder must be refused")
	}
	dir := t.TempDir()
	if err := api.SetDataDir(dir); err != nil {
		t.Fatal(err)
	}
	if api.DataDir() != dir {
		t.Errorf("data dir = %q", api.DataDir())
	}
}

func TestTextsAreTranslated(t *testing.T) {
	api := newAPI(t, "")
	de := api.Texts("de")
	if de["Save"] == "" {
		t.Fatal("German UI texts are missing the key \"Save\"")
	}
	if len(api.Texts("en")) != 0 {
		t.Error("English has no translations, the source texts are shown")
	}
}

func TestPickDataDirWithoutDialog(t *testing.T) {
	if _, err := newAPI(t, "").PickDataDir(); err == nil {
		t.Error("expected an error without a folder dialog")
	}
}
