package gitsync

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gittest"
)

var bg = context.Background()

// needShell skips tests whose server hooks are shell scripts.
func needShell(t *testing.T) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the server hooks are shell scripts")
	}
}

// setup isolates Git, installs the test codec and clears the caches.
func setup(t *testing.T) {
	t.Helper()
	gittest.Isolate(t)
	for _, who := range []string{"AUTHOR", "COMMITTER"} {
		for _, f := range []string{"NAME", "EMAIL"} {
			t.Setenv("GIT_"+who+"_"+f, "")
			_ = os.Unsetenv("GIT_" + who + "_" + f) // the identity comes from each clone
		}
	}
	git.ResetGitCache()
	git.InvalidateStatus()
	mu.Lock()
	fetched = map[string]fetchRecord{}
	mu.Unlock()
	SetCodec(gittest.FlatCodec{})
	SetValidator(noCheck)
	t.Cleanup(func() {
		SetCodec(nil)
		SetValidator(nil)
		git.InvalidateStatus()
	})
}

type person struct {
	t    *testing.T
	name string
	root string
}

func (p person) data() string { return filepath.Join(p.root, "teams") }

func (p person) write(rel, text string) {
	p.t.Helper()
	gittest.Write(p.t, filepath.Join(p.data(), filepath.FromSlash(rel)), text)
	git.InvalidateStatus()
}

func (p person) read(rel string) string {
	p.t.Helper()
	b, err := os.ReadFile(filepath.Join(p.data(), filepath.FromSlash(rel)))
	if err != nil {
		p.t.Fatal(err)
	}
	return string(b)
}

func (p person) git(args ...string) string {
	p.t.Helper()
	return gittest.Git(p.t, p.root, args...)
}

func (p person) sync(message string, tags ...string) *SyncResult {
	p.t.Helper()
	return p.syncWith(SyncOptions{Message: message, Tags: tags})
}

func (p person) syncWith(opts SyncOptions) *SyncResult {
	p.t.Helper()
	res, err := Sync(bg, p.data(), opts)
	if err != nil {
		p.t.Fatalf("sync: %v", err)
	}
	return res
}

func (p person) mustOK(message string, tags ...string) *SyncResult {
	p.t.Helper()
	res := p.sync(message, tags...)
	if !res.OK() {
		p.t.Fatalf("sync failed: %v (%s)", res.Error, res.Error.Hint())
	}
	return res
}

func (p person) state() SyncState {
	p.t.Helper()
	git.InvalidateStatus()
	s, err := State(bg, p.data())
	if err != nil {
		p.t.Fatal(err)
	}
	return s
}

// world is a server with Alice (who has made the first upload) and Bob (a clone).
type world struct {
	remote, tmp string
	alice, bob  person
}

func newWorld(t *testing.T) *world {
	t.Helper()
	setup(t)
	tmp := t.TempDir()
	remote := filepath.Join(tmp, "server.git")
	gittest.Git(t, tmp, "init", "-q", "--bare", "-b", "main", remote)
	aliceRoot := filepath.Join(tmp, "alice")
	gittest.Git(t, tmp, "init", "-q", "-b", "main", aliceRoot)
	gittest.Git(t, aliceRoot, "config", "user.name", "Alice")
	gittest.Git(t, aliceRoot, "config", "user.email", "alice@example.org")
	gittest.Git(t, aliceRoot, "remote", "add", "origin", remote)
	alice := person{t, "Alice", aliceRoot}
	alice.write("a/team.yaml", "name: A\n")
	alice.write("a/2026.1.yaml", "velocity: 10\nscope_creep: 1\n")
	alice.mustOK("Start")
	bobRoot := gittest.MakeClone(t, remote, filepath.Join(tmp, "bob"), "Bob")
	return &world{remote, tmp, alice, person{t, "Bob", bobRoot}}
}

func (w *world) clone(name string) person {
	root := gittest.MakeClone(w.alice.t, w.remote, filepath.Join(w.tmp, strings.ToLower(name)), name)
	return person{w.alice.t, name, root}
}

func (w *world) onServer() string {
	w.alice.t.Helper()
	return gittest.Git(w.alice.t, w.remote, "show", "main:"+file)
}

// noCheck is the validator of tests with flat files: no data check.
func noCheck(context.Context, string, time.Time) ([]Issue, error) { return nil, nil }
