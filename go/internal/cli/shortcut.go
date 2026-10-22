package cli

import (
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/shortcut"
)

func init() { Register(shortcutCommand) }

func shortcutCommand(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:   "shortcut",
		Short: i18n.T("Create a launcher to double-click (desktop/start menu, macOS: Applications)."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			program, err := os.Executable()
			if err != nil {
				return Failf("The program path is unknown.")
			}
			if resolved, err := filepath.EvalSymlinks(program); err == nil {
				program = resolved
			}
			paths, err := shortcut.Create(shortcut.Options{Program: program})
			if err != nil {
				return &Fail{Msg: err.Error()}
			}
			for _, p := range paths {
				env.Println(i18n.P("Created: {path}", "path", p))
			}
			env.Println(i18n.P("Double-click starts Foresprint. The data folder is set up on first start."))
			return nil
		},
	}
}
