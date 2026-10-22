package app

import (
	"errors"

	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/i18n"
)

// The area Data: changes of others, conflicts, history and Settings > Storage. The methods only
// pass on to datasvc (package comment there); the Git words stay in Settings > Storage.

// DataIncoming lists what others have changed and Refresh would take over.
func (a *API) DataIncoming() []datasvc.Change { return a.data.IncomingChanges() }

// CheckForChanges asks the server whether others changed something and returns the status.
func (a *API) CheckForChanges() Status { return statusOf(a.data.CheckForChanges()) }

// AbortSync stops the save or refresh that is running.
func (a *API) AbortSync() bool { return a.data.Abort() }

// Conflicts lists the values two people changed in different ways. Empty while no merge waits.
func (a *API) Conflicts() []datasvc.Conflict { return a.data.Conflicts() }

// ResolveConflicts applies the decisions; once every entry is decided, Save finishes the merge.
func (a *API) ResolveConflicts(decisions []datasvc.Decision) (Result, error) {
	return resultOf(a.data.ResolveConflicts(decisions), false), nil
}

// TakeTheirs decides every conflict for the value of the others ("discard mine").
func (a *API) TakeTheirs() (Result, error) { return resultOf(a.data.TakeTheirs(), false), nil }

// AbortMerge stops an unfinished merge and goes back to the own state.
func (a *API) AbortMerge() Status { return statusOf(a.data.AbortMerge()) }

// History lists who changed what and when, newest first. Scope is a team folder or file relative
// to the data folder, "" is everything.
func (a *API) History(scope string, limit int) ([]datasvc.Version, error) {
	return a.data.History(scope, limit)
}

// Restore brings the scope back to an earlier state, as unsaved changes.
func (a *API) Restore(scope, version, message string) datasvc.Done {
	return a.data.Restore(scope, version, message)
}

// Revert takes back one change of the history, as an unsaved change.
func (a *API) Revert(version string) datasvc.Done { return a.data.Revert(version) }

// Discard throws away the unsaved changes of the files (all when empty).
func (a *API) Discard(files []string) datasvc.Done { return a.data.Discard(nilIfEmpty(files)) }

// Lost lists the unsaved files and what Discard would lose of them.
func (a *API) Lost(files []string) ([]datasvc.LostFile, error) { return a.data.Lost(nilIfEmpty(files)) }

// UnsavedChanges lists what changed since the last save, value by value.
func (a *API) UnsavedChanges() ([]datasvc.UnsavedFile, error) { return a.data.UnsavedChanges() }

// DiscardValues puts single values back to what they were at the last save.
func (a *API) DiscardValues(items []datasvc.ValueRef) datasvc.Done {
	return a.data.DiscardValues(items)
}

// LineEndings checks whether the data files keep one kind of line ending on every computer.
func (a *API) LineEndings() datasvc.LineEndings { return a.data.LineEndings() }

// ApplyLineEndings writes the missing rules; the result is an unsaved change.
func (a *API) ApplyLineEndings() datasvc.LineEndings { return a.data.ApplyLineEndings() }

// Labels lists the named states (tags).
func (a *API) Labels(checkServer bool) ([]datasvc.Label, error) { return a.data.Labels(checkServer) }

// SetLabel names a state ("" = the current one).
func (a *API) SetLabel(name, version, message string) datasvc.Done {
	return a.data.SetLabel(name, version, message)
}

// ShareLabel uploads a label to the server.
func (a *API) ShareLabel(name string) datasvc.Done { return a.data.ShareLabel(name) }

// DeleteLabel removes a label here and, where it can, on the server.
func (a *API) DeleteLabel(name string) datasvc.Done { return a.data.DeleteLabel(name) }

// Storage reads Settings > Storage.
func (a *API) Storage() datasvc.StorageSettings { return a.data.Storage() }

// CheckServer tests an address and writes nothing.
func (a *API) CheckServer(address string, allowInsecure bool) datasvc.ServerCheck {
	return a.data.CheckServer(address, allowInsecure)
}

