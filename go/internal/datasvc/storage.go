package datasvc

import (
	"context"
	"os"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/signin"
)

// This file is Settings > Storage: the only place where the words of the storage kind (server,
// branch, merge request, token) appear.

// StorageSettings is everything the page shows.
type StorageSettings struct {
	Kind   string `json:"kind"`
	Folder string `json:"folder"`
	// Ready: the folder is a data repository.
	Ready bool `json:"ready"`
	// Server is the address without credentials, "" = none set up.
	Server string `json:"server"`
	// Special names a setup the app does not touch: "multi_url", "pushurl" or "name".
	Special   string `json:"special,omitempty"`
	HasSecret bool   `json:"hasSecret"` // the stored address contains a password (legacy)
	Branch    string `json:"branch"`
	// Share is "direct" or "merge_request" (a server that only takes merge requests).
	Share     string `json:"share"`
	AutoMerge bool   `json:"autoMerge"`
	// Host is the kind the person set ("" = automatic); DetectedHost what the address says.
	Host            string      `json:"host"`
	DetectedHost    string      `json:"detectedHost"`
	Hosts           []string    `json:"hosts"`
	Name            string      `json:"name"`  // user.name for saves
	Email           string      `json:"email"` // user.email for saves
	Helper          string      `json:"helper"`
	SuggestedHelper string      `json:"suggestedHelper"`
	Setup           []SetupItem `json:"setup"`
	Guide           SignInGuide `json:"guide"`
	Problem         *Problem    `json:"problem,omitempty"`
}

