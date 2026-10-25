package app

import (
	"testing"

	"github.com/swallat/foresprint/internal/selfupdate"
)

func TestUpdateModeAndStatus(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("APPDATA", "")
	t.Setenv(selfupdate.ModeEnv, "")
	a := &API{Version: "1.0.0"}
	if got := a.UpdateStatus(); got.Mode != "on" || got.Available || got.Dev {
		t.Fatalf("fresh status: %+v", got)
	}
	if err := a.SetUpdateMode("notice"); err != nil {
		t.Fatal(err)
	}
	if got := a.UpdateStatus().Mode; got != "notice" {
		t.Errorf("mode %q", got)
	}
	if err := a.SetUpdateMode("sometimes"); err == nil {
		t.Error("accepted an unknown mode")
	}
	st := selfupdate.LoadState()
	st.Latest = "1.0.1"
	if err := st.Save(); err != nil {
		t.Fatal(err)
	}
	if got := a.UpdateStatus(); !got.Available || got.Latest != "1.0.1" || got.URL == "" {
		t.Errorf("remembered release: %+v", got)
	}
}

func TestUpdateDevelopmentBuildDoesNotUpdate(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	a := &API{Version: "dev"}
	if got, err := a.CheckUpdate(false); err != nil || !got.Dev || got.Available {
		t.Errorf("check: %+v, %v", got, err)
	}
	if _, err := a.InstallUpdate(); err == nil {
		t.Error("a development build installed an update")
	}
}

func TestUpdateRememberKeepsModeAndInstalledHidesOffer(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("APPDATA", "")
	t.Setenv(selfupdate.ModeEnv, "yes") // not a mode: must not claim precedence
	a := &API{Version: "1.0.0"}
	if err := a.SetUpdateMode("notice"); err != nil {
		t.Fatal(err)
	}
	updateRemember("1.0.1") // a check that ended after the mode was set
	got := a.UpdateStatus()
	if got.Mode != "notice" || got.ModeEnv || !got.Available {
		t.Fatalf("after check: %+v", got)
	}
	updateInstalledVersion = "1.0.1"
	t.Cleanup(func() { updateInstalledVersion = "" })
	if got := a.UpdateStatus(); got.Available || !got.Restart {
		t.Errorf("after install: %+v", got)
	}
	updateInstalledVersion = ""
	if err := a.SetUpdateMode("off"); err != nil {
		t.Fatal(err)
	}
	if got := a.UpdateStatus(); got.Available {
		t.Errorf("offered with mode off: %+v", got)
	}
}
