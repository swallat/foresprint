package gitsync

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/swallat/foresprint/internal/difflib"
	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/pytext"
	"github.com/swallat/foresprint/internal/yamlmerge"
	"github.com/swallat/foresprint/internal/yamlx"
)

// stages returns the unmerged files with the stages present (1 = base, 2 = mine, 3 = theirs).
func stages(ctx context.Context, root string) (map[string]map[int]bool, error) {
	out, err := git.With(ctx, root, git.Opts{Keep: true, Lenient: true}, "ls-files", "-u", "-z")
	if err != nil {
		return nil, err
	}
	result := map[string]map[int]bool{}
	for _, entry := range strings.Split(out, "\x00") {
		if entry == "" {
			continue
		}
		info, name, _ := strings.Cut(entry, "\t")
		fields := strings.Fields(info)
		if len(fields) < 3 {
			continue
		}
		stage, err := strconv.Atoi(fields[2])
		if err != nil {
			continue
		}
		if result[name] == nil {
			result[name] = map[int]bool{}
		}
		result[name][stage] = true
	}
	return result, nil
}

func stageText(ctx context.Context, root string, stage int, file string) (string, error) {
	return git.With(ctx, root, git.Opts{Keep: true}, "show", ":"+strconv.Itoa(stage)+":"+file)
}

// Upper limits of the text view (lines and characters per line), so that a large file does not
// blow up the page.
const (
	MaxDiffLines   = 300
	MaxDiffColumns = 400
)

// UnifiedDiff is the line-by-line difference (diff -u) of two texts, truncated; empty if equal.
func UnifiedDiff(old, new, oldName, newName string) string {
	lines := difflib.UnifiedDiff(pytext.SplitLines(old, false), pytext.SplitLines(new, false), oldName, newName, 2)
	kept := make([]string, len(lines))
	for i, line := range lines {
		kept[i] = truncateChars(line, MaxDiffColumns)
	}
	if len(kept) > MaxDiffLines {
		extra := len(kept) - MaxDiffLines
		kept = append(kept[:MaxDiffLines:MaxDiffLines], fmt.Sprintf("… (+%d)", extra))
	}
	return strings.Join(kept, "\n")
}

