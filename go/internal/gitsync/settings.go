package gitsync

import (
	"context"
	"crypto/sha1" //nolint:gosec // a short name for a branch, not security
	"encoding/hex"
	"regexp"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

var prURLRe = regexp.MustCompile(
	`https?://\S+/(?:pulls?/(?:\d+|new/\S+)|merge_requests/(?:\d+|new\b\S*)|compare/\S+)`)

// getSetting is a local Git setting of the data folder; the key from before the rename is the
// fallback.
func getSetting(ctx context.Context, root, key string) string {
	value, _ := git.Lenient(ctx, root, "config", "--local", "--get", key)
	if value != "" {
		return value
	}
	value, _ = git.Lenient(ctx, root, "config", "--local", "--get", legacyKeys[key])
	return value
}

// setSetting saves (or, with nil, removes) a local Git setting and drops the old spelling of it.
func setSetting(ctx context.Context, root, key string, value *string) error {
	_, _ = git.Lenient(ctx, root, "config", "--local", "--unset-all", legacyKeys[key])
	if value == nil {
		_, _ = git.Lenient(ctx, root, "config", "--local", "--unset-all", key)
		return nil
	}
	_, err := git.Git(ctx, root, "config", "--local", key, *value)
	return err
}

func strPtr(s string) *string { return &s }

// ShareMode is "direct" (default) or "merge_request": where "Save and share" uploads to.
func ShareMode(ctx context.Context, path string) (string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", err
	}
	return shareMode(ctx, root), nil
}

func shareMode(ctx context.Context, root string) string {
	if getSetting(ctx, root, ShareKey) == ShareMergeRequest {
		return ShareMergeRequest
	}
	return ShareDirect
}

// AutoMerge says whether the merge request merges automatically once the pipeline is green.
// Default: yes.
func AutoMerge(ctx context.Context, path string) (bool, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return false, err
	}
	return autoMerge(ctx, root), nil
}

func autoMerge(ctx context.Context, root string) bool {
	return getSetting(ctx, root, AutoMergeKey) != "false"
}

// SetAutoMerge turns auto-merge on or off.
func SetAutoMerge(ctx context.Context, path string, enabled bool) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	if enabled {
		return setSetting(ctx, root, AutoMergeKey, nil)
	}
	return setSetting(ctx, root, AutoMergeKey, strPtr("false"))
}

// SetShareMode sets where "Save and share" uploads to; anything but "merge_request" is direct.
func SetShareMode(ctx context.Context, path, mode string) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	if mode == ShareMergeRequest {
		return setSetting(ctx, root, ShareKey, strPtr(mode))
	}
	return setSetting(ctx, root, ShareKey, nil)
}

// DetectHost says which kind of server is behind the address, as far as the name reveals it
// (GitHub, GitLab, Forgejo/Gitea/Codeberg); everything else is generic.
func DetectHost(url string) string {
	name := "" // the host name
	if host, _, ok := webLocation(url); ok {
		name = strings.ToLower(host)
	}
	switch {
	case name == "github.com" || strings.HasPrefix(name, "github."):
		return HostGitHub
	case strings.Contains(name, "gitlab"):
		return HostGitLab
	case name == "codeberg.org" || strings.Contains(name, "forgejo") || strings.Contains(name, "gitea"):
		return HostForgejo
	}
	return HostGeneric
}

var (
	webURLRe = regexp.MustCompile(`^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$`)
	webSCPRe = regexp.MustCompile(`^(?:[^@/\s]+@)?([^/:\s]+):(.+?)(?:\.git)?/?$`)
)

// webLocation is the host name and the path without .git from a server address (https, ssh or
// scp form); ok is false for a folder path.
func webLocation(url string) (host, repo string, ok bool) {
	m := webURLRe.FindStringSubmatch(url)
	if m == nil {
		m = webSCPRe.FindStringSubmatch(url)
		// Python: (?!//) after the colon
		if m != nil && strings.HasPrefix(url[strings.Index(url, ":")+1:], "//") {
			m = nil
		}
	}
	if m == nil {
		return "", "", false
	}
	return m[1], m[2], true
}

