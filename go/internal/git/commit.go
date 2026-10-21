package git

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// Spreadsheets must never be committed (they may contain real team data).
var forbiddenRe = regexp.MustCompile(`(?i)\.xls[xm]?$`)

// Data files that are never committed with conflict markers.
var dataFilesRe = regexp.MustCompile(`(?i)\.ya?ml$`)

var conflictMarkerRes = []*regexp.Regexp{
	regexp.MustCompile(`(?m)^<{7}( |\r?$)`),
	regexp.MustCompile(`(?m)^={7}\r?$`),
	regexp.MustCompile(`(?m)^>{7}( |\r?$)`),
}

// HasConflictMarkers says whether the text contains the markers of an unfinished merge (all
// three kinds).
func HasConflictMarkers(text string) bool {
	for _, re := range conflictMarkerRes {
		if !re.MatchString(text) {
			return false
		}
	}
	return true
}

// CheckName checks a tag name that is passed to Git: it must not start with "-" (Git would
// otherwise read it as an option), must not be called HEAD or @ (ambiguous for Git) and must not
// have whitespace at the beginning or end (it is not silently removed, otherwise a different
// name than the one entered would result).
func CheckName(name string) error {
	if strings.TrimSpace(name) == "" || name != strings.TrimSpace(name) || strings.HasPrefix(name, "-") ||
		name == "HEAD" || name == "@" {
		return Newf("error", "", "Invalid tag name: {name}", "name", name)
	}
	return nil
}

// ValidTagName is like CheckName, but additionally asks Git whether the ref name is valid.
func ValidTagName(ctx context.Context, root, name string) error {
	if err := CheckName(name); err != nil {
		return err
	}
	proc, err := Run(ctx, root, Opts{}, "check-ref-format", "refs/tags/"+name)
	if err != nil {
		return err
	}
	if proc.Code != 0 {
		return Newf("error", "", "Invalid tag name: {name}", "name", name)
	}
	return nil
}

// TagCommit is the full hash of the commit the local tag points to (empty = it does not exist).
func TagCommit(ctx context.Context, root, name string) (string, error) {
	return Lenient(ctx, root, "rev-parse", "--verify", "--quiet", "refs/tags/"+name+"^{commit}")
}

func uniqueValid(ctx context.Context, root string, tags []string) ([]string, error) {
	var names []string
	seen := map[string]bool{}
	for _, tag := range tags {
		if err := ValidTagName(ctx, root, tag); err != nil {
			return nil, err
		}
		if !seen[tag] {
			seen[tag] = true
			names = append(names, tag)
		}
	}
	return names, nil
}

// CheckNewTags checks tag names BEFORE a commit: valid and not yet taken locally (an existing tag
// never points to the new commit). On a conflict an *Error; nothing has been changed then. It
// returns the names without duplicates.
func CheckNewTags(ctx context.Context, root string, tags []string) ([]string, error) {
	names, err := uniqueValid(ctx, root, tags)
	if err != nil {
		return nil, err
	}
	for _, name := range names {
		existing, err := TagCommit(ctx, root, name)
		if err != nil {
			return nil, err
		}
		if existing != "" {
			return nil, Newf("tag_exists", HintFor("tag_exists"),
				"The tag {name} already exists on this computer (it points to {rev}). Nothing was committed.",
				"name", name, "rev", existing[:7])
		}
	}
	return names, nil
}

