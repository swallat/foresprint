package app

import "github.com/swallat/foresprint/internal/storage"

// loadTeam reads a team of the data folder (the cache of the storage makes repeated calls cheap).
func (a *API) loadTeam(key string) (*storage.TeamData, error) {
	return storage.NewRepository(a.DataDir()).Load(key)
}
