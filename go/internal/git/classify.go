package git

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/i18n"
)

// The computer does not know the SSH server yet or its key has changed.
const hostKeyPattern = `Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED`

var hostKeyRe = regexp.MustCompile(`(?i)` + hostKeyPattern)

// The server answers, but the repository does not exist at this address (or it conceals it for
// lack of permission): GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, https 404.
var notFoundRe = regexp.MustCompile(`(?i)does not appear to be a git repository|` +
	`repository '[^']*' (not found|does not exist)|returned error: 404|Repository not found|` +
	`Project not found|remote: Not Found|project you were looking for could not be found|` +
	`repository does not exist|TF401019|does not exist or you do not have permission`)

// The computer does not accept the server's certificate (company certificate, self-issued): the
// server answers, so checking the internet or VPN is of no use.
var certificateRe = regexp.MustCompile(`(?i)SSL certificate problem|certificate verification failed|` +
	`SEC_E_UNTRUSTED_ROOT|SEC_E_CERT_|CRYPT_E_|no alternative certificate subject name`)

// Git could not write anything in its own file system. A whole line is required that starts
// with the operation and ends with the error ("error: unable to create file x: Permission
// denied"): "Permission denied" alone also appears in "ssh: connect to host ... Permission
// denied" (connection blocked), "Load key ...: Permission denied" and "remote: Permission
// denied" (server hook) and belongs to offline, auth or denied there. Messages from the server
// start with "remote:" and therefore do not match.
var notWritableRe = regexp.MustCompile(`(?im)^(?:error: |fatal: )?` +
	`(?:unable to (?:create|open|write)\b|could not (?:lock|create|write|open)\b|` +
	`cannot (?:lock|create|open|mkdir)\b|open\()` +
	`[^\n]*?:\s*(?:Permission denied|Read-only file system)\.?\s*$`)

// Detection patterns in the order they are checked (English Git messages, see env). What the
// server says about the repository (not found, certificate) comes before "offline": Git appends
// "Could not read from remote repository" to such messages and starts them with "unable to
// access".
const offlineRest = `Could not resolve host|Failed to connect|Connection (timed out|refused|reset)|` +
	`Network is unreachable|unable to access|Operation timed out|Temporary failure in ` +
	`name resolution|ssh: connect to host|Connection closed by`

var (
	offlineRe  = regexp.MustCompile(`(?i)` + offlineRest)
	bareReadRe = regexp.MustCompile(`(?i)Could not read from remote repository`)
)

type pattern struct {
	kind string
	re   *regexp.Regexp
}

func ci(expr string) *regexp.Regexp { return regexp.MustCompile(`(?i)` + expr) }

var patterns = []pattern{
	{"identity", ci(`tell me who you are|unable to auto-detect email|empty ident|auto-detection is disabled`)},
	{"unsafe_directory", ci(`detected dubious ownership`)},
	// Another program holds the file; Windows often reports this as "Permission denied".
	{"locked", ci(`unable to unlink|Device or resource busy|being used by another process`)},
	// No write permission in its own file system (see notWritableRe), not just any "Permission
	// denied": that also appears at SSH login, when connecting and in messages from the server.
	{"not_writable", notWritableRe},
	{"locked", ci(`index\.lock|\.lock'?: File exists|Unable to create '.*\.lock'`)},
	{"auth", ci(`Authentication failed|could not read Username|could not read Password|` +
		`terminal prompts disabled|Permission denied \(publickey|` +
		`Invalid username or password|The requested URL returned error: 40[13]|` +
		`HTTP Basic: Access denied|Support for password authentication was removed|` +
		hostKeyPattern)},
	{"not_found", notFoundRe},
	{"certificate", certificateRe},
	{"offline", offlineRe},
	{"denied", ci(`remote rejected|hook declined|protected branch|pre-receive hook|Permission to .* denied`)},
	{"rejected", ci(`\[rejected\]|non-fast-forward|failed to push some refs|fetch first|Updates were rejected`)},
	{"merge_in_progress", ci(`You have not concluded your merge|MERGE_HEAD exists|` +
		`Exiting because of an unresolved conflict|Pulling is not possible because you have unmerged`)},
	{"conflict", ci(`CONFLICT|Automatic merge failed|fix conflicts`)},
	{"dirty", ci(`would be overwritten by (merge|checkout|revert)|Please commit your changes or stash them`)},
	{"detached", ci(`You are not currently on a branch|detached HEAD`)},
	{"no_upstream", ci(`no tracking information|has no upstream branch|no upstream configured`)},
	{"no_remote", ci(`No configured push destination|No remote repository specified|No such remote`)},
}

