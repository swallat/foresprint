// Command foresprint is the Go core of Foresprint: the command line and, later, the window
// shell (Wails) in one program (go/README.md).
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/cli"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/selfupdate"
)

// version is set at build time: -ldflags "-X main.version=1.0.0".
var version = "dev"

func init() {
	cli.Version = version
	cli.AfterRun = cli.AutoUpdate
	cli.Register(versionCommand)
}

func main() {
	reportBegin(os.Args[1:])
	defer func() {
		if r := recover(); r != nil {
			reportFailure("Foresprint stopped unexpectedly.", fmt.Errorf("%v", r))
			os.Exit(2)
		}
	}()
	selfupdate.CleanupOld()
	code := cli.Execute(os.Args[1:], os.Stdin, os.Stdout, os.Stderr)
	reportEnd(os.Args[1:], code)
	os.Exit(code)
}

func versionCommand(env *cli.Env) *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Show the version and the data it was built with.",
		Run: func(*cobra.Command, []string) {
			info := holidays.Info()
			_, _ = fmt.Fprintf(env.Out, "foresprint %s (go core, holidays %s, %d-%d)\n",
				version, info.HolidaysVersion, info.FirstYear, info.LastYear)
		},
	}
}
