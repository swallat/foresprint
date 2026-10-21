package git

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/i18n"
)

// Gitignore is the .gitignore of a new data repository.
const Gitignore = `# Never commit spreadsheets – they can contain real team data.
*.xlsx
*.xlsm
*.xls
# Leftover temporary files from saving.
*.tmp
`

// Gitattributes is the .gitattributes of a new data repository.
const Gitattributes = `# Data files and reports always with LF, even with core.autocrlf (Windows): otherwise the first
# save would rewrite all line endings and create noise in the history.
*.yaml text eol=lf
*.yml text eol=lf
*.md text eol=lf
`

// attributeRules are the rules of Gitattributes, one by one: the line and a sample file for which
// git check-attr shows whether something (possibly elsewhere) already makes the same setting.
var attributeRules = []struct{ rule, sample string }{
	{"*.yaml text eol=lf", "x.yaml"},
	{"*.yml text eol=lf", "x.yml"},
	{"*.md text eol=lf", "x.md"},
}

// AttributesOffer is the offer of a .gitattributes for an existing data repository: File is the
// file in the data folder, Rules the missing lines, Affected the tracked files (relative to the
// data folder) whose line endings are CRLF (or mixed) in the index and would be converted to LF
// by the next commit once the rules apply.
type AttributesOffer struct {
	File     string
	Rules    []string
	Affected []string
}

// lfCovered returns the sample files for which Git already applies eol=lf in the data folder.
func lfCovered(ctx context.Context, data string) (map[string]bool, error) {
	args := []string{"check-attr", "-z", "eol", "--"}
	for _, r := range attributeRules {
		args = append(args, r.sample)
	}
	out, err := With(ctx, data, Opts{Keep: true}, args...)
	if err != nil {
		return nil, err
	}
	fields := strings.Split(out, "\x00")
	covered := map[string]bool{}
	for i := 0; i+2 < len(fields); i += 3 { // path, attribute, value
		if fields[i+2] == "lf" {
			covered[fields[i]] = true
		}
	}
	return covered, nil
}

// AttributesOffered checks whether the data folder data (in a Git repository) lacks the setting
// "YAML and reports with LF". It returns nil if everything is already covered, also by a
// .gitattributes elsewhere in the repository, or if there is no repository. Nothing is written.
func AttributesOffered(ctx context.Context, data string) (*AttributesOffer, error) {
	root, err := RepoRoot(ctx, data)
	if err != nil || root == "" {
		return nil, err
	}
	covered, err := lfCovered(ctx, data)
	if err != nil {
		return nil, err
	}
	var missing []string
	for _, r := range attributeRules {
		if !covered[r.sample] {
			missing = append(missing, r.rule)
		}
	}
	if len(missing) == 0 {
		return nil, nil
	}
	// The patterns are filtered here: Git runs with literal pathspecs (no wildcards).
	var suffixes []string
	for _, r := range attributeRules {
		suffixes = append(suffixes, strings.TrimPrefix(strings.Fields(r.rule)[0], "*"))
	}
	out, err := With(ctx, data, Opts{Keep: true}, "ls-files", "--eol", "-z")
	if err != nil {
		return nil, err
	}
	var affected []string
	for _, entry := range strings.Split(out, "\x00") {
		info, name, _ := strings.Cut(entry, "\t")
		kind, _, _ := strings.Cut(info, " ")
		if kind != "i/crlf" && kind != "i/mixed" {
			continue
		}
		for _, suffix := range suffixes {
			if strings.HasSuffix(name, suffix) {
				affected = append(affected, name)
				break
			}
		}
	}
	sort.Strings(affected)
	return &AttributesOffer{File: filepath.Join(data, ".gitattributes"), Rules: missing, Affected: affected}, nil
}

// ApplyAttributes writes the missing rules into the .gitattributes of the data folder (an
// existing file is extended, nothing in it is changed) and stages the affected files for
// conversion (git add --renormalize). Nothing is committed: the change shows up among the open
// changes like any other and takes the same way (save and share, as a merge request if
// configured). It returns the offer that was applied, nil if there was nothing to do.
func ApplyAttributes(ctx context.Context, data string) (offer *AttributesOffer, err error) {
	offer, err = AttributesOffered(ctx, data)
	if err != nil || offer == nil {
		return nil, err
	}
	root, err := RequireRoot(ctx, data)
	if err != nil {
		return nil, err
	}
	previous, readErr := os.ReadFile(offer.File)
	existed := readErr == nil
	defer InvalidateStatus()
	defer func() {
		if err == nil {
			return
		}
		// Leave nothing half done: without the file the offer stays valid.
		if !existed {
			_ = os.Remove(offer.File)
		} else {
			_ = os.WriteFile(offer.File, previous, 0o644)
		}
	}()
	head := string(previous)
	if head != "" && !strings.HasSuffix(head, "\n") {
		head += "\n"
	}
	if err = os.WriteFile(offer.File, []byte(head+strings.Join(offer.Rules, "\n")+"\n"), 0o644); err != nil {
		return nil, err
	}
	// Only the index knows a deletion that is not saved yet: git add would fail there.
	args := []string{"add", "--renormalize", "--"}
	var names []string
	for _, f := range offer.Affected {
		if _, statErr := os.Stat(filepath.Join(data, f)); statErr == nil {
			names = append(names, resolve(filepath.Join(data, f)))
		}
	}
	if len(names) > 0 {
		if _, err = Git(ctx, root, append(args, names...)...); err != nil {
			return nil, err
		}
	}
	return offer, nil
}

