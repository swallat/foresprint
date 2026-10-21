package githistory

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

// Entry is one commit of the history.
type Entry struct {
	Rev     string
	Short   string
	Author  string
	Day     string
	Subject string
	Files   []string
	Merge   bool
}

// History lists the commits that affect scope (file or folder; "" = the data folder): who
// changed what and when, newest first. A zero limit means 40.
func History(ctx context.Context, path, scope string, limit int) ([]Entry, error) {
	if limit == 0 {
		limit = 40
	}
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return nil, err
	}
	if scope == "" {
		scope = path
	}
	format := rec + "%H" + sep + "%h" + sep + "%an" + sep + "%ad" + sep + "%P" + sep + "%s"
	out, err := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
		"log", "-z", "-"+strconv.Itoa(limit), "--format="+format, "--date=format:%Y-%m-%d %H:%M",
		"--name-only", "--no-renames", "--", git.Resolve(scope))
	if err != nil {
		return nil, err
	}
	var entries []Entry
	for _, record := range strings.Split(out, rec) {
		if record == "" {
			continue
		}
		head, names, _ := strings.Cut(record, "\x00")
		f := git.SplitRecord(head, 6, sep)
		entries = append(entries, Entry{
			Rev: f[0], Short: f[1], Author: f[2], Day: f[3], Subject: f[5],
			Files: git.SplitZ(strings.TrimPrefix(names, "\n")),
			Merge: len(strings.Fields(f[4])) > 1,
		})
	}
	return entries, nil
}

func checkRev(rev string) (string, error) {
	rev = pytext.Strip(rev)
	if rev == "" || strings.HasPrefix(rev, "-") {
		return "", git.New(i18n.T("Invalid version: {rev}", "rev", rev), "", "")
	}
	return rev, nil
}

// rollbackRestore undoes a half-executed restore (there were no open changes in this area
// before, so HEAD is the right state). saved: ignored files backed up beforehand (path ->
// backup) that go back to their place. It returns what could not be reset (empty = everything).
func rollbackRestore(ctx context.Context, root, rel string, added []string, saved map[string]string) []string {
	var failed []string
	for _, args := range [][]string{
		{"reset", "-q", "HEAD", "--", rel},
		{"checkout", "HEAD", "--", rel},
	} {
		if _, err := git.Git(ctx, root, args...); err != nil {
			failed = append(failed, rel)
		}
	}
	for _, file := range added {
		if _, ok := saved[file]; ok {
			continue
		}
		err := os.Remove(filepath.Join(root, filepath.FromSlash(file)))
		if err != nil && !os.IsNotExist(err) {
			failed = append(failed, file)
		}
	}
	names := make([]string, 0, len(saved))
	for file := range saved {
		names = append(names, file)
	}
	sort.Strings(names)
	for _, file := range names {
		if err := copyFile(saved[file], filepath.Join(root, filepath.FromSlash(file))); err != nil {
			failed = append(failed, file)
		}
	}
	left, _ := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
		"status", "--porcelain", "-z", "--untracked-files=no", "--", rel)
	if left != "" && !contains(failed, rel) {
		failed = append(failed, rel)
	}
	return dedupe(failed)
}

