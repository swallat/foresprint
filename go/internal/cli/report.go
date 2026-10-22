package cli

import (
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/report"
	"github.com/swallat/foresprint/internal/storage"
)

func init() { Register(reportCommand) }

func reportCommand(env *Env) *cobra.Command {
	var output string
	cmd := &cobra.Command{
		Use:   "report [TEAM]",
		Short: i18n.T("Create the Markdown report (for the Git web interface / PO round)."),
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			repo := env.Repo()
			teams := repo.Teams()
			if len(args) > 0 {
				teams = args
			}
			for _, key := range teams {
				data, err := env.LoadTeam(key)
				if err != nil {
					return err
				}
				fc, err := forecast.Build(data, env.Today)
				if err != nil {
					return asFail(err)
				}
				text, err := report.Render(fc, 10)
				if err != nil {
					return asFail(err)
				}
				if output == "-" {
					_, _ = env.Out.Write([]byte(text))
					continue
				}
				target := filepath.Join(repo.TeamDir(key), "FORECAST.md")
				if output != "" && len(args) > 0 {
					target = output
				}
				if err := storage.WriteText(target, text); err != nil {
					return asFail(err)
				}
				env.Println(target)
			}
			return nil
		},
	}
	cmd.Flags().StringVarP(&output, "output", "o", "", i18n.T("File; default <team>/FORECAST.md, - = stdout."))
	cmd.ValidArgsFunction = func(c *cobra.Command, args []string, prefix string) ([]string, cobra.ShellCompDirective) {
		return TeamNames(env)(c, args, prefix)
	}
	return cmd
}
