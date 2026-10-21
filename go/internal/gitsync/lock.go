package gitsync

import (
	"context"
	"os"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
)

// In the background: short timeout (the whole process tree is terminated) and never a login
// window or prompt (Credential Manager, GIT_ASKPASS/SSH_ASKPASS, SSH passphrase). If the login is
// missing or the server is unreachable, the state stays unchanged; the "Check state" button then
// explains the next step.
const (
	// BackgroundFetchEvery is how often the interface asks for a background fetch.
	BackgroundFetchEvery = 30 * time.Minute
	// BackgroundTimeout is the time limit of a background fetch.
	BackgroundTimeout = 20 * time.Second
	// BackgroundOffEnv set (to anything): no background fetch.
	BackgroundOffEnv = "FORESPRINT_NO_BACKGROUND_FETCH"
	// LockWarn is how long a call waits for a running sync, then a notice.
	LockWarn = 60 * time.Second
)

var quietEnv = map[string]string{
	"GCM_INTERACTIVE":     "never",
	"SSH_ASKPASS_REQUIRE": "never",
	"GIT_ASKPASS":         "", // empty (not missing): Git asks neither core.askPass nor SSH_ASKPASS
}

var (
	lockMu           sync.Mutex
	syncLocks        = map[string]chan struct{}{}
	held             = map[string]time.Time{} // data folder -> start of the running sync
	backgroundActive = map[string]bool{}
	backgroundLast   = map[string]time.Time{} // last attempt per data folder (without a Git call)
)

// lockFor returns the lock of the data folder: sync and fetch never run at the same time
// (otherwise Git locks packed-refs and the index, and "Save and share" would fail because of a
// background fetch). A function that holds the lock must not call another that takes it: the
// functions with a locked suffix are for that.
func lockFor(key string) chan struct{} {
	lockMu.Lock()
	defer lockMu.Unlock()
	ch, ok := syncLocks[key]
	if !ok {
		ch = make(chan struct{}, 1)
		syncLocks[key] = ch
	}
	return ch
}

func busyError(since time.Time) *git.Error {
	seconds := int(max(0, time.Since(since).Seconds()))
	return git.New(i18n.T("Another sync of this data folder has been running for {seconds} seconds.",
		"seconds", seconds), "sync_busy", git.HintFor("sync_busy"))
}

// locked holds the lock of the data folder while fn runs. Whoever would have to wait longer than
// wait (negative: LockWarn) gets an *Error of kind "sync_busy" instead of waiting forever. The
// running sync is never ended by this; that only happens with AbortRunningSync. fn gets a context
// whose Git calls AbortRunningSync can end.
func locked(ctx context.Context, path string, wait time.Duration, fn func(ctx context.Context) error) error {
	key := git.Resolve(path)
	lock := lockFor(key)
	if wait < 0 {
		wait = LockWarn
	}
	acquired := false
	select { // never wait if the lock is free
	case lock <- struct{}{}:
		acquired = true
	default:
	}
	if !acquired {
		timer := time.NewTimer(wait)
		defer timer.Stop()
		select {
		case lock <- struct{}{}:
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
			lockMu.Lock()
			since, ok := held[key]
			lockMu.Unlock()
			if !ok {
				since = time.Now()
			}
			return busyError(since)
		}
	}
	lockMu.Lock()
	held[key] = time.Now()
	lockMu.Unlock()
	defer func() {
		lockMu.Lock()
		delete(held, key)
		lockMu.Unlock()
		<-lock
	}()
	if root, err := Root(ctx, path); err == nil {
		var end func()
		ctx, end = git.BeginSync(ctx, root) // an abort applies only to this sync
		defer end()
	}
	return fn(ctx)
}

// SyncRunningSeconds says for how many seconds a sync has held the lock of this data folder (ok
// is false: none).
func SyncRunningSeconds(path string) (seconds float64, ok bool) {
	lockMu.Lock()
	defer lockMu.Unlock()
	since, ok := held[git.Resolve(path)]
	if !ok {
		return 0, false
	}
	return max(0, time.Since(since).Seconds()), true
}

// AbortRunningSync terminates the running Git calls of the sync of this data folder (explicit
// request). The sync then ends with an error; changes saved before stay, lock files such as
// index.lock are not touched. It returns true if something was running.
func AbortRunningSync(ctx context.Context, path string) bool {
	root, err := Root(ctx, path)
	if err != nil {
		return false
	}
	return git.AbortRunning(root)
}

// quietEnvFor is the environment for the background fetch; SSH runs without prompts (BatchMode)
// unless someone set their own SSH command (environment or core.sshCommand).
func quietEnvFor(ctx context.Context, root string) map[string]string {
	env := map[string]string{}
	for k, v := range quietEnv {
		env[k] = v
	}
	own, _ := git.Lenient(ctx, root, "config", "--get", "core.sshCommand")
	if os.Getenv("GIT_SSH_COMMAND") == "" && os.Getenv("GIT_SSH") == "" && own == "" {
		env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
	}
	return env
}

