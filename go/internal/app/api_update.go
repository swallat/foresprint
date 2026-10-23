package app

import (
	"context"
	"errors"
	"os"
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

func (a *API) updateInfo(latest, url string) UpdateInfo {
	st := selfupdate.LoadState()
	if latest == "" {
		latest = st.Latest
	}
	info := UpdateInfo{
		Version: a.Version, Latest: latest, URL: url, Mode: string(selfupdate.CurrentMode()),
		ModeEnv: os.Getenv(selfupdate.ModeEnv) != "", Dev: selfupdate.IsDevelopment(a.Version),
	}
	if !st.LastCheck.IsZero() {
		info.LastCheck = st.LastCheck.UTC().Format(time.RFC3339)
	}
	info.Available = !info.Dev && latest != "" && selfupdate.Newer(a.Version, latest)
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
	st := selfupdate.LoadState()
	if auto && (selfupdate.CurrentMode() == selfupdate.Off || !st.Due(time.Now())) {
		return a.updateInfo("", ""), nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	rel, err := (&selfupdate.Updater{Current: a.Version}).Latest(ctx)
	st.LastCheck = time.Now().UTC() // also after a failure: try again tomorrow, not at every start
	if err != nil {
		_ = st.Save()
		if auto {
			return a.updateInfo("", ""), nil
		}
		return a.updateInfo("", ""), updateErr("The newest version could not be determined: {error}", "error", err.Error())
	}
	st.Latest = rel.Version
	_ = st.Save()
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
	st := selfupdate.LoadState()
	st.LastCheck, st.Latest = time.Now().UTC(), rel.Version
	_ = st.Save()
	info := a.updateInfo(rel.Version, rel.URL)
	info.Restart = true
	return info, nil
}

// SetUpdateMode saves the automatic mode: on, notice or off. In the window every mode only
// looks for a new version; installing is always a click.
func (a *API) SetUpdateMode(mode string) error {
	m, ok := selfupdate.ParseMode(mode)
	if !ok {
		return updateErr("The mode must be on, notice or off.")
	}
	st := selfupdate.LoadState()
	st.Mode = string(m)
	if err := st.Save(); err != nil {
		return updateErr("The settings could not be saved ({path}): {error}", "path", selfupdate.StateFile(), "error", err.Error())
	}
	return nil
}

func updateErr(text string, values ...any) error { return errors.New(i18n.T(text, values...)) }
