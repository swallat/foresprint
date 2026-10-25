package app

import "github.com/swallat/foresprint/internal/storage"

// loadTeam reads a team of the data folder from its files (no cache: every call parses them).
func (a *API) loadTeam(key string) (*storage.TeamData, error) {
	return storage.NewRepository(a.DataDir()).Load(key)
}
