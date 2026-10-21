package protocol

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"
)

// AccessError is a file that cannot be read, written or locked; its text is meant for the user.
// Unlike the Python port the reason is the operating system's wording (lower case on Linux).
type AccessError struct{ Msg string }

func (e *AccessError) Error() string { return e.Msg }

func reason(err error) string {
	var pe *fs.PathError
	if errors.As(err, &pe) {
		return pe.Err.Error()
	}
	return err.Error()
}

func notReadable(path string, err error) error {
	return &AccessError{msg(
		"{path}: cannot be read ({reason}). Check the permissions or close the file in any other program.",
		"path", path, "reason", reason(err))}
}

func notSaved(path string, err error) error {
	return &AccessError{msg(
		"{path}: not saved ({reason}). The file was not changed. Is the folder writable, and is the file open in another program?",
		"path", path, "reason", reason(err))}
}

// LockWait is how long a save waits for another session that writes the same minutes.
var LockWait = 10 * time.Second

// ConfigDir is the settings folder of the user; the locks live in its "sperren" subfolder.
var ConfigDir = func() string {
	base := ""
	if appdata := os.Getenv("APPDATA"); appdata != "" && isWindows {
		base = appdata
	} else if xdg := os.Getenv("XDG_CONFIG_HOME"); xdg != "" {
		base = xdg
	} else if home, err := os.UserHomeDir(); err == nil {
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, "foresprint")
}

// Store is the minutes folder of one team.
type Store struct {
	// Dir is the team folder; the minutes live in its "protokolle" subfolder.
	Dir string
	// Now supplies the timestamp of a file name; it is read only after the lock is held, so
	// that whoever waits longer never gets an earlier timestamp than the predecessor. Nil means
	// the system clock.
	Now func() time.Time
	// OnChange is called after the folder changed (a new, renamed or removed file).
	OnChange func()
}

func (s *Store) folder() string { return filepath.Join(s.Dir, Folder) }

func (s *Store) changed() {
	if s.OnChange != nil {
		s.OnChange()
	}
}

func (s *Store) moment() time.Time {
	now := time.Now
	if s.Now != nil {
		now = s.Now
	}
	t := now()
	return t.Truncate(time.Second)
}

func (s *Store) makeFolder() (string, error) {
	folder := s.folder()
	if err := os.MkdirAll(folder, 0o777); err != nil {
		return "", notSaved(folder, err)
	}
	return folder, nil
}

// readText reads a file like Python's text mode: UTF-8 with universal newlines.
func readText(path string) (string, bool) {
	b, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(b) {
		return "", false
	}
	text := strings.ReplaceAll(string(b), "\r\n", "\n")
	return strings.ReplaceAll(text, "\r", "\n"), true
}

func bodyOfFile(path string) ([]string, bool) {
	text, ok := readText(path)
	if !ok {
		return nil, false
	}
	return BodyOf(text), true
}

// stateOf is the fingerprint stored in the last state line of a file.
func stateOf(path string) (string, bool) {
	text, ok := readText(path)
	if !ok {
		return "", false
	}
	lines := strings.Split(text, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if strings.HasPrefix(lines[i], StateMarker) {
			return strings.TrimSpace(strings.TrimSuffix(lines[i][len(StateMarker):], " -->")), true
		}
	}
	return "", false
}

// writeText writes a file via a temporary file in the same folder and replaces the target: the
// file is afterwards either completely new or unchanged, never half-written.
func writeText(path, text string) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), "*.tmp")
	if err != nil {
		return notSaved(path, err)
	}
	name := tmp.Name()
	_, werr := tmp.WriteString(text)
	cerr := tmp.Close()
	if err := errors.Join(werr, cerr); err != nil {
		_ = os.Remove(name)
		return notSaved(path, err)
	}
	if err := os.Rename(name, path); err != nil {
		_ = os.Remove(name)
		return notSaved(path, err)
	}
	return nil
}

// Entry is one file of the minutes of a sprint.
type Entry struct {
	At       time.Time
	Kind     string
	Obsolete bool
	Path     string
}

var namePattern = regexp.MustCompile(
	`^(.+)-(vorplanung|planning|review)-(\d{8}-\d{6})(?:-[0-9a-f]{4})?(?:_obsolet_(\p{Nd}{8}-\p{Nd}{6}))?\.md$`)

