// Command foresprint is the Go core of Foresprint: the command line and, later, the window
// shell (Wails) in one program (go/README.md).
package main

import (
	"fmt"
	"os"
	"runtime/debug"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/cli"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/selfupdate"
)

// version is set at build time: -ldflags "-X main.version=1.0.0".
var version = "dev"

// commit is the git commit of a local build: -ldflags "-X main.commit=abc1234" (scripts/build.mjs).
var commit = ""

func init() {
	version = withCommit(version, commit)
	cli.Version = version
	cli.AfterRun = cli.AutoUpdate
	cli.Register(versionCommand)
}

// withCommit makes a development build show its commit ("dev (abc1234)"). A release version is
// left alone; it is not a development build, and the update check compares it.
func withCommit(v, c string) string {
	if v != "dev" || c == "" {
		return v
	}
	return v + " (" + c + ")"
}

func main() { os.Exit(run()) }

// run is main without the exit, so that a panic is logged (and shown to a double click) first.
func run() (code int) {
	reportBegin(os.Args[1:])
	defer func() {
		if r := recover(); r != nil {
			reportLog("panic: %v\n%s", r, debug.Stack())
			if len(os.Args) == 1 {
				reportFailure("Foresprint stopped unexpectedly.", fmt.Errorf("%v", r))
			}
			code = 2
		}
	}()
	selfupdate.CleanupOld()
	code = cli.Execute(os.Args[1:], os.Stdin, os.Stdout, os.Stderr)
	reportEnd(os.Args[1:], code)
	return code
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
