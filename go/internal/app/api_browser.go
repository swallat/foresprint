package app

import (
	"errors"

	"github.com/swallat/foresprint/internal/i18n"
)

// BrowserInfo is the state of the browser access (the same program shown as a tab of the
// browser, see internal/webui).
type BrowserInfo struct {
	// Available is false in a build without the window and inside the browser itself.
	Available bool `json:"available"`
	Running   bool `json:"running"`
	// URL is the link with the secret key; "" while the server is off.
	URL string `json:"url"`
}

// BrowserState tells whether the browser access is on and its link.
func (a *API) BrowserState() BrowserInfo {
	if a.StartBrowser == nil {
		return BrowserInfo{Available: false}
	}
	info := BrowserInfo{Available: true}
	if a.BrowserURL != nil {
		info.URL = a.BrowserURL()
	}
	info.Running = info.URL != ""
	return info
}

// BrowserStart switches the browser access on (if it is off) and returns its state.
func (a *API) BrowserStart() (BrowserInfo, error) {
	if a.StartBrowser == nil {
		return BrowserInfo{}, errors.New(i18n.T("The browser access is only available in the window."))
	}
	if _, err := a.StartBrowser(); err != nil {
		return a.BrowserState(), err
	}
	return a.BrowserState(), nil
}

// BrowserOpen switches the browser access on and opens the link in the browser of the system.
func (a *API) BrowserOpen() (BrowserInfo, error) {
	info, err := a.BrowserStart()
	if err != nil {
		return info, err
	}
	if a.OpenURL != nil {
		a.OpenURL(info.URL)
	}
	return info, nil
}

// BrowserStop switches the browser access off; the old link stops working.
func (a *API) BrowserStop() BrowserInfo {
	if a.StopBrowser != nil {
		a.StopBrowser()
	}
	return a.BrowserState()
}
