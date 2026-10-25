// Package signin is the sign-in to the Git server with an access token (https), guided by the
// app (port of signin.py).
//
// The app never stores the token itself: it hands it over once with "git credential approve" to
// Git's credential helper (Credential Manager, keychain, libsecret ...), writes it to no file and
// no log, and never shows it again. A plain-text store (credential.helper store) is neither set
// nor used for saving. The app does not create SSH keys.
package signin

import (
	"context"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

// plainText are the credential helpers for which "git credential approve" stores a secret in
// plain text. Anything unknown ("custom") is allowed (up to the computer), "store" never.
var plainText = map[string]bool{"store": true}

const (
	// HelperTimeout is more time than a credential helper needs (Windows starts it cold).
	HelperTimeout = 30 * time.Second
	// MaxTokenLength is the longest token accepted.
	MaxTokenLength = 4096
)

// HostGuide is how to create a token at a host; Username is the default for the field (empty =
// the person enters their own user name).
type HostGuide struct {
	Kind     string
	Username string
	Steps    string
}

// GuideFor is the guide per kind of server (gitsync.Host*); anything unknown gets the generic one.
func GuideFor(kind string) HostGuide {
	switch kind {
	case gitsync.HostGitLab:
		return HostGuide{kind, "oauth2", i18n.T("GitLab: in the project (or in your own settings) under " +
			"“Access tokens” create a token with the role “Developer” or higher and the permission " +
			"“write_repository”. Copy the token once.")}
	case gitsync.HostGitHub:
		return HostGuide{kind, "x-access-token", i18n.T("GitHub: under Settings › Developer settings › " +
			"Personal access tokens create a fine-grained token for this repository with the " +
			"permission “Contents: Read and write”. Copy the token once.")}
	case gitsync.HostForgejo:
		return HostGuide{kind, "", i18n.T("Forgejo/Gitea/Codeberg: under Settings › Applications create " +
			"an access token with the permission “write:repository”. The user name is your own " +
			"account name.")}
	}
	return HostGuide{kind, "", i18n.T("Create an access token with read and write permission on the " +
		"repository at the server. The user name it expects depends on the server: GitLab takes " +
		"“oauth2”, Forgejo and Gitea take your own account name.")}
}

// HTTPSParts are the host and path of an https address for the credential helper. Other
// addresses (SSH, folder, http) are not meant here: *git.Error.
func HTTPSParts(raw string) (host, path string, err error) {
	problem := git.New(i18n.T("Token sign-in applies only to https addresses without credentials in the address."),
		"", "")
	u, perr := url.Parse(raw)
	if perr != nil || !strings.EqualFold(u.Scheme, "https") || u.Hostname() == "" {
		return "", "", problem
	}
	if u.User != nil {
		pw, _ := u.User.Password()
		if u.User.Username() != "" || pw != "" {
			return "", "", problem
		}
	}
	if p := u.Port(); p != "" {
		if n, err := strconv.Atoi(p); err != nil || n > 65535 {
			return "", "", problem
		}
	}
	return u.Host, strings.TrimLeft(u.Path, "/"), nil
}

// IsHTTPS says whether the address is one that token sign-in applies to.
func IsHTTPS(raw string) bool {
	_, _, err := HTTPSParts(raw)
	return err == nil
}

// credentialInput is the input for "git credential": key=value lines, ending with an empty line.
func credentialInput(raw, username, token string) (string, error) {
	host, path, err := HTTPSParts(raw)
	if err != nil {
		return "", err
	}
	lines := []string{"protocol=https", "host=" + host}
	if path != "" {
		lines = append(lines, "path="+path)
	}
	if username != "" {
		lines = append(lines, "username="+username)
	}
	if token != "" {
		lines = append(lines, "password="+token)
	}
	return strings.Join(lines, "\n") + "\n\n", nil
}

func clean(value, what string) (string, error) {
	value = pytext.Strip(value)
	if value == "" || strings.ContainsAny(value, "\r\n\x00") {
		return "", git.New(i18n.T("Please enter {what} (without a line break).", "what", what), "", "")
	}
	return value, nil
}

// --- Credential helper ---------------------------------------------------------------------

// helperAvailable is helperExists; a variable so that tests can pretend a helper is installed.
var helperAvailable = helperExists

// helperExists says whether there is a git-credential-<name> on the PATH or in the folder of the
// Git programs.
func helperExists(ctx context.Context, name string) bool {
	command := "git-credential-" + name
	if _, err := exec.LookPath(command); err == nil {
		return true
	}
	home, _ := os.UserHomeDir()
	run, err := git.Run(ctx, home, git.Opts{Timeout: 10 * time.Second}, "--exec-path")
	if err != nil || run.Code != 0 {
		return false
	}
	folder := pytext.Strip(run.Stdout)
	if folder == "" {
		return false
	}
	for _, ext := range []string{"", ".exe", ".cmd"} {
		if _, err := os.Stat(filepath.Join(folder, command+ext)); err == nil {
			return true
		}
	}
	return false
}

// SuggestedHelper is the credential helper the app may offer for this computer ("" = none, then
// hints only). Windows: manager (Git Credential Manager), macOS: osxkeychain, Linux: libsecret or
// manager, if the helper is present. Never store.
func SuggestedHelper(ctx context.Context) string {
	var candidates []string
	switch runtime.GOOS {
	case "windows":
		candidates = []string{"manager", "wincred"}
	case "darwin":
		candidates = []string{"osxkeychain", "manager"}
	default:
		candidates = []string{"libsecret", "manager"}
	}
	for _, name := range candidates {
		if helperAvailable(ctx, name) {
			return name
		}
	}
	return ""
}

// EnableHelper registers the credential helper for the user (git config --global, never in the
// repository). Only the names from SuggestedHelper; store is excluded.
func EnableHelper(ctx context.Context, name string) error {
	if name == "" || name != SuggestedHelper(ctx) {
		return git.New(i18n.T("The app does not set up this credential helper."), "", "")
	}
	home, _ := os.UserHomeDir()
	_, err := git.Git(ctx, home, "config", "--global", "credential.helper", name)
	return err
}

// HelperState is "none" (no helper), "plain" (plain-text store) or "ok".
func HelperState(root string) string {
	names := git.CredentialHelpers(root)
	for _, name := range names {
		if plainText[name] {
			return "plain"
		}
	}
	if len(names) > 0 {
		return "ok"
	}
	return "none"
}

// --- Store, verify, delete the token -------------------------------------------------------

// StoreToken hands the token to the credential helper (git credential approve). If there is no
// helper or it is a plain-text store, nothing happens and a *git.Error comes back. The token
// appears in no message.
func StoreToken(ctx context.Context, root, rawURL, username, token string) error {
	username, err := clean(username, i18n.T("the user name"))
	if err != nil {
		return err
	}
	if token, err = clean(token, i18n.T("the token")); err != nil {
		return err
	}
	if len([]rune(token)) > MaxTokenLength {
		return git.New(i18n.T("The token is too long."), "", "")
	}
	switch HelperState(root) {
	case "plain":
		return git.New(i18n.T("Git stores sign-ins here in plain text (`credential.helper store`)."), "auth",
			i18n.T("The app does not use that for tokens. Please set up a credential helper "+
				"of the computer (see above) and remove `store`."))
	case "none":
		return git.New(i18n.T("No Git credential helper is configured on this computer yet."), "auth",
			i18n.T("Please switch on the credential helper first (see above)."))
	}
	input, err := credentialInput(rawURL, username, token)
	if err != nil {
		return err
	}
	run, err := git.Run(ctx, root, git.Opts{Timeout: HelperTimeout, Stdin: &input}, "credential", "approve")
	if err != nil {
		return err
	}
	if run.Code != 0 {
		// The helper's output may contain the token: only the return code counts.
		return git.New(i18n.T("The Git credential helper did not accept the token."), "auth",
			i18n.T("Check the credential helper and the permissions of the user account, then "+
				"try again."))
	}
	return nil
}

// Verify checks the sign-in with git ls-remote (changes nothing) and returns the branches.
// Errors (rejected, expired, wrong permission) come with a hint as *git.Error.
func Verify(ctx context.Context, root, rawURL string) ([]string, error) {
	address, err := git.ParseRemoteURL(rawURL, false)
	if err != nil {
		return nil, err
	}
	return git.ProbeRemote(ctx, root, address, git.ProbeTimeout, "")
}

// ForgetToken removes the stored sign-in from the credential helper (git credential reject).
// With username and token it hits exactly that entry; without both, all sign-ins of this server
// (most helpers ignore the path of the address).
func ForgetToken(ctx context.Context, root, rawURL, username, token string) error {
	var err error
	if username != "" {
		if username, err = clean(username, i18n.T("the user name")); err != nil {
			return err
		}
	}
	if token != "" {
		if token, err = clean(token, i18n.T("the token")); err != nil {
			return err
		}
	}
	input, err := credentialInput(rawURL, username, token)
	if err != nil {
		return err
	}
	run, err := git.Run(ctx, root, git.Opts{Timeout: HelperTimeout, Stdin: &input}, "credential", "reject")
	if err != nil {
		return err
	}
	if run.Code != 0 {
		return git.New(i18n.T("The Git credential helper did not delete the sign-in."), "", "")
	}
	return nil
}

// --- Setup checklist -----------------------------------------------------------------------

// SetupItem is one line of the setup checklist. Page is where it is done ("" = none).
type SetupItem struct {
	Key    string
	OK     bool
	Detail string
	Page   string
}

// SetupItems are the read-only checks for the checklist on the start page (no network, no
// prompts). root is the data folder or "".
func SetupItems(ctx context.Context, root string) []SetupItem {
	var items []SetupItem
	gitOK := git.Available()
	detail := i18n.T("Git is missing.")
	if gitOK {
		detail = i18n.T("Git is installed.")
	}
	items = append(items, SetupItem{"git", gitOK, detail, "help"})
	top := ""
	if gitOK && root != "" {
		top, _ = git.RepoRoot(ctx, root)
	}
	detail = i18n.T("The data folder is not a Git repository yet.")
	if top != "" {
		detail = i18n.T("The data folder is a Git repository.")
	}
	items = append(items, SetupItem{"folder", top != "", detail, "data_dir"})
	if top == "" {
		return items
	}
	info, err := gitsync.CachedRemoteInfo(ctx, top)
	if err != nil {
		return items
	}
	detail = i18n.T("No server is configured yet.")
	if info.Name != "" {
		detail = i18n.T("A server is configured.")
	}
	items = append(items, SetupItem{"server", info.Name != "", detail, "data_dir"})
	if info.Name != "" {
		ok := true
		detail = i18n.T("The address needs no token sign-in.")
		if IsHTTPS(info.URL) {
			ok = HelperState(top) == "ok"
			if ok {
				detail = i18n.T("A credential helper is configured.")
			} else {
				detail = i18n.T("Token sign-in for the server is still missing.")
			}
		}
		items = append(items, SetupItem{"login", ok, detail, "data_dir"})
	}
	name, _ := git.Lenient(ctx, top, "config", "--get", "user.name")
	email, _ := git.Lenient(ctx, top, "config", "--get", "user.email")
	detail = i18n.T("Name and email address for changes are missing.")
	if name != "" && email != "" {
		detail = i18n.T("Name and email address for changes are set.")
	}
	items = append(items, SetupItem{"identity", name != "" && email != "", detail, "data_dir"})
	return items
}
