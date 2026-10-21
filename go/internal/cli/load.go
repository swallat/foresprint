package cli

import (
	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/storage"
)

// Repo is the repository of the data folder in use.
func (e *Env) Repo() *storage.Repository { return storage.NewRepository(e.DataDir()) }

// LoadTeam loads a team; a data error becomes a message with the exit code 1.
func (e *Env) LoadTeam(key string) (*storage.TeamData, error) {
	data, err := e.Repo().Load(key)
	if err != nil {
		return nil, asFail(err)
	}
	return data, nil
}

// asFail turns a data error into a failure that prints its message; other errors stay.
func asFail(err error) error {
	if storage.IsDataError(err) {
		return &Fail{Msg: err.Error()}
	}
	return err
}

// teamArg is the first argument of most commands: the team (folder name).
func teamArg(env *Env, cmd *cobra.Command) {
	cmd.ValidArgsFunction = func(c *cobra.Command, args []string, prefix string) ([]string, cobra.ShellCompDirective) {
		switch len(args) {
		case 0:
			return TeamNames(env)(c, args, prefix)
		case 1:
			return SprintIDs(env)(c, args, prefix)
		}
		return nil, cobra.ShellCompDirectiveNoFileComp
	}
}
