package git

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

// NetworkTimeout is the limit of network calls (fetch, push, clone): they must never hang forever
// or ask for a password in the background, there is no terminal in which anyone could answer.
const NetworkTimeout = 90 * time.Second

const (
	defaultTimeout = 120 * time.Second
	killDelay      = 5 * time.Second
)

// Opts are the options of a Git call.
type Opts struct {
	// Network marks a call that talks to a server: longer time limit and no prompt in the
	// terminal. Credential helpers (credential manager) keep running.
	Network bool
	// Timeout overrides the time limit (default 120 s, 90 s for network calls).
	Timeout time.Duration
	// Env is added to the environment last.
	Env map[string]string
	// URL is the address of the server for network calls: it determines the login help (SSH or
	// https, see Classify).
	URL string
	// Keep leaves the output as it is; otherwise whitespace at both ends is removed.
	Keep bool
	// Lenient returns an empty text instead of an error when Git exits with an error.
	Lenient bool
	// Stdin is handed to Git as input (nil: no input).
	Stdin *string
}

// Result is the outcome of a Git call, including the exit code.
type Result struct {
	Code   int
	Stdout string
	Stderr string
}

// env is the environment for Git: English messages (so that they can be recognised) and, for
// network calls, no prompt in the terminal. Trace logs (GIT_TRACE*, GIT_CURL_VERBOSE) are
// removed: they would write login headers into the error output. extra is added last. Paths
// are never search patterns: file names with *, ? or [ are meant literally.
func env(network bool, extra map[string]string) []string {
	vars := map[string]string{}
	order := []string{}
	set := func(name, value string) {
		if _, ok := vars[name]; !ok {
			order = append(order, name)
		}
		vars[name] = value
	}
	for _, kv := range os.Environ() {
		name, value, _ := strings.Cut(kv, "=")
		upper := strings.ToUpper(name)
		if strings.HasPrefix(upper, "GIT_TRACE") || strings.HasPrefix(upper, "GIT_CURL_VERBOSE") {
			continue
		}
		set(name, value)
	}
	set("LC_ALL", "C")
	set("LANGUAGE", "C")
	set("GIT_LITERAL_PATHSPECS", "1")
	if network {
		set("GIT_TERMINAL_PROMPT", "0")
	}
	for name, value := range extra {
		set(name, value)
	}
	out := make([]string, 0, len(order))
	for _, name := range order {
		out = append(out, name+"="+vars[name])
	}
	return out
}

// --- Aborting a running sync ----------------------------------------------------------------
//
// A sync of a data folder can be ended from outside (AbortRunning), also while Git hangs. The
// Git calls of the sync carry the context from BeginSync; calls with another context (display,
// status) are left alone.

type scope struct {
	cancel context.CancelFunc

	mu      sync.Mutex
	active  int
	aborted bool
}

type scopeKey struct{}

var (
	scopesMu sync.Mutex
	scopes   = map[string]*scope{}
)

func scopeOf(ctx context.Context) *scope {
	sc, _ := ctx.Value(scopeKey{}).(*scope)
	return sc
}

// BeginSync marks the calls made with the returned context as the sync of this folder: only they
// can be ended by AbortRunning. The returned function ends the sync; the abort mark expires
// with it.
func BeginSync(ctx context.Context, cwd string) (context.Context, func()) {
	key := resolve(cwd)
	inner, cancel := context.WithCancel(ctx)
	sc := &scope{cancel: cancel}
	scopesMu.Lock()
	scopes[key] = sc
	scopesMu.Unlock()
	return context.WithValue(inner, scopeKey{}, sc), func() {
		scopesMu.Lock()
		if scopes[key] == sc {
			delete(scopes, key)
		}
		scopesMu.Unlock()
		cancel()
	}
}

// AbortRunning ends the running Git calls of this folder's sync (including child processes). The
// sync starts no new call until it ends. It returns true if a call was running. Files such as
// index.lock are never removed; an aborted Git reports them as "locked".
func AbortRunning(cwd string) bool {
	scopesMu.Lock()
	sc := scopes[resolve(cwd)]
	scopesMu.Unlock()
	if sc == nil {
		return false
	}
	sc.mu.Lock()
	running := sc.active > 0
	if running {
		sc.aborted = true
	}
	sc.mu.Unlock()
	if running {
		sc.cancel()
	}
	return running
}

