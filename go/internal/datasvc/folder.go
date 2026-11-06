package datasvc

import (
	"encoding/json"
	"errors"
	"os"
	"os/user"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/sharedfolder"
	"github.com/swallat/foresprint/internal/yamlmerge"
	"github.com/swallat/foresprint/internal/yamlx"
)

// The shared-folder storage (docs/redesign/storage-interface.md, column "Folder").
//
// The person works on a local copy of the data (the data folder of the window). A shared folder on
// a file server or in a sync service (Dropbox, Nextcloud, OneDrive ...) holds the team's state.
// Next to the local copy the storage keeps, in .foresprint-local, what the shared folder looked
// like at the last Save or Refresh (the base of the merge). Per file:
//
//	local == base, shared != base   others changed it          Refresh takes it over
//	local != base, shared == base   own unsaved change         Save writes it to the shared folder
//	all three differ                both changed it            merged by key; a value changed by both is a conflict
//
// Save takes a short lock, merges, snapshots what it replaces, writes every file atomically and
// adds a line to the person's journal. Sync services do not honour the lock in time, so the
// version check (the base) is what protects the data; the lock only keeps people on one file
// server from interleaving.

const localDirName = ".foresprint-local"

// folderConfig is the file .foresprint-local/config.json of the local copy.
type folderConfig struct {
	Kind   string `json:"kind"`
	Shared string `json:"shared"`
	Person string `json:"person"`
}

func localPath(dir string, parts ...string) string {
	return filepath.Join(append([]string{dir, localDirName}, parts...)...)
}

func readFolderConfig(dir string) (folderConfig, bool) {
	var c folderConfig
	data, err := os.ReadFile(localPath(dir, "config.json"))
	if err != nil || json.Unmarshal(data, &c) != nil || c.Kind != KindFolder || c.Shared == "" {
		return folderConfig{}, false
	}
	return c, true
}

func writeFolderConfig(dir string, c folderConfig) error {
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return sharedfolder.WriteFile(localPath(dir, "config.json"), data, time.Second)
}

// defaultPerson is the name used in the journal when none is set: the user of the computer.
func defaultPerson() string {
	if u, err := user.Current(); err == nil {
		if u.Name != "" {
			return u.Name
		}
		if u.Username != "" {
			return u.Username
		}
	}
	return "unknown"
}

type folderBackend struct {
	s   *Store
	dir string
	cfg folderConfig
}

func (f *folderBackend) person() string {
	if f.cfg.Person != "" {
		return f.cfg.Person
	}
	return defaultPerson()
}

func (f *folderBackend) host() string {
	h, _ := os.Hostname()
	return h
}

func (f *folderBackend) baseDir() string { return localPath(f.dir, "base") }

// isData says whether a path relative to a folder is part of the data: no hidden files or
// folders (this includes the storage's own), no temporary files, no spreadsheets.
func isData(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		if strings.HasPrefix(part, ".") {
			return false
		}
	}
	low := strings.ToLower(rel)
	return !strings.HasSuffix(low, ".tmp") && !strings.HasSuffix(low, ".xlsx")
}

// scan lists the data files of a folder with their checksums, and the conflict copies of the sync
// service it found. Any error (a folder that cannot be listed, a file that cannot be read, for
// example because another program has it open) stops the scan: a file that cannot be read must
// never count as deleted. A folder that does not exist is empty.
func scan(root string) (sums map[string]string, copies []string, err error) {
	sums = map[string]string{}
	if _, serr := os.Stat(root); errors.Is(serr, os.ErrNotExist) {
		return sums, nil, nil
	}
	err = filepath.WalkDir(root, func(p string, d os.DirEntry, werr error) error {
		if werr != nil {
			return werr
		}
		rel, rerr := filepath.Rel(root, p)
		if rerr != nil || rel == "." {
			return rerr
		}
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			if strings.HasPrefix(d.Name(), ".") {
				return filepath.SkipDir
			}
			return nil
		}
		if !isData(rel) {
			return nil
		}
		if sharedfolder.IsConflictCopy(rel) {
			copies = append(copies, rel)
			return nil
		}
		sum, serr := sharedfolder.SumFile(p)
		if serr != nil {
			return serr
		}
		if sum != "" { // "" = the file vanished meanwhile
			sums[rel] = sum
		}
		return nil
	})
	sort.Strings(copies)
	return sums, copies, err
}

// safeRel says whether a name from outside (the journal, a decision) is a plain data path inside
// a folder: relative, clean, no "..", not hidden.
func safeRel(rel string) bool {
	return rel != "" && !path.IsAbs(rel) && !strings.Contains(rel, "\\") && path.Clean(rel) == rel &&
		rel != ".." && !strings.HasPrefix(rel, "../") && isData(rel)
}

