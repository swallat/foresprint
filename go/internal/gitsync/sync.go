package gitsync

import (
	"context"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
)

// SyncOptions are the choices of Sync.
type SyncOptions struct {
	// Message is the commit message (and the title of a merge request).
	Message string
	// Tags are created on the commit and uploaded with it.
	Tags []string
	// Today is the day the data check runs for (zero: now).
	Today time.Time
	// AllowInvalid uploads even if the merge produced new data errors.
	AllowInvalid bool
	// AllowUnrelated merges a foreign history without a common origin (explicit confirmation).
	AllowUnrelated bool
	// PullOnly ("Pull from server"): upload nothing, validate nothing.
	PullOnly bool
}

// pushUpload is the plain upload; a variable so that tests can let someone else upload in between.
var pushUpload = push

func refExists(ctx context.Context, root, ref string) bool {
	out, _ := git.Lenient(ctx, root, "rev-parse", "--verify", "--quiet", ref)
	return out != ""
}

func gitOK(ctx context.Context, root string, args ...string) (bool, error) {
	run, err := git.Run(ctx, root, git.Opts{}, args...)
	if err != nil {
		return false, err
	}
	return run.Code == 0, nil
}

// unrelated says whether the own state and upstream lack a common origin. It distinguishes "no
// common ancestor" (exit code 1) from real errors (which are returned) and from a shallow clone
// whose truncated history only looks that way: there the full history is fetched first. Without
// an own commit there is nothing that could get mixed up.
func unrelated(ctx context.Context, root, remote, upstream string) (bool, error) {
	if !refExists(ctx, root, "HEAD") {
		return false, nil
	}
	for attempt := 0; attempt < 2; attempt++ {
		run, err := git.Run(ctx, root, git.Opts{}, "merge-base", "HEAD", upstream)
		if err != nil {
			return false, err
		}
		if run.Code == 0 && strings.TrimSpace(run.Stdout) != "" {
			return false, nil
		}
		if run.Code != 0 && run.Code != 1 {
			msg := strings.TrimSpace(run.Stderr)
			if msg == "" {
				msg = strings.TrimSpace(run.Stdout)
			}
			if msg == "" {
				msg = git.SilentFailure([]string{"merge-base"}, run.Code, run.Signal)
			}
			return false, git.Classify(msg, git.ClassifyOpts{})
		}
		shallow, _ := git.Lenient(ctx, root, "rev-parse", "--is-shallow-repository")
		if attempt == 0 && shallow == "true" && remote != "" {
			if _, err := git.With(ctx, root,
				git.Opts{Network: true, URL: git.RemoteURL(ctx, root, remote)},
				"fetch", "--unshallow", "--prune", remote); err != nil {
				return false, err
			}
			continue
		}
		break
	}
	return true, nil
}

func unrelatedError(current SyncState, target string) *git.Error {
	url := git.PublicURL(current.URL)
	if url == "" {
		url = current.Remote
	}
	if url == "" {
		url = "?"
	}
	branch := target
	if i := strings.Index(target, "/"); i >= 0 {
		branch = target[i+1:]
	}
	return git.UnrelatedHistoriesError(url, branch)
}

// mergeUpstream brings in the server state. On conflicts the merge stays open, everything that
// can be resolved automatically is done; the conflicts for the human are returned (empty =
// done). The own changes are already committed. Unrelated histories are only merged with
// allowUnrelated (the caller has checked them beforehand).
func mergeUpstream(ctx context.Context, root, upstream, path string, allowUnrelated bool) ([]ConflictFile, error) {
	args := []string{"merge", "--no-edit"}
	if allowUnrelated {
		args = append(args, "--allow-unrelated-histories")
	}
	_, err := git.Git(ctx, root, append(args, upstream)...)
	if err == nil {
		return nil, nil
	}
	e := git.As(err)
	if e == nil || (e.Kind != "conflict" && e.Kind != "error") {
		return nil, err
	}
	gdir, gerr := GitDir(ctx, root)
	if gerr != nil {
		return nil, gerr
	}
	if !exists(gdir + "/MERGE_HEAD") {
		return nil, err
	}
	remaining, err := ResolveConflicts(ctx, path, nil)
	if err != nil {
		return nil, err
	}
	if len(remaining) == 0 {
		if err := git.RefuseStagedConflictMarkers(ctx, root); err != nil {
			return nil, err
		}
		if _, err := git.Git(ctx, root, "commit", "--no-edit"); err != nil {
			return nil, err
		}
	}
	return remaining, nil
}

func conflictError() *git.Error {
	return git.New(i18n.T("Merge: conflicts are waiting for your decision."), "conflict", git.HintFor("conflict"))
}

func unfinishedError() *git.Error {
	return git.New(i18n.T("An earlier operation has not been completed."), "merge_in_progress",
		git.HintFor("merge_in_progress"))
}

