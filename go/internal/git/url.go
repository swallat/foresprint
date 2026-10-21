package git

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

// --- Checking the server address -----------------------------------------------------------

// MaxURLLength is the longest address that is accepted.
const MaxURLLength = 2048

// SafeProtocols are the transports that Git may use for addresses from the app (no ext::, fd:: or
// git://).
const SafeProtocols = "https:http:ssh:file"

// ProbeTimeout is the time limit of the connection check.
const ProbeTimeout = 30 * time.Second

// With http(s), Git aborts if hardly anything arrives for ten seconds (server accepts the
// connection but never answers).
var probeEnv = map[string]string{
	"GIT_ALLOW_PROTOCOL":       SafeProtocols,
	"GIT_HTTP_LOW_SPEED_LIMIT": "1000",
	"GIT_HTTP_LOW_SPEED_TIME":  "10",
}

// The connection check reads at most this much output (bytes) per stream.
const probeOutputLimit = 64 * 1024

const (
	hostExpr    = `(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[0-9A-Fa-f:.]+\])`
	sshUserExpr = `[A-Za-z0-9_][A-Za-z0-9._~-]*`
)

var (
	sshUserRe    = regexp.MustCompile(`^` + sshUserExpr + `$`)
	hostPortRe   = regexp.MustCompile(`^(` + hostExpr + `)(?::([^:]*))?$`)
	scpFormRe    = regexp.MustCompile(`^` + sshUserExpr + `@` + hostExpr + `:`)
	scpAddressRe = regexp.MustCompile(`^(` + sshUserExpr + `)@(` + hostExpr + `):(\S+)$`)
	scpSecretRe  = regexp.MustCompile(`^[^@/\\\s]*:[^@/\\\s]*@`)    // u:password@host:path
	helperRe     = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9+.-]*::`) // ext::, fd:: and other remote helpers
	urlSchemes   = map[string]bool{"https": true, "http": true, "ssh": true}
)

// Only these messages prove that the server is not reachable. "Could not read from remote
// repository" alone does not: Git also appends it when the server refuses the repository.
var unreachableRe = ci(`Could not resolve|Couldn't resolve|Name or service not known|No such host is known|` +
	`Failed to connect|Couldn't connect|Connection (was )?(timed out|refused|reset|closed)|` +
	`Network is (unreachable|down)|No route to host|timed out|Operation too slow|` +
	`Temporary failure in name resolution|ssh: connect to host|Connection closed by|` +
	`Empty reply from server|Recv failure|Send failure|Timeout was reached`)

// RemoteAddress is a checked server address. Kind is "https", "http", "ssh" (also the form
// user@host:path) or "local" (complete folder path).
type RemoteAddress struct {
	URL  string
	Kind string
}

// SecretInURLError is the error for an address with credentials or additions after ? or #
// (without repeating the input).
func SecretInURLError() *Error {
	return New(i18n.T("The address contains a user name, a password, a token or parameters "+
		"(everything from “?” or “#”). Please enter the plain address only, e.g. "+
		"https://server/team/data.git; the login service of the computer handles the "+
		"login, and if it is missing the app explains the next step (see Help, "+
		"“Login”)."), "secret_in_url", "")
}

// RemoteSpecialError is the error for a server with several addresses or its own upload address.
func RemoteSpecialError() *Error {
	return New(i18n.T("Several addresses or a separate upload address are set for this server. This "+
		"cannot be changed here – please clean it up with a Git program."), "remote_special", "")
}

// NewBranchDetail is what a "new_branch" error knows (Error.Detail).
type NewBranchDetail struct {
	Branch string
	Heads  []string
	Unborn bool
}

// NewBranchError is the error when the server has branches, but not the local one. The message
// is plain text; for the interface Error.Render with MDCode gives the names as code, because
// they come from the server or from the configuration. unborn: the data folder has no commit
// yet (joining a team is then the common reason).
func NewBranchError(branch string, heads []string, unborn bool) *Error {
	e := &Error{Kind: "new_branch", Detail: NewBranchDetail{branch, heads, unborn}}
	e.render = func(quote func(string) string) string {
		var names []string
		for _, h := range heads[:min(5, len(heads))] {
			names = append(names, quote(h))
		}
		list := strings.Join(names, ", ")
		if len(heads) > 5 {
			list += ", …"
		}
		var text string
		if unborn {
			text = i18n.T("This data folder has no saved data yet, but the server does (available: "+
				"{heads}). The first share would create a new branch “{branch}” there "+
				"without the data of the team arriving. Anyone joining an existing team "+
				"should choose “Clone repository” further down on this page instead.",
				"branch", quote(branch), "heads", list)
		} else {
			text = i18n.T("The server has no branch “{branch}” (available: {heads}). The first share "+
				"would create it there. That is only right if this really is the data "+
				"repository. Anyone joining an existing team should choose “Clone "+
				"repository” further down on this page instead.",
				"branch", quote(branch), "heads", list)
		}
		return Scrub(text)
	}
	e.msg = Scrub(e.render(identity))
	return e
}