func refusedHint() string {
	return i18n.T("The server did not fulfil the request. Please check the address (typo in the " +
		"project name?) and the permission. The message from Git is under “Technical " +
		"message”.")
}

// missingFolder says whether the server address is a complete folder path (including a network
// share) whose parent folder is missing on this computer? Then the drive is gone (not connected,
// VPN off, stick removed, share unreachable), and Git still reports "does not appear to be a git
// repository": that is "not reachable", not a wrong address. If the parent folder is there, the
// server answers and the repository really does not exist there (not found).
func missingFolder(url string) bool {
	if url == "" || strings.Contains(url, "://") {
		return false
	}
	if !filepath.IsAbs(url) {
		return false
	}
	_, err := os.Stat(filepath.Dir(url))
	return err != nil
}

// RemoteURL is the stored address of the server remote (empty if there is none): it belongs
// with the network calls, so that Classify can tell login help and folder-path servers apart.
func RemoteURL(ctx context.Context, root, remote string) string {
	out, _ := Lenient(ctx, root, "config", "--get", "remote."+remote+".url")
	return out
}

var (
	safeDirAdviceRe = regexp.MustCompile(`(?is)\s*To add an exception for this directory.*`)
)

// withoutSafeDirectoryAdvice: Git's message about a foreign folder ends with the advice to
// register it as safe with "git config --global --add safe.directory ...". The app never advises
// such a change (that is a matter for whoever looks after the computer), not even in the
// technical message or the command line, where someone would simply copy the command.
func withoutSafeDirectoryAdvice(message string) string {
	kept := safeDirAdviceRe.ReplaceAllString(message, "")
	var lines []string
	for _, line := range strings.Split(kept, "\n") {
		if !strings.Contains(line, "safe.directory") {
			lines = append(lines, line)
		}
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

// MissingHint is the next step when Git is missing: how it can be installed without
// administrator rights, that the app has to be reopened afterwards and where it searched (list).
// broken is the path of a Git that was found but could not be started.
func MissingHint(broken string) string {
	var places []string
	for _, place := range Locations() {
		places = append(places, "- "+MDCode(place))
	}
	var advice string
	if runtime.GOOS == "windows" {
		advice = i18n.T("If Git is somewhere else, add the folder containing `git.exe` to your own " +
			"user’s PATH – possible without administrator rights via “Edit environment " +
			"variables for your account”.")
	} else {
		advice = i18n.T("If Git is somewhere else, it is best to use an installation in your own home " +
			"folder (such as Homebrew or Nix) or add the folder containing `git` to your " +
			"PATH in the file `~/.profile`.")
	}
	var parts []string
	if broken != "" {
		parts = append(parts, i18n.T("Git was found at {path} but could not be started (damaged or incomplete "+
			"installation).", "path", MDCode(broken)))
	}
	parts = append(parts,
		i18n.T("Install Git (Windows: https://git-scm.com/download/win – possible without "+
			"administrator rights, for your own user account only; macOS: `xcode-select "+
			"--install`; Linux: package manager). Then close and reopen the app and the "+
			"“Foresprint” launcher, or sign out and back in once, so that they can "+
			"find Git."),
		i18n.T("Searched in PATH and in these places:\n{places}", "places", strings.Join(places, "\n")),
		advice,
	)
	return strings.Join(parts, "\n\n")
}

// ClassifyOpts are the options of Classify.
type ClassifyOpts struct {
	// Missing: Git could not be started.
	Missing bool
	// Timeout: the call took too long.
	Timeout bool
	// URL is the address of the server if the message comes from a network call: for a login
	// error it selects the matching help (SSH or https, see AuthHelp). If URL is a folder path
	// that currently does not exist (disconnected drive), "repository not found" counts as
	// "offline", except with NoDriveCheck set (checking a newly entered address: there a missing
	// folder is a typo).
	URL          string
	NoDriveCheck bool
	// Broken is the path of a Git that was found but could not be started.
	Broken string
	// Cwd is the folder in which Git was called.
	Cwd string
}

// Classify turns a Git error message into an *Error with kind and next step.
func Classify(message string, opts ClassifyOpts) *Error {
	if opts.Missing {
		return New(i18n.T("git is not installed or not in PATH"), "git_missing", MissingHint(opts.Broken))
	}
	if opts.Timeout {
		return New(i18n.T("The server does not answer in time."), "offline",
			i18n.T("Check the internet connection and VPN and try again later."))
	}
	for _, p := range patterns {
		if !p.re.MatchString(message) {
			continue
		}
		kind := p.kind
		if kind == "unsafe_directory" {
			message = withoutSafeDirectoryAdvice(message)
		}
		if kind == "not_found" && !opts.NoDriveCheck && missingFolder(opts.URL) {
			kind = "offline" // network drive disconnected, stick removed: not the address
		}
		var hint string
		if kind == "auth" {
			hint = AuthHelp(opts.URL, message, opts.Cwd)
		} else {
			hint = HintFor(kind)
		}
		text := message
		if text == "" {
			text = kind
		}
		return New(text, kind, hint).WithRaw(message != "")
	}
	if bareReadRe.MatchString(message) {
		// Git appends this even when the server refuses the repository; on its own it does not
		// prove a missing connection. All other patterns take precedence.
		return New(message, "error", refusedHint()).WithRaw(true)
	}
	text := message
	if text == "" {
		text = i18n.T("Unknown Git error")
	}
	return New(text, "error", "").WithRaw(message != "")
}

// TitleFor is a short heading for an error kind.
func TitleFor(kind string) string {
	titles := map[string]string{
		"git_missing":         "Git is not installed",
		"identity":            "Name and email address are missing",
		"locked":              "A file is locked",
		"not_writable":        "File or folder not writable",
		"unsafe_directory":    "Git considers the folder unsafe",
		"auth":                "Login is missing or was rejected",
		"offline":             "Server not reachable",
		"denied":              "Server refuses the upload",
		"rejected":            "Upload rejected because something new arrived in the meantime",
		"merge_in_progress":   "Merge is incomplete",
		"conflict":            "Conflict while merging",
		"invalid":             "Merged data is not valid",
		"dirty":               "Open changes outside the data folder",
		"detached":            "No branch selected (detached HEAD)",
		"no_upstream":         "Branch is not connected to the server",
		"no_remote":           "No server set up",
		"not_repo":            "No Git repository",
		"not_found":           "Repository not found",
		"unrelated_histories": "Server has a different history",
		"tag_exists":          "Tag name is already taken",
		"bad_url":             "Invalid address",
		"secret_in_url":       "Credentials do not belong in the address",
		"insecure_url":        "Unencrypted connection",
		"new_branch":          "Branch missing on the server",
		"remote_special":      "Unusual server setting",
		"certificate":         "Server certificate not accepted",
		"folder":              "Folder cannot be used",
		"nothing_to_share":    "Nothing to share yet",
		"sync_busy":           "Another sync is still running",
		"aborted":             "Sync aborted",
	}
	if title, ok := titles[kind]; ok {
		return i18n.T(title)
	}
	return i18n.T("Git error")
}

// HintFor is the next step in everyday language for an error kind (empty if there is none).
func HintFor(kind string) string {
	return HintForURL(kind, "")
}

// HintForURL is HintFor with the address of the server, which selects the login help for the
// kind "auth".
func HintForURL(kind, url string) string {
	if kind == "auth" {
		return AuthHelp(url, "", "")
	}
	switch kind {
	case "sync_busy":
		return i18n.T("A sync of this data folder has been running for a very long time and may be " +
			"stuck (e.g. because of a bad network connection). Wait, or abort the running " +
			"sync: your files stay saved locally.")
	case "aborted":
		return i18n.T("The sync was ended by hand. Your files are saved locally; please share again. " +
			"If Git then reports a locked file, follow the hint for it.")
	case "identity":
		return i18n.T("Git does not know your name yet. Please enter name and email address in the sidebar.")
	case "locked":
		return i18n.T("A file is locked because another program (Git client, editor, virus scanner, " +
			"sync service) is using it. Close other programs and try again. If it stays " +
			"that way, a lock file (index.lock in the .git folder) may have been left " +
			"behind after a crash: please ask whoever looks after the computer or the " +
			"repository before it is removed.")
	case "not_writable":
		return i18n.T("Git may not write here. Please check that your user account has write " +
			"permission in the data folder (including the hidden .git folder inside it), " +
			"that the folder is not write-protected and – for a network drive or cloud " +
			"folder – is connected and writable. If that does not help, ask whoever looks " +
			"after the computer.")
	case "unsafe_directory":
		return i18n.T("Git refuses to work in this folder because it belongs to a different user " +
			"account than the one the app runs under (a protection by Git, common with " +
			"network drives, copied folders or after an account change). The app changes " +
			"no Git settings. Please ask whoever looks after the computer: they can assign " +
			"the folder to your own account or deliberately mark it as safe.")
	case "certificate":
		return i18n.T("The server responds, but this computer does not accept its security " +
			"certificate (often a company certificate or a self-issued one). Please ask IT " +
			"to install the certificate on the computer. The app changes no Git settings.")
	case "offline":
		return i18n.T("The server is not reachable. Your changes stay safely stored locally; check " +
			"the internet connection or VPN and choose “Save and share” again later.")
	case "denied":
		return i18n.T("The server refused the upload, for example because of a protected branch or " +
			"missing write permission. Your changes are stored locally; please ask whoever " +
			"looks after the repository.")
	case "rejected":
		return i18n.T("Someone else has uploaded changes in the meantime. Choose “Save and share” " +
			"once more; they will be taken over first.")
	case "merge_in_progress":
		return i18n.T("A merge is incomplete. It can be aborted; your own changes are kept.")
	case "conflict":
		return i18n.T("Two people changed the same place. On the “Resolve conflicts” page choose " +
			"“my” or “other” change for each entry, or abort the merge. Nothing is lost.")
	case "invalid":
		return i18n.T("The merge was technically possible, but the data is now invalid in content " +
			"(see list). Nothing was uploaded. Please correct the values and choose “Save " +
			"and share” again – or deliberately “Share anyway”.")
	case "dirty":
		return i18n.T("There are unsaved changes outside the data folder that collide with the new " +
			"changes. Please commit or discard them first.")
	case "detached":
		return i18n.T("The repository is not on a branch (detached HEAD). Choose “Back to the " +
			"branch” in the sidebar; open changes are saved on a rescue branch first.")
	case "no_upstream":
		return i18n.T("The branch is not connected to the server yet. “Save and share” sets that up " +
			"the first time.")
	case "no_remote":
		return i18n.T("This data folder has no server yet. On the “Data folder” page, under “Server " +
			"(remote)”, enter the address of the shared data repository; until then all " +
			"changes stay on this computer. Anyone joining an existing team chooses “Clone " +
			"repository” there.")
	case "not_repo":
		return i18n.T("The data folder must be inside a Git repository: create a new one with `git " +
			"init` or fetch an existing one with `git clone`. An unpacked ZIP archive " +
			"(“Download source code” on GitHub or GitLab) is not a repository because it " +
			"lacks the hidden `.git` folder. For an existing team repository, choose " +
			"“Clone repository” on the “Data folder” page instead.")
	case "not_found":
		return i18n.T("The repository was not found or you have no access. Check address and " +
			"permission; the address can be changed on the “Data folder” page under " +
			"“Server (remote)”.")
	case "unrelated_histories":
		return i18n.T("The server contains a different history than this data folder – probably the " +
			"wrong repository is connected (e.g. a code repository). Nothing was merged " +
			"and nothing was uploaded; your changes are safe locally. If it is the wrong " +
			"repository, the address can be changed on the “Data folder” page under " +
			"“Server (remote)”. If the data repository on the server is the right one, " +
			"merging must be confirmed explicitly.")
	case "tag_exists":
		return i18n.T("Choose a different name or remove the existing tag first. The changes are " +
			"unchanged and not yet saved.")
	}
	return ""
}

// UnwritableFileHint is the next step when the app itself cannot write a file in the data folder
// (not Git, as with HintFor("locked")): the paragraph about the orphaned index.lock does not fit
// there. On Windows the file system says "Permission denied" both for a file held by another
// program and for a write-protected file; the hint names both.
func UnwritableFileHint() string {
	return i18n.T("The file could not be written. Either another program is using it right now " +
		"(editor, spreadsheet program, virus scanner, sync service; on Windows usually the " +
		"reason), or it is write-protected or your user account may not change it. Close " +
		"other programs, check the write protection and permissions, and choose “Save and " +
		"share” again: the interrupted merge is then continued and nothing is lost. If " +
		"that does not help, ask whoever looks after the computer.")
}

// AuthHelp is the login help matching the server address (https or SSH). The text starts right
// with the next step and does not repeat the cause: where the hint sits under the heading
// (TitleFor) ("Login is missing or was rejected"), that already names it; where there is none,
// Error.Full puts it first. If Git (message) reports an unknown or changed key of the server, no
// login instructions help, only the fingerprint does.
func AuthHelp(url, message, cwd string) string {
	if hostKeyRe.MatchString(message) {
		return i18n.T("This computer does not know this SSH server yet (or its key has changed). The " +
			"app cannot confirm this: please connect to the server once with an SSH or Git " +
			"program and confirm the fingerprint, or use the https address of the " +
			"repository. Then try again.")
	}
	if strings.HasPrefix(strings.ToLower(url), "ssh://") || scpFormRe.MatchString(url) {
		return i18n.T("This address uses login with an SSH key. To set it up, create a key " +
			"(`ssh-keygen -t ed25519`), register the public part (`.pub` file) with the " +
			"server (GitHub, GitLab …) under “SSH keys” and make the key available in the " +
			"ssh-agent without a passphrase prompt. Then try again.")
	}
	steps := i18n.T("With https the server usually needs an access token instead of the password " +
		"(GitHub: Settings › Developer settings › Personal access tokens; GitLab: access " +
		"token with the “write_repository” scope). If you use the GitHub CLI, set up the " +
		"login with `gh auth setup-git`; otherwise store the token in the computer's " +
		"credential service or enter it as the password in the next login window.")
	return steps + " " + CredentialAdvice(cwd) + " " + i18n.T("Then try again.")
}

// Credential services that Git ships or that are widespread; everything else is "custom". Only
// these names are evaluated, never the wording of the setting (may contain paths).
var safeHelpers = map[string]bool{
	"manager": true, "manager-core": true, "wincred": true, "osxkeychain": true,
	"libsecret": true, "gnome-keyring": true, "cache": true, "oauth": true,
}

// plainTextHelpers store the token unencrypted in ~/.git-credentials.
var plainTextHelpers = map[string]bool{"store": true}

var storeHelperRe = regexp.MustCompile(`(?:^|[/\\ ])(?:git-credential-)?store(?:\.exe|\.cmd)?(?:\s|$)`)

// CredentialHelpers returns the names of the credential services that Git has set up for this
// user (read only: git config, no change). An empty setting cancels the ones before it, as in Git
// itself. Names outside the known list appear as "custom". cwd is the folder in which Git asks
// (the data folder): that way an entry that exists only in its repository counts too. If Git
// cannot be started, the list is empty.
func CredentialHelpers(cwd string) []string {
	if cwd == "" {
		cwd, _ = os.Getwd()
	}
	proc, err := Run(context.Background(), cwd, Opts{Timeout: 10 * time.Second},
		"config", "--get-regexp", `^credential(\..+)?\.helper$`)
	if err != nil {
		return nil
	}
	var names []string
	for _, line := range splitLinesSimple(proc.Stdout) {
		key, value, _ := strings.Cut(line, " ")
		value = strings.TrimSpace(value)
		if value == "" {
			if key == "credential.helper" { // only the general entry cancels all
				names = nil
			}
			continue
		}
		if storeHelperRe.MatchString(value) { // also with path, extension or options
			names = append(names, "store")
			continue
		}
		first := "custom"
		if !strings.HasPrefix(value, "!") {
			first = strings.Fields(value)[0]
		}
		// A helper with a full path (.../git-credential-store.exe) is recognised by its name too.
		first = strings.ReplaceAll(first, `\`, "/")
		if i := strings.LastIndex(first, "/"); i >= 0 {
			first = first[i+1:]
		}
		first = strings.TrimPrefix(strings.TrimSuffix(strings.TrimSuffix(first, ".exe"), ".cmd"), "git-credential-")
		if safeHelpers[first] || plainTextHelpers[first] {
			names = append(names, first)
		} else {
			names = append(names, "custom")
		}
	}
	return names
}

// splitLinesSimple splits at line breaks like str.splitlines for command output.
func splitLinesSimple(s string) []string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	lines := strings.Split(s, "\n")
	if n := len(lines); n > 0 && lines[n-1] == "" {
		lines = lines[:n-1]
	}
	return lines
}

// CredentialAdvice is the concrete next step for https logins, matching this computer's
// operating system and the configured credential service. The app only reads and changes no Git
// setting; a plain-text store ("store") is never recommended.
func CredentialAdvice(cwd string) string {
	helpers := CredentialHelpers(cwd)
	for _, name := range helpers {
		if plainTextHelpers[name] {
			return i18n.T("Attention: Git stores logins here in plain text (`credential.helper store`, " +
				"file `.git-credentials` in the user folder). Better use the computer's " +
				"credential service; the app does not change this setting.")
		}
	}
	if len(helpers) > 0 {
		return i18n.T("A credential service is set up. If the login still fails, the stored token " +
			"has probably expired or been revoked: delete the old entry in the credential " +
			"service and enter the new token on the next attempt.")
	}
	prefix := i18n.T("No credential service is set up in the Git settings yet.")
	var step string
	switch runtime.GOOS {
	case "windows":
		step = i18n.T("Git for Windows ships the Git Credential Manager; `git config --global " +
			"credential.helper manager` in a terminal turns it on. On the next attempt, " +
			"enter the token as the password in the login window.")
	case "darwin":
		step = i18n.T("The Keychain is turned on with `git config --global credential.helper " +
			"osxkeychain` in a terminal (the helper belongs to Git from Xcode or " +
			"Homebrew). On the next attempt, enter the token as the password.")
	default:
		step = i18n.T("Either enter `git config --global credential.helper libsecret` in a terminal " +
			"(desktop keyring; the helper `git-credential-libsecret` comes with the " +
			"distribution's Git package) or use the GitHub CLI with `gh auth setup-git`. " +
			"Plain-text storage (`store`) is not a good choice.")
	}
	note := i18n.T("The app does not change any Git setting itself.")
	return prefix + " " + step + " " + note
}