// HostSetting is the explicitly chosen server kind ("" = detect automatically from the address).
func HostSetting(ctx context.Context, path string) (string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", err
	}
	return hostSetting(ctx, root), nil
}

func hostSetting(ctx context.Context, root string) string {
	value := getSetting(ctx, root, HostKey)
	if contains(Hosts, value) {
		return value
	}
	return ""
}

// SetHost chooses the server kind ("" or an unknown value: detect automatically).
func SetHost(ctx context.Context, path, host string) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	if contains(Hosts, host) {
		return setSetting(ctx, root, HostKey, strPtr(host))
	}
	return setSetting(ctx, root, HostKey, nil)
}

// HostKind is the kind of server: the chosen one or, as long as none is chosen, the detected one.
func HostKind(ctx context.Context, path string) (string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", err
	}
	return hostKind(ctx, root)
}

func hostKind(ctx context.Context, root string) (string, error) {
	if h := hostSetting(ctx, root); h != "" {
		return h, nil
	}
	return detectedHost(ctx, root)
}

// DetectedHost is the kind detected from the server's address, regardless of any choice.
func DetectedHost(ctx context.Context, path string) (string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", err
	}
	return detectedHost(ctx, root)
}

func detectedHost(ctx context.Context, root string) (string, error) {
	current, err := State(ctx, root)
	if err != nil {
		return "", err
	}
	remote := current.Remote
	if remote == "" {
		remote = "origin"
	}
	return DetectHost(git.RemoteURL(ctx, root, remote)), nil
}

// CompareURL is the web address where a pull request is opened from the branch on GitHub ("" if
// there is none).
func CompareURL(url, target, branch string) string {
	host, repo, ok := webLocation(url)
	if !ok || len([]rune(host)) == 1 { // drive letter like C:\x, not a host
		return ""
	}
	return "https://" + host + "/" + repo + "/compare/" + target + "..." + branch + "?expand=1"
}

var slugRe = regexp.MustCompile(`[^a-z0-9_-]+`)

// MergeRequestBranch is the branch this person uploads to for merge requests: a fixed name per
// person (sprintforecast/<name>-<short hash of the address>), so that another share updates the
// same merge request and two people with the same name prefix do not collide. The prefix is the
// one from before the rename, so that open merge requests keep working.
func MergeRequestBranch(ctx context.Context, root string) string {
	email, _ := git.Lenient(ctx, root, "config", "--get", "user.email")
	email = strings.ToLower(pytext.Strip(email))
	who, _, _ := strings.Cut(email, "@")
	if who == "" {
		who, _ = git.Lenient(ctx, root, "config", "--get", "user.name")
	}
	slug := strings.Trim(slugRe.ReplaceAllString(strings.ToLower(who), "-"), "-_")
	if slug == "" {
		slug = "user"
	}
	key := email
	if key == "" {
		key = who
	}
	sum := sha1.Sum([]byte(key)) //nolint:gosec // see import
	return "sprintforecast/" + slug + "-" + hex.EncodeToString(sum[:])[:6]
}

