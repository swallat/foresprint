package git

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/swallat/foresprint/internal/gittest"
)

var bg = context.Background()

// repo is a repository with the data folder teams/a and a file outside of it.
func repo(t *testing.T) string {
	t.Helper()
	gittest.Isolate(t)
	ResetGitCache()
	InvalidateStatus()
	root := t.TempDir()
	gittest.Git(t, root, "init", "-q", "-b", "main")
	gittest.Write(t, filepath.Join(root, "teams", "a", "team.yaml"), "name: A\n")
	gittest.Write(t, filepath.Join(root, "other.txt"), "x")
	gittest.Git(t, root, "add", "-A")
	gittest.Git(t, root, "commit", "-qm", "init")
	resolved, _ := filepath.EvalSymlinks(root)
	return resolved
}

func files(changes []Change) []string {
	var out []string
	for _, c := range changes {
		out = append(out, c.File)
	}
	sort.Strings(out)
	return out
}

func TestRepoRoot(t *testing.T) {
	root := repo(t)
	got, err := RepoRoot(bg, filepath.Join(root, "teams", "does-not-exist-yet"))
	if err != nil || got != root {
		t.Fatalf("RepoRoot = %q, %v; want %q", got, err, root)
	}
	outside := t.TempDir()
	if got, _ := RepoRoot(bg, outside); got != "" {
		t.Fatalf("RepoRoot(outside) = %q, want none", got)
	}
	_, err = RequireRoot(bg, outside)
	if e := As(err); e == nil || e.Kind != "error" || !strings.Contains(e.Error(), "is not inside a Git repository") {
		t.Fatalf("RequireRoot(outside) = %v", err)
	}
}

func TestCommitOnlyDataDirectory(t *testing.T) {
	root := repo(t)
	teams := filepath.Join(root, "teams")
	gittest.Write(t, filepath.Join(teams, "a", "team.yaml"), "name: A2\n")
	gittest.Write(t, filepath.Join(teams, "a", "new.yaml"), "x: 1\n")
	gittest.Write(t, filepath.Join(root, "other.txt"), "changed")
	changes, err := PendingChanges(bg, teams)
	if err != nil {
		t.Fatal(err)
	}
	if got := files(changes); strings.Join(got, ",") != "teams/a/new.yaml,teams/a/team.yaml" {
		t.Fatalf("pending = %v", got)
	}
	if _, err := CommitDirectory(bg, teams, "Data", []string{"a/2026.1"}); err != nil {
		t.Fatal(err)
	}
	if changes, _ := PendingChanges(bg, teams); len(changes) != 0 {
		t.Fatalf("still pending: %v", changes)
	}
	if got := gittest.Git(t, root, "status", "--porcelain"); got != "M other.txt" {
		t.Fatalf("outside stays open, got %q", got)
	}
	if got := gittest.Git(t, root, "tag"); got != "a/2026.1" {
		t.Fatalf("tag = %q", got)
	}
}

func TestDeletionsAreCommitted(t *testing.T) {
	root := repo(t)
	if err := os.Remove(filepath.Join(root, "teams", "a", "team.yaml")); err != nil {
		t.Fatal(err)
	}
	if _, err := CommitDirectory(bg, filepath.Join(root, "teams"), "gone", nil); err != nil {
		t.Fatal(err)
	}
	if got := gittest.Git(t, root, "ls-files", "teams"); got != "" {
		t.Fatalf("ls-files = %q", got)
	}
}

func TestSpreadsheetIsRefused(t *testing.T) {
	root := repo(t)
	gittest.Write(t, filepath.Join(root, "teams", "sheet.xlsx"), "x")
	_, err := CommitDirectory(bg, filepath.Join(root, "teams"), "no", nil)
	if e := As(err); e == nil || !strings.Contains(e.Error(), "Spreadsheets are not committed") {
		t.Fatalf("err = %v", err)
	}
	if n := strings.Count(gittest.Git(t, root, "log", "--oneline"), "\n"); n != 0 {
		t.Fatalf("a commit was made")
	}
}