func (sc *scope) enter() bool {
	sc.mu.Lock()
	defer sc.mu.Unlock()
	if sc.aborted {
		return false
	}
	sc.active++
	return true
}

func (sc *scope) leave() {
	sc.mu.Lock()
	sc.active--
	sc.mu.Unlock()
}

func raiseIfAborted(ctx context.Context) error {
	sc := scopeOf(ctx)
	if sc == nil {
		return nil
	}
	sc.mu.Lock()
	aborted := sc.aborted
	sc.mu.Unlock()
	if aborted {
		return New(i18n.T("The sync was aborted."), "aborted", HintFor("aborted"))
	}
	return nil
}

// --- Running Git ----------------------------------------------------------------------------

var errTimedOut = errors.New("git: timed out")

// startError is a failure to start the program.
type startError struct{ err error }

func (e *startError) Error() string { return e.err.Error() }
func (e *startError) Unwrap() error { return e.err }

// decode turns output into text; invalid bytes become U+FFFD.
func decode(b []byte) string {
	if utf8.Valid(b) {
		return string(b)
	}
	var sb strings.Builder
	for len(b) > 0 {
		r, size := utf8.DecodeRune(b)
		if r == utf8.RuneError && size == 1 {
			sb.WriteRune(utf8.RuneError)
		} else {
			sb.Write(b[:size])
		}
		b = b[size:]
	}
	return sb.String()
}

// runTracked runs a command with a time limit. The process runs in a session of its own, so that
// the whole tree can be ended on a timeout or an abort.
func runTracked(ctx context.Context, argv []string, cwd string, timeout time.Duration, environ []string, stdin *string) (*Result, error) {
	sc := scopeOf(ctx)
	if sc != nil {
		if !sc.enter() {
			return nil, context.Canceled
		}
		defer sc.leave()
	}
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, argv[0], argv[1:]...)
	cmd.Dir = cwd
	cmd.Env = environ
	cmd.Cancel = func() error { return terminateTree(cmd) }
	cmd.WaitDelay = killDelay // pipes can be kept open by grandchildren (ssh): do not wait forever
	setProcAttr(cmd)
	var out, errOut bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errOut
	if stdin != nil {
		cmd.Stdin = strings.NewReader(*stdin)
	}
	if err := cmd.Start(); err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, &startError{err}
	}
	_ = cmd.Wait()
	if runCtx.Err() != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, errTimedOut
	}
	code := -1
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	return &Result{Code: code, Stdout: decode(out.Bytes()), Stderr: decode(errOut.Bytes())}, nil
}

// Errors at startup that make the program permanently unusable: not found, no access, not a
// valid program. Others (arguments too long, file currently being written, too many open files,
// out of memory ...) are temporary or do not concern the program.
func programErrno(errno syscall.Errno) bool {
	switch errno {
	case syscall.ENOENT, syscall.EACCES, syscall.ENOEXEC:
		return true
	}
	switch runtime.GOOS {
	case "windows":
		// not found (2), access denied (5), not a valid program (193), elevation required
		// (740), application cannot be run (1260)
		switch errno {
		case 2, 5, 193, 740, 1260:
			return true
		}
	case "linux":
		return errno == 80 // ELIBBAD
	case "darwin":
		return errno == 86 // EBADARCH
	}
	return false
}

// programFailed says whether the startup error makes the program itself permanently unusable.
// On POSIX every exec error carries the program path as its file name; the kind is therefore
// decisive.
func programFailed(err error, executable string) bool {
	var execErr *exec.Error
	if errors.As(err, &execErr) {
		return execErr.Name == executable
	}
	var pathErr *fs.PathError
	if errors.As(err, &pathErr) {
		var errno syscall.Errno
		if errors.As(pathErr.Err, &errno) {
			return pathErr.Path == executable && programErrno(errno)
		}
	}
	return false
}

