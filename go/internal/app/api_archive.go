package app

import (
	"errors"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
)

// ArchiveTeam moves a team out of the way without deleting anything: its folder goes to the
// archive folder of the data folder, and the window no longer lists it. confirm must be the
// name (or key) of the team, so that no click alone archives a team. Git shows a move; the team
// comes back with RestoreTeam.
func (a *API) ArchiveTeam(team, confirm string) error {
	repo := storage.NewRepository(a.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		return err
	}
	typed := strings.ToLower(strings.TrimSpace(confirm))
	if typed == "" || (typed != strings.ToLower(data.Team.Name) && typed != strings.ToLower(team)) {
		return errors.New(i18n.T("Type the name of the team to archive it."))
	}
	a.mu.Lock()
	busy := a.run.syncing[team]
	a.mu.Unlock()
	if busy {
		return errors.New(i18n.T("A sync is running for this team. Archive it afterwards."))
	}
	a.forget(team)
	return repo.ArchiveTeam(team)
}

// ArchivedTeams lists the archived teams of the data folder.
func (a *API) ArchivedTeams() []TeamSummary {
	repo := storage.NewRepository(a.DataDir())
	out := []TeamSummary{}
	for _, key := range repo.ArchivedTeams() {
		name := key
		if data, err := storage.NewRepository(filepath.Join(repo.Root, storage.ArchiveDir)).Load(key); err == nil {
			name = data.Team.Name
		}
		out = append(out, TeamSummary{Key: key, Name: name})
	}
	return out
}

// RestoreTeam brings an archived team back into the data folder.
func (a *API) RestoreTeam(team string) error {
	return storage.NewRepository(a.DataDir()).RestoreTeam(team)
}
