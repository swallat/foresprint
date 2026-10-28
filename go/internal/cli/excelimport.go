package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/yamlx"
)

func init() { Register(excelImportCommand) }

// importPreviewLimit is the number of changes the preview lists.
const importPreviewLimit = 200

func excelImportCommand(env *Env) *cobra.Command {
	var apply bool
	cmd := &cobra.Command{
		Use:   "excel-import TEAM FILE",
		Short: i18n.T("Read an Excel list back from the Excel output: preview the changes, write them with --apply."),
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			return runExcelImport(env, args[0], args[1], apply)
		},
	}
	teamArg(env, cmd)
	cmd.Flags().BoolVar(&apply, "apply", false, i18n.T("Write the changes (otherwise preview only)."))
	return cmd
}

func runExcelImport(env *Env, key, file string, apply bool) error {
	content, err := os.ReadFile(file)
	if err != nil {
		return Failf("{path}: not readable ({reason})", "path", file, "reason", err.Error())
	}
	data, fileTeam, err := excel.ReadWorkbook(content, key)
	if err != nil {
		return asFail(err)
	}
	if fileTeam == nil {
		_, _ = fmt.Fprintln(env.Err, i18n.P("The workbook names no team (older Excel export); it is not checked whether it "+
			"belongs to {team}.", "team", yamlx.PyRepr(key)))
	}
	plan, err := excel.Plan(env.Repo(), data, env.TodayFor(data))
	if err != nil {
		return asFail(err)
	}
	if len(plan.Changes) == 0 {
		env.Println(i18n.P("No changes compared to the existing files."))
		return nil
	}
	t := &Table{Header: []string{i18n.T("File"), i18n.T("Value"), i18n.T("before"), i18n.T("new")}}
	for i, c := range plan.Changes {
		if i == importPreviewLimit {
			break
		}
		t.Add(textfmt.BlankControls(c.File), textfmt.BlankControls(c.Path), changeText(c.Old), changeText(c.New))
	}
	t.Render(env.Out)
	if n := len(plan.Changes); n > importPreviewLimit {
		env.Println(i18n.P("… and {count} more changes", "count", n-importPreviewLimit))
	}
	for _, name := range plan.Untouched {
		env.Println(i18n.P("Not in the workbook, stays unchanged: {file}", "file", textfmt.BlankControls(name)))
	}
	if !apply {
		env.Println(i18n.P("Preview only – write with --apply."))
		return nil
	}
	paths, err := excel.Apply(env.Repo(), plan)
	if err != nil {
		return asFail(err)
	}
	for _, p := range paths {
		env.Println(p)
	}
	return nil
}

// changeText is a value of the preview; a missing value shows as a dash.
func changeText(v any) string {
	if v == nil {
		return "–"
	}
	return textfmt.BlankControls(yamlx.PyStr(v))
}
