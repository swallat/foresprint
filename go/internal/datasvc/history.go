package datasvc

import (
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/githistory"
	"github.com/swallat/foresprint/internal/i18n"
)

// scopePath turns a scope of the window (relative to the data folder, "" = everything) into the
// path of the folder or file; ok is false when it points outside the data folder.
func (s *Store) scopePath(scope string) (string, bool) {
	dir := s.Folder()
	if scope == "" {
		return dir, true
	}
	full := filepath.Join(dir, filepath.FromSlash(scope))
	rel, err := filepath.Rel(dir, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", false
	}
	return full, true
}

func outside() error {
	return git.New(i18n.T("The folder is outside the data repository."), "", "")
}

// History lists who changed what and when, newest first (D6). Scope is a team folder or a file,
// relative to the data folder; "" is everything. Limit 0 means 40.
func (s *Store) History(scope string, limit int) ([]Version, error) {
	path, ok := s.scopePath(scope)
	if !ok {
		return nil, outside()
	}
	ctx := s.ctx()
	entries, err := githistory.History(ctx, s.Folder(), path, limit)
	if err != nil {
		return nil, err
	}
	tags := map[string][]string{}
	if list, err := githistory.ListTags(ctx, s.Folder(), false); err == nil {
		for _, t := range list {
			tags[t.Target] = append(tags[t.Target], t.Name)
		}
	}
	out := make([]Version, 0, len(entries))
	for _, e := range entries {
		v := Version{ID: e.Rev, Short: e.Short, Who: e.Author, Day: e.Day, Summary: e.Subject,
			Files: e.Files, Merge: e.Merge, Tags: tags[e.Short]}
		if v.Files == nil {
			v.Files = []string{}
		}
		if v.Tags == nil {
			v.Tags = []string{}
		}
		out = append(out, v)
	}
	return out, nil
}

// Restore brings the folder or file of scope back to the state of an earlier version. It is a
// save on this computer that Save shares and Revert takes back. It is refused while there are
// unsaved changes in that area.
func (s *Store) Restore(scope, version, message string) Done {
	path, ok := s.scopePath(scope)
	if !ok {
		return s.undone(outside())
	}
	rev, err := githistory.RestoreVersion(s.ctx(), s.Folder(), path, version, message)
	return s.done(rev, err)
}

// Revert takes back one change of the history with a new change (D6, "take back this change").
// Merge entries cannot be taken back.
func (s *Store) Revert(version string) Done {
	rev, err := githistory.RevertCommit(s.ctx(), s.Folder(), version)
	return s.done(rev, err)
}

func (s *Store) done(rev string, err error) Done {
	git.InvalidateStatus()
	if err != nil {
		return s.undone(err)
	}
	return Done{Version: rev, Status: s.Status()}
}

func (s *Store) undone(err error) Done {
	return Done{Problem: problemOf(err), Status: s.Status()}
}

// Discard throws away the unsaved changes of the listed files (all when empty). Anything thrown
// away is kept in the trash folder of the data repository; Lost says what would go.
func (s *Store) Discard(files []string) Done {
	trash, err := githistory.Discard(s.ctx(), s.Folder(), files)
	git.InvalidateStatus()
	if err != nil {
		return s.undone(err)
	}
	d := Done{Status: s.Status()}
	if trash != "" {
		d.Warning = i18n.T("Ignored files were kept in {folder}.", "folder", trash)
	}
	return d
}

// Lost lists what Discard would lose: unsaved files and whether they can be recovered.
func (s *Store) Lost(files []string) ([]LostFile, error) {
	list, err := githistory.DiscardPreview(s.ctx(), s.Folder(), files)
	if err != nil {
		return nil, err
	}
	out := make([]LostFile, 0, len(list))
	for _, l := range list {
		out = append(out, LostFile{Status: l.Status, File: l.File, Added: l.Added, Removed: l.Removed, Orig: l.Orig})
	}
	return out, nil
}

// LostFile is an unsaved file and how much of it Discard would lose. Status is M (changed),
// D (deleted), A or ?? (new) or R (renamed from Orig).
type LostFile struct {
	Status  string `json:"status"`
	File    string `json:"file"`
	Added   int    `json:"added"`
	Removed int    `json:"removed"`
	Orig    string `json:"orig,omitempty"`
}

// Labels lists the named states (tags), with what the server knows when it can be reached.
func (s *Store) Labels(checkServer bool) ([]Label, error) {
	tags, err := githistory.ListTags(s.ctx(), s.Folder(), checkServer)
	if err != nil {
		return nil, err
	}
	out := make([]Label, 0, len(tags))
	for _, t := range tags {
		out = append(out, Label{Name: t.Name, Target: t.Target, Day: t.Day, Summary: t.Subject,
			OnServer: t.OnServer, Differs: t.Differs})
	}
	return out, nil
}

// SetLabel names a state ("" = the current one). A server that cannot be reached is a warning,
// the label stays on this computer.
func (s *Store) SetLabel(name, version, message string) Done {
	warning, err := githistory.SetTag(s.ctx(), s.Folder(), name, version, message)
	if err != nil {
		return s.undone(err)
	}
	d := Done{Status: s.Status()}
	if warning != nil {
		d.Warning = warning.Error()
	}
	return d
}

// ShareLabel uploads a label to the server.
func (s *Store) ShareLabel(name string) Done {
	if err := githistory.UploadTag(s.ctx(), s.Folder(), name); err != nil {
		return s.undone(err)
	}
	return Done{Status: s.Status()}
}

// DeleteLabel removes a label here and, where it can, on the server.
func (s *Store) DeleteLabel(name string) Done {
	warning, err := githistory.DeleteTag(s.ctx(), s.Folder(), name)
	if err != nil {
		return s.undone(err)
	}
	d := Done{Status: s.Status()}
	if warning != nil {
		d.Warning = warning.Error()
	}
	return d
}
