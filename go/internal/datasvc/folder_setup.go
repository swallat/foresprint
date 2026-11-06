package datasvc

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/sharedfolder"
)

// SharedFolderCheck is the result of testing a folder for the shared storage.
type SharedFolderCheck struct {
	OK      bool                       `json:"ok"`
	Results []sharedfolder.CheckResult `json:"results"`
	// HasData: the folder already holds team data (then the local copy takes it over).
	HasData bool `json:"hasData"`
	// Service names a sync service recognised from the path ("" = none).
	Service string `json:"service"`
}

var serviceHints = []struct{ marker, name string }{
	{"dropbox", "Dropbox"}, {"nextcloud", "Nextcloud"}, {"onedrive", "OneDrive"},
	{"sharepoint", "SharePoint"}, {"owncloud", "ownCloud"}, {"syncthing", "Syncthing"},
}

// CheckSharedFolder tests a folder for use as the shared storage. It writes only a temporary
// subfolder that it removes again.
func (s *Store) CheckSharedFolder(shared string) SharedFolderCheck {
	out := SharedFolderCheck{Results: sharedfolder.Check(shared)}
	out.OK = len(out.Results) > 0
	for _, r := range out.Results {
		if !r.OK {
			out.OK = false
		}
	}
	low := strings.ToLower(shared)
	for _, h := range serviceHints {
		if strings.Contains(low, h.marker) {
			out.Service = h.name
		}
	}
	files, _ := scan(shared)
	out.HasData = len(files) > 0
	return out
}

// UseSharedFolder sets the data folder local up as a copy of the shared folder, for the person
// with the given name (empty = the user of the computer). The shared folder gets a small file that
// says it is a shared storage. Existing data on either side is kept; the first Refresh takes over
// what the shared folder has (a local file the shared folder lacks becomes an unsaved change).
func (s *Store) UseSharedFolder(local, shared, person string) Opened {
	if local == "" || shared == "" {
		return Opened{Problem: problemOf(git.New(i18n.T("Choose a folder first."), "path", ""))}
	}
	local, err1 := filepath.Abs(local)
	shared, err2 := filepath.Abs(shared)
	if err1 != nil || err2 != nil {
		return Opened{Problem: problemOf(git.New(i18n.T("The folder {path} does not exist.", "path", shared), "path", ""))}
	}
	if info, err := os.Stat(shared); err != nil || !info.IsDir() {
		return Opened{Problem: problemOf(git.New(i18n.T("The folder {path} does not exist.", "path", shared), "path", ""))}
	}
	if local == shared || strings.HasPrefix(local, shared+string(filepath.Separator)) || strings.HasPrefix(shared, local+string(filepath.Separator)) {
		return Opened{Problem: problemOf(git.New(i18n.T("The local copy and the shared folder must be different folders, neither inside the other."), "path", ""))}
	}
	if _, err := os.Stat(filepath.Join(local, ".git")); err == nil {
		return Opened{Problem: problemOf(git.New(i18n.T("The folder {path} is a Git repository already.", "path", local), "path", ""))}
	}
	if err := os.MkdirAll(local, 0o755); err != nil {
		return Opened{Problem: problemOf(err)}
	}
	marker := filepath.Join(shared, sharedfolder.Dir, "storage.yaml")
	if _, err := os.Stat(marker); err != nil {
		if err := sharedfolder.WriteFile(marker, []byte("kind: folder\nformat: 1\n"), 2*1e9); err != nil {
			return Opened{Problem: problemOf(err)}
		}
	}
	cfg := folderConfig{Kind: KindFolder, Shared: shared, Person: strings.TrimSpace(person)}
	if err := writeFolderConfig(local, cfg); err != nil {
		return Opened{Problem: problemOf(err)}
	}
	s.SetFolder(local)
	if res := s.Refresh(); res.Problem != nil && res.Outcome != OutcomeOffline {
		return Opened{Folder: local, Problem: res.Problem}
	}
	return Opened{Folder: local}
}
