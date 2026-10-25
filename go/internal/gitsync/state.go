// Package gitsync is the state and "Save and share" for shared data repositories (port of
// gitsync.py).
//
// The model is deliberately simple: one branch, always kept in sync. The functions call the git
// program (package git) and report errors as *git.Error with a kind and the next step. Own
// changes are committed before every sync so that they can never get lost; if merging fails, it
// is aborted and the state stays as it was.
package gitsync

import (
	"context"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/yamlmerge"
)

// How own changes reach the server: directly onto the branch or (server with a protected main
// branch, e.g. GitLab) via a merge request. The choice applies per data repository and is stored
// in its local Git configuration.
const (
	// ShareKey is the Git setting of the way to share.
	ShareKey = "foresprint.share"
	// AutoMergeKey set to "false" turns auto-merge off (default: on).
	AutoMergeKey = "foresprint.mrautomerge"
	// HostKey overrides the detection of the server kind from the address (default: automatic).
	HostKey = "foresprint.host"
)

// legacyKeys were written before the rename to Foresprint; they are still read and removed when
// the setting is saved.
var legacyKeys = map[string]string{
	ShareKey:     "sprintforecast.share",
	AutoMergeKey: "sprintforecast.mrautomerge",
	HostKey:      "sprintforecast.host",
}

// The ways to share.
const (
	ShareDirect       = "direct"
	ShareMergeRequest = "merge_request"
)

// The kinds of server.
const (
	HostGitLab  = "gitlab"
	HostGitHub  = "github"
	HostForgejo = "forgejo"
	HostGeneric = "generic"
)

// Hosts lists the kinds of server.
var Hosts = []string{HostGitLab, HostGitHub, HostForgejo, HostGeneric}

// MaxAttempts is how often a push is retried after "someone else has uploaded in the meantime".
const MaxAttempts = 3

const sep = "\x1f"

// Commit is a commit of someone else.
type Commit struct {
	Rev     string
	Author  string
	Day     string
	Subject string
}

// SyncState is the state of the data folder relative to the server (determined without network
// access; Behind applies to the state at the last fetch, see Fetch).
type SyncState struct {
	Root     string
	Branch   string // "" = detached HEAD
	Upstream string // e.g. "origin/main"
	Remote   string // name of the server, "" = none set up
	// URL is the raw address, may contain credentials (legacy data): never display it.
	URL        string
	Ahead      int
	Behind     int
	Unfinished string // "merge" or "rebase"
	Conflicts  []string
	// FetchError is the result of the last fetch, nil = ok/unknown.
	FetchError *git.Error
	FetchedAt  time.Time // zero = no fetch yet
	Unborn     bool      // no commit yet (freshly created repository)
}

// Detached says the repository is not on a branch.
func (s SyncState) Detached() bool { return s.Branch == "" }

// Offline says the last fetch could not reach the server.
func (s SyncState) Offline() bool { return s.FetchError != nil && s.FetchError.Kind == "offline" }

// CanShare says a server is set up, the repository is on a branch and no operation is open.
func (s SyncState) CanShare() bool { return s.Remote != "" && !s.Detached() && s.Unfinished == "" }

// ConflictFile is a file that does not merge on its own.
type ConflictFile struct {
	File          string // relative to the repository root
	Keys          []yamlmerge.KeyConflict
	Whole         bool // can only be decided as a whole (not YAML, deleted on one side)
	OursDeleted   bool
	TheirsDeleted bool
}

// Open says the file needs a decision (otherwise it is merged automatically).
func (c ConflictFile) Open() bool { return c.Whole || len(c.Keys) > 0 }

// SyncResult is the result of Sync: what was done, what came from others and what got stuck.
type SyncResult struct {
	Committed          string // short hash of the own commit
	Pulled             []Commit
	PulledFiles        []FileChange
	Pushed             bool
	MergeRequestURL    string // sharing via merge request: address, if reported
	MergeRequestBranch string // branch that was uploaded
	PullOnly           bool   // "Pull from server": upload nothing, not even when resuming
	Merged             bool   // changes from others were merged
	Conflicts          []ConflictFile
	Validation         []string // new errors after merging
	Notes              []string // notes even though everything worked
	Error              *git.Error
}

// OK says the sync ended without an error.
func (r *SyncResult) OK() bool { return r.Error == nil }

// FileChange is a changed file: status letter and path.
type FileChange struct {
	Status string
	Path   string
}

type fetchRecord struct {
	at  time.Time
	err *git.Error
}

type cachedState struct {
	at    time.Time
	state SyncState
}

var (
	mu         sync.Mutex
	fetched    = map[string]fetchRecord{}
	stateCache = map[string]cachedState{}
	infoCache  = map[string]cachedInfo{}
)

const stateTTL = 5 * time.Second

func init() {
	git.OnInvalidate(func() {
		mu.Lock()
		stateCache = map[string]cachedState{}
		infoCache = map[string]cachedInfo{}
		mu.Unlock()
	})
}

// Available says whether Git can be found.
func Available() bool { return git.Available() }

// Root is the root of the repository of path; an error if Git is missing or there is none.
func Root(ctx context.Context, path string) (string, error) {
	if !git.Available() {
		return "", git.Classify("", git.ClassifyOpts{Missing: true, Broken: git.BrokenGit()})
	}
	return git.RequireRoot(ctx, path)
}

