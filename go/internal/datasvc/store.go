package datasvc

import (
	"context"
	"path/filepath"
	"sync"
	"time"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/i18n"
)

// Store is the storage of the data folder as the window uses it. Today only Git is built; the
// methods are the operations of the storage interface (status, save, refresh, conflicts,
// history, restore, revert, capabilities), so that a shared folder can sit behind the same
// calls after 1.0.
type Store struct {
	mu  sync.Mutex
	dir string
	// today is the day the data check runs for; tests set it.
	today func() time.Time
	// review remembers the address of the merge request of the last save.
	review string
}

// New returns the storage of the data folder dir (the folder with the team folders).
func New(dir string) *Store {
	s := &Store{today: time.Now}
	s.SetFolder(dir)
	return s
}

// SetFolder points the storage to another data folder.
func (s *Store) SetFolder(dir string) {
	if dir != "" {
		if abs, err := filepath.Abs(dir); err == nil {
			dir = abs
		}
	}
	s.mu.Lock()
	s.dir = dir
	s.review = ""
	s.mu.Unlock()
}

// Folder is the data folder.
func (s *Store) Folder() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.dir
}

func (s *Store) ctx() context.Context { return context.Background() }

// folder is the data folder, or the error "no folder chosen": without one, Git would work on
// whatever repository holds the current directory of the process.
func (s *Store) folder() (string, error) {
	if dir := s.Folder(); dir != "" {
		return dir, nil
	}
	return "", git.New(i18n.T("No data folder chosen."), "path", "")
}

func (s *Store) setReview(link string) {
	s.mu.Lock()
	s.review = link
	s.mu.Unlock()
}

func (s *Store) lastReview() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.review
}

// Abort stops the save or refresh that is running (Git is told to stop; what was saved stays).
func (s *Store) Abort() bool {
	dir, err := s.folder()
	if err != nil {
		return false
	}
	return gitsync.AbortRunningSync(s.ctx(), dir)
}

// names lists the people who made the commits, each once, in the order they came.
func names(commits []gitsync.Commit) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, c := range commits {
		if c.Author != "" && !seen[c.Author] {
			seen[c.Author] = true
			out = append(out, c.Author)
		}
	}
	return out
}

// who writes the people as "Anna", "Anna and Ben" or "Anna and 2 others".
func who(people []string) string {
	switch len(people) {
	case 0:
		return i18n.T("others")
	case 1:
		return people[0]
	case 2:
		return i18n.T("{first} and {second}", "first", people[0], "second", people[1])
	}
	return i18n.T("{first} and {count} others", "first", people[0], "count", len(people)-1)
}

func changeOf(c gitsync.Commit) Change {
	return Change{Who: c.Author, Day: c.Day, Summary: c.Subject}
}

func changes(commits []gitsync.Commit) []Change {
	out := make([]Change, 0, len(commits))
	for _, c := range commits {
		out = append(out, changeOf(c))
	}
	return out
}
