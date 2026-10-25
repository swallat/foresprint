package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
)

// Serve shows the program as a page of the browser until interrupted; it is set by the main
// package of a build that has the window (build tag "desktop"). It prints the link with out.
// Nil in a build without the window.
var Serve func(dataDir string, out func(string)) error

func init() { Register(serveCommand) }

func serveCommand(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:    "serve",
		Short:  i18n.P("Show the program in the browser (this computer only)."),
		Hidden: Serve == nil,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if Serve == nil {
				return &Fail{Msg: i18n.T("This build has no window.")}
			}
			return Serve(env.DataDir(), func(link string) {
				fmt.Fprintln(cmd.OutOrStdout(), i18n.T("Open this link in your browser (stop with Ctrl+C):"))
				fmt.Fprintln(cmd.OutOrStdout(), link)
			})
		},
	}
}