// List returns the minutes of a sprint, newest first.
func (s *Store) List(sprintID string) ([]Entry, error) {
	folder := s.folder()
	var entries []os.DirEntry
	if info, err := os.Stat(folder); err == nil && info.IsDir() {
		var rerr error
		if entries, rerr = os.ReadDir(folder); rerr != nil {
			return nil, notReadable(folder, rerr)
		}
	}
	found := []Entry{}
	for _, e := range entries {
		name := e.Name()
		m := namePattern.FindStringSubmatch(strings.TrimSuffix(name, "\n")) // Python's $ allows one
		if m == nil || m[1] != sprintID {
			continue
		}
		path := filepath.Join(folder, name)
		if info, err := os.Stat(path); err != nil || !info.Mode().IsRegular() {
			continue
		}
		at, err := time.Parse(stamp, m[3])
		if err != nil || at.Year() < 1 { // renamed by hand or by sync: impossible timestamp
			continue
		}
		found = append(found, Entry{At: at, Kind: m[2], Obsolete: m[4] != "", Path: path})
	}
	sort.Slice(found, func(i, j int) bool {
		if !found[i].At.Equal(found[j].At) {
			return found[i].At.After(found[j].At)
		}
		return filepath.Base(found[i].Path) > filepath.Base(found[j].Path)
	})
	return found, nil
}

// Renames lists the renames by which the minutes of the sprints "old" are kept under "new" from
// now on (obsolete ones too); nothing is renamed here.
func (s *Store) Renames(pairs [][2]string) ([][2]string, error) {
	found := [][2]string{}
	for _, p := range pairs {
		entries, err := s.List(p[0])
		if err != nil {
			return nil, err
		}
		for _, e := range entries {
			base := filepath.Base(e.Path)
			found = append(found, [2]string{e.Path, filepath.Join(filepath.Dir(e.Path), p[1]+strings.TrimPrefix(base, p[0]))})
		}
	}
	return found, nil
}

// WriteNew writes the minutes (LF line endings, via a temporary file) and reports whether they
// are new. With a state (see Fingerprint) no further minutes are created if the state is
// unchanged; without one the text decides. If the name already exists (two saves in the same
// second), the second is counted up. Searching and writing run under a lock per sprint and
// meeting.
func (s *Store) WriteNew(sprintID, kind, text string, state *string) (path string, created bool, err error) {
	folder, err := s.makeFolder()
	if err != nil {
		return "", false, err
	}
	err = s.locked(folder, sprintID, kind, func() error {
		var werr error
		path, created, werr = s.writeLocked(sprintID, kind, text, state)
		return werr
	})
	return path, created, err
}

func (s *Store) latest(sprintID, kind string) (string, bool, error) {
	entries, err := s.List(sprintID)
	if err != nil {
		return "", false, err
	}
	for _, e := range entries {
		if e.Kind == kind && !e.Obsolete {
			return e.Path, true, nil
		}
	}
	return "", false, nil
}

func (s *Store) writeLocked(sprintID, kind, text string, state *string) (string, bool, error) {
	latest, ok, err := s.latest(sprintID, kind)
	if err != nil {
		return "", false, err
	}
	if ok {
		same := false
		if state != nil {
			got, has := stateOf(latest)
			same = has && got == *state
		} else if body, has := bodyOfFile(latest); has {
			same = equal(body, BodyOf(text))
		}
		if same {
			return latest, false, nil // nothing changed: no further identical minutes
		}
	}
	tag := ""
	if state != nil {
		text = strings.TrimRight(text, "\n") + "\n\n" + StateMarker + *state + " -->\n"
		tag = *state
	}
	if tag == "" {
		sum := sha256.Sum256([]byte(text))
		tag = hex.EncodeToString(sum[:])
	}
	if len(tag) > 4 {
		tag = tag[:4]
	}
	at := s.moment()
	var path string
	for {
		path = filepath.Join(s.folder(), fmt.Sprintf("%s-%s-%s-%s.md", sprintID, kind, at.Format(stamp), tag))
		if _, err := os.Stat(path); err != nil {
			break
		}
		at = at.Add(time.Second)
	}
	if err := writeText(path, text); err != nil {
		return "", false, err
	}
	s.changed() // a new file is an open change, even without changed YAML
	return path, true, nil
}

// SaveWithProtocol writes the minutes first, then calls save (which writes the sprint files).
// If the minutes cannot be written, the sprint files stay unchanged; if save fails, the minutes
// just written are removed again. documents are the YAML texts of the sprint files as they are
// saved (they enter the fingerprint). save runs under the lock and must not take it itself.
func (s *Store) SaveWithProtocol(sprintID, kind, text string, documents []string, save func() ([]string, error)) (saved []string, err error) {
	state := Fingerprint(text, documents...)
	folder, err := s.makeFolder()
	if err != nil {
		return nil, err
	}
	err = s.locked(folder, sprintID, kind, func() error {
		path, created, werr := s.writeLocked(sprintID, kind, text, &state)
		if werr != nil {
			return werr
		}
		var serr error
		saved, serr = save()
		if serr != nil && created {
			if rerr := os.Remove(path); rerr != nil && !errors.Is(rerr, fs.ErrNotExist) {
				serr = errors.Join(serr, rollbackNote(path, rerr))
			}
			s.changed()
		}
		return serr
	})
	return saved, err
}