// UnrelatedHistoriesError is the error when the server has a different history than the data
// folder. The message is plain text; for the interface Error.Render with MDCode gives address and
// branch as code, because they come from the server or from the configuration. url is the
// display form (PublicURL).
func UnrelatedHistoriesError(url, branch string) *Error {
	e := &Error{Kind: "unrelated_histories", hint: Scrub(HintFor("unrelated_histories"))}
	e.render = func(quote func(string) string) string {
		return i18n.T("The server ({url}, branch {branch}) contains a different history than this "+
			"data folder.", "url", quote(url), "branch", quote(branch))
	}
	e.msg = Scrub(e.render(identity))
	return e
}

// NothingToShareError is the error when "Save and share" is chosen although the data folder
// contains nothing saved yet (no commit): there would be nothing to upload.
func NothingToShareError() *Error {
	return New(i18n.T("The data folder holds no saved data yet, so there is nothing to share."),
		"nothing_to_share",
		i18n.T("Create data first (e.g. a team) and save it. Anyone joining an existing team "+
			"chooses “Clone repository” on the “Data folder” page."))
}

func badURL(message string) *Error { return New(message, "bad_url", "") }

// isCategoryC reports the Unicode categories Z-line, Z-paragraph and C (control, format,
// private use, surrogate, unassigned).
func isRejectedRune(r rune) bool {
	if (unicode.Is(unicode.Zs, r) && r != ' ') || unicode.Is(unicode.Zl, r) || unicode.Is(unicode.Zp, r) || unicode.Is(unicode.C, r) {
		return true
	}
	// Unassigned code points (category Cn) belong to no table.
	return !unicode.In(r, unicode.L, unicode.M, unicode.N, unicode.P, unicode.S, unicode.Z)
}

