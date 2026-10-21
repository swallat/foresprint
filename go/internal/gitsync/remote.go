package gitsync

import (
	"context"
	"regexp"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
)

// remoteNameRe is the valid name of a server (remote); only then is it touched.
var remoteNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// RemoteInfo is the server set up for a data folder (determined locally, without network).
//
// URL is the display version (without credentials), HasSecret says that the stored address
// contains some. Others are further servers, which are never changed. Special names settings the
// app does not touch: "multi_url" (several addresses), "pushurl" (own upload address) or "name"
// (unusual name). Branch is the local branch ("" = detached HEAD), Unborn says that there is no
// commit yet (a freshly created repository).
type RemoteInfo struct {
	Root      string
	Name      string
	URL       string
	HasSecret bool
	Others    []string
	Special   string
	Branch    string
	Unborn    bool
}

type cachedInfo struct {
	at   time.Time
	info RemoteInfo
}

// GetRemoteInfo is the server of the data folder including special cases (see RemoteInfo).
func GetRemoteInfo(ctx context.Context, path string) (RemoteInfo, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return RemoteInfo{}, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return RemoteInfo{}, err
	}
	name := current.Remote
	remotes, _ := git.Lenient(ctx, root, "remote")
	var urls []string
	special := ""
	if name != "" {
		if !remoteNameRe.MatchString(name) {
			special = "name"
		} else {
			out, _ := git.Lenient(ctx, root, "config", "--get-all", "remote."+name+".url")
			urls = splitLines(out)
			if len(urls) > 1 {
				special = "multi_url"
			} else if push, _ := git.Lenient(ctx, root, "config", "--get-all", "remote."+name+".pushurl"); push != "" {
				special = "pushurl"
			}
		}
	}
	if len(urls) == 0 {
		urls = []string{current.URL}
	}
	secret := false
	for _, u := range urls {
		if git.HasCredentials(u) {
			secret = true
		}
	}
	info := RemoteInfo{Root: root, Name: name, HasSecret: secret, Special: special,
		Branch: current.Branch, Unborn: current.Unborn}
	if name != "" {
		info.URL = git.PublicURL(current.URL)
	}
	for _, r := range strings.Fields(remotes) {
		if r != name {
			info.Others = append(info.Others, r)
		}
	}
	return info, nil
}

func splitLines(s string) []string {
	if s == "" {
		return nil
	}
	return strings.Split(s, "\n")
}

// CachedRemoteInfo is like GetRemoteInfo, but cached briefly (for the UI, which redraws on every
// input); invalidated by git.InvalidateStatus.
func CachedRemoteInfo(ctx context.Context, path string) (RemoteInfo, error) {
	key := git.Resolve(path)
	mu.Lock()
	cached, ok := infoCache[key]
	mu.Unlock()
	if ok && time.Since(cached.at) < stateTTL {
		return cached.info, nil
	}
	info, err := GetRemoteInfo(ctx, path)
	if err != nil {
		return RemoteInfo{}, err
	}
	mu.Lock()
	infoCache[key] = cachedInfo{time.Now(), info}
	mu.Unlock()
	return info, nil
}

// RemoteCheck is the result of the connection check: checked address, branches of the server
// (all that fit the query limit, see git.ProbeRemote; truncated only when displayed) and local
// branch ("" = detached HEAD). Unborn: the data folder has no commit yet.
type RemoteCheck struct {
	Address git.RemoteAddress
	Heads   []string
	Branch  string
	Unborn  bool
}

// Empty says the server is reachable but has no branch yet.
func (c RemoteCheck) Empty() bool { return len(c.Heads) == 0 }

// BranchMissing says the server has branches, but not the local one: the first upload creates it.
func (c RemoteCheck) BranchMissing() bool {
	return len(c.Heads) > 0 && c.Branch != "" && !contains(c.Heads, c.Branch)
}

// CheckRemote checks a server address (format and connection, git ls-remote) and writes nothing.
// A zero timeout means git.ProbeTimeout.
func CheckRemote(ctx context.Context, path, raw string, allowInsecure bool, timeout time.Duration) (RemoteCheck, error) {
	if timeout == 0 {
		timeout = git.ProbeTimeout
	}
	root, err := Root(ctx, path)
	if err != nil {
		return RemoteCheck{}, err
	}
	address, err := git.ParseRemoteURL(raw, allowInsecure)
	if err != nil {
		return RemoteCheck{}, err
	}
	info, err := GetRemoteInfo(ctx, root)
	if err != nil {
		return RemoteCheck{}, err
	}
	heads, err := git.ProbeRemote(ctx, root, address, timeout, info.Branch)
	if err != nil {
		return RemoteCheck{}, err
	}
	return RemoteCheck{address, heads, info.Branch, info.Unborn}, nil
}

// RemoteSaved is the result of SetRemote: name of the server, display version of the address and
// whether the connection could be checked (false = explicitly saved unchecked).
type RemoteSaved struct {
	Name     string
	URL      string
	Verified bool
}

// SetRemoteOptions are the explicit confirmations of SetRemote.
type SetRemoteOptions struct {
	AllowInsecure bool
	// AcceptNewBranch: the server has branches, but not the local one.
	AcceptNewBranch bool
	// AllowOffline: save even though the server is unreachable.
	AllowOffline bool
	Timeout      time.Duration
}

// SetRemote sets the address of the server (name as before, otherwise "origin"), after a renewed
// check in the backend, since the UI is not considered trustworthy. It is saved only after a
// passed check; two exceptions apply only with explicit confirmation: AllowOffline (server
// unreachable) and AcceptNewBranch (the server has branches, but not the local one). On login
// problems, repository not found and other errors nothing is ever saved. Blocked are an open
// merge, several addresses, an own upload address and an unusual server name; nothing is cleaned
// up. No fetch, no credentials, nothing global.
func SetRemote(ctx context.Context, path, raw string, opts SetRemoteOptions) (RemoteSaved, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return RemoteSaved{}, err
	}
	address, err := git.ParseRemoteURL(raw, opts.AllowInsecure)
	if err != nil {
		return RemoteSaved{}, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return RemoteSaved{}, err
	}
	if current.Unfinished != "" {
		return RemoteSaved{}, git.New(i18n.T("The server cannot be changed while a merge is open."),
			"merge_in_progress", git.HintFor("merge_in_progress"))
	}
	info, err := GetRemoteInfo(ctx, root)
	if err != nil {
		return RemoteSaved{}, err
	}
	if info.Special != "" {
		return RemoteSaved{}, git.RemoteSpecialError()
	}
	verified := true
	check, err := CheckRemote(ctx, root, address.URL, opts.AllowInsecure, opts.Timeout)
	if err != nil {
		if e := git.As(err); e == nil || e.Kind != "offline" || !opts.AllowOffline {
			return RemoteSaved{}, err
		}
		verified = false
	} else if check.BranchMissing() && !opts.AcceptNewBranch {
		return RemoteSaved{}, git.NewBranchError(check.Branch, check.Heads, check.Unborn)
	}
	name := info.Name
	if name == "" {
		name = "origin"
	}
	if info.Name == "" {
		_, err = git.Git(ctx, root, "remote", "add", "--", name, address.URL)
	} else {
		_, err = git.Git(ctx, root, "remote", "set-url", name, "--", address.URL)
	}
	mu.Lock()
	delete(fetched, root) // the state of the old server no longer applies
	mu.Unlock()
	git.InvalidateStatus()
	if err != nil {
		return RemoteSaved{}, err
	}
	return RemoteSaved{name, git.PublicURL(address.URL), verified}, nil
}
