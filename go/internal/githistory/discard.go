// Package githistory has the everyday operations without a terminal: discard changes, history,
// restore an earlier state and manage tags (port of githistory.py).
//
// Everything runs through the git program (package git). Discarding first backs up the affected
// files to a trash folder under .git; restoring is itself a commit and can be undone with
// RevertCommit. Paths are always read from NUL-separated output (-z): only that keeps names with
// umlauts or quotation marks intact.
package githistory

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

const (
	sep = "\x1f"
	rec = "\x1e"

	// chunkChars is the most characters of paths per Git call (Windows allows about 32,000 per
	// line).
	chunkChars = 16000

	// trashFolder keeps the name from before the rename to Foresprint.
	trashFolder = "sprintforecast-verworfen"
)

// Lost is what is lost when discarding.
type Lost struct {
	Status  string // M modified, D deleted, A/?? new, R renamed
	File    string // relative to the repository root
	Added   int
	Removed int
	Orig    string // previous path for renames
}

func noUnfinished(ctx context.Context, path string) error {
	current, err := gitsync.State(ctx, path)
	if err != nil {
		return err
	}
	if current.Unfinished != "" || len(current.Conflicts) > 0 {
		return git.New(i18n.T("A merge has not been completed yet."), "merge_in_progress",
			git.HintFor("merge_in_progress"))
	}
	return nil
}

// chunks splits a long path list so that every line stays short enough for Git.
func chunks(paths []string) [][]string {
	var out [][]string
	var chunk []string
	size := 0
	for _, p := range paths {
		if len(chunk) > 0 && size+len(p)+1 > chunkChars {
			out = append(out, chunk)
			chunk, size = nil, 0
		}
		chunk = append(chunk, p)
		size += len(p) + 1
	}
	if len(chunk) > 0 {
		out = append(out, chunk)
	}
	return out
}

// inside says whether file (path relative to the root) is inside rel; "." is the root itself.
func inside(file, rel string) bool {
	if rel == "" || rel == "." {
		return true
	}
	return file == rel || strings.HasPrefix(file, strings.TrimRight(rel, "/")+"/")
}

func selected(ctx context.Context, path string, files []string) ([]git.Change, error) {
	changes, err := git.ChangesIn(ctx, path)
	if err != nil {
		return nil, err
	}
	if files == nil {
		return changes, nil
	}
	var out []git.Change
	for _, c := range changes {
		if contains(files, c.File) {
			out = append(out, c)
		}
	}
	return out, nil
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// numstat is the added/removed lines per file (key: new path).
func numstat(ctx context.Context, root, path string) (map[string][2]int, error) {
	out, err := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
		"diff", "HEAD", "-M", "--numstat", "-z", "--", git.Resolve(path))
	if err != nil {
		return nil, err
	}
	stats := map[string][2]int{}
	entries := strings.Split(out, "\x00")
	for i := 0; i < len(entries); {
		parts := strings.SplitN(entries[i], "\t", 3)
		i++
		if len(parts) != 3 {
			continue
		}
		added, removed, name := parts[0], parts[1], parts[2]
		if name == "" { // rename: previous and new path follow
			if i+1 >= len(entries) {
				break
			}
			name = entries[i+1]
			i += 2
		}
		a, errA := strconv.Atoi(added)
		r, errR := strconv.Atoi(removed)
		if errA == nil && errR == nil && isDigits(added) && isDigits(removed) {
			stats[name] = [2]int{a, r}
		}
	}
	return stats, nil
}

func isDigits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return s != ""
}

// DiscardPreview shows what a discard costs (files relative to the root; nil = everything in the
// data folder): status and number of added/removed lines.
func DiscardPreview(ctx context.Context, path string, files []string) ([]Lost, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return nil, err
	}
	changes, err := selected(ctx, path, files)
	if err != nil {
		return nil, err
	}
	stats, err := numstat(ctx, root, path)
	if err != nil {
		return nil, err
	}
	var lost []Lost
	for _, c := range changes {
		st := stats[c.File]
		added, removed := st[0], st[1]
		if (c.Status == "??" || c.Status == "A") && added == 0 {
			if data, err := os.ReadFile(filepath.Join(root, c.File)); err == nil {
				added = countLines(string(data))
			}
		}
		lost = append(lost, Lost{c.Status, c.File, added, removed, c.Orig})
	}
	return lost, nil
}