func TestNothingToCommit(t *testing.T) {
	root := repo(t)
	_, err := CommitDirectory(bg, filepath.Join(root, "teams"), "empty", nil)
	if e := As(err); e == nil || e.Error() != "No changes to commit" {
		t.Fatalf("err = %v", err)
	}
}

func TestConflictMarkersAreNotCommitted(t *testing.T) {
	root := repo(t)
	marked := "a: 1\n<<<<<<< HEAD\nb: 2\n=======\nb: 3\n>>>>>>> origin/main\n"
	gittest.Write(t, filepath.Join(root, "teams", "a", "team.yaml"), marked)
	_, err := CommitDirectory(bg, filepath.Join(root, "teams"), "x", nil)
	e := As(err)
	if e == nil || e.Kind != "conflict" || !strings.Contains(e.Error(), "teams/a/team.yaml") {
		t.Fatalf("err = %v", err)
	}
	if !strings.Contains(e.Hint(), "teams/a/team.yaml") {
		t.Fatalf("hint = %q", e.Hint())
	}
}

func TestTags(t *testing.T) {
	root := repo(t)
	teams := filepath.Join(root, "teams")
	gittest.Write(t, filepath.Join(teams, "a", "new.yaml"), "x: 1\n")
	if _, err := CommitDirectory(bg, teams, "one", []string{"v1", "v1"}); err != nil {
		t.Fatal(err)
	}
	// the name is taken: nothing is committed
	gittest.Write(t, filepath.Join(teams, "a", "new.yaml"), "x: 2\n")
	_, err := CommitDirectory(bg, teams, "two", []string{"v1"})
	if e := As(err); e == nil || e.Kind != "tag_exists" {
		t.Fatalf("err = %v", err)
	}
	if got := gittest.Git(t, root, "log", "--oneline"); strings.Count(got, "\n") != 1 {
		t.Fatalf("log = %q", got)
	}
	// EnsureTags sets missing tags on HEAD and reports tags that sit elsewhere
	created, elsewhere, err := EnsureTags(bg, root, []string{"v1", "v2"}, "msg")
	if err != nil || len(created) != 1 || created[0] != "v2" || len(elsewhere) != 0 {
		t.Fatalf("EnsureTags = %v %v %v", created, elsewhere, err)
	}
	if _, err := CommitDirectory(bg, teams, "three", nil); err != nil {
		t.Fatal(err)
	}
	created, elsewhere, err = EnsureTags(bg, root, []string{"v2"}, "msg")
	if err != nil || len(created) != 0 || len(elsewhere) != 1 {
		t.Fatalf("EnsureTags = %v %v %v", created, elsewhere, err)
	}
	if err := ValidTagName(bg, root, "bad name"); err == nil {
		t.Fatal("a name with a space is no valid tag name")
	}
}

func TestChangesWithRename(t *testing.T) {
	root := repo(t)
	gittest.Git(t, root, "mv", "teams/a/team.yaml", "teams/a/renamed.yaml")
	changes, err := ChangesIn(bg, filepath.Join(root, "teams"))
	if err != nil || len(changes) != 1 {
		t.Fatalf("changes = %v, %v", changes, err)
	}
	if c := changes[0]; c.Status != "R" || c.File != "teams/a/renamed.yaml" || c.Orig != "teams/a/team.yaml" {
		t.Fatalf("change = %+v", c)
	}
}

func TestCommitFiles(t *testing.T) {
	root := repo(t)
	file := gittest.Write(t, filepath.Join(root, "teams", "a", "team.yaml"), "name: B\n")
	if _, err := Commit(bg, []string{file}, "files", "t1"); err != nil {
		t.Fatal(err)
	}
	if got := gittest.Git(t, root, "tag"); got != "t1" {
		t.Fatalf("tag = %q", got)
	}
	// a deleted file that Git never knew is left out instead of aborting the add
	ghost := filepath.Join(root, "teams", "a", "never.yaml")
	file = gittest.Write(t, file, "name: C\n")
	if _, err := Commit(bg, []string{file, ghost}, "files", ""); err != nil {
		t.Fatal(err)
	}
}

