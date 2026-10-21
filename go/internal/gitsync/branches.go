package gitsync

import (
	"context"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
)

// RestoreFile restores a file to the last saved (committed) state.
func RestoreFile(ctx context.Context, path, file string) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	_, err = git.Git(ctx, root, "checkout", "HEAD", "--", git.Resolve(file))
	git.InvalidateStatus()
	return err
}

// AbortUnfinished aborts an unfinished merge (or rebase); own committed changes stay unchanged.
func AbortUnfinished(ctx context.Context, path string) error {
	root, err := Root(ctx, path)
	if err != nil {
		return err
	}
	current, err := State(ctx, path)
	if err != nil {
		return err
	}
	switch {
	case current.Unfinished == "merge" || (len(current.Conflicts) > 0 && current.Unfinished == ""):
		_, err = git.Git(ctx, root, "merge", "--abort")
	case current.Unfinished == "rebase":
		_, err = git.Git(ctx, root, "rebase", "--abort")
	}
	git.InvalidateStatus()
	return err
}

// Reattached is the result of Reattach: the branch the data folder is now on, and the rescue
// branch holding saved work ("" = nothing was saved). Commits: the commits of the detached state
// are there; Changes: the open changes in the data folder are there too (as a commit of their
// own).
type Reattached struct {
	Branch  string
	Rescue  string
	Commits bool
	Changes bool
}

func reattachHint(saved string) string {
	text := i18n.T("Switching back to the branch would overwrite open changes that lie outside the " +
		"data folder. The app only touches the data folder. The way out: save or discard " +
		"the changes in Git outside the data folder (Git client or terminal; ask whoever " +
		"looks after the computer if needed) and then choose “Back to the branch” again. " +
		"The files are named in the message from Git under “Technical message”.")
	if saved != "" {
		text = savedNote(saved) + " " + text
	}
	return text
}

// savedNote is the sentence naming the rescue branch that holds the changes in the data folder.
func savedNote(rescue string) string {
	return i18n.T("The open changes in the data folder are already saved on the rescue branch {rescue}.",
		"rescue", rescue)
}

const (
	saveSubject       = "Open changes saved before the switch"
	legacySaveSubject = "Offene Änderungen vor dem Wechsel gesichert" // commits of older versions
	rescuePrefix      = "rescue-"
	legacyRescue      = "rettung-" // older versions named the branches like this
)

func isSaveSubject(s string) bool { return s == saveSubject || s == legacySaveSubject }

func isRescue(name string) bool {
	return strings.HasPrefix(name, rescuePrefix) || strings.HasPrefix(name, legacyRescue)
}

func allRescue(names []string) bool {
	for _, n := range names {
		if !isRescue(n) {
			return false
		}
	}
	return true
}

func rescueName() string { return rescuePrefix + time.Now().Format("20060102-150405") }

// saveOpenChanges commits the open changes in the data folder on a rescue branch and returns its
// name. rescue is an existing rescue branch at this point ("" = create a new one). If committing
// fails (identity, spreadsheets, conflict markers ...), the repository is back in the detached
// state as before.
func saveOpenChanges(ctx context.Context, root, path, rescue string) (string, error) {
	start, err := git.Git(ctx, root, "rev-parse", "HEAD")
	if err != nil {
		return "", err
	}
	index, err := git.Git(ctx, root, "write-tree") // the user's staged state, for the rollback
	if err != nil {
		return "", err
	}
	name := rescue
	if name == "" {
		name = rescueName()
		_, err = git.Git(ctx, root, "switch", "-c", name)
	} else {
		_, err = git.Git(ctx, root, "switch", rescue)
	}
	if err != nil {
		return "", err
	}
	if _, err := git.CommitDirectory(ctx, path, saveSubject, nil); err != nil {
		// Restore the index exactly as before (git add changed it; the working tree stays
		// untouched) and go back to the detached state; HEAD never stays on the new rescue
		// branch.
		cctx := context.WithoutCancel(ctx) // the rollback must also run after a cancellation
		_, _ = git.Lenient(cctx, root, "read-tree", index)
		_, _ = git.Git(cctx, root, "switch", "--detach", start)
		if rescue == "" {
			_, _ = git.Git(cctx, root, "branch", "-D", name)
		}
		git.InvalidateStatus()
		return "", err
	}
	return name, nil
}