func rollbackNote(path string, err error) error {
	return errors.New(msg("{path}: not rolled back ({reason})", "path", path, "reason", reason(err)))
}

var obsoleteSuffix = regexp.MustCompile(`_obsolet_\d{8}-\d{6}(\.md)$`)

// undo reverses MarkObsolete as far as possible and returns the errors of renames back.
func (s *Store) undo(renamed []string) error {
	var errs []error
	for _, target := range renamed {
		original := obsoleteSuffix.ReplaceAllString(filepath.Base(target), "$1")
		if err := os.Rename(target, filepath.Join(filepath.Dir(target), original)); err != nil {
			errs = append(errs, rollbackNote(target, err))
		}
	}
	if len(renamed) > 0 {
		s.changed()
	}
	return errors.Join(errs...)
}

// MarkObsolete renames the valid minutes of the meeting to …_obsolet_<date>-<time>.md (e.g. when
// the freeze of the sprint is lifted) and returns the new files. If a rename fails, those
// already renamed are renamed back.
func (s *Store) MarkObsolete(sprintID, kind string) ([]string, error) {
	folder, err := s.makeFolder()
	if err != nil {
		return nil, err
	}
	var renamed []string
	err = s.locked(folder, sprintID, kind, func() error {
		var merr error
		renamed, merr = s.markObsolete(sprintID, kind)
		return merr
	})
	return renamed, err
}

func (s *Store) markObsolete(sprintID, kind string) ([]string, error) {
	renamed := []string{}
	moment := s.moment()
	entries, err := s.List(sprintID)
	if err != nil {
		return nil, err
	}
	for _, e := range entries {
		if e.Kind != kind || e.Obsolete {
			continue
		}
		at := moment
		stem := strings.TrimSuffix(e.Path, ".md")
		target := fmt.Sprintf("%s_obsolet_%s.md", stem, at.Format(stamp))
		for {
			if _, err := os.Stat(target); err != nil {
				break
			}
			at = at.Add(time.Second) // two lifts in the same second
			target = fmt.Sprintf("%s_obsolet_%s.md", stem, at.Format(stamp))
		}
		if err := os.Rename(e.Path, target); err != nil {
			failure := &AccessError{msg("{path}: not renamed ({reason})", "path", e.Path, "reason", reason(err))}
			return nil, errors.Join(failure, s.undo(renamed))
		}
		renamed = append(renamed, target)
	}
	if len(renamed) > 0 {
		s.changed()
	}
	return renamed, nil
}

// ObsoleteWithSave renames the minutes first and then calls save; if saving fails, the minutes
// are renamed back. save runs under the lock and must not take it itself.
func (s *Store) ObsoleteWithSave(sprintID, kind string, save func() ([]string, error)) (saved []string, err error) {
	folder, err := s.makeFolder()
	if err != nil {
		return nil, err
	}
	err = s.locked(folder, sprintID, kind, func() error {
		renamed, merr := s.markObsolete(sprintID, kind)
		if merr != nil {
			return merr
		}
		var serr error
		saved, serr = save()
		if serr != nil {
			serr = errors.Join(serr, s.undo(renamed))
		}
		return serr
	})
	return saved, err
}

// --- locks ---

// lockUnsupported is a permanent failure to lock a file (not just contention), e.g. on a file
// system without file locks.
type lockUnsupported struct{ err error }

func (e *lockUnsupported) Error() string { return e.err.Error() }

// privateDir creates the folder; only the last level is private (on POSIX), parents get the
// default mode.
func privateDir(path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return err
	}
	if err := os.Mkdir(path, privateMode); err != nil && !errors.Is(err, fs.ErrExist) {
		return err
	}
	if info, err := os.Stat(path); err != nil || !info.IsDir() {
		return &fs.PathError{Op: "mkdir", Path: path, Err: syscall.EEXIST}
	}
	return nil
}

// tempDir is the temp folder like Python's tempfile.gettempdir: TMPDIR, TEMP, TMP, then the
// system default.
func tempDir() string {
	for _, name := range []string{"TMPDIR", "TEMP", "TMP"} {
		if dir := os.Getenv(name); dir != "" {
			return dir
		}
	}
	return os.TempDir()
}