func unpushedMerges(ctx context.Context, root string, current SyncState) (bool, error) {
	// Without a counterpart (never uploaded or removed from the server) there is nothing to compare.
	if current.Upstream == "" || !refExists(ctx, root, "refs/remotes/"+current.Upstream) {
		return false, nil
	}
	count, err := git.Git(ctx, root, "rev-list", "--merges", "--count", current.Upstream+"..HEAD")
	if err != nil {
		return false, err
	}
	return count != "" && count != "0" && isDigits(count), nil
}

func isDigits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return s != ""
}

// Sync is "Save and share": commit own changes, fetch and merge those of others, validate,
// upload. Expected errors (offline, rejected, login, conflict ...) are in the result's Error;
// whatever succeeded up to then (e.g. the own commit) is kept. On conflicts the merge stays
// open (Conflicts); after the decision (ResolveConflicts) a new call resumes. After a merge the
// full validation runs: new errors prevent the upload, unless AllowInvalid is set. If the server
// has a foreign history without a common origin (usually the wrong repository), it aborts before
// merging with the error kind unrelated_histories; only with AllowUnrelated (explicit
// confirmation) is it merged anyway, after which the usual conflict handling applies. Tags are
// checked before the commit: if a name is invalid or already taken locally, it aborts without
// committing; missing tags are also created without a new commit. If the data folder still has
// no commit after saving (freshly created, no files), there is nothing to share: error kind
// nothing_to_share. With PullOnly the process ends after the merge: own changes are saved and
// the server state is taken over, but nothing is uploaded or validated.
//
// It never runs at the same time as a fetch. Errors that are no *git.Error (a cancelled
// context) are returned as err.
func Sync(ctx context.Context, path string, opts SyncOptions) (*SyncResult, error) {
	var result *SyncResult
	err := locked(ctx, path, -1, func(ctx context.Context) error {
		var err error
		result, err = syncLocked(ctx, path, opts)
		return err
	})
	if err != nil {
		if e := git.As(err); e != nil && e.Kind == "sync_busy" {
			return &SyncResult{Error: e}, nil
		}
		return result, err
	}
	return result, nil
}

func syncLocked(ctx context.Context, path string, opts SyncOptions) (*SyncResult, error) {
	result := &SyncResult{PullOnly: opts.PullOnly}
	defer git.InvalidateStatus()
	err := runSync(ctx, path, opts, result)
	if err != nil {
		e := git.As(err)
		if e == nil {
			return result, err
		}
		result.Error = e
	}
	return result, nil
}

