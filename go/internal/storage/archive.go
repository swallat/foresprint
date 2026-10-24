package storage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// ArchiveDir is the folder inside the data folder that holds archived teams. Its name starts with
// an underscore, so that it can never be the key of a team (TeamKeyProblem).
const ArchiveDir = "_archiv"

// ArchivedTeams are the keys of the archived teams, sorted.
func (r *Repository) ArchivedTeams() []string {
	entries, err := os.ReadDir(filepath.Join(r.Root, ArchiveDir))
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if fileExists(filepath.Join(r.Root, ArchiveDir, e.Name(), "team.yaml")) {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

// ArchiveTeam moves the whole folder of a team into the archive folder. Nothing is deleted: Git
// sees a move, and RestoreTeam puts the folder back.
func (r *Repository) ArchiveTeam(key string) error {
	if !r.Exists(key) {
		return errors.New(tr("The team {team} does not exist.", "team", key))
	}
	to := filepath.Join(r.Root, ArchiveDir, key)
	if _, err := os.Lstat(to); err == nil {
		return errors.New(tr("The archive already holds a team {team}. Restore or remove that one first.", "team", key))
	}
	if err := os.MkdirAll(filepath.Dir(to), 0o755); err != nil {
		return fmt.Errorf("%s: %w", filepath.Dir(to), err)
	}
	if err := os.Rename(r.TeamDir(key), to); err != nil {
		return errors.New(tr("The team could not be moved to the archive ({reason}).", "reason", reason(err)))
	}
	OnWrite()
	return nil
}

// RestoreTeam moves an archived team back to the data folder.
func (r *Repository) RestoreTeam(key string) error {
	from := filepath.Join(r.Root, ArchiveDir, key)
	if !fileExists(filepath.Join(from, "team.yaml")) {
		return errors.New(tr("The archive holds no team {team}.", "team", key))
	}
	if _, clash := r.ClashingTeam(key); clash {
		return errors.New(tr("A team {team} exists already; it cannot be restored under the same name.", "team", key))
	}
	if _, err := os.Lstat(r.TeamDir(key)); err == nil {
		return errors.New(tr("A team {team} exists already; it cannot be restored under the same name.", "team", key))
	}
	if err := os.Rename(from, r.TeamDir(key)); err != nil {
		return errors.New(tr("The team could not be restored ({reason}).", "reason", reason(err)))
	}
	OnWrite()
	return nil
}