// EnsureTags sets missing tags on the current state (HEAD), without a new commit - e.g. when an
// earlier attempt wrote the commit but not the tag. It returns the newly set tags and the tags
// that already sit on a different state and stay unchanged.
func EnsureTags(ctx context.Context, root string, tags []string, message string) (created, elsewhere []string, err error) {
	names, err := uniqueValid(ctx, root, tags)
	if err != nil {
		return nil, nil, err
	}
	head, err := Lenient(ctx, root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
	if err != nil {
		return nil, nil, err
	}
	if head == "" {
		return nil, nil, nil
	}
	defer InvalidateStatus()
	for _, name := range names {
		existing, err := TagCommit(ctx, root, name)
		if err != nil {
			return created, elsewhere, err
		}
		switch {
		case existing == "":
			if _, err := Git(ctx, root, "tag", "-a", "-m", message, "--", name); err != nil {
				return created, elsewhere, err
			}
			created = append(created, name)
		case existing != head:
			elsewhere = append(elsewhere, name)
		}
	}
	return created, elsewhere, nil
}

// RefuseConflictMarkers refuses to commit data files that still contain conflict markers of an
// incomplete merge: they would be shared and then block editing for everyone else. files are
// absolute paths; the message names them relative to root (sprint files and team.yaml are called
// the same in every team).
func RefuseConflictMarkers(root string, files []string) error {
	var marked []string
	for _, file := range files {
		if !dataFilesRe.MatchString(filepath.Base(file)) {
			continue
		}
		raw, err := os.ReadFile(file)
		if err != nil { // deleted or unreadable: nothing to check
			continue
		}
		if !HasConflictMarkers(decode(raw)) {
			continue
		}
		name := filepath.ToSlash(file)
		if rel, err := filepath.Rel(resolve(root), resolve(file)); err == nil && !strings.HasPrefix(rel, "..") {
			name = filepath.ToSlash(rel)
		}
		if !containsString(marked, name) {
			marked = append(marked, name)
		}
	}
	if len(marked) == 0 {
		return nil
	}
	names := strings.Join(marked, ", ")
	hint := "Affected: {files}. The markers come from an incomplete merge: remove them " +
		"in an editor or, if the page “Resolve conflicts” appears, restore the " +
		"last saved state there."
	return New(i18n.T("These files still contain conflict markers (<<<<<<<, =======, >>>>>>>); "+
		"they are not taken over: {files}", "files", names),
		"conflict", i18n.T(hint, "files", names)).
		WithHintMD(i18n.T(hint, "files", MDPlain(names)))
}

// RefuseStagedConflictMarkers is like RefuseConflictMarkers for everything that is currently
// staged (before a commit that does not go through CommitDirectory: completing a merge,
// restoring, reverting).
func RefuseStagedConflictMarkers(ctx context.Context, root string) error {
	out, err := With(ctx, root, Opts{Keep: true}, "diff", "--cached", "--name-only", "-z")
	if err != nil {
		return err
	}
	var files []string
	for _, name := range SplitZ(out) {
		files = append(files, filepath.Join(root, name))
	}
	return RefuseConflictMarkers(root, files)
}

// CommitDirectory commits all changes below path (only there) and optionally sets tags. It
// returns the short hash.
func CommitDirectory(ctx context.Context, path, message string, tags []string) (string, error) {
	root, err := RequireRoot(ctx, path)
	if err != nil {
		return "", err
	}
	changes, err := PendingChanges(ctx, path)
	if err != nil {
		return "", err
	}
	if len(changes) == 0 {
		return "", Newf("error", "", "No changes to commit")
	}
	var blocked []string
	for _, c := range changes {
		if forbiddenRe.MatchString(c.File) {
			blocked = append(blocked, c.File)
		}
	}
	if len(blocked) > 0 {
		return "", Newf("error", "",
			"Spreadsheets are not committed – please remove them or add them to .gitignore: {files}",
			"files", strings.Join(blocked, ", "))
	}
	var live []string
	for _, c := range changes {
		if !strings.Contains(c.Status, "D") {
			live = append(live, filepath.Join(root, c.File))
		}
	}
	if err := RefuseConflictMarkers(root, live); err != nil {
		return "", err
	}
	names, err := CheckNewTags(ctx, root, tags) // before the commit: on a conflict everything stays open
	if err != nil {
		return "", err
	}
	target := resolve(path)
	defer InvalidateStatus()
	if _, err := Git(ctx, root, "add", "--all", "--", target); err != nil {
		return "", err
	}
	if _, err := Git(ctx, root, "commit", "-m", message, "--", target); err != nil {
		return "", err
	}
	for _, name := range names {
		if _, err := Git(ctx, root, "tag", "-a", "-m", message, "--", name); err != nil {
			return "", err
		}
	}
	return Git(ctx, root, "rev-parse", "--short", "HEAD")
}

var notARepositoryRe = regexp.MustCompile(`(?i)not a git repository`)

// committable drops deleted files that Git never knew (e.g. a sprint file that was never
// committed and has since been renamed): git add would abort on them with "pathspec did not
// match".
func committable(ctx context.Context, root string, paths []string) ([]string, error) {
	var gone []string
	for _, p := range paths {
		if _, err := os.Stat(p); err != nil {
			gone = append(gone, resolve(p))
		}
	}
	if len(gone) == 0 {
		return paths, nil
	}
	listed, err := Git(ctx, root, append([]string{"ls-files", "--"}, gone...)...)
	if err != nil {
		return nil, err
	}
	tracked := map[string]bool{}
	for _, line := range strings.Split(listed, "\n") {
		if line != "" {
			tracked[resolve(filepath.Join(root, line))] = true
		}
	}
	var kept []string
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil || tracked[resolve(p)] {
			kept = append(kept, p)
		}
	}
	return kept, nil
}

// Commit commits paths and optionally sets a tag. It returns the short hash.
func Commit(ctx context.Context, paths []string, message, tag string) (string, error) {
	cwd := filepath.Dir(resolve(paths[0]))
	top, err := Git(ctx, cwd, "rev-parse", "--show-toplevel")
	if err != nil {
		var e *Error
		if errors.As(err, &e) && e.Kind == "error" && notARepositoryRe.MatchString(e.Error()) {
			return "", Newf("not_repo", HintFor("not_repo"), "{path} is not inside a Git repository", "path", cwd)
		}
		return "", err
	}
	root := filepath.FromSlash(top)
	if err := RefuseConflictMarkers(root, paths); err != nil {
		return "", err
	}
	if paths, err = committable(ctx, root, paths); err != nil {
		return "", err
	}
	var tags []string
	if tag != "" {
		tags = []string{tag}
	}
	names, err := CheckNewTags(ctx, root, tags)
	if err != nil {
		return "", err
	}
	defer InvalidateStatus()
	resolved := make([]string, len(paths))
	for i, p := range paths {
		resolved[i] = resolve(p)
	}
	if _, err := Git(ctx, root, append([]string{"add", "--"}, resolved...)...); err != nil {
		return "", err
	}
	if _, err := Git(ctx, root, append([]string{"commit", "-m", message, "--"}, resolved...)...); err != nil {
		return "", err
	}
	for _, name := range names {
		if _, err := Git(ctx, root, "tag", "-a", "-m", message, "--", name); err != nil {
			return "", err
		}
	}
	return Git(ctx, root, "rev-parse", "--short", "HEAD")
}
