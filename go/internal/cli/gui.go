package cli

import (
	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
)

// GUI opens the window of the program; it is set by the main package of a build that has the
// window (build tag "desktop", see internal/desktop). dataDir is the data folder in use. Nil
// in a build without the window.
var GUI func(dataDir string) error

func init() { Register(guiCommand) }

func guiCommand(env *Env) *cobra.Command {
	cmd := &cobra.Command{
		Use:    "gui",
		Short:  i18n.P("Open the window."),
		Hidden: GUI == nil,
		RunE: func(*cobra.Command, []string) error {
			if GUI == nil {
				return &Fail{Msg: i18n.T("This build has no window.")}
			}
			if env.Fresh {
				return startFresh(env)
			}
			return GUI(env.DataDir())
		},
	}
	cmd.Flags().BoolVar(&env.Fresh, "fresh", false, i18n.P(
		"Open the window as on the very first start, with empty settings and no remembered data folder. Nothing saved is read, changed or deleted; settings made in this session are discarded at the end."))
	return cmd
}