func dedupe(list []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, x := range list {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}

// saveIgnored backs up ignored, untracked files that a restore would overwrite (path -> backup in
// the trash).
func saveIgnored(root, trash string, files []string) (map[string]string, error) {
	saved := map[string]string{}
	for _, file := range files {
		dst := filepath.Join(trash, filepath.FromSlash(file))
		if err := copyFile(filepath.Join(root, filepath.FromSlash(file)), dst); err != nil {
			return nil, err
		}
		saved[file] = dst
	}
	return saved, nil
}

func setOf(list []string) map[string]bool {
	m := make(map[string]bool, len(list))
	for _, x := range list {
		m[x] = true
	}
	return m
}

// RestoreVersion resets scope (file or folder) to the state of rev, as a new commit that can be
// undone with RevertCommit. It returns the short hash. It is refused if there are open changes in
// the area (they would otherwise be overwritten). Ignored, untracked files (e.g. *.tmp) that the
// old state would overwrite are first backed up to the trash under .git/sprintforecast-verworfen.
// An empty message gets a default.
func RestoreVersion(ctx context.Context, path, scope, rev, message string) (string, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return "", err
	}
	if err := noUnfinished(ctx, path); err != nil {
		return "", err
	}
	if rev, err = checkRev(rev); err != nil {
		return "", err
	}
	target := git.Resolve(scope)
	relPath, err := filepath.Rel(root, target)
	if err != nil || strings.HasPrefix(relPath, "..") {
		return "", git.New(i18n.T("The folder is outside the data repository."), "", "")
	}
	rel := filepath.ToSlash(relPath) // "." = the root itself
	changes, err := git.ChangesIn(ctx, path)
	if err != nil {
		return "", err
	}
	for _, c := range changes {
		if inside(c.File, rel) || (c.Orig != "" && inside(c.Orig, rel)) {
			return "", git.New(i18n.T("There are open changes in this area."), "dirty",
				i18n.T("Please save (commit) or discard them first, then restore."))
		}
	}
	var where []string
	if rel != "." {
		where = []string{"--", rel}
	}
	thenOut, err := git.With(ctx, root, git.Opts{Keep: true},
		append([]string{"ls-tree", "-r", "-z", "--name-only", rev}, where...)...)
	if err != nil {
		return "", err
	}
	nowOut, err := git.With(ctx, root, git.Opts{Keep: true}, append([]string{"ls-files", "-z"}, where...)...)
	if err != nil {
		return "", err
	}
	then, now := git.SplitZ(thenOut), git.SplitZ(nowOut)
	thenSet, nowSet := setOf(then), setOf(now)
	var gone, added []string
	for _, f := range now {
		if !thenSet[f] {
			gone = append(gone, f)
		}
	}
	for _, f := range then {
		if !nowSet[f] {
			added = append(added, f)
		}
	}
	sort.Strings(gone)
	sort.Strings(added)
	listing, err := git.With(ctx, root, git.Opts{Lenient: true, Keep: true},
		append([]string{"ls-files", "-z", "--others", "--ignored", "--exclude-standard"}, where...)...)
	if err != nil {
		return "", err
	}
	var clash []string
	for _, f := range git.SplitZ(listing) {
		if thenSet[f] {
			clash = append(clash, f)
		}
	}
	sort.Strings(clash)
	clash = dedupe(clash)
	saved := map[string]string{}
	trash := ""
	if len(clash) > 0 {
		if trash, err = newTrash(ctx, root); err != nil {
			return "", git.New(i18n.T("Backing up ignored files is not possible: {error}", "error", err.Error()),
				"error", i18n.T("Nothing was changed."))
		}
		if saved, err = saveIgnored(root, trash, clash); err != nil {
			_ = os.RemoveAll(trash)
			return "", git.New(i18n.T("Backing up ignored files is not possible: {error}", "error", err.Error()),
				"error", i18n.T("Nothing was changed."))
		}
	}
	err = func() error {
		sortedThen := append([]string(nil), then...)
		sort.Strings(sortedThen)
		for _, chunk := range chunks(sortedThen) {
			if _, err := git.Git(ctx, root, append([]string{"checkout", rev, "--"}, chunk...)...); err != nil {
				return err
			}
		}
		for _, chunk := range chunks(gone) {
			if _, err := git.Git(ctx, root, append([]string{"rm", "-q", "--"}, chunk...)...); err != nil {
				return err
			}
		}
		status, err := git.With(ctx, root, git.Opts{Keep: true}, "status", "--porcelain", "-z", "--", rel)
		if err != nil {
			return err
		}
		if status == "" {
			return git.New(i18n.T("This area already has exactly this state."), "", "")
		}
		short, err := git.Git(ctx, root, "rev-parse", "--short", rev)
		if err != nil {
			return err
		}
		text := message
		if text == "" {
			text = i18n.T("State of {rev} restored ({scope})", "rev", short, "scope", rel)
		}
		if _, err := git.Git(ctx, root, "add", "--all", "--", rel); err != nil {
			return err
		}
		if err := git.RefuseStagedConflictMarkers(ctx, root); err != nil { // an earlier shared faulty state
			return err
		}
		_, err = git.Git(ctx, root, "commit", "-m", text, "--", rel)
		return err
	}()
	if err != nil {
		e := git.As(err)
		if e == nil {
			return "", err
		}
		failed := rollbackRestore(ctx, root, rel, added, saved)
		git.InvalidateStatus()
		if len(failed) > 0 {
			whereSaved := trash
			if whereSaved == "" {
				gdir, _ := gitsync.GitDir(ctx, root)
				whereSaved = filepath.Join(gdir, trashFolder)
			}
			return "", git.New(e.Error(), e.Kind,
				i18n.T("The original version could not be fully restored (affected: {files}). "+
					"Saved ignored files are in {trash}.", "files", strings.Join(failed, ", "), "trash", whereSaved))
		}
		return "", err
	}
	git.InvalidateStatus()
	return git.Git(ctx, root, "rev-parse", "--short", "HEAD")
}