func (f *folderBackend) abs(root, rel string) string {
	return filepath.Join(root, filepath.FromSlash(rel))
}

func readIf(p string) ([]byte, bool) {
	data, err := os.ReadFile(p)
	return data, err == nil
}

// connected says whether the shared folder can be reached.
func (f *folderBackend) connected() bool {
	// The marker tells a shared folder from an empty mount point or a folder a sync service has not
	// filled yet; without it nothing is read from or written to the folder.
	_, err := os.Stat(filepath.Join(f.cfg.Shared, sharedfolder.Dir, "storage.yaml"))
	return err == nil
}

func (f *folderBackend) offline() *Problem {
	return &Problem{Kind: "offline", Title: i18n.T("The shared folder is not reachable"),
		Message: i18n.T("The folder {path} cannot be reached.", "path", f.cfg.Shared),
		Hint:    i18n.T("Check the network connection or the drive. You can keep working; saving waits.")}
}

// state is how the three versions of every file relate.
type folderState struct {
	base, local, shared map[string]string
	copies              []string
	incoming            []string // others changed, local untouched
	outgoing            []string // local changed, shared untouched
	both                []string // all three differ
	inSync              []string // local and shared equal but base differs
}

func (f *folderBackend) state() (folderState, error) {
	st := folderState{}
	var err error
	if st.base, _, err = scan(f.baseDir()); err != nil {
		return st, err
	}
	if st.local, _, err = scan(f.dir); err != nil {
		return st, err
	}
	if f.connected() {
		if st.shared, st.copies, err = scan(f.cfg.Shared); err != nil {
			return st, err
		}
	} else {
		// Nothing is known about the shared folder: assume it is as at the last sync.
		st.shared = map[string]string{}
		for rel, sum := range st.base {
			st.shared[rel] = sum
		}
	}
	all := map[string]bool{}
	for _, m := range []map[string]string{st.base, st.local, st.shared} {
		for rel := range m {
			all[rel] = true
		}
	}
	rels := make([]string, 0, len(all))
	for rel := range all {
		rels = append(rels, rel)
	}
	sort.Strings(rels)
	for _, rel := range rels {
		b, l, s := st.base[rel], st.local[rel], st.shared[rel]
		switch {
		case l == s:
			if b != l {
				st.inSync = append(st.inSync, rel)
			}
		case l == b:
			st.incoming = append(st.incoming, rel)
		case s == b:
			st.outgoing = append(st.outgoing, rel)
		default:
			st.both = append(st.both, rel)
		}
	}
	return st, nil
}

// errChanged is returned when a file is not what the scan saw a moment ago: someone (or a sync
// service) changed it while this program worked. Nothing is written for it; trying again works.
var errChanged = errors.New("a file changed while it was being processed")

// readExpect reads a file once and checks it against the checksum the scan saw; "" means the file
// must not exist. What is read here is also what is written to the base, so that the base always
// is exactly what was merged or copied and never something newer.
func readExpect(root, rel, sum string) (data []byte, exists bool, err error) {
	data, err = os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
	switch {
	case errors.Is(err, os.ErrNotExist):
		if sum != "" {
			return nil, false, errChanged
		}
		return nil, false, nil
	case err != nil:
		return nil, false, err
	case sharedfolder.Sum(data) != sum:
		return nil, false, errChanged
	}
	return data, true, nil
}

// merged is the outcome of merging one file changed on both sides.
type merged struct {
	text      string
	conflicts []yamlmerge.KeyConflict
	whole     bool // cannot be merged by key: decided as a whole
	// theirs is the shared version that went into the merge (what the base becomes).
	theirs    []byte
	hasTheirs bool
}

