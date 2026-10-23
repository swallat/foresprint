package app

import (
	"errors"
	"os"
	"path/filepath"
	"time"

	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/tutorial"
)

// demoState is the demo mode (area Start): the window works on the invented Team Atlas in a
// throwaway folder, so that guided flows can be tried without touching the data of the person.
type demoState struct {
	on       bool
	previous string // the data folder to go back to
	dir      string // the throwaway folder
}

// EnterDemo writes Team Atlas into a throwaway folder and makes it the data folder, until
// LeaveDemo. team ("atlas" or "simple") and source ("packages", "tracker" or "none") choose the
// variant; "" means the full Atlas with work packages. Nothing is remembered in the settings of
// the person. It returns the key of the team.
func (a *API) EnterDemo(lang, team, source string) (string, error) {
	a.enterMu.Lock() // two overlapping calls would lose the folder to go back to
	defer a.enterMu.Unlock()
	a.mu.Lock()
	if a.demo.on { // start over with fresh data
		a.demoDropLocked()
		a.data.SetFolder(a.dataDir)
	}
	a.mu.Unlock()
	dir, err := os.MkdirTemp("", "foresprint-demo-")
	if err != nil {
		return "", err
	}
	if code := i18n.Normalize(lang); code != "" {
		lang = code
	}
	if err := tutorial.WriteWith(dir, a.today(), lang, tutorial.Options{Team: team, Source: source}); err != nil {
		_ = os.RemoveAll(dir)
		return "", err
	}
	a.mu.Lock()
	a.demo = demoState{on: true, previous: a.dataDir, dir: dir}
	a.dataDir = dir
	a.undo = nil
	a.mu.Unlock()
	a.data.SetFolder(dir)
	storage.ClearTeamCache()
	return tutorial.Key, nil
}

// LeaveDemo goes back to the data folder and drops the demo data. It does nothing outside the
// demo.
func (a *API) LeaveDemo() error {
	a.mu.Lock()
	previous := a.demo.previous
	was := a.demo.on
	a.demoDropLocked()
	a.mu.Unlock()
	if was {
		a.data.SetFolder(previous)
		storage.ClearTeamCache()
	}
	return nil
}

// InDemo reports whether the demo mode is on.
func (a *API) InDemo() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.demo.on
}

// demoDropLocked removes the throwaway folder and restores the data folder; a.mu is held.
func (a *API) demoDropLocked() {
	if !a.demo.on {
		return
	}
	_ = os.RemoveAll(a.demo.dir)
	a.dataDir = a.demo.previous
	a.undo = nil
	a.demo = demoState{}
}

// demoStatus is the top bar in the demo: nothing is shared, so there is nothing to save.
func demoStatus() Status {
	return Status{Storage: StorageLocal, Detail: i18n.T("Demo data, not saved"), Data: datasvc.Status{}}
}

// demoResult is the answer of Save, Refresh and the tracker sync in the demo.
func demoResult() Result {
	return Result{OK: true, Message: i18n.T("This is demo data: nothing is saved or shared.")}
}

// demoSweep removes demo folders a former run left behind (the program was closed in the demo);
// a day old ones only, another window may still use a younger one.
func demoSweep() {
	old, _ := filepath.Glob(filepath.Join(os.TempDir(), "foresprint-demo-*"))
	for _, dir := range old {
		if info, err := os.Stat(dir); err == nil && time.Since(info.ModTime()) > 24*time.Hour {
			_ = os.RemoveAll(dir)
		}
	}
}

// demoRefusal is the answer to anything that would change the data folder while the demo runs.
func (a *API) demoRefusal() error {
	if a.InDemo() {
		return errors.New(i18n.T("Leave the demo first: click \"Back to my data\"."))
	}
	return nil
}

// demoProblem is demoRefusal as the problem the storage calls report.
func (a *API) demoProblem() *datasvc.Problem {
	if err := a.demoRefusal(); err != nil {
		return &datasvc.Problem{Kind: "error", Message: err.Error()}
	}
	return nil
}
