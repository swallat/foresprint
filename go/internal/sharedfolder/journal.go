package sharedfolder

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Entry is one line of the journal: one save.
type Entry struct {
	ID      string            `json:"id"`
	Who     string            `json:"who"`
	Time    time.Time         `json:"time"`
	Summary string            `json:"summary"`
	Files   map[string]Change `json:"files"` // by path relative to the shared folder
}

// Change records one file of a save by the checksums before and after ("" = did not exist /
// was deleted).
type Change struct {
	Before string `json:"before"`
	After  string `json:"after"`
}

var unsafeName = regexp.MustCompile(`[^\pL\pN._-]+`)

// PersonFile is the journal file name of a person.
func PersonFile(who string) string {
	n := strings.Trim(unsafeName.ReplaceAllString(who, "_"), "._")
	if n == "" {
		n = "unknown"
	}
	return n + ".jsonl"
}

func journalDir(root string) string { return filepath.Join(root, Dir, "journal") }

// Append adds an entry to the journal of its author. Each person has a file of their own, so two
// people never write to the same file and sync services have nothing to conflict on.
func Append(root string, e Entry) error {
	if err := os.MkdirAll(journalDir(root), 0o755); err != nil {
		return err
	}
	line, err := json.Marshal(e)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(journalDir(root), PersonFile(e.Who)), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, werr := f.Write(append(line, '\n'))
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	return werr
}

// ReadJournal reads all journals, newest entry first. Lines that do not read are skipped (a sync
// service may deliver a file half written).
func ReadJournal(root string) ([]Entry, error) {
	files, err := filepath.Glob(filepath.Join(journalDir(root), "*.jsonl"))
	if err != nil {
		return nil, err
	}
	out := []Entry{}
	for _, name := range files {
		f, err := os.Open(name)
		if err != nil {
			continue
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 16<<20)
		for sc.Scan() {
			var e Entry
			if json.Unmarshal(sc.Bytes(), &e) == nil && e.ID != "" {
				out = append(out, e)
			}
		}
		f.Close()
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Time.After(out[j].Time) })
	return out, nil
}