func (f *folderBackend) merge(st folderState, rel string, choices yamlmerge.Choices) (merged, error) {
	baseB, hasBase, err := readExpect(f.baseDir(), rel, st.base[rel])
	if err != nil {
		return merged{}, err
	}
	oursB, hasOurs, err := readExpect(f.dir, rel, st.local[rel])
	if err != nil {
		return merged{}, err
	}
	theirsB, hasTheirs, err := readExpect(f.cfg.Shared, rel, st.shared[rel])
	if err != nil {
		return merged{}, err
	}
	whole := merged{whole: true, theirs: theirsB, hasTheirs: hasTheirs}
	if !isYAML(rel) || !hasOurs || !hasTheirs {
		return whole, nil
	}
	codec := gitsync.YAMLCodec{}
	base := yamlmerge.Missing
	if hasBase {
		t, err := codec.Parse(string(baseB))
		if err != nil {
			return whole, nil
		}
		if t == nil {
			t = &yamlx.Map{}
		}
		base = t
	}
	ours, err1 := codec.Parse(string(oursB))
	theirs, err2 := codec.Parse(string(theirsB))
	if err1 != nil || err2 != nil {
		return whole, nil
	}
	if ours == nil {
		ours = &yamlx.Map{}
	}
	if theirs == nil {
		theirs = &yamlx.Map{}
	}
	_, om := ours.(*yamlx.Map)
	_, tm := theirs.(*yamlx.Map)
	if !om || !tm {
		return whole, nil
	}
	tree, conflicts := yamlmerge.Merge3(base, ours, theirs, choices)
	if len(conflicts) > 0 {
		return merged{conflicts: conflicts, theirs: theirsB, hasTheirs: true}, nil
	}
	dumped, err := codec.Dump(tree)
	if err != nil {
		return whole, nil
	}
	return merged{text: yamlmerge.HeaderOf(string(oursB)) + dumped, theirs: theirsB, hasTheirs: true}, nil
}

// setBase makes the base of a file the given content (not existing = removed).
func (f *folderBackend) setBase(rel string, data []byte, exists bool) error {
	dst := f.abs(f.baseDir(), rel)
	if !exists {
		if err := os.Remove(dst); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		return nil
	}
	return sharedfolder.WriteFile(dst, data, 2*time.Second)
}

func (f *folderBackend) writeLocal(rel string, data []byte) error {
	return sharedfolder.WriteFile(f.abs(f.dir, rel), data, 2*time.Second)
}