func TestCommitOutsideARepositoryIsClassified(t *testing.T) {
	gittest.Isolate(t)
	folder := t.TempDir()
	file := gittest.Write(t, filepath.Join(folder, "team.yaml"), "name: A\n")
	_, err := Commit(bg, []string{file}, "no repo", "")
	e := As(err)
	if e == nil || e.Kind != "not_repo" || !strings.Contains(e.Error(), folder) {
		t.Fatalf("err = %v", err)
	}
}

func TestInitDataRepository(t *testing.T) {
	gittest.Isolate(t)
	path := filepath.Join(t.TempDir(), "data")
	data, err := InitDataRepository(bg, path, true)
	if err != nil {
		t.Fatal(err)
	}
	if data != filepath.Join(path, "teams") {
		t.Fatalf("data = %q", data)
	}
	for _, name := range []string{".gitignore", filepath.Join("teams", ".gitattributes"), ".git"} {
		if _, err := os.Stat(filepath.Join(path, name)); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	// again: nothing is overwritten
	gittest.Write(t, filepath.Join(path, ".gitignore"), "mine\n")
	if _, err := InitDataRepository(bg, path, true); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(filepath.Join(path, ".gitignore")); string(got) != "mine\n" {
		t.Fatalf(".gitignore = %q", got)
	}
	// a file as the target
	file := gittest.Write(t, filepath.Join(t.TempDir(), "file"), "x")
	_, err = InitDataRepository(bg, file, true)
	if e := As(err); e == nil || e.Kind != "folder" {
		t.Fatalf("err = %v", err)
	}
}

func TestAttributesOfferAndApply(t *testing.T) {
	root := repo(t)
	teams := filepath.Join(root, "teams")
	// CRLF in the index makes files affected
	gittest.Write(t, filepath.Join(teams, "a", "team.yaml"), "name: A\r\n")
	gittest.Git(t, root, "-c", "core.autocrlf=false", "add", "-A")
	gittest.Git(t, root, "commit", "-qm", "crlf")
	offer, err := AttributesOffered(bg, teams)
	if err != nil || offer == nil {
		t.Fatalf("offer = %v, %v", offer, err)
	}
	if len(offer.Rules) != 3 || strings.Join(offer.Affected, ",") != "a/team.yaml" {
		t.Fatalf("offer = %+v", offer)
	}
	if _, err := ApplyAttributes(bg, teams); err != nil {
		t.Fatal(err)
	}
	text, _ := os.ReadFile(filepath.Join(teams, ".gitattributes"))
	if string(text) != "*.yaml text eol=lf\n*.yml text eol=lf\n*.md text eol=lf\n" {
		t.Fatalf(".gitattributes = %q", text)
	}
	if again, _ := AttributesOffered(bg, teams); again != nil {
		t.Fatalf("still offered: %+v", again)
	}
}

func TestCloneRepository(t *testing.T) {
	gittest.Isolate(t)
	dir := t.TempDir()
	server := gittest.MakeServer(t, dir, "server.git", "main")
	target := filepath.Join(dir, "clone")
	if err := CloneRepository(bg, server, target, 0); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(target, "teams", "team.yaml")); err != nil {
		t.Fatal(err)
	}
	// the target is not empty now
	err := CloneRepository(bg, server, target, 0)
	if e := As(err); e == nil || e.Kind != "folder" {
		t.Fatalf("err = %v", err)
	}
	// credentials in the address are refused
	err = CloneRepository(bg, "https://u:p@host/x.git", filepath.Join(dir, "other"), 0)
	if e := As(err); e == nil || e.Kind != "secret_in_url" {
		t.Fatalf("err = %v", err)
	}
	// a server that does not exist
	err = CloneRepository(bg, filepath.Join(dir, "missing.git"), filepath.Join(dir, "third"), 0)
	if e := As(err); e == nil || (e.Kind != "not_found" && e.Kind != "offline") {
		t.Fatalf("err = %v", err)
	}
}