// savedBefore says whether HEAD is on the backup of an earlier attempt of Reattach (commit "Open
// changes saved before the switch", only on rescue branches). If so (known = true): were there
// commits on no branch before it (value true) or not (false)?
func savedBefore(ctx context.Context, root string, holders []string) (value, known bool) {
	if len(holders) == 0 || !allRescue(holders) {
		return false, false
	}
	subject := func(rev string) string {
		s, _ := git.Lenient(ctx, root, "log", "-1", "--format=%s", rev)
		return s
	}
	if !isSaveSubject(subject("HEAD")) {
		return false, false
	}
	// Go back through the whole chain of backups (several attempts): only the first other commit
	// shows whether the detached state had commits of its own.
	depth := 1
	for isSaveSubject(subject("HEAD~" + itoa(depth))) {
		depth++
	}
	parent, _ := git.Lenient(ctx, root, "branch", "--contains", "HEAD~"+itoa(depth),
		"--format=%(refname:short)")
	for _, b := range strings.Split(parent, "\n") {
		b = strings.TrimSpace(b)
		if b != "" && !strings.HasPrefix(b, "(") && !isRescue(b) {
			return false, true
		}
	}
	return true, true
}

// Reattach goes from "detached HEAD" back to the main branch. If commits are on no branch, they
// are saved on a rescue branch first, as are the open changes in the data folder (as a commit of
// their own there). If the switch fails because of changes outside the data folder, the rescue
// branch remains and is named again on the next attempt.
func Reattach(ctx context.Context, path string) (Reattached, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return Reattached{}, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return Reattached{}, err
	}
	if current.Branch != "" {
		return Reattached{}, git.New(i18n.T("The repository is already on a branch."), "", "")
	}
	def, _ := git.Lenient(ctx, root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
	var candidates []string
	if def != "" {
		parts := strings.SplitN(def, "/", 2)
		candidates = append(candidates, parts[len(parts)-1])
	}
	candidates = append(candidates, "main", "master")
	localOut, err := git.Git(ctx, root, "branch", "--format=%(refname:short)")
	if err != nil {
		return Reattached{}, err
	}
	local := strings.Fields(localOut)
	target := ""
	for _, c := range candidates {
		if contains(local, c) {
			target = c
			break
		}
	}
	if target == "" {
		return Reattached{}, git.New(i18n.T("No main branch found (main or master)."), "detached",
			i18n.T("Please use a Git client or a terminal."))
	}
	containing, _ := git.Lenient(ctx, root, "branch", "--contains", "HEAD", "--format=%(refname:short)")
	var holders []string
	for _, b := range strings.Split(containing, "\n") {
		if b != "" && !strings.HasPrefix(b, "(") {
			holders = append(holders, b)
		}
	}
	rescue := ""
	commits := false
	switch {
	case len(holders) == 0:
		commits = true
		rescue = rescueName()
	case allRescue(holders): // saved by an earlier attempt
		commits = true
		rescue = holders[0]
	}
	pending, err := git.ChangesIn(ctx, path)
	if err != nil {
		return Reattached{}, err
	}
	newChanges := len(pending) > 0
	earlier, known := savedBefore(ctx, root, holders) // backup from an earlier attempt
	if known {
		commits = earlier
	}
	savedAt := ""
	if newChanges {
		// Commit on the rescue branch (an existing one at this point, otherwise a new one).
		existing := ""
		if len(holders) > 0 {
			existing = rescue
		}
		if rescue, err = saveOpenChanges(ctx, root, path, existing); err != nil {
			return Reattached{}, err
		}
		if savedAt, err = git.Git(ctx, root, "rev-parse", "HEAD"); err != nil {
			return Reattached{}, err
		}
	} else if rescue != "" && len(holders) == 0 {
		if _, err := git.Git(ctx, root, "branch", rescue); err != nil {
			return Reattached{}, err
		}
	}
	changes := newChanges || known
	if _, err := git.Git(ctx, root, "switch", target); err != nil {
		if newChanges { // detached again on the backup: the next attempt finds it
			if _, derr := git.Git(context.WithoutCancel(ctx), root, "switch", "--detach", savedAt); derr != nil {
				return Reattached{}, derr
			}
		}
		git.InvalidateStatus()
		saved := ""
		if changes {
			saved = rescue
		}
		e := git.As(err)
		if e == nil {
			return Reattached{}, err
		}
		if e.Kind != "dirty" {
			if saved != "" { // do not hide where the changes were saved
				hint := savedNote(saved)
				if e.Hint() != "" {
					hint += " " + e.Hint()
				}
				e.SetHint(hint)
			}
			return Reattached{}, e
		}
		out := git.New(e.Error(), "detached", reattachHint(saved))
		out.Raw = e.Raw
		return Reattached{}, out
	}
	git.InvalidateStatus()
	return Reattached{target, rescue, commits, changes}, nil
}