func (f *folderBackend) removeLocal(rel string) error {
	if err := os.Remove(f.abs(f.dir, rel)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// keep copies a local file to .foresprint-local/trash before something replaces or deletes it, if
// it has unsaved changes (it differs from the base). Nothing is kept for files that are saved.
func (f *folderBackend) keep(rel string) error {
	cur, ok := readIf(f.abs(f.dir, rel))
	if !ok {
		return nil
	}
	if base, has := readIf(f.abs(f.baseDir(), rel)); has && sharedfolder.Sum(base) == sharedfolder.Sum(cur) {
		return nil
	}
	stamp := time.Now().UTC().Format("20060102T150405")
	return sharedfolder.WriteFile(localPath(f.dir, "trash", stamp, filepath.FromSlash(rel)), cur, 2*time.Second)
}

// overwriteLocal replaces a local file, keeping a copy of unsaved changes it would lose.
func (f *folderBackend) overwriteLocal(rel string, data []byte) error {
	if err := f.keep(rel); err != nil {
		return err
	}
	return f.writeLocal(rel, data)
}

// openConflicts counts the files that still need a decision: both sides changed a value in
// different ways, or a file only decidable as a whole, plus conflict copies of the sync service.
func (f *folderBackend) openConflicts(st folderState) (int, error) {
	n := len(st.copies)
	for _, rel := range st.both {
		m, err := f.merge(st, rel, nil)
		if err != nil {
			return 0, err
		}
		if m.whole || len(m.conflicts) > 0 {
			n++
		}
	}
	return n, nil
}

func (f *folderBackend) changedProblem() *Problem {
	return &Problem{Kind: "changed", Title: i18n.T("A file changed meanwhile"),
		Message: i18n.T("Someone saved or a sync service delivered a file while this was running. Nothing was lost."),
		Hint:    i18n.T("Try again.")}
}

// problemFor turns an error of the folder storage into the problem the window shows.
func problemFor(f *folderBackend, err error) *Problem {
	if errors.Is(err, errChanged) {
		return f.changedProblem()
	}
	return problemOf(err)
}

// Status implements Backend.
func (f *folderBackend) Status() Status {
	out := Status{Kind: KindFolder, Location: f.cfg.Shared, Configured: true, Writable: true,
		Capabilities: f.Capabilities(), IncomingFrom: []string{}}
	if _, err := os.Stat(f.dir); err != nil {
		return withProblem(out, git.New(i18n.T("The folder {path} does not exist.", "path", f.dir), "path", ""))
	}
	out.Connected = f.connected()
	st, err := f.state()
	if err != nil {
		return withProblem(out, err)
	}
	out.Unsaved = len(st.outgoing) + len(st.both)
	out.Incoming = len(st.incoming) + len(st.both)
	if out.Conflicts, err = f.openConflicts(st); err != nil {
		if errors.Is(err, errChanged) { // changed while counting: show without
			out.Conflicts = len(st.copies)
		} else {
			return withProblem(out, err)
		}
	}
	if out.Incoming > 0 {
		out.IncomingFrom = f.whoChanged(st, append(append([]string{}, st.incoming...), st.both...))
	}
	out.Chip = f.chip(out)
	return out
}

func (f *folderBackend) chip(s Status) Chip {
	switch {
	case s.Conflicts > 0:
		return Chip{State: ChipConflict, Text: plural(s.Conflicts, "{count} file needs your decision", "{count} files need your decision")}
	case !s.Connected:
		return Chip{State: ChipOffline, Text: i18n.T("Shared folder not reachable: saving waits")}
	case s.Incoming > 0:
		return Chip{State: ChipIncoming, Text: plural(s.Incoming, "{count} new change from {who}", "{count} new changes from {who}",
			"who", who(s.IncomingFrom))}
	case s.Unsaved > 0:
		return Chip{State: ChipUnsaved, Text: plural(s.Unsaved, "{count} unsaved change", "{count} unsaved changes")}
	}
	return Chip{State: ChipOK, Text: i18n.T("Up to date")}
}

// whoChanged names the people whose journal entries produced the shared versions of the files.
func (f *folderBackend) whoChanged(st folderState, rels []string) []string {
	var commits []gitsync.Commit
	for _, c := range f.changesOf(st, rels) {
		commits = append(commits, gitsync.Commit{Author: c.Who})
	}
	return names(commits)
}

// Capabilities implements Backend: the local copy can be edited without a connection; there are
// no tags or branches, but snapshots.
func (f *folderBackend) Capabilities() Capabilities {
	return Capabilities{OfflineWrite: true, Snapshots: true}
}

// CheckForChanges implements Backend: the status reads the shared folder directly.
func (f *folderBackend) CheckForChanges() Status { return f.Status() }

// StartBackgroundCheck implements Backend: there is no background check; the window asks on focus.
func (f *folderBackend) StartBackgroundCheck() bool { return false }

// IncomingChanges implements Backend.
func (f *folderBackend) IncomingChanges() []Change {
	st, err := f.state()
	if err != nil {
		return []Change{}
	}
	return f.changesOf(st, append(append([]string{}, st.incoming...), st.both...))
}

func (f *folderBackend) changesOf(st folderState, rels []string) []Change {
	out := []Change{}
	entries, err := sharedfolder.ReadJournal(f.cfg.Shared)
	if err != nil {
		return out
	}
	seen := map[string]bool{}
	for _, rel := range rels {
		for _, e := range entries { // newest first
			if c, ok := e.Files[rel]; ok && c.After == st.shared[rel] {
				if !seen[e.ID] {
					seen[e.ID] = true
					out = append(out, Change{Who: e.Who, Day: e.Time.Format("2006-01-02"), Summary: e.Summary})
				}
				break
			}
		}
	}
	return out
}

func (f *folderBackend) problem(err error) Result {
	return Result{Outcome: OutcomeProblem, Taken: []Change{}, Problem: problemFor(f, err), Status: f.Status()}
}

// Save implements Backend.
func (f *folderBackend) Save(opts SaveOptions) Result {
	return f.run(true, f.s.messageOf(opts.Message))
}

// Refresh implements Backend.
func (f *folderBackend) Refresh() Result { return f.run(false, "") }

func (f *folderBackend) run(push bool, message string) Result {
	f.s.fmu.Lock()
	defer f.s.fmu.Unlock()
	if !f.connected() {
		return Result{Outcome: OutcomeOffline, Taken: []Change{}, Problem: f.offline(), Status: f.Status()}
	}
	// Refresh and Save both change the base and the local files; both hold the lock of the shared
	// folder, so that nobody saves between the scan and the writes of this run.
	lock, err := sharedfolder.Acquire(f.cfg.Shared, f.person(), f.host(), 10*time.Second, time.Now)
	if err != nil {
		var held *sharedfolder.Held
		if errors.As(err, &held) {
			return Result{Outcome: OutcomeProblem, Taken: []Change{}, Status: f.Status(), Problem: &Problem{
				Kind: "locked", Title: i18n.T("The shared folder is being saved"),
				Message: i18n.T("{who} is saving right now.", "who", held.By.Owner),
				Hint:    i18n.T("Try again in a moment.")}}
		}
		return f.problem(err)
	}
	defer lock.Release()
	st, err := f.state()
	if err != nil {
		return f.problem(err)
	}
	res := Result{Taken: []Change{}, Notes: []string{}}
	res.Taken = f.changesOf(st, append(append([]string{}, st.incoming...), st.both...))
	taken := 0
	for _, rel := range st.incoming {
		data, ok, err := readExpect(f.cfg.Shared, rel, st.shared[rel])
		if err != nil {
			return f.problem(err)
		}
		if !ok {
			err = f.removeLocal(rel)
		} else {
			err = f.writeLocal(rel, data)
		}
		if err == nil {
			err = f.setBase(rel, data, ok)
		}
		if err != nil {
			return f.problem(err)
		}
		taken++
	}
	open := 0
	for _, rel := range st.both {
		m, err := f.merge(st, rel, nil)
		if err != nil {
			return f.problem(err)
		}
		if m.whole || len(m.conflicts) > 0 {
			open++
			continue
		}
		// The merged file contains the shared version; its base is exactly that version.
		if err := f.writeLocal(rel, []byte(m.text)); err != nil {
			return f.problem(err)
		}
		if err := f.setBase(rel, m.theirs, m.hasTheirs); err != nil {
			return f.problem(err)
		}
		taken++
	}
	for _, rel := range st.inSync {
		data, ok, err := readExpect(f.dir, rel, st.local[rel])
		if err == nil {
			err = f.setBase(rel, data, ok)
		}
		if err != nil {
			return f.problem(err)
		}
	}
	res.Conflicts = open + len(st.copies)
	if res.Conflicts > 0 {
		res.Outcome = OutcomeConflict
		res.Status = f.Status()
		return res
	}
	pushed := 0
	if push {
		if pushed, err = f.publish(lock, message); err != nil {
			return f.problem(err)
		}
	}
	if pushed > 0 || taken > 0 {
		res.Outcome = OutcomeSaved
	} else {
		res.Outcome = OutcomeNothing
	}
	res.Status = f.Status()
	return res
}

// publish writes the files that only the local copy changed to the shared folder, with snapshot
// and journal. The caller holds the lock and has taken over and merged everything of others. A
// fresh scan decides what is written, and each file is checked against it right before it is
// replaced: whatever changed in the shared folder since is left alone and the save stops.
func (f *folderBackend) publish(lock *sharedfolder.Handle, message string) (int, error) {
	st, err := f.state()
	if err != nil {
		return 0, err
	}
	if len(st.both) > 0 || len(st.incoming) > 0 {
		return 0, errChanged
	}
	rels := st.outgoing
	if len(rels) == 0 {
		return 0, nil
	}
	now := time.Now()
	if err := sharedfolder.Snapshot(f.cfg.Shared, rels, now, isData); err != nil {
		return 0, err
	}
	done := map[string]sharedfolder.Change{}
	// Whatever was written is journaled, also when the save stops half way.
	defer func() {
		if len(done) > 0 {
			_ = sharedfolder.Append(f.cfg.Shared, sharedfolder.Entry{ID: entryID(now, f.person()), Who: f.person(),
				Time: now, Summary: message, Files: done})
		}
	}()
	for _, rel := range rels {
		if err := lock.Renew(time.Now); err != nil {
			return len(done), err
		}
		data, exists, err := readExpect(f.dir, rel, st.local[rel])
		if err != nil {
			return len(done), err
		}
		dst := f.abs(f.cfg.Shared, rel)
		if cur, err := sharedfolder.SumFile(dst); err != nil || cur != st.shared[rel] {
			return len(done), errChanged
		}
		if exists {
			err = sharedfolder.WriteFile(dst, data, 10*time.Second)
		} else if err = os.Remove(dst); errors.Is(err, os.ErrNotExist) {
			err = nil
		}
		if err != nil {
			return len(done), err
		}
		done[rel] = sharedfolder.Change{Before: st.shared[rel], After: st.local[rel]}
		if err := f.setBase(rel, data, exists); err != nil {
			return len(done), err
		}
	}
	return len(done), nil
}

func entryID(t time.Time, who string) string {
	return t.UTC().Format("20060102T150405.000000000Z") + "-" + sharedfolder.Sum([]byte(who))[:6]
}

// Conflicts implements Backend.
func (f *folderBackend) Conflicts() []Conflict {
	st, err := f.state()
	if err != nil {
		return []Conflict{}
	}
	out := []Conflict{}
	for _, rel := range st.both {
		m, err := f.merge(st, rel, nil)
		if err != nil {
			continue
		}
		switch {
		case m.whole:
			_, hasOurs := readIf(f.abs(f.dir, rel))
			out = append(out, Conflict{File: rel, Whole: true, Entries: []ConflictEntry{}, MineDeleted: !hasOurs, TheirsDeleted: !m.hasTheirs})
		case len(m.conflicts) > 0:
			c := Conflict{File: rel, Entries: []ConflictEntry{}}
			for _, k := range m.conflicts {
				e := ConflictEntry{Path: append([]string{}, k.Path...), Label: k.Label(), Mine: show(k.Ours), Theirs: show(k.Theirs),
					MineMissing: yamlmerge.IsMissing(k.Ours), TheirsMissing: yamlmerge.IsMissing(k.Theirs),
					Before: show(k.Base), HasBefore: !yamlmerge.IsMissing(k.Base)}
				c.Entries = append(c.Entries, e)
			}
			out = append(out, c)
		}
	}
	for _, cp := range st.copies {
		// Mine: the file in the shared folder; theirs: the copy the sync service made.
		out = append(out, Conflict{File: cp, Whole: true, Entries: []ConflictEntry{}})
	}
	return out
}

// ResolveConflicts implements Backend. Decisions for values and whole files change the local copy
// only; the next Save writes the result to the shared folder. A conflict copy of a sync service is
// decided the same way: "mine" keeps the file as it is and removes the copy, "theirs" takes the
// content of the copy into the local file as an unsaved change. What a decision replaces and was
// not saved is kept in .foresprint-local/trash.
func (f *folderBackend) ResolveConflicts(decisions []Decision) Result {
	f.s.fmu.Lock()
	defer f.s.fmu.Unlock()
	byFile := map[string]yamlmerge.Choices{}
	var order []string
	for _, d := range decisions {
		if !safeRel(d.File) {
			continue
		}
		if byFile[d.File] == nil {
			byFile[d.File] = yamlmerge.Choices{}
			order = append(order, d.File)
		}
		choice := d.Choice
		switch choice {
		case Mine:
			choice = yamlmerge.Ours
		case Theirs:
			choice = yamlmerge.Theirs
		case Custom:
			choice = yamlmerge.CustomChoice(d.Value)
		}
		byFile[d.File].Choose(yamlmerge.Path(d.Path), choice)
	}
	st, err := f.state()
	if err != nil {
		return f.problem(err)
	}
	isBoth := map[string]bool{}
	for _, rel := range st.both {
		isBoth[rel] = true
	}
	isCopy := map[string]bool{}
	for _, cp := range st.copies {
		isCopy[cp] = true
	}
	for _, rel := range order {
		choices := byFile[rel]
		whole := choices[yamlmerge.Path(nil).Key()]
		var err error
		switch {
		case isCopy[rel]:
			if whole != "" {
				err = f.decideCopy(rel, whole == yamlmerge.Theirs)
			}
		case isBoth[rel]:
			err = f.decide(st, rel, choices, whole)
		}
		if err != nil {
			return f.problem(err)
		}
	}
	res := Result{Outcome: OutcomeDecided, Taken: []Change{}, Status: f.Status()}
	res.Conflicts = res.Status.Conflicts
	if res.Conflicts > 0 {
		res.Outcome = OutcomeConflict
	}
	return res
}

// decide applies the decisions to a file both sides changed.
func (f *folderBackend) decide(st folderState, rel string, choices yamlmerge.Choices, whole string) error {
	m, err := f.merge(st, rel, nil)
	if err != nil {
		return err
	}
	if m.whole {
		switch {
		case whole == "":
			return nil
		case strings.HasPrefix(whole, yamlmerge.CustomPrefix):
			if err := f.overwriteLocal(rel, []byte(strings.TrimPrefix(whole, yamlmerge.CustomPrefix))); err != nil {
				return err
			}
		case whole == yamlmerge.Theirs:
			if !m.hasTheirs {
				if err := f.keep(rel); err != nil {
					return err
				}
				if err := f.removeLocal(rel); err != nil {
					return err
				}
			} else if err := f.overwriteLocal(rel, m.theirs); err != nil {
				return err
			}
		}
		// Ours: the local file stays; it is now an unsaved change over the shared version.
		return f.setBase(rel, m.theirs, m.hasTheirs)
	}
	m, err = f.merge(st, rel, choices)
	if err != nil {
		return err
	}
	if len(m.conflicts) > 0 || m.whole {
		return nil // some values still without a decision
	}
	if err := f.writeLocal(rel, []byte(m.text)); err != nil {
		return err
	}
	return f.setBase(rel, m.theirs, m.hasTheirs)
}

// decideCopy handles one conflict copy; the copy is removed in the shared folder under the lock.
func (f *folderBackend) decideCopy(copyRel string, takeCopy bool) error {
	orig := sharedfolder.OriginalOf(copyRel)
	if takeCopy && !safeRel(orig) {
		return git.New(i18n.T("Foresprint cannot tell which file {file} belongs to; open it and copy what you need by hand.", "file", copyRel), "error", "")
	}
	lock, err := sharedfolder.Acquire(f.cfg.Shared, f.person(), f.host(), 10*time.Second, time.Now)
	if err != nil {
		return err
	}
	defer lock.Release()
	if takeCopy {
		data, err := os.ReadFile(f.abs(f.cfg.Shared, copyRel))
		if err != nil {
			return err
		}
		if err := f.overwriteLocal(orig, data); err != nil {
			return err
		}
	}
	if err := os.Remove(f.abs(f.cfg.Shared, copyRel)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// TakeTheirs implements Backend: every open conflict is decided for the others' side.
func (f *folderBackend) TakeTheirs() Result {
	var decisions []Decision
	for _, c := range f.Conflicts() {
		if c.Whole {
			decisions = append(decisions, Decision{File: c.File, Path: []string{}, Choice: Theirs})
			continue
		}
		for _, e := range c.Entries {
			decisions = append(decisions, Decision{File: c.File, Path: e.Path, Choice: Theirs})
		}
	}
	return f.ResolveConflicts(decisions)
}

// AbortMerge implements Backend: decisions are not kept between calls, so there is nothing to give up.
func (f *folderBackend) AbortMerge() Status { return f.Status() }

// Abort implements Backend: saves are short and cannot be stopped from outside.
func (f *folderBackend) Abort() bool { return false }

// UnsavedChanges implements Backend.
func (f *folderBackend) UnsavedChanges() ([]UnsavedFile, error) {
	st, err := f.state()
	if err != nil {
		return nil, err
	}
	out := []UnsavedFile{}
	rels := append(append([]string{}, st.outgoing...), st.both...)
	sort.Strings(rels)
	for _, rel := range rels {
		file := UnsavedFile{File: rel, Values: []ValueChange{}}
		baseB, hasBase := readIf(f.abs(f.baseDir(), rel))
		curB, hasCur := readIf(f.abs(f.dir, rel))
		switch {
		case !hasCur:
			file.Status, file.Whole = "D", true
		case !hasBase:
			file.Status, file.Whole = "A", true
		default:
			file.Status = "M"
			before, e1 := yamlx.Load(string(baseB))
			after, e2 := yamlx.Load(string(curB))
			if !isYAML(rel) || e1 != nil || e2 != nil {
				file.Whole = true
				break
			}
			if before == nil {
				before = &yamlx.Map{}
			}
			if after == nil {
				after = &yamlx.Map{}
			}
			for _, ch := range yamlmerge.Changes(before, after) {
				file.Values = append(file.Values, ValueChange{Path: append([]string{}, ch.Path...), Label: ch.Label(),
					Kind: kindOf(ch), Before: show(ch.Before), After: show(ch.After),
					HasBefore: !yamlmerge.IsMissing(ch.Before), HasAfter: !yamlmerge.IsMissing(ch.After)})
			}
		}
		out = append(out, file)
	}
	return out, nil
}

// Discard implements Backend: the files go back to the last saved state; nil = all files. A copy
// of what is discarded stays in .foresprint-local/trash.
func (f *folderBackend) Discard(files []string) Done {
	f.s.fmu.Lock()
	defer f.s.fmu.Unlock()
	st, err := f.state()
	if err != nil {
		return f.s.undone(err)
	}
	pending := append(append([]string{}, st.outgoing...), st.both...)
	want := map[string]bool{}
	for _, r := range files {
		want[path.Clean(filepath.ToSlash(r))] = true
	}
	for _, rel := range pending {
		if len(files) > 0 && !want[rel] {
			continue
		}
		if err := f.keep(rel); err != nil {
			return f.s.undone(err)
		}
		if data, ok := readIf(f.abs(f.baseDir(), rel)); ok {
			err = f.writeLocal(rel, data)
		} else {
			err = f.removeLocal(rel)
		}
		if err != nil {
			return f.s.undone(err)
		}
	}
	return Done{Status: f.Status()}
}

// History implements Backend: the saves from the journals, newest first; scope is a folder or a
// file relative to the data folder.
func (f *folderBackend) History(scope string, limit int) ([]Version, error) {
	if !f.connected() {
		return []Version{}, git.New(i18n.T("The folder {path} cannot be reached.", "path", f.cfg.Shared), "offline", "")
	}
	if limit <= 0 {
		limit = 40
	}
	scope = strings.Trim(path.Clean(filepath.ToSlash(scope)), "/")
	if scope == "." {
		scope = ""
	}
	if strings.HasPrefix(scope, "..") {
		return nil, outside()
	}
	entries, err := sharedfolder.ReadJournal(f.cfg.Shared)
	if err != nil {
		return nil, err
	}
	out := []Version{}
	for _, e := range entries {
		files := []string{}
		for rel := range e.Files {
			if safeRel(rel) && (scope == "" || rel == scope || strings.HasPrefix(rel, scope+"/")) {
				files = append(files, rel)
			}
		}
		if len(files) == 0 {
			continue
		}
		sort.Strings(files)
		short := e.ID
		if len(short) > 15 {
			short = short[:15]
		}
		out = append(out, Version{ID: e.ID, Short: short, Who: e.Who, Day: e.Time.Format("2006-01-02"),
			Summary: e.Summary, Files: files, Tags: []string{}})
		if len(out) >= limit {
			break
		}
	}
	return out, nil
}

func (f *folderBackend) entry(id string) (sharedfolder.Entry, bool) {
	entries, _ := sharedfolder.ReadJournal(f.cfg.Shared)
	for _, e := range entries {
		if e.ID == id {
			return e, true
		}
	}
	return sharedfolder.Entry{}, false
}

// inScope says whether rel is within scope ("" = everything).
func inScope(scope, rel string) bool {
	scope = strings.Trim(scope, "/")
	return scope == "" || rel == scope || strings.HasPrefix(rel, scope+"/")
}

// Restore implements Backend: the files of the save, as they were at the start of the day of that
// save (the snapshot), become unsaved changes in the local copy. scope narrows the files. All
// snapshots are read before the first file is written; unsaved changes that are replaced stay in
// .foresprint-local/trash.
func (f *folderBackend) Restore(scope, version, message string) Done {
	f.s.fmu.Lock()
	defer f.s.fmu.Unlock()
	e, ok := f.entry(version)
	if !ok {
		return f.s.undone(git.New(i18n.T("This save is not in the history."), "error", ""))
	}
	day := e.Time.Format("2006-01-02")
	plan := map[string][]byte{}
	for rel := range e.Files {
		if !safeRel(rel) || !inScope(scope, rel) {
			continue
		}
		data, found := sharedfolder.SnapshotFile(f.cfg.Shared, rel, day)
		if !found {
			return f.s.undone(git.New(i18n.T("There is no snapshot of {file} from that day.", "file", rel), "error", ""))
		}
		plan[rel] = data
	}
	for rel, data := range plan {
		if err := f.overwriteLocal(rel, data); err != nil {
			return f.s.undone(err)
		}
	}
	return Done{Version: e.ID, Status: f.Status()}
}

// Revert implements Backend: takes one save back as unsaved changes. It works for a file where
// nothing happened since that save (the shared file is still as the save left it, and there are
// no unsaved changes) and the state before the save is still a snapshot (the first save of a day).
// Otherwise the call says so instead of overwriting later work.
func (f *folderBackend) Revert(version string) Done {
	f.s.fmu.Lock()
	defer f.s.fmu.Unlock()
	e, ok := f.entry(version)
	if !ok {
		return f.s.undone(git.New(i18n.T("This save is not in the history."), "error", ""))
	}
	st, err := f.state()
	if err != nil {
		return f.s.undone(err)
	}
	day := e.Time.Format("2006-01-02")
	type restore struct {
		rel  string
		data []byte
		del  bool
	}
	var plan []restore
	for rel, c := range e.Files {
		if !safeRel(rel) {
			continue
		}
		if st.shared[rel] != c.After {
			return f.s.undone(git.New(i18n.T("{file} was saved again after this save; take those saves back first.", "file", rel), "error", ""))
		}
		if st.local[rel] != st.base[rel] {
			return f.s.undone(git.New(i18n.T("{file} has unsaved changes; save or discard them first.", "file", rel), "error", ""))
		}
		if c.Before == "" {
			plan = append(plan, restore{rel: rel, del: true})
			continue
		}
		data, found := sharedfolder.SnapshotFile(f.cfg.Shared, rel, day)
		if !found || sharedfolder.Sum(data) != c.Before {
			return f.s.undone(git.New(i18n.T("This save cannot be taken back exactly: the state before it is not kept."), "error", ""))
		}
		plan = append(plan, restore{rel: rel, data: data})
	}
	for _, r := range plan {
		var err error
		if r.del {
			err = f.removeLocal(r.rel)
		} else {
			err = f.writeLocal(r.rel, r.data)
		}
		if err != nil {
			return f.s.undone(err)
		}
	}
	return Done{Version: e.ID, Status: f.Status()}
}
