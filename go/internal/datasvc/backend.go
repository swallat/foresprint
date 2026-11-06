package datasvc

// Backend is the storage behind the window: the operations of the storage interface
// (docs/redesign/storage-interface.md). Git is the first backend; a shared folder is the second.
// Store picks the backend by Kind and passes every call on, so the window and the API do not
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
	return gitBackend{s}
}

func (s *Store) Status() Status                       { return s.backend().Status() }
func (s *Store) CheckForChanges() Status              { return s.backend().CheckForChanges() }
func (s *Store) StartBackgroundCheck() bool           { return s.backend().StartBackgroundCheck() }
func (s *Store) IncomingChanges() []Change            { return s.backend().IncomingChanges() }
func (s *Store) Save(opts SaveOptions) Result         { return s.backend().Save(opts) }
func (s *Store) Refresh() Result                      { return s.backend().Refresh() }
func (s *Store) Conflicts() []Conflict                { return s.backend().Conflicts() }
func (s *Store) ResolveConflicts(d []Decision) Result { return s.backend().ResolveConflicts(d) }
func (s *Store) TakeTheirs() Result                   { return s.backend().TakeTheirs() }
func (s *Store) AbortMerge() Status                   { return s.backend().AbortMerge() }
func (s *Store) History(scope string, limit int) ([]Version, error) {
	return s.backend().History(scope, limit)
}
func (s *Store) Restore(scope, version, message string) Done {
	return s.backend().Restore(scope, version, message)
}
func (s *Store) Revert(version string) Done             { return s.backend().Revert(version) }
func (s *Store) Discard(files []string) Done            { return s.backend().Discard(files) }
func (s *Store) Capabilities() Capabilities             { return s.backend().Capabilities() }
func (s *Store) UnsavedChanges() ([]UnsavedFile, error) { return s.backend().UnsavedChanges() }
func (s *Store) Abort() bool                            { return s.backend().Abort() }