// Branch is a branch that can be switched to: Local = exists in the data folder, Remote = the
// server has it too (a remote-only branch is created as a local one when switching).
type Branch struct {
	Name    string
	Local   bool
	Remote  bool
	Current bool
}

// Branches lists local and remote branches (as known since the last fetch), the current one
// first, then alphabetically.
func Branches(ctx context.Context, path string) ([]Branch, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return nil, err
	}
	current, err := State(ctx, path)
	if err != nil {
		return nil, err
	}
	out, err := git.Git(ctx, root, "branch", "--format=%(refname:short)")
	if err != nil {
		return nil, err
	}
	local := map[string]bool{}
	for _, n := range strings.Split(out, "\n") {
		if n != "" && !strings.HasPrefix(n, "(") { // "(HEAD detached at …)"
			local[n] = true
		}
	}
	remote := map[string]bool{}
	if current.Remote != "" {
		prefix := current.Remote + "/"
		refs, _ := git.Lenient(ctx, root, "branch", "-r", "--format=%(refname:short)")
		for _, r := range strings.Fields(refs) {
			if name, ok := strings.CutPrefix(r, prefix); ok && name != "HEAD" {
				remote[name] = true
			}
		}
	}
	names := map[string]bool{}
	for n := range local {
		names[n] = true
	}
	for n := range remote {
		names[n] = true
	}
	var found []Branch
	for n := range names {
		found = append(found, Branch{n, local[n], remote[n], n == current.Branch})
	}
	sort.Slice(found, func(i, j int) bool {
		if found[i].Current != found[j].Current {
			return found[i].Current
		}
		return found[i].Name < found[j].Name
	})
	return found, nil
}

// SwitchBranch switches the data folder to branch name (a remote-only one is created locally and
// follows the server). It refuses while the data folder has open changes: nothing is saved or
// discarded implicitly. It returns the name of the branch.
func SwitchBranch(ctx context.Context, path, name string) (string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", err
	}
	current, err := State(ctx, path)
	if err != nil {
		return "", err
	}
	if current.Unfinished != "" || len(current.Conflicts) > 0 {
		return "", git.New(git.HintFor("conflict"), "conflict", "")
	}
	pending, err := git.ChangesIn(ctx, path)
	if err != nil {
		return "", err
	}
	if len(pending) > 0 {
		return "", git.New(i18n.T("There are open changes. Commit or discard them before switching the branch."), "", "")
	}
	all, err := Branches(ctx, path)
	if err != nil {
		return "", err
	}
	var found *Branch
	for i := range all {
		if all[i].Name == name {
			found = &all[i]
		}
	}
	if found == nil {
		return "", git.New(i18n.T("Branch {name} not found.", "name", name), "", "")
	}
	err = locked(ctx, path, -1, func(ctx context.Context) error {
		var err error
		if found.Local {
			_, err = git.Git(ctx, root, "switch", name)
		} else { // explicit remote: git's guessing fails with several servers having the name
			_, err = git.Git(ctx, root, "switch", "-c", name, "--track", current.Remote+"/"+name)
		}
		return err
	})
	git.InvalidateStatus()
	if err != nil {
		return "", err
	}
	return name, nil
}

// SetIdentity stores name and email address for commits (global for the user).
func SetIdentity(ctx context.Context, home, name, email string) error {
	if pytext.Strip(name) == "" || !strings.Contains(email, "@") {
		return git.New(i18n.T("Please enter a name and a valid email address."), "", "")
	}
	if _, err := git.Git(ctx, home, "config", "--global", "user.name", pytext.Strip(name)); err != nil {
		return err
	}
	_, err := git.Git(ctx, home, "config", "--global", "user.email", pytext.Strip(email))
	return err
}
