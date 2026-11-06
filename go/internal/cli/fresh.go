package cli

import (
	"os"
	"runtime"
)

// startFresh opens the window as on the first start (to try the setup dialogs): the settings
// folder is redirected to an empty temporary folder, so that neither the remembered data folder,
// the language, the theme nor the update state are read, and nothing saved is touched. The
// folder is removed when the window is closed. --data is still honoured; FORESPRINT_DATA and
// teams in the current folder are not looked at.
func startFresh(env *Env) error {
	tmp, err := os.MkdirTemp("", "foresprint-fresh-")
	if err != nil {
		return err
	}
	defer func() { _ = os.RemoveAll(tmp) }()
	for _, name := range []string{"XDG_CONFIG_HOME", "APPDATA", DataEnv} {
		if old, had := os.LookupEnv(name); had {
			defer os.Setenv(name, old) //nolint:errcheck
		} else {
			defer os.Unsetenv(name) //nolint:errcheck
		}
	}
	_ = os.Setenv("XDG_CONFIG_HOME", tmp)
	if runtime.GOOS == "windows" {
		_ = os.Setenv("APPDATA", tmp)
	}
	_ = os.Unsetenv(DataEnv)
	return GUI(env.Data) // "" = no data folder: the setup starts
}