func truncateChars(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// ConflictTextDiffs shows how the file changed on both sides compared to the common state during
// an open merge, as text (diff -u): my side and the other side. Empty if that stage does not
// exist, the file is too large or not text.
func ConflictTextDiffs(ctx context.Context, path, file string) (mine, theirs string, err error) {
	root, err := Root(ctx, path)
	if err != nil {
		return "", "", err
	}
	present, err := stages(ctx, root)
	if err != nil {
		return "", "", err
	}
	have := present[file]
	text := func(stage int) (*string, bool) {
		if !have[stage] {
			return nil, true
		}
		size, _ := git.Lenient(ctx, root, "cat-file", "-s", ":"+strconv.Itoa(stage)+":"+file)
		n, convErr := strconv.Atoi(size)
		if convErr != nil || n > 1_000_000 {
			return nil, false
		}
		raw, bytesErr := git.Bytes(ctx, root, "show", ":"+strconv.Itoa(stage)+":"+file)
		if bytesErr != nil || !isUTF8(raw) {
			return nil, false
		}
		s := string(raw)
		return &s, true
	}
	var texts [3]*string
	for i, stage := range []int{1, 2, 3} {
		var ok bool
		if texts[i], ok = text(stage); !ok {
			return "", "", nil
		}
	}
	shown := ""
	if texts[0] != nil {
		shown = *texts[0]
	}
	one := func(side *string, label string) string {
		s := ""
		if side != nil {
			s = *side
		}
		return UnifiedDiff(shown, s, file+" ("+i18n.T("common state")+")", file+" ("+label+")")
	}
	return one(texts[1], i18n.T("my change")), one(texts[2], i18n.T("other change")), nil
}

func isUTF8(b []byte) bool { return bytes.Equal(bytes.ToValidUTF8(b, nil), b) }

// parseTree reads one YAML file with the codec; an empty file is an empty mapping.
func parseTree(text string) (any, error) {
	c := currentCodec()
	if c == nil {
		return nil, errors.New("gitsync: no YAML codec set")
	}
	tree, err := c.Parse(text)
	if err != nil {
		return nil, err
	}
	if tree == nil {
		return &yamlx.Map{}, nil
	}
	return tree, nil
}

// analyse checks a file: can it be merged at key level? It returns the open value conflicts and,
// if none remain, the merged text (merged is "" and hasMerged false otherwise).
func analyse(ctx context.Context, root, file string, present map[int]bool, choices yamlmerge.Choices) (info ConflictFile, merged string, hasMerged bool) {
	whole := ConflictFile{File: file, Whole: true, OursDeleted: !present[2], TheirsDeleted: !present[3]}
	if (!strings.HasSuffix(file, ".yaml") && !strings.HasSuffix(file, ".yml")) || !present[2] || !present[3] {
		return whole, "", false
	}
	oursText, err := stageText(ctx, root, 2, file)
	if err != nil {
		return whole, "", false
	}
	theirsText, err := stageText(ctx, root, 3, file)
	if err != nil {
		return whole, "", false
	}
	base := yamlmerge.Missing
	if present[1] {
		baseText, err := stageText(ctx, root, 1, file)
		if err != nil {
			return whole, "", false
		}
		if base, err = parseTree(baseText); err != nil {
			return whole, "", false
		}
	}
	ours, err := parseTree(oursText)
	if err != nil {
		return whole, "", false
	}
	theirs, err := parseTree(theirsText)
	if err != nil {
		return whole, "", false
	}
	_, oursIsMap := ours.(*yamlx.Map)
	_, theirsIsMap := theirs.(*yamlx.Map)
	if !oursIsMap || !theirsIsMap {
		return whole, "", false
	}
	tree, conflicts := yamlmerge.Merge3(base, ours, theirs, choices)
	if len(conflicts) > 0 {
		return ConflictFile{File: file, Keys: conflicts}, "", false
	}
	dumped, err := currentCodec().Dump(tree)
	if err != nil {
		return whole, "", false
	}
	header := oursText
	if header == "" {
		header = theirsText
	}
	return ConflictFile{File: file}, yamlmerge.HeaderOf(header) + dumped, true
}

func sortedFiles(m map[string]map[int]bool) []string {
	files := make([]string, 0, len(m))
	for f := range m {
		files = append(files, f)
	}
	sort.Strings(files)
	return files
}

// PendingConflicts returns the files of an unfinished merge: with their real value conflicts
// (none = can be merged automatically) or to be decided as a whole.
func PendingConflicts(ctx context.Context, path string) ([]ConflictFile, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return nil, err
	}
	present, err := stages(ctx, root)
	if err != nil {
		return nil, err
	}
	var out []ConflictFile
	for _, file := range sortedFiles(present) {
		info, _, _ := analyse(ctx, root, file, present[file], nil)
		out = append(out, info)
	}
	return out, nil
}

// Choices are the decisions for the conflicts of an unfinished merge: file -> path -> "ours" or
// "theirs". The empty path (nil) decides a file as a whole.
type Choices map[string]yamlmerge.Choices

// ResolveConflicts resolves everything that can be resolved: files without a value conflict
// automatically, the rest according to choices. It returns the remaining conflicts. The merge is
// only completed by Sync.
func ResolveConflicts(ctx context.Context, path string, choices Choices) ([]ConflictFile, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return nil, err
	}
	present, err := stages(ctx, root)
	if err != nil {
		return nil, err
	}
	for _, file := range sortedFiles(present) {
		wanted := choices[file]
		info, merged, hasMerged := analyse(ctx, root, file, present[file], wanted)
		switch {
		case info.Whole:
			choice, decided := wanted[yamlmerge.Path(nil).Key()]
			if !decided {
				continue
			}
			keep, flag := 3, "--theirs"
			if choice == yamlmerge.Ours {
				keep, flag = 2, "--ours"
			}
			if present[file][keep] {
				if _, err := git.Git(ctx, root, "checkout", flag, "--", file); err != nil {
					return nil, err
				}
				if _, err := git.Git(ctx, root, "add", "--", file); err != nil {
					return nil, err
				}
			} else { // deleted on this side
				if _, err := git.Git(ctx, root, "rm", "-q", "--", file); err != nil {
					return nil, err
				}
			}
		case hasMerged:
			if err := os.WriteFile(filepath.Join(root, file), []byte(merged), 0o666); err != nil {
				// locked or read-only: the merge stays open. The kind stays "locked" ("A file is
				// locked"): Windows reports a file held by another program as "Permission denied",
				// like a read-only one, and the error number does not reliably tell them apart.
				// Unlike with Git's index.lock, only the hint about the file fits here.
				return nil, git.New(i18n.T("{file} could not be written ({reason}).",
					"file", file, "reason", reason(err)), "locked", git.UnwritableFileHint())
			}
			if _, err := git.Git(ctx, root, "add", "--", file); err != nil {
				return nil, err
			}
		}
	}
	git.InvalidateStatus()
	return PendingConflicts(ctx, path)
}