func runSync(ctx context.Context, path string, opts SyncOptions, result *SyncResult) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	current, err := State(ctx, path)
	if err != nil {
		return err
	}
	if current.Unfinished == "rebase" {
		return unfinishedError()
	}
	if current.Detached() {
		return git.New(i18n.T("No branch selected."), "detached", git.HintFor("detached"))
	}
	// 0. Resumption: finish an open merge first.
	switch {
	case current.Unfinished == "merge":
		if result.Conflicts, err = ResolveConflicts(ctx, path, nil); err != nil {
			return err
		}
		if len(result.Conflicts) > 0 {
			return conflictError()
		}
		if err := git.RefuseStagedConflictMarkers(ctx, root); err != nil {
			return err
		}
		if _, err := git.Git(ctx, root, "commit", "--no-edit"); err != nil {
			return err
		}
		result.Merged = true
	case len(current.Conflicts) > 0:
		return unfinishedError()
	}
	// 1. Secure own changes: first as a commit, then nothing is in danger anymore.
	pending, err := git.PendingChanges(ctx, path)
	if err != nil {
		return err
	}
	if len(pending) > 0 {
		if result.Committed, err = git.CommitDirectory(ctx, path, opts.Message, opts.Tags); err != nil {
			return err
		}
	} else if len(opts.Tags) > 0 {
		_, elsewhere, err := git.EnsureTags(ctx, root, opts.Tags, opts.Message)
		if err != nil {
			return err
		}
		for _, tag := range elsewhere {
			result.Notes = append(result.Notes, i18n.T("The tag {tag} points to a different commit "+
				"than the current version and was not moved.", "tag", tag))
		}
	}
	if current, err = State(ctx, path); err != nil {
		return err
	}
	if current.Remote == "" {
		return git.New(i18n.T("No server set up."), "no_remote", git.HintFor("no_remote"))
	}
	if !refExists(ctx, root, "HEAD") {
		// Fresh repository without own data: there is nothing to upload, and a branch without a
		// commit can neither be connected to the server nor pushed (Git would otherwise report
		// "failed to push some refs", which looks like a race).
		return git.NothingToShareError()
	}
	mode := shareMode(ctx, root)
	// 2. Fetch server state, 3. merge, 4. validate, 5. upload (retry on a race).
	for attempt := 0; attempt < MaxAttempts; attempt++ {
		if current, err = fetchLocked(ctx, path); err != nil {
			return err
		}
		if current.FetchError != nil {
			return current.FetchError
		}
		isUnrelated := false
		if target := serverBranch(ctx, root, current); target != "" {
			if isUnrelated, err = unrelated(ctx, root, current.Remote, target); err != nil {
				return err
			}
			if isUnrelated && !opts.AllowUnrelated {
				return unrelatedError(current, target)
			}
		}
		if current.Upstream == "" && current.Branch != "" {
			if current, err = adoptRemoteBranch(ctx, root, current); err != nil {
				return err
			}
		}
		commits, files, err := Incoming(ctx, path, 0)
		if err != nil {
			return err
		}
		for _, c := range commits {
			if !containsCommit(result.Pulled, c) {
				result.Pulled = append(result.Pulled, c)
			}
		}
		for _, f := range files {
			if !containsFile(result.PulledFiles, f) {
				result.PulledFiles = append(result.PulledFiles, f)
			}
		}
		if current.Upstream != "" && current.Behind > 0 {
			if result.Conflicts, err = mergeUpstream(ctx, root, current.Upstream, path, isUnrelated); err != nil {
				return err
			}
			if len(result.Conflicts) > 0 {
				return conflictError()
			}
			result.Merged = true
			if current, err = State(ctx, path); err != nil {
				return err
			}
		}
		if opts.PullOnly {
			if mode == ShareMergeRequest {
				notes, err := openMergeRequestNote(ctx, root, current)
				if err != nil {
					return err
				}
				result.Notes = append(result.Notes, notes...)
			}
			break
		}
		if !opts.AllowInvalid {
			unpushed, err := unpushedMerges(ctx, root, current)
			if err != nil {
				return err
			}
			if unpushed {
				baseline := current.Upstream
				if baseline == "" {
					baseline = "HEAD"
				}
				found, err := NewErrors(ctx, path, baseline, opts.Today)
				if err != nil {
					return err
				}
				if len(found) > 0 {
					result.Validation = found
					return git.New(i18n.T("The merged data is not valid."), "invalid", git.HintFor("invalid"))
				}
			}
		}
		viaMR := mode == ShareMergeRequest
		if viaMR && current.Upstream != "" && current.Ahead > 0 {
			// e.g. after "squash" in the merge
			if current, err = dropMergedCommits(ctx, root, current); err != nil {
				return err
			}
		}
		if viaMR && len(opts.Tags) > 0 {
			result.Notes = append(result.Notes, i18n.T("Tags are not uploaded with merge requests; "+
				"share them in the “Tags” section after the merge."))
		}
		if viaMR && current.Upstream != "" && current.Ahead == 0 {
			break // nothing of our own that would need a merge request
		}
		if viaMR {
			result.MergeRequestBranch, result.MergeRequestURL, err = pushMergeRequest(ctx, root, current, opts.Message)
		} else {
			err = pushUpload(ctx, root, current)
		}
		if err != nil {
			if e := git.As(err); e != nil && e.Kind == "rejected" && !viaMR && attempt+1 < MaxAttempts {
				continue
			}
			return err
		}
		result.Pushed = true
		notes, err := tagNotes(ctx, root, current, opts.Tags)
		if err != nil {
			return err
		}
		result.Notes = append(result.Notes, notes...)
		break
	}
	return nil
}

func containsCommit(list []Commit, c Commit) bool {
	for _, x := range list {
		if x == c {
			return true
		}
	}
	return false
}

func containsFile(list []FileChange, f FileChange) bool {
	for _, x := range list {
		if x == f {
			return true
		}
	}
	return false
}

// serverBranch is the server state for the current branch (e.g. origin/main), if there is one:
// the connected upstream or, before the first connection, the branch of the same name.
func serverBranch(ctx context.Context, root string, current SyncState) string {
	candidate := current.Upstream
	if candidate == "" && current.Remote != "" && current.Branch != "" {
		candidate = current.Remote + "/" + current.Branch
	}
	if candidate != "" && refExists(ctx, root, "refs/remotes/"+candidate) {
		return candidate
	}
	return ""
}

// adoptRemoteBranch connects the branch to the server if it already has it but this computer
// has not yet connected it (e.g. a repository started separately). Afterwards the server state is
// merged as usual.
func adoptRemoteBranch(ctx context.Context, root string, current SyncState) (SyncState, error) {
	candidate := current.Remote + "/" + current.Branch
	if current.Remote != "" && refExists(ctx, root, "refs/remotes/"+candidate) {
		if _, err := git.Git(ctx, root, "branch", "--set-upstream-to="+candidate); err != nil {
			return current, err
		}
		return State(ctx, root)
	}
	return current, nil
}