func TestProbeRemote(t *testing.T) {
	gittest.Isolate(t)
	dir := t.TempDir()
	root := gittest.MakeLocal(t, dir, "work", true)
	full := gittest.MakeServer(t, dir, "full.git", "main")
	empty := gittest.MakeServer(t, dir, "empty.git", "")
	heads, err := ProbeRemote(bg, root, RemoteAddress{URL: full, Kind: "local"}, 0, "")
	if err != nil || len(heads) != 1 || heads[0] != "main" {
		t.Fatalf("heads = %v, %v", heads, err)
	}
	heads, err = ProbeRemote(bg, root, RemoteAddress{URL: empty, Kind: "local"}, 0, "")
	if err != nil || len(heads) != 0 {
		t.Fatalf("heads = %v, %v", heads, err)
	}
	_, err = ProbeRemote(bg, root, RemoteAddress{URL: filepath.Join(dir, "missing.git"), Kind: "local"}, 0, "")
	if e := As(err); e == nil || (e.Kind != "not_found" && e.Kind != "offline") || e.Hint() == "" {
		t.Fatalf("err = %v", err)
	}
}

func TestManyBranchesAreAskedForSpecifically(t *testing.T) {
	gittest.Isolate(t)
	dir := t.TempDir()
	root := gittest.MakeLocal(t, dir, "work", true)
	server := gittest.MakeServer(t, dir, "full.git", "main")
	commit := gittest.Git(t, server, "rev-parse", "HEAD")
	gittest.Git(t, server, "pack-refs", "--all")
	var lines strings.Builder
	lines.WriteString("# pack-refs with: peeled fully-peeled \n")
	text, _ := os.ReadFile(filepath.Join(server, "packed-refs"))
	for _, line := range strings.Split(string(text), "\n") {
		if line != "" && line[0] != '#' {
			lines.WriteString(line + "\n")
		}
	}
	for i := 0; i < 1500; i++ {
		lines.WriteString(commit + " refs/heads/branch-with-a-rather-long-name-number-" + strings.Repeat("0", 3) + itoa(i) + "\n")
	}
	if err := os.WriteFile(filepath.Join(server, "packed-refs"), []byte(lines.String()), 0o644); err != nil {
		t.Fatal(err)
	}
	address := RemoteAddress{URL: server, Kind: "local"}
	heads, err := ProbeRemote(bg, root, address, 0, "main")
	if err != nil || !containsString(heads, "main") {
		t.Fatalf("main is missing: %d heads, %v", len(heads), err)
	}
	heads, err = ProbeRemote(bg, root, address, 0, "nope")
	if err != nil || containsString(heads, "nope") {
		t.Fatalf("nope should be missing: %v", err)
	}
}

func itoa(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	var out []byte
	for ; i > 0; i /= 10 {
		out = append([]byte{digits[i%10]}, out...)
	}
	return string(out)
}