func reason(err error) string {
	var errno syscall.Errno
	if errors.As(err, &errno) {
		s := errno.Error()
		if s != "" {
			return strings.ToUpper(s[:1]) + s[1:]
		}
	}
	return err.Error()
}

// Issues of the data check.
func issueSet(ctx context.Context, dir string, today time.Time) (map[Issue]bool, error) {
	check := currentValidator()
	if check == nil {
		return map[Issue]bool{}, nil
	}
	issues, err := check(ctx, dir, today)
	if err != nil {
		return nil, err
	}
	// Without the folder in the text: the comparison of working state against commit runs in
	// different folders, and load errors name the file path.
	relative := func(text string) string {
		return strings.ReplaceAll(strings.ReplaceAll(text, dir+string(os.PathSeparator), ""), dir, "")
	}
	set := map[Issue]bool{}
	for _, i := range issues {
		set[Issue{i.Key, relative(i.Where), relative(i.Message)}] = true
	}
	return set, nil
}

// errorsAt returns the errors of the full validation for the state of a commit (without checking
// it out).
func errorsAt(ctx context.Context, root, path, rev string, today time.Time) (map[Issue]bool, error) {
	rel, err := filepath.Rel(git.Resolve(root), git.Resolve(path))
	if err != nil {
		return nil, err
	}
	rel = filepath.ToSlash(rel)
	tree := rev
	if rel != "." {
		tree = rev + ":" + rel
	}
	data, err := git.Bytes(ctx, root, "archive", "--format=tar", tree)
	if err != nil {
		if git.As(err) != nil {
			return map[Issue]bool{}, nil
		}
		return nil, err
	}
	tmp, err := os.MkdirTemp("", "foresprint-archive-")
	if err != nil {
		return nil, err
	}
	defer func() { _ = os.RemoveAll(tmp) }()
	if err := extract(data, tmp); err != nil {
		return nil, err
	}
	return issueSet(ctx, tmp, today)
}

// extract unpacks a tar archive of Git into dir: regular files and folders only, nothing outside
// of dir.
func extract(data []byte, dir string) error {
	reader := tar.NewReader(bytes.NewReader(data))
	for {
		header, err := reader.Next()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		name := filepath.Clean(filepath.FromSlash(header.Name))
		if filepath.IsAbs(name) || name == ".." || strings.HasPrefix(name, ".."+string(filepath.Separator)) {
			return fmt.Errorf("unsafe path in archive: %q", header.Name)
		}
		target := filepath.Join(dir, name)
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			file, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, fs.FileMode(0o644))
			if err != nil {
				return err
			}
			if _, err := io.Copy(file, reader); err != nil {
				_ = file.Close()
				return err
			}
			if err := file.Close(); err != nil {
				return err
			}
		}
	}
}

// NewErrors returns the errors of the full validation in the working state that were not yet
// present in the state baseline (commit), as readable lines.
func NewErrors(ctx context.Context, path, baseline string, today time.Time) ([]string, error) {
	root, err := Root(ctx, path)
	if err != nil {
		return nil, err
	}
	if today.IsZero() {
		today = time.Now()
	}
	now, err := issueSet(ctx, path, today)
	if err != nil {
		return nil, err
	}
	before, err := errorsAt(ctx, root, path, baseline, today)
	if err != nil {
		return nil, err
	}
	var found []Issue
	for i := range now {
		if !before[i] {
			found = append(found, i)
		}
	}
	sort.Slice(found, func(a, b int) bool {
		x, y := found[a], found[b]
		if x.Key != y.Key {
			return x.Key < y.Key
		}
		if x.Where != y.Where {
			return x.Where < y.Where
		}
		return x.Message < y.Message
	})
	lines := make([]string, len(found))
	for i, f := range found {
		lines[i] = f.Key + ": " + f.Where + ": " + f.Message
	}
	return lines, nil
}
