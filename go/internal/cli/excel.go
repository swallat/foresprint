package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
)

func init() { Register(excelCommand) }

func excelCommand(env *Env) *cobra.Command {
	var output string
	cmd := &cobra.Command{
		Use:   "excel TEAM",
		Short: i18n.T("Write a team's Excel list (formulas, trend chart, split per product)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			key := args[0]
			data, err := env.LoadTeam(key)
			if err != nil {
				return err
			}
			for _, w := range excel.ImportUnsafeSprintIDs(data) {
				_, _ = fmt.Fprintln(env.Err, w)
			}
			fc, err := forecast.Build(data, env.TodayFor(data))
			if err != nil {
				return asFail(err)
			}
			content, err := excel.Build(fc)
			if err != nil {
				return asFail(err)
			}
			target := output
			if target == "" {
				target = key + "-forecast.xlsx"
			}
			if err := os.WriteFile(target, content, 0o644); err != nil {
				return Failf("{path}: not written ({reason})", "path", target, "reason", err.Error())
			}
			env.Println(target)
			return nil
		},
	}
	teamArg(env, cmd)
	cmd.Flags().StringVarP(&output, "output", "o", "", i18n.T("File; default <team>-forecast.xlsx in the current folder (not in the data "+
		"folder: spreadsheets are not committed)."))
	return cmd
}
