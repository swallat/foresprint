package app

import (
	"context"
	"errors"
	"os"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/selfupdate"
)

// UpdateInfo is what Settings > Updates and the notice in the top bar show.
type UpdateInfo struct {
	Version   string `json:"version"`   // installed
	Latest    string `json:"latest"`    // newest known, "" if never checked
	Available bool   `json:"available"` // Latest is newer than Version
	URL       string `json:"url"`       // page of the release
	Mode      string `json:"mode"`      // on, notice or off
	ModeEnv   bool   `json:"modeEnv"`   // the environment variable overrides the saved mode
	LastCheck string `json:"lastCheck"` // RFC 3339, "" if never
	Dev       bool   `json:"dev"`       // a development build does not update itself
	Restart   bool   `json:"restart"`   // an update was installed, the next start uses it
}

// updateMu serializes the changes of update.json: a check on its way must not undo a mode set
// meanwhile. updateInstalledVersion is the version this process has put in place.
var (
	updateMu               sync.Mutex
	updateInstalledVersion string
)

// updateRemember stores what a check found and leaves the rest of the state (the mode) as it
// is now.
func updateRemember(latest string) {
	updateMu.Lock()
	defer updateMu.Unlock()
	st := selfupdate.LoadState()
	st.LastCheck = time.Now().UTC()
	if latest != "" {
		st.Latest = latest
	}
	_ = st.Save()
}

func (a *API) updateInfo(latest, url string) UpdateInfo {
	st := selfupdate.LoadState()
	if latest == "" {
		latest = st.Latest
	}
	info := UpdateInfo{
		Version: a.Version, Latest: latest, URL: url, Mode: string(selfupdate.CurrentMode()),
		ModeEnv: updateEnvMode(), Dev: selfupdate.IsDevelopment(a.Version),
	}
	if !st.LastCheck.IsZero() {
		info.LastCheck = st.LastCheck.UTC().Format(time.RFC3339)
	}
	info.Restart = latest != "" && latest == updateInstalledVersion
	info.Available = !info.Dev && !info.Restart && info.Mode != string(selfupdate.Off) && latest != "" && selfupdate.Newer(a.Version, latest)
	if info.URL == "" && latest != "" {
		info.URL = "https://github.com/" + selfupdate.DefaultRepo + "/releases/tag/v" + latest
	}
	return info
}

// UpdateStatus answers from what the last check remembered; it does not use the network.
func (a *API) UpdateStatus() UpdateInfo { return a.updateInfo("", "") }

// CheckUpdate asks GitHub for the newest release. With auto, it only asks when the daily check
// is due and the mode is not off (the check at the start of the window).
func (a *API) CheckUpdate(auto bool) (UpdateInfo, error) {
	if selfupdate.IsDevelopment(a.Version) {
		return a.updateInfo("", ""), nil
	}
	if auto && (selfupdate.CurrentMode() == selfupdate.Off || !selfupdate.LoadState().Due(time.Now())) {
		return a.updateInfo("", ""), nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	rel, err := (&selfupdate.Updater{Current: a.Version}).Latest(ctx)
	if err != nil {
		updateRemember("") // also after a failure: try again tomorrow, not at every start
		if auto {
			return a.updateInfo("", ""), nil
		}
		return a.updateInfo("", ""), updateErr("The newest version could not be determined: {error}", "error", err.Error())
	}
	updateRemember(rel.Version)
	return a.updateInfo(rel.Version, rel.URL), nil
}

// InstallUpdate downloads the newest release, checks its checksum and replaces the program. The
// window keeps running; the next start uses the new version.
func (a *API) InstallUpdate() (UpdateInfo, error) {
	if selfupdate.IsDevelopment(a.Version) {
		return a.updateInfo("", ""), updateErr("A development build does not update itself. Install a release from {url}.",
			"url", "https://github.com/"+selfupdate.DefaultRepo+"/releases")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	u := &selfupdate.Updater{Current: a.Version}
	rel, err := u.Latest(ctx)
	if err != nil {
		return a.updateInfo("", ""), updateErr("The newest version could not be determined: {error}", "error", err.Error())
	}
	if !selfupdate.Newer(a.Version, rel.Version) {
		return a.updateInfo(rel.Version, rel.URL), nil
	}
	if err := u.Install(ctx, rel); err != nil {
		return a.updateInfo(rel.Version, rel.URL), updateErr("The update failed: {error}", "error", err.Error())
	}
	updateRemember(rel.Version)
	updateMu.Lock()
	updateInstalledVersion = rel.Version
	updateMu.Unlock()
	return a.updateInfo(rel.Version, rel.URL), nil
}

// SetUpdateMode saves the automatic mode: on, notice or off. In the window every mode only
// looks for a new version; installing is always a click.
func (a *API) SetUpdateMode(mode string) error {
	m, ok := selfupdate.ParseMode(mode)
	if !ok {
		return updateErr("The mode must be on, notice or off.")
	}
	updateMu.Lock()
	defer updateMu.Unlock()
	st := selfupdate.LoadState()
	st.Mode = string(m)
	if err := st.Save(); err != nil {
		return updateErr("The settings could not be saved ({path}): {error}", "path", selfupdate.StateFile(), "error", err.Error())
	}
	return nil
}

func updateErr(text string, values ...any) error { return errors.New(i18n.T(text, values...)) }

// updateEnvMode reports whether the environment variable holds a mode (that is when it wins).
func updateEnvMode() bool {
	_, ok := selfupdate.ParseMode(os.Getenv(selfupdate.ModeEnv))
	return ok
}