// folderMissing says the working folder is gone (e.g. a disconnected network drive). Go reports
// that as a failure to start the program, which must not mark Git as broken.
func folderMissing(cwd string) bool {
	if cwd == "" {
		return false
	}
	info, err := os.Stat(cwd)
	return err != nil || !info.IsDir()
}

// retryWithNext blocks the path if the error concerns the program, and says whether another
// candidate is available with which the call can be tried once more.
func retryWithNext(err error, executable, cwd string) bool {
	if folderMissing(cwd) || !programFailed(err, executable) {
		return false
	}
	markBroken(executable)
	other := FindGit()
	return other != "" && other != abs(executable)
}

// startFailed interprets an error when starting Git. If it concerns the program, the program
// counts as unusable. Other errors - working folder missing or not a folder, arguments too long,
// too many open files, out of memory - do not block Git: a missing folder counts as "Git is
// missing", as before, everything else is passed on unchanged.
func startFailed(err error, executable, cwd string) error {
	if folderMissing(cwd) {
		return Classify("", ClassifyOpts{Missing: true})
	}
	if programFailed(err, executable) {
		markBroken(executable)
		broken := executable
		if executable == "git" {
			broken = ""
		}
		return Classify("", ClassifyOpts{Missing: true, Broken: broken})
	}
	if errors.Is(err, fs.ErrNotExist) {
		return Classify("", ClassifyOpts{Missing: true})
	}
	return err
}

// Run runs git and returns the result including the exit code (no check of the code). Only "git
// is missing" and timeouts come as *Error.
func Run(ctx context.Context, cwd string, opts Opts, args ...string) (*Result, error) {
	if err := raiseIfAborted(ctx); err != nil {
		return nil, err
	}
	timeout := opts.Timeout
	if timeout == 0 {
		timeout = defaultTimeout
		if opts.Network {
			timeout = NetworkTimeout
		}
	}
	for attempt := 0; attempt < startAttempts; attempt++ {
		argv := command(args...)
		result, err := runTracked(ctx, argv, cwd, timeout, env(opts.Network, opts.Env), opts.Stdin)
		if err != nil {
			if aborted := raiseIfAborted(ctx); aborted != nil {
				return nil, aborted
			}
			if errors.Is(err, errTimedOut) {
				return nil, Classify("", ClassifyOpts{Timeout: true})
			}
			var start *startError
			if !errors.As(err, &start) {
				return nil, err
			}
			if attempt+1 < startAttempts && retryWithNext(start.err, argv[0], cwd) {
				continue
			}
			return nil, startFailed(start.err, argv[0], cwd)
		}
		started(argv[0])
		if aborted := raiseIfAborted(ctx); aborted != nil { // an ended Git reports nothing useful
			return nil, aborted
		}
		return result, nil
	}
	panic("unreachable")
}

// Git runs git and returns its output without whitespace at both ends. On errors the result is
// an *Error with the recognised kind and next step.
func Git(ctx context.Context, cwd string, args ...string) (string, error) {
	return With(ctx, cwd, Opts{}, args...)
}

// Lenient is Git, but an exit code other than 0 gives an empty text instead of an error.
func Lenient(ctx context.Context, cwd string, args ...string) (string, error) {
	return With(ctx, cwd, Opts{Lenient: true}, args...)
}

// With runs git with options (see Opts).
func With(ctx context.Context, cwd string, opts Opts, args ...string) (string, error) {
	proc, err := Run(ctx, cwd, opts, args...)
	if err != nil {
		return "", err
	}
	if proc.Code != 0 {
		if opts.Lenient {
			return "", nil
		}
		message := pytext.Strip(proc.Stderr)
		if message == "" {
			message = pytext.Strip(proc.Stdout)
		}
		if message == "" {
			message = SilentFailure(args, proc.Code)
		}
		return "", Classify(message, ClassifyOpts{URL: opts.URL, Cwd: cwd})
	}
	if opts.Keep {
		return proc.Stdout, nil
	}
	return pytext.Strip(proc.Stdout), nil
}

