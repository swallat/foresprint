package app

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/swallat/foresprint/internal/i18n"
)

// Undo and redo for everything the window changes in the data folder. The window calls
// HistoryBegin before a write and HistoryEnd after it; when files differ, the step goes on the
// undo list (only the files that changed, before and after). Only unsaved work is kept: the
// window clears the list when something else rewrites files (save, fetch, discard, a change of
// the other view, a switch of the data folder), and a step whose files were touched since is
// refused, so undo never overwrites newer work.

const historyMax = 50

// historyMaxFile keeps a stray big file out of the snapshots.
const historyMaxFile = 8 << 20

type historyStep struct {
	dir    string
	before map[string][]byte // nil value = the file did not exist
	after  map[string][]byte
}

type historyLog struct {
	mu      sync.Mutex
	pending map[string][]byte
	dir     string
	undo    []historyStep
	redo    []historyStep
}

// HistoryState tells what the undo and redo keys can do.
type HistoryState struct {
	CanUndo bool `json:"canUndo"`
	CanRedo bool `json:"canRedo"`
}

// HistoryResult is the answer of HistoryUndo and HistoryRedo.
type HistoryResult struct {
	OK      bool         `json:"ok"`
	Message string       `json:"message"`
	Files   int          `json:"files"`
	State   HistoryState `json:"state"`
}

func historyData(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		if strings.HasPrefix(part, ".") {
			return false
		}
	}
	low := strings.ToLower(rel)
	return !strings.HasSuffix(low, ".tmp") && !strings.HasSuffix(low, ".xlsx")
}

// historySnapshot reads the data files of the folder (relative path -> content).
func historySnapshot(dir string) map[string][]byte {
	out := map[string][]byte{}
	if dir == "" {
		return out
	}
	_ = filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, rerr := filepath.Rel(dir, path)
		if rerr != nil || rel == "." {
			return nil
		}
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			if !historyData(rel) {
				return filepath.SkipDir
			}
			return nil
		}
		if !historyData(rel) {
			return nil
		}
		if info, ierr := d.Info(); ierr != nil || info.Size() > historyMaxFile {
			return nil
		}
		if b, berr := os.ReadFile(path); berr == nil {
			out[rel] = b
		}
		return nil
	})
	return out
}

func (h *historyLog) state() HistoryState {
	return HistoryState{CanUndo: len(h.undo) > 0, CanRedo: len(h.redo) > 0}
}

// HistoryBegin remembers the data files before a step of the window.
func (a *API) HistoryBegin() {
	dir := a.DataDir()
	snap := historySnapshot(dir)
	a.hist.mu.Lock()
	defer a.hist.mu.Unlock()
	a.hist.pending, a.hist.dir = snap, dir
}

// HistoryEnd compares the files with what HistoryBegin saw and, when they differ, puts the step
// on the undo list. A new step empties the redo list.
func (a *API) HistoryEnd() HistoryState {
	dir := a.DataDir()
	now := historySnapshot(dir)
	a.hist.mu.Lock()
	defer a.hist.mu.Unlock()
	h := &a.hist
	before := h.pending
	h.pending = nil
	if before == nil || h.dir != dir {
		return h.state()
	}
	step := historyStep{dir: dir, before: map[string][]byte{}, after: map[string][]byte{}}
	for rel, b := range before {
		if n, ok := now[rel]; !ok {
			step.before[rel], step.after[rel] = b, nil
		} else if !bytes.Equal(b, n) {
			step.before[rel], step.after[rel] = b, n
		}
	}
	for rel, n := range now {
		if _, ok := before[rel]; !ok {
			step.before[rel], step.after[rel] = nil, n
		}
	}
	if len(step.before) == 0 {
		return h.state()
	}
	h.undo = append(h.undo, step)
	if len(h.undo) > historyMax {
		h.undo = h.undo[len(h.undo)-historyMax:]
	}
	h.redo = nil
	return h.state()
}

// HistoryClear forgets all steps (after a save, a fetch, a change from outside).
func (a *API) HistoryClear() HistoryState {
	a.hist.mu.Lock()
	defer a.hist.mu.Unlock()
	a.hist.undo, a.hist.redo, a.hist.pending = nil, nil, nil
	return a.hist.state()
}

// HistoryInfo tells whether undo and redo have a step.
func (a *API) HistoryInfo() HistoryState {
	a.hist.mu.Lock()
	defer a.hist.mu.Unlock()
	return a.hist.state()
}

// HistoryUndo takes the last step back.
func (a *API) HistoryUndo() HistoryResult { return a.historyMove(true) }

// HistoryRedo does the step again that undo took back.
func (a *API) HistoryRedo() HistoryResult { return a.historyMove(false) }

func (a *API) historyMove(undo bool) HistoryResult {
	dir := a.DataDir()
	a.hist.mu.Lock()
	defer a.hist.mu.Unlock()
	h := &a.hist
	from, to := &h.undo, &h.redo
	if !undo {
		from, to = &h.redo, &h.undo
	}
	if len(*from) == 0 {
		return HistoryResult{Message: i18n.T("Nothing to undo or redo."), State: h.state()}
	}
	step := (*from)[len(*from)-1]
	// The files must still be as the step left (undo) or found (redo).
	have, want := step.after, step.before
	if !undo {
		have, want = step.before, step.after
	}
	stale := step.dir != dir
	if !stale {
		for rel, b := range have {
			cur, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(rel)))
			if (b == nil) != (err != nil) || (err == nil && !bytes.Equal(cur, b)) {
				stale = true
				break
			}
		}
	}
	if stale {
		h.undo, h.redo = nil, nil
		return HistoryResult{Message: i18n.T("The data changed in the meantime, so the steps were dropped."), State: h.state()}
	}
	for rel, b := range want {
		path := filepath.Join(dir, filepath.FromSlash(rel))
		if b == nil {
			if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
				return HistoryResult{Message: err.Error(), State: h.state()}
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return HistoryResult{Message: err.Error(), State: h.state()}
		}
		if err := os.WriteFile(path, b, 0o644); err != nil {
			return HistoryResult{Message: err.Error(), State: h.state()}
		}
	}
	*from = (*from)[:len(*from)-1]
	*to = append(*to, step)
	return HistoryResult{OK: true, Files: len(want), State: h.state()}
}