// countLines is len(text.splitlines()) after decoding with replacement characters.
func countLines(text string) int {
	return len(pytext.SplitLines(text, false))
}

// newTrash makes a new, not yet existing trash folder (also for several operations in the same
// second).
func newTrash(ctx context.Context, root string) (string, error) {
	gdir, err := gitsync.GitDir(ctx, root)
	if err != nil {
		return "", err
	}
	base := filepath.Join(gdir, trashFolder)
	stamp := time.Now().Format("20060102-150405")
	if err := os.MkdirAll(base, 0o755); err != nil {
		return "", err
	}
	for n := 0; ; n++ {
		name := stamp
		if n > 0 {
			name = stamp + "-" + strconv.Itoa(n)
		}
		trash := filepath.Join(base, name)
		err := os.Mkdir(trash, 0o755)
		if errors.Is(err, os.ErrExist) {
			continue
		}
		if err != nil {
			return "", err
		}
		return trash, nil
	}
}

// pathsOf are all paths touched by the changes (new and previous name), without duplicates.
func pathsOf(changes []git.Change) []string {
	var out []string
	seen := map[string]bool{}
	for _, c := range changes {
		for _, p := range []string{c.File, c.Orig} {
			if p != "" && !seen[p] {
				seen[p] = true
				out = append(out, p)
			}
		}
	}
	return out
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	info, err := in.Stat()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, info.Mode().Perm())
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	return os.Chtimes(dst, info.ModTime(), info.ModTime())
}

func backup(root, trash string, changes []git.Change) error {
	for _, name := range pathsOf(changes) {
		source := filepath.Join(root, filepath.FromSlash(name))
		if isFile(source) {
			if err := copyFile(source, filepath.Join(trash, filepath.FromSlash(name))); err != nil {
				return err
			}
		}
	}
	return nil
}

// snapshot is the state before discarding, so that everything can be put back after a partial
// failure: which files existed (content is in the trash), which did not (e.g. deleted or before a
// rename) and the staging (index).
type snapshot struct {
	present []string
	absent  []string
	index   []byte
	hasIdx  bool
}

func takeSnapshot(ctx context.Context, root string, changes []git.Change) (snapshot, error) {
	var snap snapshot
	gdir, err := gitsync.GitDir(ctx, root)
	if err != nil {
		return snap, err
	}
	if data, err := os.ReadFile(filepath.Join(gdir, "index")); err == nil {
		snap.index, snap.hasIdx = data, true
	}
	for _, p := range pathsOf(changes) {
		full := filepath.Join(root, filepath.FromSlash(p))
		switch {
		case isFile(full):
			snap.present = append(snap.present, p)
		case !pathExists(full):
			snap.absent = append(snap.absent, p)
		}
	}
	return snap, nil
}

func pathExists(p string) bool {
	_, err := os.Lstat(p)
	return err == nil
}

func writeIndex(ctx context.Context, root string, data []byte) error {
	gdir, err := gitsync.GitDir(ctx, root)
	if err != nil {
		return err
	}
	index := filepath.Join(gdir, "index")
	tmp := filepath.Join(gdir, "index.sprintforecast-rollback")
	defer func() { _ = os.Remove(tmp) }()
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, index)
}

// putBack restores the state before discarding (after a partial failure): copy backed-up files
// back, remove re-created (previously deleted) files, write the staging back. It returns what
// could not be restored (empty = everything).
func putBack(ctx context.Context, root, trash string, snap snapshot) []string {
	var failed []string
	for _, name := range snap.present {
		saved := filepath.Join(trash, filepath.FromSlash(name))
		if !isFile(saved) {
			failed = append(failed, name)
			continue
		}
		if err := copyFile(saved, filepath.Join(root, filepath.FromSlash(name))); err != nil {
			failed = append(failed, name)
		}
	}
	for _, name := range snap.absent {
		err := os.Remove(filepath.Join(root, filepath.FromSlash(name)))
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			failed = append(failed, name)
		}
	}
	if snap.hasIdx {
		if err := writeIndex(ctx, root, snap.index); err != nil {
			failed = append(failed, i18n.T("the staging area (index)"))
		}
	}
	return failed
}