// SetupItem is one line of the setup checklist.
type SetupItem struct {
	Key    string `json:"key"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
	Page   string `json:"page,omitempty"`
}

// SignInGuide is how to get a token at the server of the address.
type SignInGuide struct {
	Kind     string `json:"kind"`
	Username string `json:"username"`
	Steps    string `json:"steps"`
}

// Storage reads the settings page. It changes nothing and needs no network.
func (s *Store) Storage() StorageSettings {
	dir := s.Folder()
	out := StorageSettings{Kind: "git", Folder: dir, Hosts: gitsync.Hosts, Setup: []SetupItem{}}
	ctx := s.ctx()
	root, err := gitsync.Root(ctx, dir)
	if err != nil {
		out.Problem = problemOf(err)
		for _, i := range signin.SetupItems(ctx, "") {
			out.Setup = append(out.Setup, SetupItem(i))
		}
		out.Guide = guide("")
		return out
	}
	out.Ready = true
	if info, err := gitsync.GetRemoteInfo(ctx, dir); err == nil {
		out.Server, out.Special, out.HasSecret, out.Branch = info.URL, info.Special, info.HasSecret, info.Branch
	}
	out.Share, _ = gitsync.ShareMode(ctx, root)
	out.AutoMerge, _ = gitsync.AutoMerge(ctx, root)
	out.Host, _ = gitsync.HostSetting(ctx, root)
	out.DetectedHost, _ = gitsync.DetectedHost(ctx, root)
	out.Name = config(root, "user.name")
	out.Email = config(root, "user.email")
	out.Helper = signin.HelperState(root)
	out.SuggestedHelper = signin.SuggestedHelper(ctx)
	for _, i := range signin.SetupItems(ctx, root) {
		out.Setup = append(out.Setup, SetupItem(i))
	}
	kind := out.Host
	if kind == "" {
		kind = out.DetectedHost
	}
	out.Guide = guide(kind)
	return out
}

func config(root, key string) string {
	ctx := context.Background()
	v, _ := git.Lenient(ctx, root, "config", "--get", key)
	return strings.TrimSpace(v)
}

func guide(kind string) SignInGuide {
	g := signin.GuideFor(kind)
	return SignInGuide{Kind: g.Kind, Username: g.Username, Steps: g.Steps}
}

// ServerCheck is the result of checking an address.
type ServerCheck struct {
	OK bool `json:"ok"`
	// Address is the address as it will be saved, without credentials.
	Address string `json:"address"`
	// Empty: the server is reachable and has nothing yet; BranchMissing: it has data, but not
	// under the branch of this folder (the first save creates it).
	Empty         bool     `json:"empty"`
	BranchMissing bool     `json:"branchMissing"`
	Heads         []string `json:"heads"`
	Problem       *Problem `json:"problem,omitempty"`
}

// CheckServer tests an address (format and connection) and writes nothing.
func (s *Store) CheckServer(address string, allowInsecure bool) ServerCheck {
	c, err := gitsync.CheckRemote(s.ctx(), s.Folder(), address, allowInsecure, 0)
	if err != nil {
		return ServerCheck{Heads: []string{}, Problem: problemOf(err)}
	}
	return ServerCheck{OK: true, Address: c.Address.URL, Empty: c.Empty(), BranchMissing: c.BranchMissing(),
		Heads: append([]string{}, c.Heads...)}
}

// ServerOptions are the confirmations the person gave for SaveServer.
type ServerOptions struct {
	AllowInsecure   bool `json:"allowInsecure"`
	AcceptNewBranch bool `json:"acceptNewBranch"`
	// AllowOffline saves the address although the server cannot be reached now.
	AllowOffline bool `json:"allowOffline"`
}

// ServerSaved is the result of SaveServer.
type ServerSaved struct {
	Address  string   `json:"address"`
	Verified bool     `json:"verified"`
	Problem  *Problem `json:"problem,omitempty"`
}

// SaveServer sets the address of the server after checking it again.
func (s *Store) SaveServer(address string, opts ServerOptions) ServerSaved {
	saved, err := gitsync.SetRemote(s.ctx(), s.Folder(), address, gitsync.SetRemoteOptions{
		AllowInsecure: opts.AllowInsecure, AcceptNewBranch: opts.AcceptNewBranch, AllowOffline: opts.AllowOffline})
	git.InvalidateStatus()
	if err != nil {
		return ServerSaved{Problem: problemOf(err)}
	}
	return ServerSaved{Address: saved.URL, Verified: saved.Verified}
}

// SetShare chooses how saves reach the server: "direct" or "merge_request".
func (s *Store) SetShare(mode string) *Problem {
	if mode != gitsync.ShareDirect && mode != gitsync.ShareMergeRequest {
		return &Problem{Kind: "error", Message: i18n.T("Unknown way to share: {mode}", "mode", mode)}
	}
	return s.setting(gitsync.SetShareMode, mode)
}

// SetHost sets the kind of server ("" = detect from the address).
func (s *Store) SetHost(kind string) *Problem {
	return s.setting(gitsync.SetHost, kind)
}

// SetAutoMerge turns "merge when the checks pass" on or off for merge requests.
func (s *Store) SetAutoMerge(enabled bool) *Problem {
	root, err := gitsync.Root(s.ctx(), s.Folder())
	if err == nil {
		err = gitsync.SetAutoMerge(s.ctx(), root, enabled)
	}
	git.InvalidateStatus()
	return problemOf(err)
}

func (s *Store) setting(set func(ctx context.Context, root, value string) error, value string) *Problem {
	root, err := gitsync.Root(s.ctx(), s.Folder())
	if err == nil {
		err = set(s.ctx(), root, value)
	}
	git.InvalidateStatus()
	return problemOf(err)
}

// SetIdentity stores the name and email address that saves are made with.
func (s *Store) SetIdentity(name, email string) *Problem {
	home, _ := os.UserHomeDir()
	return problemOf(gitsync.SetIdentity(s.ctx(), home, name, email))
}

// EnableHelper turns on the credential helper this computer offers (StorageSettings.SuggestedHelper).
func (s *Store) EnableHelper(name string) *Problem {
	return problemOf(signin.EnableHelper(s.ctx(), name))
}

// SignInGuide is how to get a token at a kind of server.
func (s *Store) SignInGuide(kind string) SignInGuide { return guide(kind) }

// SignIn hands a token to the credential helper of this computer and checks that the server takes
// it. The token is not kept, logged or returned; Git's helper stores it.
func (s *Store) SignIn(address, username, token string) *Problem {
	ctx := s.ctx()
	root, err := gitsync.Root(ctx, s.Folder())
	if err != nil {
		return problemOf(err)
	}
	if err := signin.StoreToken(ctx, root, address, username, token); err != nil {
		return problemOf(err)
	}
	if _, err := signin.Verify(ctx, root, address); err != nil {
		return problemOf(err)
	}
	git.InvalidateStatus()
	return nil
}

// ForgetSignIn removes the stored sign-in for the address from the credential helper.
func (s *Store) ForgetSignIn(address, username string) *Problem {
	root, err := gitsync.Root(s.ctx(), s.Folder())
	if err != nil {
		return problemOf(err)
	}
	return problemOf(signin.ForgetToken(s.ctx(), root, address, username, ""))
}

// Branch is a version line of the data (a Git branch).
type Branch struct {
	Name    string `json:"name"`
	Local   bool   `json:"local"`
	Remote  bool   `json:"remote"`
	Current bool   `json:"current"`
}

// Branches lists the branches, the current one first.
func (s *Store) Branches() ([]Branch, error) {
	list, err := gitsync.Branches(s.ctx(), s.Folder())
	if err != nil {
		return nil, err
	}
	out := make([]Branch, 0, len(list))
	for _, b := range list {
		out = append(out, Branch(b))
	}
	return out, nil
}

// SwitchBranch moves the data to another branch. Unsaved changes are saved on a rescue branch
// first by the caller's choice (see Reattach); a plain switch refuses with open changes.
func (s *Store) SwitchBranch(name string) Done {
	if _, err := gitsync.SwitchBranch(s.ctx(), s.Folder(), name); err != nil {
		return s.undone(err)
	}
	git.InvalidateStatus()
	return Done{Status: s.Status()}
}

// Reattached says where the data is now after Reattach.
type Reattached struct {
	Branch string `json:"branch"`
	// Rescue is the branch holding saved work, "" = nothing had to be saved.
	Rescue  string   `json:"rescue"`
	Commits bool     `json:"commits"`
	Changes bool     `json:"changes"`
	Problem *Problem `json:"problem,omitempty"`
}

// Reattach goes back to the main branch from a data state that is on no branch; work in it is
// kept on a rescue branch.
func (s *Store) Reattach() Reattached {
	r, err := gitsync.Reattach(s.ctx(), s.Folder())
	git.InvalidateStatus()
	if err != nil {
		return Reattached{Rescue: r.Rescue, Commits: r.Commits, Changes: r.Changes, Problem: problemOf(err)}
	}
	return Reattached{Branch: r.Branch, Rescue: r.Rescue, Commits: r.Commits, Changes: r.Changes}
}

// Opened is the result of OpenFolder, CreateFolder and CloneFrom.
type Opened struct {
	Folder  string   `json:"folder"`
	Problem *Problem `json:"problem,omitempty"`
}

// CloneFrom copies the data from a server address into a new local folder and uses it (D1).
func (s *Store) CloneFrom(address, folder string) Opened {
	if err := git.CloneRepository(s.ctx(), address, folder, 0); err != nil {
		return Opened{Problem: problemOf(err)}
	}
	s.SetFolder(folder)
	git.InvalidateStatus()
	return Opened{Folder: folder}
}

// CreateFolder starts a new, empty data repository in folder and uses it (D1).
func (s *Store) CreateFolder(folder string) Opened {
	data, err := git.InitDataRepository(s.ctx(), folder, true)
	if err != nil {
		return Opened{Problem: problemOf(err)}
	}
	s.SetFolder(data)
	git.InvalidateStatus()
	return Opened{Folder: data}
}

// OpenFolder uses an existing local data repository (D1).
func (s *Store) OpenFolder(folder string) Opened {
	if _, err := gitsync.Root(s.ctx(), folder); err != nil {
		return Opened{Problem: problemOf(err)}
	}
	s.SetFolder(folder)
	git.InvalidateStatus()
	return Opened{Folder: folder}
}