// RevertCommit reverts a commit with a new commit (e.g. undoes a restore). Merges cannot be
// reverted this way.
func RevertCommit(ctx context.Context, path, rev string) (string, error) {
	root, err := gitsync.Root(ctx, path)
	if err != nil {
		return "", err
	}
	if err := noUnfinished(ctx, path); err != nil {
		return "", err
	}
	if rev, err = checkRev(rev); err != nil {
		return "", err
	}
	out, err := git.Git(ctx, root, "rev-list", "--parents", "-n", "1", rev)
	if err != nil {
		return "", err
	}
	if len(strings.Fields(out)) > 2 {
		return "", git.New(i18n.T("A merge cannot be taken back."), "", "")
	}
	open, err := git.ChangesIn(ctx, root) // the whole repository, not only the data folder
	if err != nil {
		return "", err
	}
	if len(open) > 0 {
		return "", git.New(i18n.T("There are open changes."), "dirty",
			i18n.T("Please save (commit) or discard them first, then take back."))
	}
	if _, err := git.Git(ctx, root, "revert", "--no-edit", rev); err != nil {
		e := git.As(err)
		if e == nil {
			return "", err
		}
		_, _ = git.Lenient(ctx, root, "revert", "--abort")
		if e.Kind == "conflict" {
			return "", git.New(i18n.T("Taking back is not possible without a conflict: {error}", "error", e.Error()),
				"conflict", i18n.T("Later changes affect the same places. Nothing was changed."))
		}
		if strings.Contains(e.Error(), "now empty") || strings.Contains(e.Error(), "nothing to commit") {
			return "", git.New(i18n.T("This commit changes nothing (any more); there is nothing to take back."),
				"error", i18n.T("Nothing was changed."))
		}
		return "", err
	}
	changedOut, err := git.With(ctx, root, git.Opts{Keep: true},
		"diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD")
	if err != nil {
		return "", err
	}
	var changed []string
	for _, name := range git.SplitZ(changedOut) {
		changed = append(changed, filepath.Join(root, filepath.FromSlash(name)))
	}
	if err := git.RefuseConflictMarkers(root, changed); err != nil { // no state with conflict markers
		_, _ = git.Git(ctx, root, "reset", "--hard", "HEAD~1") // our own commit from just now
		git.InvalidateStatus()
		return "", err
	}
	git.InvalidateStatus()
	return git.Git(ctx, root, "rev-parse", "--short", "HEAD")
}