func rollbackHint(failed []string, trash string, quote func(string) string) string {
	if quote == nil {
		quote = func(s string) string { return s }
	}
	if len(failed) == 0 {
		return i18n.T("The original state (files and staging) was restored. Backup of the changes: {trash}",
			"trash", quote(trash))
	}
	return i18n.T("The original state could not be fully restored. Not restored: {files}. The backup "+
		"of the changes is in {trash}; please copy the files back from there.",
		"files", quote(strings.Join(failed, ", ")), "trash", quote(trash))
}

// Discard discards open changes (single files or everything in the data folder). The files are
// first copied to a trash folder under .git; its folder is returned ("" = nothing needed
// backing up). If something fails, the state before is restored from the backup (files, deleted
// files, staging); the error message names what could not be restored and where the backup is.
func Discard(ctx context.Context, path string, files []string) (string, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return "", err
	}
	if err := noUnfinished(ctx, path); err != nil {
		return "", err
	}
	changes, err := selected(ctx, path, files)
	if err != nil {
		return "", err
	}
	if len(changes) == 0 {
		return "", git.New(i18n.T("No changes to discard"), "", "")
	}
	trash, err := newTrash(ctx, root)
	if err != nil {
		return "", git.New(i18n.T("The changes cannot be backed up: {error}", "error", err.Error()),
			"error", i18n.T("Nothing was discarded."))
	}
	var snap snapshot
	err = backup(root, trash, changes)
	if err == nil {
		snap, err = takeSnapshot(ctx, root, changes)
	}
	if err != nil {
		_ = os.RemoveAll(trash)
		return "", git.New(i18n.T("The changes cannot be backed up: {error}", "error", err.Error()),
			"error", i18n.T("Nothing was discarded."))
	}
	if err := applyDiscard(ctx, root, changes); err != nil {
		failed := putBack(context.WithoutCancel(ctx), root, trash, snap)
		git.InvalidateStatus()
		kind := git.KindOf(err)
		if kind == "" {
			kind = "error"
		}
		return "", git.New(i18n.T("Discarding did not fully succeed: {error}", "error", err.Error()),
			kind, rollbackHint(failed, trash, nil)).
			WithHintMD(rollbackHint(failed, trash, git.MDPlain))
	}
	git.InvalidateStatus()
	entries, _ := os.ReadDir(trash)
	if len(entries) == 0 {
		_ = os.Remove(trash)
		return "", nil
	}
	return trash, nil
}

// applyDiscard resets the paths to the state of HEAD: known files are restored (also the
// previous name of a rename), files that do not exist in HEAD (new, target of a rename) are
// removed from the staging and deleted.
func applyDiscard(ctx context.Context, root string, changes []git.Change) error {
	paths := pathsOf(changes)
	inHead := map[string]bool{}
	for _, chunk := range chunks(paths) {
		out, err := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
			append([]string{"ls-tree", "-r", "-z", "--name-only", "HEAD", "--"}, chunk...)...)
		if err != nil {
			return err
		}
		for _, n := range git.SplitZ(out) {
			inHead[n] = true
		}
	}
	var restore, remove []string
	for _, p := range paths {
		if inHead[p] {
			restore = append(restore, p)
		} else {
			remove = append(remove, p)
		}
	}
	for _, chunk := range chunks(remove) {
		if _, err := git.Git(ctx, root,
			append([]string{"rm", "-q", "-f", "--cached", "--ignore-unmatch", "--"}, chunk...)...); err != nil {
			return err
		}
	}
	for _, chunk := range chunks(restore) {
		if _, err := git.Git(ctx, root,
			append([]string{"restore", "--source=HEAD", "--staged", "--worktree", "--"}, chunk...)...); err != nil {
			return err
		}
	}
	for _, p := range remove {
		err := os.Remove(filepath.Join(root, filepath.FromSlash(p)))
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

// pySplitLines is str.splitlines().
func pySplitLines(s string) []string { return pytext.SplitLines(s, false) }