// SaveServer sets the address of the server.
func (a *API) SaveServer(address string, opts datasvc.ServerOptions) datasvc.ServerSaved {
	return a.data.SaveServer(address, opts)
}

// SetShare sets the way of sharing ("direct" or "merge_request").
func (a *API) SetShare(mode string) *datasvc.Problem { return a.data.SetShare(mode) }

// SetHost sets the kind of server ("" = detect from the address).
func (a *API) SetHost(kind string) *datasvc.Problem { return a.data.SetHost(kind) }

// SetAutoMerge sets whether the review is merged automatically where the server can.
func (a *API) SetAutoMerge(enabled bool) *datasvc.Problem { return a.data.SetAutoMerge(enabled) }

// SetIdentity sets the name and e-mail written into saves.
func (a *API) SetIdentity(name, email string) *datasvc.Problem {
	return a.data.SetIdentity(name, email)
}

// EnableHelper turns on a credential helper of the system.
func (a *API) EnableHelper(name string) *datasvc.Problem { return a.data.EnableHelper(name) }

// SignInGuide says how to get a token at the server of a kind.
func (a *API) SignInGuide(kind string) datasvc.SignInGuide { return a.data.SignInGuide(kind) }

// SignIn hands a token to the credential helper of the system; it is never stored by Foresprint.
func (a *API) SignIn(address, username, token string) *datasvc.Problem {
	return a.data.SignIn(address, username, token)
}

// ForgetSignIn removes the stored token from the credential helper.
func (a *API) ForgetSignIn(address, username string) *datasvc.Problem {
	return a.data.ForgetSignIn(address, username)
}

// Branches lists the branches of the data.
func (a *API) Branches() ([]datasvc.Branch, error) { return a.data.Branches() }

// SwitchBranch moves the data to another branch.
func (a *API) SwitchBranch(name string) datasvc.Done { return a.data.SwitchBranch(name) }

// Reattach goes back to the main branch from a state that is on no branch.
func (a *API) Reattach() datasvc.Reattached { return a.data.Reattach() }

// CloneFrom copies the data from a server address into a new folder and uses it.
func (a *API) CloneFrom(address, folder string) datasvc.Opened {
	if p := a.demoProblem(); p != nil {
		return datasvc.Opened{Problem: p}
	}
	return a.adopt(a.data.CloneFrom(address, folder))
}

// CreateFolder starts a new, empty data repository in a folder and uses it.
func (a *API) CreateFolder(folder string) datasvc.Opened {
	if p := a.demoProblem(); p != nil {
		return datasvc.Opened{Problem: p}
	}
	return a.adopt(a.data.CreateFolder(folder))
}

// OpenFolder uses an existing local data repository.
func (a *API) OpenFolder(folder string) datasvc.Opened {
	if p := a.demoProblem(); p != nil {
		return datasvc.Opened{Problem: p}
	}
	return a.adopt(a.data.OpenFolder(folder))
}

// PickFolder asks the user for a folder and only returns it ("" if cancelled).
func (a *API) PickFolder(title string) (string, error) {
	if a.ChooseFolder == nil {
		return "", errors.New(i18n.T("No folder dialog in this build."))
	}
	return a.ChooseFolder(title)
}

// nilIfEmpty turns the empty list the window sends for "all files" into the nil the core means by it.
func nilIfEmpty(files []string) []string {
	if len(files) == 0 {
		return nil
	}
	return files
}

// adopt remembers a folder the storage has just switched to as the data folder of the program.
func (a *API) adopt(o datasvc.Opened) datasvc.Opened {
	if o.Problem != nil || o.Folder == "" {
		return o
	}
	if err := a.SetDataDir(o.Folder); err != nil {
		a.data.SetFolder(a.DataDir()) // the storage must not point elsewhere than the window
		o.Problem = &datasvc.Problem{Kind: "error", Message: err.Error()}
	}
	return o
}