// tagNotes are notes on tags that push --follow-tags did not publish: the name is already used
// on the server for a different state (two people tagged the same sprint); the tag stays
// unchanged there, locally it points to the own state.
func tagNotes(ctx context.Context, root string, current SyncState, tags []string) ([]string, error) {
	var notes []string
	if len(tags) == 0 || current.Remote == "" {
		return notes, nil
	}
	head, _ := git.Lenient(ctx, root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
	for _, tag := range tags {
		local, err := git.TagCommit(ctx, root, tag)
		if err != nil {
			return nil, err
		}
		if local == "" {
			continue
		}
		if local != head {
			ancestor, err := gitOK(ctx, root, "merge-base", "--is-ancestor", local, "HEAD")
			if err != nil {
				return nil, err
			}
			if !ancestor {
				notes = append(notes, i18n.T("The tag {tag} points to a different commit that is not "+
					"part of the current version; it was not moved.", "tag", tag))
				continue
			}
		}
		out, err := git.With(ctx, root, git.Opts{Network: true, URL: current.URL},
			"ls-remote", "--tags", current.Remote, "refs/tags/"+tag, "refs/tags/"+tag+"^{}")
		if err != nil {
			if git.As(err) != nil && git.KindOf(err) != "aborted" {
				continue // without an answer from the server nothing can be said
			}
			return nil, err
		}
		refs := map[string]string{}
		for _, line := range strings.Split(out, "\n") {
			sha, ref, _ := strings.Cut(line, "\t")
			refs[ref] = sha
		}
		remote := refs["refs/tags/"+tag+"^{}"]
		if remote == "" {
			remote = refs["refs/tags/"+tag]
		}
		switch {
		case remote != "" && remote != local:
			notes = append(notes, i18n.T("The tag {tag} is already used on the server for a different "+
				"version and was not overwritten. On this computer it points to your own version.",
				"tag", tag))
		case remote == "":
			notes = append(notes, i18n.T("The tag {tag} could not be transferred to the server.", "tag", tag))
		}
	}
	return notes, nil
}

// dropMergedCommits resets the branch to the server state if the own state has the same content
// as the server (the merge request is merged, e.g. as a "squash" with a new commit): otherwise it
// would stay "ahead" forever and every share would create an empty merge request. --keep aborts
// where something would be lost.
func dropMergedCommits(ctx context.Context, root string, current SyncState) (SyncState, error) {
	upstream := current.Upstream
	if upstream == "" {
		upstream = "HEAD"
	}
	same, err := gitOK(ctx, root, "diff", "--quiet", upstream, "HEAD", "--")
	if err != nil {
		return current, err
	}
	if same {
		if same, err = gitOK(ctx, root, "diff", "--quiet", "--cached"); err != nil {
			return current, err
		}
	}
	if !same {
		return current, nil
	}
	if _, err := git.Lenient(ctx, root, "reset", "--keep", upstream); err != nil {
		return current, err
	}
	return State(ctx, root)
}

// openMergeRequestNote is the note for "Pull from server" in merge request mode: if own changes
// are not yet in the main branch, it says whether they are in an open merge request (the own
// branch is on the server and contains the state) or have not been shared at all. Content that is
// already in the main branch (merged, e.g. as a "squash") does not count.
func openMergeRequestNote(ctx context.Context, root string, current SyncState) ([]string, error) {
	var err error
	if current.Upstream != "" && current.Ahead > 0 {
		if current, err = dropMergedCommits(ctx, root, current); err != nil {
			return nil, err
		}
	}
	if current.Upstream == "" || current.Ahead == 0 {
		return nil, nil
	}
	_, branch, _ := strings.Cut(current.Upstream, "/")
	if branch == "" {
		branch = "main"
	}
	remote := current.Remote
	if remote == "" {
		remote = "origin"
	}
	mrRef := "refs/remotes/" + remote + "/" + MergeRequestBranch(ctx, root)
	if refExists(ctx, root, mrRef) {
		ancestor, err := gitOK(ctx, root, "merge-base", "--is-ancestor", "HEAD", mrRef)
		if err != nil {
			return nil, err
		}
		if ancestor {
			return []string{i18n.T("Your merge request is still open: your changes are not in {branch} "+
				"on the server yet. Pull again after the merge.", "branch", branch)}, nil
		}
	}
	host, err := hostKind(ctx, root)
	if err != nil {
		return nil, err
	}
	if host == HostForgejo {
		// The pull request is not on a branch of its own that could be seen here.
		return []string{i18n.T("Your changes are not in {branch} on the server yet. If they are in an "+
			"open pull request, fetch them again after the merge.", "branch", branch)}, nil
	}
	return []string{i18n.T("Your changes are not shared yet (not in {branch}, no merge request on the "+
		"server). “Save and share” creates it.", "branch", branch)}, nil
}