func TestTimeoutAndAbort(t *testing.T) {
	gittest.Isolate(t)
	root := repo(t)
	// a Git call that takes too long: a pager-free sleep via a config alias
	_, err := With(bg, root, Opts{Timeout: 300 * time.Millisecond, Lenient: true},
		"-c", "alias.slow=!sleep 5", "slow")
	if e := As(err); e == nil || e.Kind != "offline" {
		t.Fatalf("timeout err = %v", err)
	}

	ctx, end := BeginSync(bg, root)
	defer end()
	done := make(chan error, 1)
	go func() {
		_, err := With(ctx, root, Opts{}, "-c", "alias.slow=!sleep 5", "slow")
		done <- err
	}()
	deadline := time.Now().Add(5 * time.Second)
	for !AbortRunning(root) {
		if time.Now().After(deadline) {
			t.Fatal("no call was running")
		}
		time.Sleep(20 * time.Millisecond)
	}
	select {
	case err := <-done:
		if e := As(err); e == nil || e.Kind != "aborted" {
			t.Fatalf("abort err = %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the aborted call did not end")
	}
	// the sync starts no new call
	if _, err := Git(ctx, root, "status"); KindOf(err) != "aborted" {
		t.Fatalf("after abort: %v", err)
	}
	// other contexts keep reading
	if _, err := Git(bg, root, "status"); err != nil {
		t.Fatal(err)
	}
}

func TestGitIsMissing(t *testing.T) {
	gittest.Isolate(t)
	root := repo(t)
	t.Setenv("PATH", "")
	ResetGitCache()
	if FindGit() != "" && !strings.HasPrefix(FindGit(), "/") {
		t.Skip("git found in an unusual place")
	}
	if Available() {
		t.Skip("git is installed in one of the fallback places")
	}
	_, err := Git(bg, root, "status")
	if e := As(err); e == nil || e.Kind != "git_missing" || !strings.Contains(e.Hint(), "Searched in PATH") {
		t.Fatalf("err = %v", err)
	}
}

func TestStrerror(t *testing.T) {
	err := FolderProblem("/x", &os.PathError{Op: "mkdir", Path: "/x", Err: os.ErrNotExist})
	if err.Kind != "folder" {
		t.Fatal(err)
	}
	_, statErr := os.Stat("/definitely/not/here")
	if got := FolderProblem("/x", statErr).Error(); !strings.Contains(got, "(No such file or directory)") {
		t.Fatalf("message = %q", got)
	}
}

// assumeForeignOwner makes Git consider root the folder of another user account ("detected
// dubious ownership") without changing owners. The caller creates the repository beforehand.
func assumeForeignOwner(t *testing.T, root string) {
	t.Helper()
	t.Setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
	proc, err := Run(bg, root, Opts{}, "rev-parse")
	if err != nil || !strings.Contains(proc.Stderr, "dubious ownership") {
		t.Skip("this Git version does not check the owner of the folder")
	}
	InvalidateStatus()
}

func TestUnsafeDirectoryIsNamed(t *testing.T) {
	root := repo(t)
	assumeForeignOwner(t, root)
	folder := filepath.Join(root, "teams")
	if got, _ := RepoRoot(bg, folder); got != "" {
		t.Fatalf("RepoRoot = %q, want none", got)
	}
	problem, err := RootProblem(bg, folder)
	if err != nil || problem == nil || problem.Kind != "unsafe_directory" || !problem.Raw {
		t.Fatalf("problem = %v, %v", problem, err)
	}
	if strings.Contains(problem.Error(), "safe.directory") || !strings.HasPrefix(problem.Error(), "fatal: detected dubious ownership in repository at") {
		t.Fatalf("message = %q", problem.Error())
	}
	if strings.Contains(problem.Hint(), "safe.directory") {
		t.Fatal("the hint must not recommend a Git setting")
	}
	for name, call := range map[string]func() error{
		"RequireRoot":     func() error { _, err := RequireRoot(bg, folder); return err },
		"ChangesIn":       func() error { _, err := ChangesIn(bg, folder); return err },
		"CommitDirectory": func() error { _, err := CommitDirectory(bg, folder, "x", nil); return err },
		"InitData":        func() error { _, err := InitDataRepository(bg, root, true); return err },
	} {
		e := As(call())
		if e == nil || e.Kind != "unsafe_directory" || !e.Raw {
			t.Errorf("%s: err = %v", name, e)
		}
	}
	if _, err := os.Stat(filepath.Join(root, ".gitignore")); err == nil {
		t.Error("InitDataRepository wrote into the unsafe folder")
	}
	// the reason is not permanent
	t.Setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "")
	InvalidateStatus()
	if got, _ := RepoRoot(bg, root); got != root {
		t.Fatalf("RepoRoot = %q after the fix", got)
	}
}
