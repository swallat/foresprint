package datasvc

// Backend is the storage behind the window: the operations of the storage interface
// (docs/redesign/storage-interface.md). Git is the first backend; a shared folder is the second.
// Store passes every call on to the backend (today always Git; the folder backend adds a Kind switch in backend()), so the window and the API do not
// change with the storage.
//
// Operations that only exist for Git (branches, labels, server settings, sign-in) stay on Store
// and belong to Settings > Storage.
type Backend interface {
	Status() Status
	CheckForChanges() Status
	StartBackgroundCheck() bool
	IncomingChanges() []Change
	Save(opts SaveOptions) Result
	Refresh() Result
	Conflicts() []Conflict
	ResolveConflicts(decisions []Decision) Result
	TakeTheirs() Result
	AbortMerge() Status
	History(scope string, limit int) ([]Version, error)
	Restore(scope, version, message string) Done
	Revert(version string) Done
	Discard(files []string) Done
	Capabilities() Capabilities
	UnsavedChanges() ([]UnsavedFile, error)
	Abort() bool
}

// Storage kinds.
const (
	KindGit    = "git"
	KindFolder = "folder"
)

// gitBackend is the Git storage: the methods of Store that start with "git".
type gitBackend struct{ s *Store }

func (g gitBackend) Status() Status                       { return g.s.gitStatus() }
func (g gitBackend) CheckForChanges() Status              { return g.s.gitCheckForChanges() }
func (g gitBackend) StartBackgroundCheck() bool           { return g.s.gitStartBackgroundCheck() }
func (g gitBackend) IncomingChanges() []Change            { return g.s.gitIncomingChanges() }
func (g gitBackend) Save(o SaveOptions) Result            { return g.s.gitSave(o) }
func (g gitBackend) Refresh() Result                      { return g.s.gitRefresh() }
func (g gitBackend) Conflicts() []Conflict                { return g.s.gitConflicts() }
func (g gitBackend) ResolveConflicts(d []Decision) Result { return g.s.gitResolveConflicts(d) }
func (g gitBackend) TakeTheirs() Result                   { return g.s.gitTakeTheirs() }
func (g gitBackend) AbortMerge() Status                   { return g.s.gitAbortMerge() }
func (g gitBackend) History(scope string, n int) ([]Version, error) {
	return g.s.gitHistory(scope, n)
}
func (g gitBackend) Restore(scope, version, message string) Done {
	return g.s.gitRestore(scope, version, message)
}
func (g gitBackend) Revert(version string) Done             { return g.s.gitRevert(version) }
func (g gitBackend) Discard(files []string) Done            { return g.s.gitDiscard(files) }
func (g gitBackend) Capabilities() Capabilities             { return g.s.gitCapabilities() }
func (g gitBackend) UnsavedChanges() ([]UnsavedFile, error) { return g.s.gitUnsavedChanges() }
func (g gitBackend) Abort() bool                            { return g.s.gitAbort() }

// backend is the storage of the current data folder.
func (s *Store) backend() Backend {
	if dir := s.Folder(); dir != "" {
		if cfg, ok := readFolderConfig(dir); ok {
			return &folderBackend{s: s, dir: dir, cfg: cfg}
		}
	}
	return gitBackend{s}
}

// Status is the state of the storage as the top bar shows it, without network access.
func (s *Store) Status() Status { return s.backend().Status() }

// CheckForChanges asks the storage whether others have changed something and returns the new status.
func (s *Store) CheckForChanges() Status { return s.backend().CheckForChanges() }

// StartBackgroundCheck starts the check for changes in the background if it is due.
func (s *Store) StartBackgroundCheck() bool { return s.backend().StartBackgroundCheck() }

// IncomingChanges lists what others have changed and Refresh would take over.
func (s *Store) IncomingChanges() []Change { return s.backend().IncomingChanges() }

// Save makes the work visible to the team.
func (s *Store) Save(opts SaveOptions) Result { return s.backend().Save(opts) }

// Refresh takes over what others have saved, without sharing anything.
func (s *Store) Refresh() Result { return s.backend().Refresh() }

// Conflicts lists what two people changed in different ways and needs a decision.
func (s *Store) Conflicts() []Conflict { return s.backend().Conflicts() }

// ResolveConflicts records the decisions; entries without a decision stay open.
func (s *Store) ResolveConflicts(d []Decision) Result { return s.backend().ResolveConflicts(d) }

// TakeTheirs decides every open conflict for the other side.
func (s *Store) TakeTheirs() Result { return s.backend().TakeTheirs() }

// AbortMerge gives up an unfinished merge and returns the new status.
func (s *Store) AbortMerge() Status { return s.backend().AbortMerge() }

// History lists the saves of the scope, newest first.
func (s *Store) History(scope string, limit int) ([]Version, error) {
	return s.backend().History(scope, limit)
}

// Restore brings the files of an earlier save back as unsaved changes.
func (s *Store) Restore(scope, version, message string) Done {
	return s.backend().Restore(scope, version, message)
}

// Revert takes one save back as unsaved changes.
func (s *Store) Revert(version string) Done { return s.backend().Revert(version) }

// Discard drops the unsaved changes of the files.
func (s *Store) Discard(files []string) Done { return s.backend().Discard(files) }

// Capabilities are the flags the window uses to show or hide features.
func (s *Store) Capabilities() Capabilities { return s.backend().Capabilities() }

// UnsavedChanges lists the files with unsaved changes and their values.
func (s *Store) UnsavedChanges() ([]UnsavedFile, error) { return s.backend().UnsavedChanges() }

// Abort stops the save or refresh that is running.
func (s *Store) Abort() bool { return s.backend().Abort() }
