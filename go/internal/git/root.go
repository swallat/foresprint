package git

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	rootTTL   = 30 * time.Second
	statusTTL = 5 * time.Second
)

type rootEntry struct {
	at      time.Time
	root    string
	problem *Error
}

var (
	cacheMu       sync.Mutex
	rootCache     = map[string]rootEntry{}
	statusCache   = map[string]statusEntry{}
	invalidations []func()
)

type statusEntry struct {
	at      time.Time
	changes []Change
}

// locateRoot returns the root of the repository that contains path and - if there is none
// although there is one - the reason: Git rejects the folder as unsafe ("unsafe_directory").
// Any other error counts as "no repository".
func locateRoot(ctx context.Context, path string) (string, *Error, error) {
	path = resolve(path)
	cacheMu.Lock()
	cached, ok := rootCache[path]
	cacheMu.Unlock()
	if ok && now().Sub(cached.at) < rootTTL {
		return cached.root, cached.problem, nil
	}
	start := path
	for {
		if _, err := os.Stat(start); err == nil {
			break
		}
		parent := filepath.Dir(start)
		if parent == start {
			break
		}
		start = parent
	}
	if info, err := os.Stat(start); err == nil && !info.IsDir() {
		start = filepath.Dir(start)
	}
	var root string
	var problem *Error
	out, err := Git(ctx, start, "rev-parse", "--show-toplevel")
	switch {
	case err == nil:
		root = filepath.FromSlash(out)
	case As(err) != nil:
		if e := As(err); e.Kind == "unsafe_directory" {
			problem = e
		}
	default:
		return "", nil, err
	}
	cacheMu.Lock()
	rootCache[path] = rootEntry{now(), root, problem}
	cacheMu.Unlock()
	return root, problem, nil
}

// RepoRoot is the root of the Git repository that contains path - or "". "" also means that Git
// rejects the folder as unsafe; RootProblem then names the reason.
func RepoRoot(ctx context.Context, path string) (string, error) {
	root, _, err := locateRoot(ctx, path)
	return root, err
}

// RootProblem is the reason why RepoRoot returns "" although path is inside a repository (kind
// "unsafe_directory"); otherwise nil.
func RootProblem(ctx context.Context, path string) (*Error, error) {
	_, problem, err := locateRoot(ctx, path)
	return problem, err
}

// RequireRoot is like RepoRoot, but returns an *Error if there is no root: with the reason from
// RootProblem or as "is not inside a Git repository".
func RequireRoot(ctx context.Context, path string) (string, error) {
	root, problem, err := locateRoot(ctx, path)
	if err != nil {
		return "", err
	}
	if root != "" {
		return root, nil
	}
	if problem != nil { // created anew: the stored one accumulated traces on every raise
		return "", New(problem.Error(), problem.Kind, problem.Hint()).WithRaw(problem.Raw)
	}
	return "", Newf("error", "", "{path} is not inside a Git repository", "path", path)
}

// isAncestor says whether a is a folder above b.
func isAncestor(a, b string) bool {
	rel, err := filepath.Rel(a, b)
	return err == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

// ForgetRoots forgets cached roots for path, below it and above it (after git init or git clone -
// otherwise "no repository" would still apply for up to 30 seconds).
func ForgetRoots(path string) {
	path = resolve(path)
	cacheMu.Lock()
	defer cacheMu.Unlock()
	for key := range rootCache {
		if key == path || isAncestor(path, key) || isAncestor(key, path) {
			delete(rootCache, key)
		}
	}
}

// Change is an uncommitted change. Status: M modified, D deleted, A new (staged), R renamed, ??
// new (not staged) - also combined (AM, RM, AD ...). For renames and copies Orig is the previous
// path.
type Change struct {
	Status string
	File   string // relative to the repository root
	Orig   string
}

// ChangesIn returns the uncommitted changes below path, with the previous path for renames.
func ChangesIn(ctx context.Context, path string) ([]Change, error) {
	root, err := RequireRoot(ctx, path)
	if err != nil {
		return nil, err
	}
	// Do not strip: the status column may start with a space (" M file").
	out, err := With(ctx, root, Opts{Keep: true},
		"status", "--porcelain=v1", "-z", "--untracked-files=all", "--", resolve(path))
	if err != nil {
		return nil, err
	}
	entries := strings.Split(out, "\x00")
	var changes []Change
	for i := 0; i < len(entries); {
		entry := entries[i]
		i++
		if len(entry) < 4 {
			continue
		}
		xy, file, orig := entry[:2], entry[3:], ""
		if (strings.Contains(xy, "R") || strings.Contains(xy, "C")) && i < len(entries) { // the previous path follows
			orig = entries[i]
			i++
		}
		changes = append(changes, Change{strings.TrimSpace(xy), file, orig})
	}
	return changes, nil
}

// PendingChanges is ChangesIn for callers that only need status and (new) path.
func PendingChanges(ctx context.Context, path string) ([]Change, error) {
	return ChangesIn(ctx, path)
}

// CachedPendingChanges is like PendingChanges, but queried anew only every few seconds (for the
// interface, which redraws on every input). Invalidate with InvalidateStatus after saving,
// committing and switching the data folder.
func CachedPendingChanges(ctx context.Context, path string) ([]Change, error) {
	key := resolve(path)
	cacheMu.Lock()
	cached, ok := statusCache[key]
	cacheMu.Unlock()
	if ok && now().Sub(cached.at) < statusTTL {
		return append([]Change(nil), cached.changes...), nil
	}
	changes, err := PendingChanges(ctx, path)
	if err != nil {
		return nil, err
	}
	cacheMu.Lock()
	statusCache[key] = statusEntry{now(), changes}
	cacheMu.Unlock()
	return append([]Change(nil), changes...), nil
}

// OnInvalidate registers a further cache that is cleared by InvalidateStatus.
func OnInvalidate(hook func()) {
	cacheMu.Lock()
	invalidations = append(invalidations, hook)
	cacheMu.Unlock()
}

// InvalidateStatus discards cached Git states (after saving, commit, sync).
func InvalidateStatus() {
	cacheMu.Lock()
	statusCache = map[string]statusEntry{}
	for key, entry := range rootCache {
		if entry.root == "" {
			delete(rootCache, key) // "no repository" is not permanent
		}
	}
	hooks := append([]func(){}, invalidations...)
	cacheMu.Unlock()
	for _, hook := range hooks {
		hook()
	}
}