// SilentFailure describes a Git call that failed without any output, so that the message says
// which call it was: the subcommand, the option names and the exit code. Values and positional
// arguments (addresses, titles, paths) are left out: they may carry credentials.
func SilentFailure(args []string, code int) string {
	var shown []string
	for i, a := range args {
		switch {
		case i == 0 && !strings.HasPrefix(a, "-"):
			shown = append(shown, a)
		case a == "--":
			return fmt.Sprintf("git %s ended with exit code %d and no message", strings.Join(shown, " "), code)
		case strings.HasPrefix(a, "--"):
			name, _, _ := strings.Cut(a, "=")
			shown = append(shown, name)
		case strings.HasPrefix(a, "-"):
			shown = append(shown, a[:min(len(a), 2)]) // a short option may carry its value: -oValue
		}
	}
	return fmt.Sprintf("git %s ended with exit code %d and no message", strings.Join(shown, " "), code)
}

// Bytes is like Git, but returns the raw output (e.g. an archive).
func Bytes(ctx context.Context, cwd string, args ...string) ([]byte, error) {
	for attempt := 0; attempt < startAttempts; attempt++ {
		argv := command(args...)
		runCtx, cancel := context.WithTimeout(ctx, defaultTimeout)
		cmd := exec.CommandContext(runCtx, argv[0], argv[1:]...)
		cmd.Dir = cwd
		cmd.Env = env(false, nil)
		cmd.Cancel = func() error { return terminateTree(cmd) }
		cmd.WaitDelay = killDelay
		setProcAttr(cmd)
		var out, errOut bytes.Buffer
		cmd.Stdout, cmd.Stderr = &out, &errOut
		err := cmd.Start()
		if err != nil {
			cancel()
			if attempt+1 < startAttempts && retryWithNext(err, argv[0], cwd) {
				continue
			}
			return nil, startFailed(err, argv[0], cwd)
		}
		_ = cmd.Wait()
		timedOut := runCtx.Err() != nil
		cancel()
		started(argv[0])
		if timedOut {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			return nil, Classify("", ClassifyOpts{Timeout: true})
		}
		if cmd.ProcessState.ExitCode() != 0 {
			return nil, Classify(strings.TrimSpace(decode(errOut.Bytes())), ClassifyOpts{})
		}
		return out.Bytes(), nil
	}
	panic("unreachable")
}

// SplitRecord splits a line of sep-separated fields into exactly count fields. Git calls strip
// whitespace at the end of the output, and that includes the separator \x1f: if the last field
// of the last line is empty (e.g. the subject of a commit without text), it is missing from the
// line. Missing fields at the end count as empty.
func SplitRecord(line string, count int, sep string) []string {
	fields := strings.SplitN(line, sep, count)
	for len(fields) < count {
		fields = append(fields, "")
	}
	return fields
}

// SplitZ splits NUL-separated Git output (-z) into its entries. Only this way do paths with
// umlauts, quotation marks or tabs stay unchanged (without -z Git puts them in quotation marks
// and escapes special characters).
func SplitZ(out string) []string {
	var items []string
	for _, item := range strings.Split(out, "\x00") {
		if item != "" {
			items = append(items, item)
		}
	}
	return items
}

// resolve is the absolute path with symbolic links resolved as far as the path exists.
func resolve(path string) string {
	p := abs(path)
	rest := ""
	for {
		if real, err := filepath.EvalSymlinks(p); err == nil {
			return filepath.Join(real, rest)
		}
		parent := filepath.Dir(p)
		if parent == p {
			return abs(path)
		}
		rest = filepath.Join(filepath.Base(p), rest)
		p = parent
	}
}

// Resolve is the absolute path with symbolic links resolved as far as the path exists
// (Python's Path.resolve()).
func Resolve(path string) string { return resolve(path) }

// execCommand is a command that ends its whole process tree when the context is done.
func execCommand(ctx context.Context, argv []string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Cancel = func() error { return terminateTree(cmd) }
	cmd.WaitDelay = killDelay
	setProcAttr(cmd)
	return cmd
}
