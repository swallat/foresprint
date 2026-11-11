package datasvc

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/yamlmerge"
	"github.com/swallat/foresprint/internal/yamlx"
)

// ValueChange is one unsaved value: what it was at the last save and what it is now.
type ValueChange struct {
	// Path is the way to the value inside the file (keys, and "[id]" for the entry of a list).
	Path  []string `json:"path"`
	Label string   `json:"label"`
	// Kind is "added", "changed" or "removed".
	Kind      string `json:"kind"`
	Before    string `json:"before"`
	After     string `json:"after"`
	HasBefore bool   `json:"hasBefore"`
	HasAfter  bool   `json:"hasAfter"`
}

// UnsavedFile is a file with unsaved changes. Whole files (new, deleted, not YAML, or not
// readable as YAML) have no Values and are shown as one change.
type UnsavedFile struct {
	// File is relative to the root of the data repository.
	File string `json:"file"`
	// Status is M (changed), D (deleted), A or ?? (new), R (renamed).
	Status string        `json:"status"`
	Whole  bool          `json:"whole"`
	Values []ValueChange `json:"values"`
}

// ValueRef names one unsaved value for DiscardValues.
type ValueRef struct {
	File string   `json:"file"`
	Path []string `json:"path"`
}

func isYAML(file string) bool {
	return strings.HasSuffix(file, ".yaml") || strings.HasSuffix(file, ".yml")
}

func kindOf(c yamlmerge.Change) string {
	switch {
	case yamlmerge.IsMissing(c.Before):
		return "added"
	case yamlmerge.IsMissing(c.After):
		return "removed"
	}
	return "changed"
}

// treesOf reads the saved and the current version of a changed YAML file.
func treesOf(root, file string, ctx context.Context) (before, after any, text string, ok bool) {
	raw, err := git.Bytes(ctx, root, "show", "HEAD:"+filepath.ToSlash(file))
	if err != nil {
		return nil, nil, "", false
	}
	current, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(file)))
	if err != nil {
		return nil, nil, "", false
	}
	b, err := yamlx.Load(string(raw))
	if err != nil {
		return nil, nil, "", false
	}
	a, err := yamlx.Load(string(current))
	if err != nil {
		return nil, nil, "", false
	}
	if b == nil {
		b = &yamlx.Map{}
	}
	if a == nil {
		a = &yamlx.Map{}
	}
	return b, a, string(current), true
}

// gitUnsavedChanges lists what changed since the last save, value by value instead of file by file
// (D2: the list before Save).
func (s *Store) gitUnsavedChanges() ([]UnsavedFile, error) {
	dir, err := s.folder()
	if err != nil {
		return nil, err
	}
	ctx := s.ctx()
	root, err := gitsync.Root(ctx, dir)
	if err != nil {
		return nil, err
	}
	pending, err := git.PendingChanges(ctx, dir)
	if err != nil {
		return nil, err
	}
	out := make([]UnsavedFile, 0, len(pending))
	for _, c := range pending {
		f := UnsavedFile{File: c.File, Status: c.Status, Values: []ValueChange{}}
		if isYAML(c.File) && (c.Status == "M" || c.Status == "MM") {
			if before, after, _, ok := treesOf(root, c.File, ctx); ok {
				for _, ch := range yamlmerge.Changes(before, after) {
					f.Values = append(f.Values, ValueChange{Path: append([]string{}, ch.Path...), Label: ch.Label(),
						Kind: kindOf(ch), Before: show(ch.Before), After: show(ch.After),
						HasBefore: !yamlmerge.IsMissing(ch.Before), HasAfter: !yamlmerge.IsMissing(ch.After)})
				}
				// Only the layout differs (order of keys, quotes, line ends): there is no value to
				// put back, the file can only be taken back as a whole.
				f.Whole = len(f.Values) == 0
				out = append(out, f)
				continue
			}
		}
		f.Whole = true
		out = append(out, f)
	}
	return out, nil
}