// GitDir is the .git folder of the repository.
func GitDir(ctx context.Context, root string) (string, error) {
	inner := filepath.Join(root, ".git")
	if info, err := statDir(inner); err == nil && info {
		return inner, nil
	}
	out, err := git.Git(ctx, root, "rev-parse", "--absolute-git-dir")
	if err != nil {
		return "", err
	}
	return filepath.FromSlash(out), nil
}

// State is the state of the data folder (determined locally, without network).
func State(ctx context.Context, path string) (SyncState, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return SyncState{}, err
	}
	out, err := git.With(ctx, root, git.Opts{Keep: true},
		"status", "--porcelain=v2", "-z", "--branch", "--untracked-files=no")
	if err != nil {
		return SyncState{}, err
	}
	s := SyncState{Root: root}
	skip := 0
	for _, line := range strings.Split(out, "\x00") {
		if skip > 0 { // previous path of a rename
			skip--
			continue
		}
		switch {
		case strings.HasPrefix(line, "2 "):
			skip = 1
		case strings.HasPrefix(line, "# branch.oid "):
			s.Unborn = field(line, 2) == "(initial)" // no commit yet
		case strings.HasPrefix(line, "# branch.head "):
			if head := field(line, 2); head != "(detached)" {
				s.Branch = head
			}
		case strings.HasPrefix(line, "# branch.upstream "):
			s.Upstream = field(line, 2)
		case strings.HasPrefix(line, "# branch.ab "):
			parts := strings.Split(line, " ")
			if len(parts) >= 4 {
				plus, _ := strconv.Atoi(strings.TrimLeft(parts[2], "+"))
				minus, _ := strconv.Atoi(parts[3])
				s.Ahead, s.Behind = plus, abs(minus)
			}
		case strings.HasPrefix(line, "u "): // unmerged file
			fields := strings.SplitN(line, " ", 11)
			s.Conflicts = append(s.Conflicts, fields[len(fields)-1])
		}
	}
	if s.Upstream != "" {
		s.Remote, _, _ = strings.Cut(s.Upstream, "/")
	} else {
		remotes, _ := git.Lenient(ctx, root, "remote")
		list := strings.Fields(remotes)
		switch {
		case contains(list, "origin"):
			s.Remote = "origin"
		case len(list) > 0:
			s.Remote = list[0]
		}
	}
	if s.Remote != "" {
		s.URL, _ = git.Lenient(ctx, root, "config", "--get", "remote."+s.Remote+".url")
	}
	gdir, err := GitDir(ctx, root)
	if err != nil {
		return SyncState{}, err
	}
	switch {
	case exists(filepath.Join(gdir, "MERGE_HEAD")):
		s.Unfinished = "merge"
	case exists(filepath.Join(gdir, "rebase-merge")) || exists(filepath.Join(gdir, "rebase-apply")):
		s.Unfinished = "rebase"
	}
	mu.Lock()
	if f, ok := fetched[root]; ok {
		s.FetchError, s.FetchedAt = f.err, f.at
	}
	mu.Unlock()
	return s, nil
}

// field returns the space separated field i of a status line (the rest of the line for the
// third field, as Python's split(" ", 2)).
func field(line string, i int) string {
	parts := strings.SplitN(line, " ", 3)
	if i < len(parts) {
		return parts[i]
	}
	return ""
}

// CachedState is like State, but cached briefly (for the UI); invalidated by
// git.InvalidateStatus.
func CachedState(ctx context.Context, path string) (SyncState, error) {
	key := git.Resolve(path)
	mu.Lock()
	cached, ok := stateCache[key]
	mu.Unlock()
	if ok && time.Since(cached.at) < stateTTL {
		return cached.state, nil
	}
	current, err := State(ctx, path)
	if err != nil {
		return SyncState{}, err
	}
	mu.Lock()
	stateCache[key] = cachedState{time.Now(), current}
	mu.Unlock()
	return current, nil
}

// Incoming returns what others have changed since the own state (as of the last fetch): commits
// and changed files (status, path) below path.
func Incoming(ctx context.Context, path string, limit int) ([]Commit, []FileChange, error) {
	if limit == 0 {
		limit = 50
	}
	root, err := Root(ctx, path)
	if err != nil {
		return nil, nil, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return nil, nil, err
	}
	if current.Upstream == "" || current.Behind == 0 {
		return nil, nil, nil
	}
	target := git.Resolve(path)
	logOut, _ := git.Lenient(ctx, root, "log", "-"+strconv.Itoa(limit),
		"--format=%h"+sep+"%an"+sep+"%as"+sep+"%s", "HEAD.."+current.Upstream, "--", target)
	var commits []Commit
	for _, line := range strings.Split(logOut, "\n") {
		if strings.Contains(line, sep) {
			f := git.SplitRecord(line, 4, sep)
			commits = append(commits, Commit{f[0], f[1], f[2], f[3]})
		}
	}
	base, _ := git.Lenient(ctx, root, "merge-base", "HEAD", current.Upstream)
	span := "HEAD.." + current.Upstream
	if base != "" {
		span = "HEAD..." + current.Upstream
	}
	diff, _ := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
		"diff", "--name-status", "-z", span, "--", target)
	var files []FileChange
	entries := strings.Split(diff, "\x00")
	for i := 0; i < len(entries) && entries[i] != ""; {
		status := entries[i]
		i++
		names := 1 // for renames: old, new
		if status[:1] == "R" || status[:1] == "C" {
			names = 2
		}
		if i+names > len(entries) {
			break
		}
		files = append(files, FileChange{status[:1], entries[i+names-1]})
		i += names
	}
	return commits, files, nil
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}
