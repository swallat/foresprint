package cli

import (
	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/validate"
)

func init() { Register(checkCommand) }

func checkCommand(env *Env) *cobra.Command {
	var strict bool
	cmd := &cobra.Command{
		Use:   "check",
		Short: i18n.T("Check all team data for errors and plausibility (for CI and before committing)."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			repo := env.Repo()
			teams := repo.Teams()
			if len(teams) == 0 {
				return Failf("No teams found in {root}", "root", repo.Root)
			}
			failed := false
			for _, key := range teams {
				issues := checkTeam(repo, key, env)
				if len(issues) == 0 {
					env.Println("✔ " + textfmt.BlankControls(key))
					continue
				}
				env.Println(textfmt.BlankControls(key))
				for _, i := range issues {
					env.Printf("  %s %s: %s\n", i18n.T(string(i.Level)),
						textfmt.BlankControls(i.Where), textfmt.BlankControls(i.Message))
					failed = failed || i.Level == validate.Error || strict
				}
			}
			if failed {
				return errExit1
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&strict, "strict", false, i18n.T("Treat notes as errors too."))
	return cmd
}

// checkTeam is the data check of one team: the findings of the data and of the files; a data
// error while loading is a finding.
func checkTeam(repo *storage.Repository, key string, env *Env) []validate.Issue {
	data, err := repo.Load(key)
	if err != nil {
		return []validate.Issue{{Level: validate.Error, Where: key, Message: err.Error()}}
	}
	issues := validate.CheckTeam(data, env.TodayFor(data))
	return append(issues, validate.CheckFiles(repo.TeamDir(key), data.Team.Features)...)
}