// permanent reports errors when creating or opening in the settings folder after which the temp
// folder is used; transient ones (too many files, no space, I/O) are raised instead of silently
// spreading sessions across different lock files.
func permanent(err error) bool {
	for _, target := range []error{
		fs.ErrNotExist, fs.ErrPermission, fs.ErrExist,
		syscall.EROFS, syscall.EISDIR, syscall.ENOTDIR,
	} {
		if errors.Is(err, target) {
			return true
		}
	}
	return false
}

func fallbackLockDir() (string, error) {
	name := regexp.MustCompile(`[^\p{L}\p{N}_]`).ReplaceAllString(userName(), "_")
	root := filepath.Join(tempDir(), "sprintforecast-sperren-"+name)
	if err := privateDir(root); err != nil {
		return "", notSaved(root, err)
	}
	if !safeLockDir(root) {
		return "", &AccessError{msg(
			"The folder {path} for the locks belongs to another user. Please have it removed or make the settings folder writable.",
			"path", root)}
	}
	return root, nil
}

func lockDir() (string, error) {
	root := filepath.Join(ConfigDir(), "sperren")
	if err := privateDir(root); err != nil {
		if !permanent(err) {
			return "", notSaved(root, err)
		}
		return fallbackLockDir()
	}
	if !writableDir(root) { // an existing, non-writable folder is no good
		return fallbackLockDir()
	}
	return root, nil
}

func lockFile(folder, sprintID, kind string) (string, error) {
	resolved, err := filepath.Abs(folder)
	if err != nil {
		resolved = folder
	}
	if real, err := filepath.EvalSymlinks(resolved); err == nil {
		resolved = real
	}
	sum := sha256.Sum256([]byte(resolved + "|" + sprintID + "|" + kind))
	dir, err := lockDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, hex.EncodeToString(sum[:])[:24]+".lock"), nil
}

func openLock(path string) (*os.File, string, error) {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o666)
	if err == nil {
		return f, path, nil
	}
	if !permanent(err) {
		return nil, "", notSaved(path, err)
	}
	dir, derr := fallbackLockDir()
	if derr != nil {
		return nil, "", derr
	}
	if dir == filepath.Dir(path) { // that was already the fallback folder
		return nil, "", notSaved(path, err)
	}
	fallback := filepath.Join(dir, filepath.Base(path))
	f, ferr := os.OpenFile(fallback, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o666)
	if ferr != nil {
		return nil, "", notSaved(fallback, ferr)
	}
	return f, fallback, nil
}

func acquire(f *os.File) error {
	deadline := time.Now().Add(LockWait)
	for {
		ok, err := tryLock(f)
		if err != nil {
			return &lockUnsupported{err}
		}
		if ok {
			return nil
		}
		if !time.Now().Before(deadline) {
			return &AccessError{msg("Another session is currently writing minutes for this sprint. Please save again in a moment.")}
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func acquireInFallback(used string) (*os.File, error) {
	unsupported := &AccessError{msg(
		"File locks are not supported on the drive of {path}. Please move the settings folder to a local drive.",
		"path", filepath.Dir(used))}
	dir, err := fallbackLockDir()
	if err != nil {
		return nil, err
	}
	if dir == filepath.Dir(used) {
		return nil, unsupported
	}
	f, err := os.OpenFile(filepath.Join(dir, filepath.Base(used)), os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o666)
	if err != nil {
		return nil, unsupported
	}
	if err := acquire(f); err != nil {
		_ = f.Close()
		var lu *lockUnsupported
		if errors.As(err, &lu) {
			return nil, unsupported
		}
		return nil, err
	}
	return f, nil
}

// locked runs fn with an operating system lock per sprint and meeting, which ends with the
// process by itself. It has no effect between clones on different machines; there the file name
// derived from the content protects.
func (s *Store) locked(folder, sprintID, kind string, fn func() error) error {
	path, err := lockFile(folder, sprintID, kind)
	if err != nil {
		return err
	}
	handle, used, err := openLock(path)
	if err != nil {
		return err
	}
	defer func() { _ = handle.Close() }()
	if err := acquire(handle); err != nil {
		var lu *lockUnsupported
		if !errors.As(err, &lu) {
			return err
		}
		_ = handle.Close()
		if handle, err = acquireInFallback(used); err != nil {
			return err
		}
	}
	defer func() { _ = unlock(handle) }()
	return fn()
}

func userName() string {
	if n := currentUser(); n != "" {
		return n
	}
	return "unknown"
}