// fetchInBackground does a git fetch --prune with a timeout; only a success is stored (a failure
// without prompting says nothing about the server and must not overwrite the last good state). If
// the server has changed in the meantime, the result is discarded.
func fetchInBackground(ctx context.Context, root string, current SyncState) {
	remote := current.Remote
	if remote == "" {
		remote = "origin"
	}
	run, err := git.RunProbe(ctx, root, []string{"fetch", "--prune", "--no-tags", remote},
		BackgroundTimeout, quietEnvFor(ctx, root))
	if err != nil || run.Code != 0 {
		return
	}
	if git.RemoteURL(ctx, root, remote) != current.URL {
		return
	}
	mu.Lock()
	fetched[root] = fetchRecord{at: time.Now()}
	mu.Unlock()
	git.InvalidateStatus()
}

// Fetch fetches the state from the server (download only, change nothing) and remembers whether
// the server was reachable. Errors of the server are not returned but recorded in the state.
func Fetch(ctx context.Context, path string) (SyncState, error) {
	var out SyncState
	err := locked(ctx, path, -1, func(ctx context.Context) (err error) {
		out, err = fetchLocked(ctx, path)
		return err
	})
	if git.IsKind(err, "sync_busy", "aborted") {
		// no Git call alongside the running sync
		mu.Lock()
		cached, ok := stateCache[git.Resolve(path)]
		mu.Unlock()
		if ok {
			return cached.state, nil
		}
		return State(ctx, path)
	}
	return out, err
}

func fetchLocked(ctx context.Context, path string) (SyncState, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return SyncState{}, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return SyncState{}, err
	}
	var fetchErr *git.Error
	if current.Remote == "" {
		fetchErr = git.New(i18n.T("No server set up."), "no_remote", git.HintFor("no_remote"))
	} else if _, err := git.With(ctx, root, git.Opts{Network: true, URL: current.URL},
		"fetch", "--prune", current.Remote); err != nil {
		e := git.As(err)
		if e == nil || e.Kind == "aborted" { // no finding about the server: record nothing
			return SyncState{}, err
		}
		fetchErr = e
	}
	mu.Lock()
	fetched[root] = fetchRecord{time.Now(), fetchErr}
	mu.Unlock()
	git.InvalidateStatus()
	return State(ctx, path)
}

// BackgroundFetchDue says whether the last fetch (background attempt or manual fetch) is more
// than 30 minutes ago, or there has been none in this program run, and the data folder has a
// server. The time check comes first and needs no Git call: the sidebar asks on every redraw.
func BackgroundFetchDue(ctx context.Context, path string, now time.Time) (bool, error) {
	if now.IsZero() {
		now = time.Now()
	}
	key := git.Resolve(path)
	// Some leeway: the UI calls exactly every 30 minutes, but the last fetch ended a few seconds
	// after it started.
	dueAfter := BackgroundFetchEvery - time.Minute
	lockMu.Lock()
	last, seen := backgroundLast[key]
	lockMu.Unlock()
	if seen && now.Sub(last) < dueAfter {
		return false, nil
	}
	current, err := CachedState(ctx, path)
	if err != nil {
		return false, err
	}
	if current.Remote == "" {
		lockMu.Lock()
		backgroundLast[key] = now // without a server, do not ask again on every redraw
		lockMu.Unlock()
		return false, nil
	}
	root, err := Root(ctx, path)
	if err != nil {
		return false, err
	}
	mu.Lock()
	record, ok := fetched[root]
	mu.Unlock()
	return !ok || now.Sub(record.at) >= dueAfter, nil
}

// StartBackgroundFetch starts a background fetch of the server state (git fetch --prune) if
// needed and returns whether one was started. Never more than one runs per data folder, never at
// the same time as a sync, and there is no endless loop: it is only called from a connected
// session (at startup and every 30 minutes).
func StartBackgroundFetch(ctx context.Context, path string) bool {
	if os.Getenv(BackgroundOffEnv) != "" {
		return false
	}
	key := git.Resolve(path)
	due, err := BackgroundFetchDue(ctx, path, time.Time{})
	if err != nil || !due {
		return false
	}
	if _, running := SyncRunningSeconds(path); running {
		return false // a sync is running: no Git call alongside it
	}
	root, err := Root(ctx, path)
	if err != nil {
		return false
	}
	current, err := State(ctx, path)
	if err != nil {
		return false
	}
	lockMu.Lock()
	if backgroundActive[key] {
		lockMu.Unlock()
		return false
	}
	backgroundActive[key] = true
	backgroundLast[key] = time.Now()
	lockMu.Unlock()

	// The fetch must outlive the call that started it.
	bg := context.WithoutCancel(ctx)
	go func() {
		defer func() {
			_ = recover() // a background fetch must never end anything
			lockMu.Lock()
			delete(backgroundActive, key)
			lockMu.Unlock()
		}()
		// a sync is running: try again next time
		_ = locked(bg, path, 0, func(ctx context.Context) error {
			fetchInBackground(ctx, root, current)
			return nil
		})
	}()
	return true
}
