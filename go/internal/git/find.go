package git

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"time"
)

// Finding Git. Without administrator rights, people often install Git only for their own user
// account; right afterwards it is not yet in the PATH of the running app (or of the launcher).
// That is why the app searches the usual places and then calls Git with its full path. The PATH
// of the subprocesses stays unchanged: Git finds its helper programs (credential manager, ssh)
// through its own program folder.

// brokenTTL is how long a path that could not be started counts as unusable; then it is tried
// again.
const brokenTTL = 60 * time.Second

// startAttempts is how often a call tries the next candidate after a startup failure of the
// program (no endless retrying).
const startAttempts = 2

type brokenEntry struct {
	path  string
	since time.Time
}

var (
	findMu sync.Mutex
	found  string        // most recently found path outside the PATH
	broken []brokenEntry // paths that could not be started, oldest first

	now = time.Now // replaced in tests
)

// Locations returns the places where Git is searched for besides the PATH (in this order).
func Locations() []string {
	home, _ := os.UserHomeDir()
	if runtime.GOOS == "windows" {
		var places []string
		if local := os.Getenv("LOCALAPPDATA"); local != "" {
			places = append(places, filepath.Join(local, "Programs", "Git", "cmd", "git.exe"))
		}
		places = append(places,
			filepath.Join(home, "scoop", "shims", "git.exe"),
			filepath.Join(home, "scoop", "apps", "git", "current", "cmd", "git.exe"),
		)
		for _, name := range []string{"ProgramFiles", "ProgramFiles(x86)"} {
			if base := os.Getenv(name); base != "" {
				places = append(places, filepath.Join(base, "Git", "cmd", "git.exe"))
			}
		}
		return places
	}
	return []string{
		"/opt/homebrew/bin/git",
		"/usr/local/bin/git",
		"/usr/local/git/bin/git",
		"/home/linuxbrew/.linuxbrew/bin/git",
		filepath.Join(home, ".local", "bin", "git"),
		filepath.Join(home, ".nix-profile", "bin", "git"),
	}
}

func isExecutableFile(path string) bool {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return false
	}
	if runtime.GOOS == "windows" {
		return true
	}
	return info.Mode().Perm()&0o111 != 0
}

// whichIn looks for git in one PATH folder.
func whichIn(dir string) string {
	names := []string{"git"}
	if runtime.GOOS == "windows" {
		names = []string{"git.exe", "git.cmd", "git.bat", "git.com"}
	}
	for _, name := range names {
		path := filepath.Join(dir, name)
		if isExecutableFile(path) {
			return path
		}
	}
	return ""
}

func abs(path string) string {
	if a, err := filepath.Abs(path); err == nil {
		return a
	}
	return path
}

// activeBroken returns the paths that still count as unusable, oldest first. A block expires
// after brokenTTL, then the path is tried again. The caller holds findMu.
func activeBroken() []string {
	var out []string
	var kept []brokenEntry
	t := now()
	for _, b := range broken {
		if t.Sub(b.since) < brokenTTL {
			kept = append(kept, b)
			out = append(out, b.path)
		}
	}
	broken = kept
	return out
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// FindGit returns the path to Git: first in the PATH, otherwise in the places from Locations;
// "" if Git is nowhere to be found. A find outside the PATH is remembered (as long as the file
// exists); a failure is not, so that a fresh installation is found immediately.
func FindGit() string {
	findMu.Lock()
	defer findMu.Unlock()
	return findGitLocked()
}

func findGitLocked() string {
	unusable := activeBroken()
	// An empty or "." entry in the PATH yields a relative hit (the working folder).
	if hit, err := exec.LookPath("git"); hit != "" && (err == nil || errors.Is(err, exec.ErrDot)) {
		if a := abs(hit); !contains(unusable, a) {
			return a
		}
		// the first hit is unusable: check further PATH entries
		for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
			if dir == "" {
				continue
			}
			if other := whichIn(dir); other != "" && !contains(unusable, abs(other)) {
				return abs(other)
			}
		}
	}
	if found != "" && !contains(unusable, found) && isExecutableFile(found) {
		return found
	}
	found = ""
	for _, candidate := range Locations() {
		path := abs(candidate)
		if contains(unusable, path) {
			continue
		}
		if isExecutableFile(candidate) {
			found = path
			return path
		}
	}
	return ""
}

// ResetGitCache forgets the remembered Git path and those recognised as unusable (for tests and
// after a reinstallation).
func ResetGitCache() {
	findMu.Lock()
	defer findMu.Unlock()
	found = ""
	broken = nil
}

// BrokenGit returns the path of the Git most recently recognised as unusable ("" if there is
// none).
func BrokenGit() string {
	findMu.Lock()
	defer findMu.Unlock()
	if list := activeBroken(); len(list) > 0 {
		return list[len(list)-1]
	}
	return ""
}

func markBroken(executable string) {
	findMu.Lock()
	defer findMu.Unlock()
	found = ""
	if executable != "git" {
		path := abs(executable)
		kept := broken[:0]
		for _, b := range broken {
			if b.path != path {
				kept = append(kept, b)
			}
		}
		kept = append(kept, brokenEntry{path, now()}) // to the end of the order, new deadline
		broken = kept
	}
}

// started lifts an earlier block on a path: Git could be started.
func started(executable string) {
	findMu.Lock()
	defer findMu.Unlock()
	if len(broken) == 0 {
		return
	}
	path := abs(executable)
	kept := broken[:0]
	for _, b := range broken {
		if b.path != path {
			kept = append(kept, b)
		}
	}
	broken = kept
}

// Available says whether Git can be found.
func Available() bool { return FindGit() != "" }

// command returns the command line for a Git call. If Git is missing entirely, it stays at
// "git": the call then fails with a not-found error; any start error counts for the callers as
// "Git is missing or unusable". If only unusable ones exist, their path is tried once more: that
// way the message names it.
func command(args ...string) []string {
	exe := FindGit()
	if exe == "" {
		exe = BrokenGit()
	}
	if exe == "" {
		exe = "git"
	}
	return append([]string{exe}, args...)
}