// pushMergeRequest uploads the state for review by others, depending on the server:
//
//   - GitLab (and unknown servers): to the own branch, with push options so that the server
//     creates or updates the merge request (and merges by itself on request).
//   - Forgejo/Gitea/Codeberg: AGit flow (refs/for/<target>), the pull request is created on push;
//     if that does not work, the branch stays.
//   - GitHub: the own branch; the app has no access token, it names the address where the pull
//     request can be opened.
//
// The branch belongs to this person: if it has diverged after a rebase in the merge request or a
// merged state, it is overwritten with --force-with-lease. Tags are not pushed (otherwise they
// would point to commits that never reach the main branch). It returns the branch and, if known,
// the address of the merge/pull request.
func pushMergeRequest(ctx context.Context, root string, current SyncState, title string) (branch, url string, err error) {
	branch = MergeRequestBranch(ctx, root)
	host, err := hostKind(ctx, root)
	if err != nil {
		return "", "", err
	}
	ref := "refs/heads/" + branch
	remote := current.Remote
	if remote == "" {
		remote = "origin"
	}
	_, target, _ := strings.Cut(current.Upstream, "/")
	if target == "" {
		target = current.Branch
	}
	if target == "" {
		target = "main"
	}
	subject := i18n.T("Changes")
	if lines := splitFirstLine(title); lines != "" {
		subject = lines
	}
	if host == HostForgejo {
		proc, err := git.Run(ctx, root, git.Opts{Network: true}, "push",
			"-o", "topic="+branch, "-o", "title="+subject, "-o", "force-push=true",
			remote, "HEAD:refs/for/"+target)
		if err != nil {
			return "", "", err
		}
		if proc.Code == 0 {
			if found := prURLRe.FindString(proc.Stderr + proc.Stdout); found != "" {
				return branch, strings.TrimRight(found, ".,)"), nil
			}
			return branch, "", nil
		}
	}
	listed, _ := git.With(ctx, root, git.Opts{Network: true, URL: current.URL, Lenient: true},
		"ls-remote", remote, ref)
	lease := "--force-with-lease=" + ref + ":"
	if f := strings.Fields(listed); len(f) > 0 {
		lease += f[0]
	}
	var options []string
	if host == HostGitLab || host == HostGeneric {
		options = []string{
			"-o", "merge_request.create",
			"-o", "merge_request.target=" + target,
			"-o", "merge_request.title=" + subject,
			"-o", "merge_request.remove_source_branch",
		}
		if autoMerge(ctx, root) {
			// Newer GitLab versions also know merge_request.auto_merge (same effect).
			options = append(options, "-o", "merge_request.merge_when_pipeline_succeeds")
		}
	}
	args := func(opts []string) []string {
		out := append([]string{"push", lease}, opts...)
		return append(out, remote, "HEAD:"+ref)
	}
	proc, err := git.Run(ctx, root, git.Opts{Network: true}, args(options)...)
	if err != nil {
		return "", "", err
	}
	message := outputMessage(proc)
	if proc.Code != 0 && len(options) > 0 && strings.Contains(message, "does not support push options") {
		if host == HostGitLab {
			return "", "", git.New(i18n.T("The server does not support push options, so sharing via "+
				"merge request is not possible. Please switch the setting off on the “Data folder” page."),
				"error", "")
		}
		// Not GitLab: only upload the branch, the pull request is opened on the server.
		if proc, err = git.Run(ctx, root, git.Opts{Network: true}, args(nil)...); err != nil {
			return "", "", err
		}
		options = nil
		message = outputMessage(proc)
	}
	if proc.Code != 0 {
		if message == "" {
			message = git.SilentFailure(args(options), proc.Code, proc.Signal)
		}
		return "", "", git.Classify(message, git.ClassifyOpts{URL: current.URL, Cwd: root})
	}
	if found := prURLRe.FindString(proc.Stderr + proc.Stdout); found != "" {
		return branch, strings.TrimRight(found, ".,)"), nil
	}
	if host == HostGitHub {
		return branch, CompareURL(current.URL, target, branch), nil
	}
	return branch, "", nil
}

func splitFirstLine(s string) string {
	lines := pytext.SplitLines(pytext.Strip(s), false)
	if len(lines) == 0 {
		return ""
	}
	return lines[0]
}

func outputMessage(proc *git.Result) string {
	if m := pytext.Strip(proc.Stderr); m != "" {
		return m
	}
	return pytext.Strip(proc.Stdout)
}

// push uploads the own commits (and tags); the first push connects the branch to the server.
func push(ctx context.Context, root string, current SyncState) error {
	opts := git.Opts{Network: true, URL: current.URL}
	if current.Upstream != "" {
		_, err := git.With(ctx, root, opts, "push", "--follow-tags")
		return err
	}
	remote, branch := current.Remote, current.Branch
	if remote == "" {
		remote = "origin"
	}
	if branch == "" {
		branch = "HEAD"
	}
	_, err := git.With(ctx, root, opts, "push", "--follow-tags", "-u", remote, branch)
	return err
}
