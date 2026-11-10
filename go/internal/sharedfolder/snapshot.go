package sharedfolder

import (
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Retention of the snapshots: daily ones for 30 days, the weekly full ones for 12 weeks.
const (
	KeepDays  = 30
	KeepFulls = 12
)

func snapshotDir(root string) string { return filepath.Join(root, Dir, "snapshots") }

// Snapshot keeps the state of the files before a save, as the daily snapshot: the first save of a
// day stores the state of each file it changes; later saves of the same day add files not yet
// stored (the oldest state of the day wins). On the first save of a week (Monday on or after the
// last full snapshot is 7 days old) a full copy of all data files is stored as well. rel lists the
// files the save is about to change, relative to root; skip decides which files belong to the
// data (team folders) for the full copy. Old snapshots are removed after.
func Snapshot(root string, rel []string, now time.Time, isData func(rel string) bool) error {
	day := now.Format("2006-01-02")
	for _, r := range rel {
		src := filepath.Join(root, filepath.FromSlash(r))
		dst := filepath.Join(snapshotDir(root), day, filepath.FromSlash(r))
		if _, err := os.Stat(dst); err == nil {
			continue
		}
		data, err := os.ReadFile(src)
		if err != nil {
			continue // a new file has no earlier state
		}
		if err := WriteFile(dst, data, time.Second); err != nil {
			return err
		}
	}
	if needFull(root, now) {
		full := filepath.Join(snapshotDir(root), day+"-full")
		err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			r, _ := filepath.Rel(root, p)
			r = filepath.ToSlash(r)
			if d.IsDir() {
				if r == Dir {
					return filepath.SkipDir
				}
				return nil
			}
			if !isData(r) {
				return nil
			}
			data, err := os.ReadFile(p)
			if err != nil {
				return nil
			}
			return WriteFile(filepath.Join(full, filepath.FromSlash(r)), data, time.Second)
		})
		if err != nil {
			return err
		}
	}
	return prune(root)
}

func needFull(root string, now time.Time) bool {
	names := snapshotNames(root, true)
	if len(names) == 0 {
		return true
	}
	last, err := time.Parse("2006-01-02", strings.TrimSuffix(names[len(names)-1], "-full"))
	return err != nil || now.Sub(last) >= 7*24*time.Hour
}

// snapshotNames lists the snapshot folders, oldest first; full selects the "-full" ones.
func snapshotNames(root string, full bool) []string {
	entries, _ := os.ReadDir(snapshotDir(root))
	out := []string{}
	for _, e := range entries {
		if e.IsDir() && strings.HasSuffix(e.Name(), "-full") == full {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

func prune(root string) error {
	for _, full := range []bool{false, true} {
		names := snapshotNames(root, full)
		keep := KeepDays
		if full {
			keep = KeepFulls
		}
		for len(names) > keep {
			if err := os.RemoveAll(filepath.Join(snapshotDir(root), names[0])); err != nil {
				return err
			}
			names = names[1:]
		}
	}
	return nil
}

// SnapshotFile returns the file as it was in the newest snapshot on or before day ("2006-01-02"),
// looking at the daily snapshots first and the full ones for files no daily snapshot has.
func SnapshotFile(root, rel string, day string) ([]byte, bool) {
	var cands []string
	for _, full := range []bool{false, true} {
		for _, n := range snapshotNames(root, full) {
			if strings.TrimSuffix(n, "-full") <= day {
				cands = append(cands, n)
			}
		}
	}
	sort.Slice(cands, func(i, j int) bool {
		return strings.TrimSuffix(cands[i], "-full") > strings.TrimSuffix(cands[j], "-full")
	})
	for _, n := range cands {
		if data, err := os.ReadFile(filepath.Join(snapshotDir(root), n, filepath.FromSlash(rel))); err == nil {
			return data, true
		}
	}
	return nil, false
}