// parseURLForm reads an address of the form scheme://... (https, http, ssh); text has no control
// characters.
func parseURLForm(text, scheme, rest string, allowInsecure bool) (RemoteAddress, error) {
	if !urlSchemes[scheme] {
		return RemoteAddress{}, badURL(i18n.T("This protocol is not supported. Allowed are https://, ssh://, " +
			"git@server:path and complete folder paths."))
	}
	printable := true
	for i := 0; i < len(text); i++ {
		if text[i] < '!' || text[i] > '~' {
			printable = false
		}
	}
	if strings.Contains(text, `\`) || !printable {
		return RemoteAddress{}, badURL(i18n.T("It contains spaces or invalid characters."))
	}
	if strings.ContainsAny(rest, "?#") {
		return RemoteAddress{}, SecretInURLError()
	}
	authority, path, _ := strings.Cut(rest, "/")
	if strings.Contains(path, "@") { // also catches https://u:12/ss@host/x
		return RemoteAddress{}, SecretInURLError()
	}
	hostPort := authority
	if at := strings.LastIndex(authority, "@"); at >= 0 {
		user := authority[:at]
		hostPort = authority[at+1:]
		if scheme != "ssh" || strings.Contains(user, ":") { // always for http(s); for ssh the password part
			return RemoteAddress{}, SecretInURLError()
		}
		if !sshUserRe.MatchString(user) {
			return RemoteAddress{}, badURL(i18n.T("It contains spaces or invalid characters."))
		}
	}
	found := hostPortRe.FindStringSubmatchIndex(hostPort)
	if found == nil {
		return RemoteAddress{}, badURL(i18n.T("The server name is invalid."))
	}
	if found[4] >= 0 { // a port part is there
		port := hostPort[found[4]:found[5]]
		if n, err := strconv.Atoi(port); err != nil || !allDigits(port) || n <= 0 || n >= 65536 {
			return RemoteAddress{}, badURL(i18n.T("The port number is invalid."))
		}
	}
	if strings.Trim(path, "/") == "" {
		return RemoteAddress{}, badURL(i18n.T("The path to the repository is missing, e.g. …/team/sprint-data.git."))
	}
	if scheme == "http" && !allowInsecure {
		return RemoteAddress{}, New(i18n.T("The address starts with http:// – data and login would be sent "+
			"unencrypted. Better use https:// or explicitly confirm the unencrypted "+
			"connection."), "insecure_url", "")
	}
	return RemoteAddress{URL: scheme + "://" + rest, Kind: scheme}, nil
}

func allDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// ParseRemoteURL checks a server address before it is passed to Git. Allowed are https://,
// ssh://, user@host:path, complete local folder paths and (only with allowInsecure) http://.
// Everything else - git://, file://, relative paths, remote helpers (ext::), credentials in the
// address - is an *Error with a fixed text that never repeats the input.
func ParseRemoteURL(raw string, allowInsecure bool) (RemoteAddress, error) {
	text := pytext.Strip(raw)
	if text == "" {
		return RemoteAddress{}, badURL(i18n.T("Please enter an address."))
	}
	if utf8.RuneCountInString(text) > MaxURLLength {
		return RemoteAddress{}, badURL(i18n.T("It is too long."))
	}
	// Control characters, line separators and invisible characters (zero-width, bidi, BOM).
	for _, r := range text {
		if isRejectedRune(r) {
			return RemoteAddress{}, badURL(i18n.T("It contains line breaks or control characters."))
		}
	}
	if strings.HasPrefix(text, "-") { // Git would otherwise read the address as an option
		return RemoteAddress{}, badURL(i18n.T("It must not start with “-”."))
	}
	if helperRe.MatchString(text) {
		return RemoteAddress{}, badURL(i18n.T("Special transports (e.g. “ext::”) are not allowed."))
	}
	if m := schemeRe.FindStringSubmatchIndex(text); m != nil {
		return parseURLForm(text, strings.ToLower(text[m[2]:m[3]]), text[m[1]:], allowInsecure)
	}
	if filepath.IsAbs(text) { // the platform decides what "complete" is
		return RemoteAddress{URL: text, Kind: "local"}, nil
	}
	if scpSecretRe.MatchString(text) {
		return RemoteAddress{}, SecretInURLError()
	}
	if found := scpAddressRe.FindStringSubmatch(text); found != nil {
		if strings.HasPrefix(found[3], "-") {
			return RemoteAddress{}, badURL(i18n.T("It contains spaces or invalid characters."))
		}
		return RemoteAddress{URL: text, Kind: "ssh"}, nil
	}
	return RemoteAddress{}, badURL(i18n.T("The format is not recognised. Examples: https://server/team/data.git, " +
		"git@server:team/data.git or a complete folder path."))
}

// ProbeRun is the result of a connection check. TimedOut: the call took too long (the process
// tree has been ended then). Truncated: the output was longer than the limit.
type ProbeRun struct {
	Code      int
	TimedOut  bool
	Out       string
	Err       string
	Truncated bool
}

func readOutput(f *os.File) (text string, truncated bool) {
	_, _ = f.Seek(0, io.SeekStart)
	data, _ := io.ReadAll(io.LimitReader(f, probeOutputLimit+1))
	if len(data) > probeOutputLimit {
		return decode(data[:probeOutputLimit]), true
	}
	return decode(data), false
}

// RunProbe runs git for the connection check: exit code, output and error output (each at most
// 64 KB, see ProbeRun).
//
// Output goes through temporary files instead of pipes: on Windows a helper process of Git
// (git-remote-http) keeps the pipes open even long after the call has ended; reading to the end
// would then hang. On a timeout the whole tree is ended.
func RunProbe(ctx context.Context, root string, args []string, timeout time.Duration, envExtra map[string]string) (*ProbeRun, error) {
	out, err := os.CreateTemp("", "foresprint-out-*")
	if err != nil {
		return nil, err
	}
	defer func() { _ = out.Close(); _ = os.Remove(out.Name()) }()
	errFile, err := os.CreateTemp("", "foresprint-err-*")
	if err != nil {
		return nil, err
	}
	defer func() { _ = errFile.Close(); _ = os.Remove(errFile.Name()) }()
	merged := map[string]string{}
	for k, v := range probeEnv {
		merged[k] = v
	}
	for k, v := range envExtra {
		merged[k] = v
	}
	for attempt := 0; attempt < startAttempts; attempt++ {
		argv := command(args...)
		runCtx, cancel := context.WithTimeout(ctx, timeout)
		cmd := execCommand(runCtx, argv)
		cmd.Dir = root
		cmd.Env = env(true, merged)
		cmd.Stdout, cmd.Stderr = out, errFile
		if err := cmd.Start(); err != nil {
			cancel()
			if attempt+1 < startAttempts && retryWithNext(err, argv[0], root) {
				continue
			}
			return nil, startFailed(err, argv[0], root)
		}
		started(argv[0])
		_ = cmd.Wait()
		timedOut := runCtx.Err() != nil && ctx.Err() == nil
		cancel()
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		run := &ProbeRun{TimedOut: timedOut, Code: -1}
		if !timedOut && cmd.ProcessState != nil {
			run.Code = cmd.ProcessState.ExitCode()
		}
		run.Out, run.Truncated = readOutput(out)
		run.Err, _ = readOutput(errFile)
		return run, nil
	}
	panic("unreachable")
}

// headsOf returns branch names from the output of git ls-remote --heads. If the output is
// truncated, the last (incomplete) line is dropped.
func headsOf(run *ProbeRun) []string {
	lines := strings.Split(run.Out, "\n")
	if run.Truncated {
		lines = lines[:len(lines)-1]
	}
	const prefix = "refs/heads/"
	var heads []string
	for _, line := range lines {
		_, ref, _ := strings.Cut(line, "\t")
		if strings.HasPrefix(ref, prefix) {
			heads = append(heads, strings.TrimSpace(ref[len(prefix):]))
		}
	}
	return heads
}

// ProbeRemote asks the server for its branches (git ls-remote, changes nothing) and returns
// their names. An empty server is valid (empty list). Errors come as *Error with an
// understandable hint (see probeError).
//
// The list is not shortened as long as the output fits the limit (64 KB, around 900 branches).
// With more branches a second request asks specifically for branch: the name is in the list
// exactly when the server has it. Shortening for display is a matter for the interface.
func ProbeRemote(ctx context.Context, root string, address RemoteAddress, timeout time.Duration, branch string) ([]string, error) {
	if timeout == 0 {
		timeout = ProbeTimeout
	}
	run, err := RunProbe(ctx, root, []string{"ls-remote", "--heads", "--", address.URL}, timeout, nil)
	if err != nil {
		return nil, err
	}
	if run.Code != 0 {
		return nil, probeFailure(run, address, root)
	}
	heads := headsOf(run)
	if branch != "" && run.Truncated && !containsString(heads, branch) {
		wanted, err := RunProbe(ctx, root,
			[]string{"ls-remote", "--heads", "--", address.URL, "refs/heads/" + branch}, timeout, nil)
		if err != nil {
			return nil, err
		}
		if wanted.Code != 0 {
			return nil, probeFailure(wanted, address, root)
		}
		if containsString(headsOf(wanted), branch) { // the pattern also matches .../refs/heads/NAME
			heads = append(heads, branch)
		}
	}
	return heads, nil
}

func containsString(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func probeFailure(run *ProbeRun, address RemoteAddress, root string) *Error {
	message := strings.TrimSpace(run.Err)
	if message == "" {
		message = strings.TrimSpace(run.Out)
	}
	if r := []rune(message); len(r) > 4000 {
		message = string(r[:4000])
	}
	return probeError(message, address, run.TimedOut, root)
}

// probeError turns the error output of the connection check into an understandable error. Kind
// and hint for login, fingerprint, repository not found and certificate come from Classify, as
// with any other network call. What only the check knows is added here: only what proves a
// network error (unreachableRe) or the timeout counts as "server not reachable" ("offline"),
// because only then does the interface offer to save the address unchecked. "Could not read from
// remote repository" alone does not prove that (Git also appends it when the server refuses the
// repository). The text from Git stays in the message (appears as "Technical message"); there is
// always a hint.
func probeError(message string, address RemoteAddress, timedOut bool, cwd string) *Error {
	err := Classify(message, ClassifyOpts{Timeout: timedOut, URL: address.URL, NoDriveCheck: true, Cwd: cwd})
	switch {
	case timedOut:
		err.SetHint(unreachableHint())
	case err.Kind == "certificate":
		err.SetHint(err.Hint() + " " + i18n.T("The address is not saved this way."))
	case err.Kind == "offline" && unreachableRe.MatchString(message):
		err.SetHint(unreachableHint())
	case err.Kind == "offline": // network error without proven unreachability
		err.Kind = "error"
		err.SetHint(refusedHint())
	case err.Kind == "error" && bareReadRe.MatchString(message):
		// Classify already explained "Could not read from remote repository" without a reason
	case err.Kind != "auth" && err.Kind != "not_found" && err.Kind != "unsafe_directory" &&
		err.Kind != "not_writable" && err.Kind != "locked":
		err.SetHint(i18n.T("The connection to the server failed. Git’s message is under “Technical message”."))
	}
	return err
}

func unreachableHint() string {
	return i18n.T("The server cannot be reached at this address. Please check the address (typo?), " +
		"the internet connection and the VPN. A login window of the computer can delay the " +
		"process.")
}
