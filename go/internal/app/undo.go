package app

import (
	"errors"
	"os"
	"path/filepath"
	"sync"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
)

// A step of the window that changes several files (ending a product writes products.yaml, the
// tickets and the projects) can be taken back with one call: before such a step the files are
// remembered, and Undo puts them back. Only the last step of a team is kept, and only until the
// program ends; the next step replaces it, so Undo refuses a token that is no longer the last.
type undoEntry struct {
	token int
	files map[string][]byte // path -> content before; nil = the file did not exist
}

type undoLog struct {
	mu    sync.Mutex
	next  int
	steps map[string]undoEntry
}

// remember reads the files as they are now and returns the token that undoes the step.
func (a *API) remember(team string, files ...string) int {
	a.teamUndo.mu.Lock()
	defer a.teamUndo.mu.Unlock()
	if a.teamUndo.steps == nil {
		a.teamUndo.steps = map[string]undoEntry{}
	}
	a.teamUndo.next++
	e := undoEntry{token: a.teamUndo.next, files: map[string][]byte{}}
	for _, f := range files {
		b, err := os.ReadFile(f)
		switch {
		case err == nil:
			e.files[f] = b
		case os.IsNotExist(err):
			e.files[f] = nil // Undo removes the file again
		}
	}
	a.teamUndo.steps[team] = e
	return e.token
}

// forget drops the undo step of the team. Every write that is not itself a step calls it, so
// Undo never puts back files over a newer edit.
func (a *API) forget(team string) {
	a.teamUndo.mu.Lock()
	defer a.teamUndo.mu.Unlock()
	delete(a.teamUndo.steps, team)
}

func (a *API) teamFile(team, name string) string {
	return filepath.Join(storage.NewRepository(a.DataDir()).TeamDir(team), name)
}

// Undo takes back the last step of the team if token is still its token.
func (a *API) Undo(team string, token int) error {
	a.teamUndo.mu.Lock()
	e, ok := a.teamUndo.steps[team]
	if !ok || e.token != token {
		a.teamUndo.mu.Unlock()
		return errors.New(i18n.T("This change can no longer be undone."))
	}
	delete(a.teamUndo.steps, team)
	a.teamUndo.mu.Unlock()
	for path, content := range e.files {
		if content == nil {
			if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
				return err
			}
			continue
		}
		if err := storage.WriteText(path, string(content)); err != nil {
			return err
		}
	}
	return nil
}