// reasonOf is the system's text for an OS error (like Python's strerror, which starts with a
// capital letter), or the text of the error itself.
func reasonOf(err error) string {
	var errno syscall.Errno
	if errors.As(err, &errno) {
		return capitalize(errno.Error())
	}
	return err.Error()
}

func capitalize(s string) string {
	r, size := utf8.DecodeRuneInString(s)
	return string(unicode.ToUpper(r)) + s[size:]
}

// FolderProblem is a file system error on the folder path as an *Error of kind "folder" with
// plain text (paths appear as code, because the message is shown as Markdown).
func FolderProblem(path string, err error) *Error {
	shown := MDCode(path)
	var message string
	if errors.Is(err, fs.ErrPermission) {
		message = i18n.T("No access rights for {path} – please choose another folder or adjust the "+
			"permissions.", "path", shown)
	} else {
		message = i18n.T("{path} cannot be created ({reason}) – please check the path.",
			"path", shown, "reason", reasonOf(err))
	}
	return New(message, "folder", "")
}

func isOSError(err error) bool {
	var (
		pathErr *fs.PathError
		linkErr *os.LinkError
		sysErr  *os.SyscallError
		errno   syscall.Errno
	)
	return errors.As(err, &pathErr) || errors.As(err, &linkErr) || errors.As(err, &sysErr) || errors.As(err, &errno)
}

// folderAccess runs fn on the target folder path of a create or clone: a file at this location
// and file system errors (no permission, unusable path, including those reported by Git) come as
// an *Error of kind "folder" with plain text instead of a raw error.
func folderAccess(path string, fn func() error) error {
	if info, err := os.Stat(path); err == nil && info.Mode().IsRegular() {
		return New(i18n.T("{path} is a file, not a folder – please specify a folder.", "path", MDCode(path)), "folder", "")
	}
	err := fn()
	if err == nil {
		return nil
	}
	if e := As(err); e != nil {
		if e.Kind == "not_writable" || (e.Kind == "error" && strings.Contains(e.Error(), "Permission denied")) {
			return FolderProblem(path, fs.ErrPermission)
		}
		return err
	}
	if isOSError(err) {
		return FolderProblem(path, err)
	}
	return err
}

// InitDataRepository creates a data repository (git init, .gitignore, optionally a teams folder)
// and returns the folder for the teams. A new repository also gets a .gitattributes in the data
// folder (YAML and reports with LF): it is committed with the data and thus reaches the clones
// too. Existing files and existing repositories stay unchanged: CRLF files might be in the index
// there, which would suddenly count as modified with the setting. A file as the target and file
// system errors come as *Error (kind "folder"), a folder that Git rejects as unsafe as kind
// "unsafe_directory" (without writing anything).
func InitDataRepository(ctx context.Context, path string, teamsFolder bool) (string, error) {
	var data string
	err := folderAccess(path, func() error {
		problem, err := RootProblem(ctx, path)
		if err != nil {
			return err
		}
		if problem != nil {
			// Git rejects the folder because it belongs to a different account: no "git init"
			// there, write nothing into it, but name the reason.
			return New(problem.Error(), problem.Kind, problem.Hint()).WithRaw(problem.Raw)
		}
		if err := os.MkdirAll(path, 0o777); err != nil {
			return err
		}
		root, err := RepoRoot(ctx, path)
		if err != nil {
			return err
		}
		fresh := root == ""
		if fresh {
			if _, err := Git(ctx, path, "init", "-q"); err != nil {
				return err
			}
			ForgetRoots(path)
		}
		ignore := filepath.Join(path, ".gitignore")
		if _, err := os.Stat(ignore); err != nil {
			if err := os.WriteFile(ignore, []byte(Gitignore), 0o666); err != nil {
				return err
			}
		}
		data = path
		if teamsFolder {
			data = filepath.Join(path, "teams")
			if err := os.MkdirAll(data, 0o777); err != nil {
				return err
			}
		}
		attributes := filepath.Join(data, ".gitattributes")
		if _, err := os.Stat(attributes); fresh && err != nil {
			if err := os.WriteFile(attributes, []byte(Gitattributes), 0o666); err != nil {
				return err
			}
		}
		return nil
	})
	return data, err
}

// CloneRepository clones an existing data repository to path. The address is checked as with
// ParseRemoteURL (credentials in the address, relative paths, git:// and file:// are rejected).
// Errors (address, target folder, login, server not reachable, timeout) come as *Error with the
// next step. A zero timeout means five minutes.
func CloneRepository(ctx context.Context, url, path string, timeout time.Duration) error {
	// When cloning, http:// is also enough (many company-network repositories offer nothing else).
	address, err := ParseRemoteURL(url, true)
	if err != nil {
		return err
	}
	if timeout == 0 {
		timeout = 5 * time.Minute
	}
	path = abs(path) // else a relative target would be relative to the parent
	defer ForgetRoots(path)
	return folderAccess(path, func() error {
		if entries, err := os.ReadDir(path); err == nil && len(entries) > 0 {
			return New(i18n.T("{path} is not empty", "path", MDCode(path)), "folder", "")
		}
		parent := filepath.Dir(path)
		if err := os.MkdirAll(parent, 0o777); err != nil {
			return err
		}
		_, err := With(ctx, parent, Opts{
			Network: true, Timeout: timeout, URL: address.URL,
			Env: map[string]string{"GIT_ALLOW_PROTOCOL": SafeProtocols},
		}, "clone", "--", address.URL, path)
		return err
	})
}