// DiscardValues puts single values back to what they were at the last save. The file is written
// again the way the app writes files; the other values in it stay as they are.
func (s *Store) DiscardValues(items []ValueRef) Done {
	dir, err := s.folder()
	if err != nil {
		return s.undone(err)
	}
	ctx := s.ctx()
	root, err := gitsync.Root(ctx, dir)
	if err != nil {
		return s.undone(err)
	}
	byFile := map[string][]ValueRef{}
	var order []string
	for _, it := range items {
		if _, seen := byFile[it.File]; !seen {
			order = append(order, it.File)
		}
		byFile[it.File] = append(byFile[it.File], it)
	}
	codec := gitsync.YAMLCodec{}
	for _, file := range order {
		if !isYAML(file) || strings.Contains(file, "..") {
			return s.undone(git.New(i18n.T("Only values of YAML files can be put back one by one."), "error", ""))
		}
		before, after, text, ok := treesOf(root, file, ctx)
		if !ok {
			return s.undone(git.New(i18n.T("This file cannot be put back value by value."), "error", ""))
		}
		changes := map[string]yamlmerge.Change{}
		for _, c := range yamlmerge.Changes(before, after) {
			changes[c.Path.Key()] = c
		}
		tree := after
		for _, ref := range byFile[file] {
			c, found := changes[yamlmerge.Path(ref.Path).Key()]
			if !found {
				return s.undone(git.New(i18n.T("This value has changed in the meantime; look at the changes again."), "error", ""))
			}
			if tree, ok = yamlmerge.Apply(tree, c.Path, c.Before); !ok {
				return s.undone(git.New(i18n.T("This value cannot be put back."), "error", ""))
			}
		}
		if sameAsSaved(ctx, root, file, text, before, tree) {
			// Every value is back. Write the file as it was saved instead of dumping the tree:
			// a dump may order keys or write timestamps differently, and the file would still
			// count as changed although nothing differs.
			if _, err := git.Git(ctx, root, "restore", "--source=HEAD", "--staged", "--worktree", "--", file); err != nil {
				return s.undone(err)
			}
			continue
		}
		dumped, err := codec.Dump(tree)
		if err != nil {
			return s.undone(err)
		}
		if err := os.WriteFile(filepath.Join(root, filepath.FromSlash(file)), []byte(yamlmerge.HeaderOf(text)+dumped), 0o666); err != nil {
			return s.undone(err)
		}
	}
	git.InvalidateStatus()
	return Done{Status: s.Status()}
}

// sameAsSaved says that the tree is what was saved: same values, lists in the same order, same
// leading comment. The order of keys of a mapping does not count (a put-back key may come back
// at another place). Only then is the saved file put back as it is; a difference the value list
// cannot show (a reordered list, an edited comment) stays.
func sameAsSaved(ctx context.Context, root, file, current string, before, tree any) bool {
	raw, err := git.Bytes(ctx, root, "show", "HEAD:"+filepath.ToSlash(file))
	if err != nil || yamlmerge.HeaderOf(string(raw)) != yamlmerge.HeaderOf(current) {
		return false
	}
	return sameInOrder(before, tree)
}

func sameInOrder(a, b any) bool {
	switch x := a.(type) {
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !sameInOrder(x[i], y[i]) {
				return false
			}
		}
		return true
	case *yamlx.Map:
		y, ok := b.(*yamlx.Map)
		if !ok || len(x.Entries) != len(y.Entries) {
			return false
		}
		for _, e := range x.Entries {
			found := false
			for _, f := range y.Entries {
				if yamlx.PyStr(e.Key) == yamlx.PyStr(f.Key) {
					found = sameInOrder(e.Value, f.Value)
					break
				}
			}
			if !found {
				return false
			}
		}
		return true
	}
	return yamlmerge.Same(a, b)
}
