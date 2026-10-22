package app

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// OpenFile opens a file of the data folder with the program the system has for it. Only files
// inside the data folder are opened, so the page cannot start arbitrary files.
func (a *API) OpenFile(path string) error {
	dir := a.DataDir()
	if dir == "" {
		return errors.New(i18n.T("No data folder is open."))
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	root, err := filepath.EvalSymlinks(dir)
	if err != nil {
		return err
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(root, real)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return errors.New(i18n.T("Only files of the data folder can be opened."))
	}
	// Documents only: a program, script or shortcut that is committed to the data must not start from here.
	if fi, err := os.Stat(real); err != nil || fi.IsDir() || !openable[strings.ToLower(filepath.Ext(real))] || insideGit(rel) {
		return errors.New(i18n.T("Only files of the data folder can be opened."))
	}
	open := a.OpenPath
	if open == nil {
		open = openWithSystem
	}
	return open(real)
}

var openable = map[string]bool{".md": true, ".txt": true, ".csv": true, ".yaml": true, ".yml": true, ".pdf": true, ".xlsx": true}

// insideGit: the path (relative to the data folder) runs through a .git folder.
func insideGit(rel string) bool {
	for _, part := range strings.Split(filepath.ToSlash(rel), "/") {
		if strings.EqualFold(part, ".git") {
			return true
		}
	}
	return false
}

// openWithSystem starts the program the system has for the file and does not wait for it.
func openWithSystem(path string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", path)
	case "darwin":
		cmd = exec.Command("open", path)
	default:
		cmd = exec.Command("xdg-open", path)
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}
