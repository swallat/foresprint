// Package cli is the command line of Foresprint: the same commands as the Python version, as
// subcommands of the one program. Output is plain text (no colours, no boxes), so that it reads
// the same in a terminal, a log and a pipe.
//
// A command is a file with an init function that calls Register; the builder gets the Env that
// holds the global options (--data, --as-of) and the streams. Tests call Execute with their own
// streams.
package cli

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/config"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
)

// Environment variables of the program.
const (
	DataEnv  = "FORESPRINT_DATA"
	AsOfEnv  = "FORESPRINT_AS_OF"
	progName = "foresprint"
)

// Version is set by the program at start (a build number such as "1.0.0").
var Version = "dev"

// Env is what a command needs from the global options and the process.
type Env struct {
	// Data is the value of --data / FORESPRINT_DATA ("" = not given; see DataDir).
	Data string
	// AsOf is the value of --as-of / FORESPRINT_AS_OF ("" = not given).
	AsOf string
	// Today is the date that counts as today: --as-of or the clock.
	Today time.Time

	In  io.Reader
	Out io.Writer
	Err io.Writer

	// input reads In line by line; one reader serves all prompts of a run.
	input *bufio.Reader
}

// Printf writes to the standard output.
func (e *Env) Printf(format string, args ...any) { _, _ = fmt.Fprintf(e.Out, format, args...) }

// Println writes a line to the standard output.
func (e *Env) Println(args ...any) { _, _ = fmt.Fprintln(e.Out, args...) }

// Warnf writes a line to the standard error output.
func (e *Env) Warnf(format string, args ...any) { _, _ = fmt.Fprintf(e.Err, format+"\n", args...) }

// Fail is an error that stops the command with an understandable message and the exit code 1.
// The message has been translated already.
type Fail struct{ Msg string }

func (f *Fail) Error() string { return f.Msg }

// errExit1 ends a command with the exit code 1 after it has printed its findings itself.
var errExit1 = &Fail{}

// Failf makes a Fail from a translated text.
func Failf(text string, values ...any) *Fail { return &Fail{Msg: i18n.P(text, values...)} }

// Builder makes a command. It is called for every start, after the language is known, so that
// the texts of the command are translated.
type Builder func(*Env) *cobra.Command

var builders []Builder

// Register adds a command to the program. Call it from an init function.
func Register(b Builder) { builders = append(builders, b) }

// Execute runs the program with the arguments (without the program name) and returns the exit
// code: 0 success, 1 failure of the command, 2 wrong use.
func Execute(args []string, in io.Reader, out, errOut io.Writer) int {
	config.Install()
	storage.Translate = func(text string) string { return i18n.T(text) }
	sources.Translate = func(text string) string { return i18n.T(text) }
	i18n.SetLanguage("") // a language chosen by an earlier run in this process must not stay
	env := &Env{In: in, Out: out, Err: errOut}
	root := newRoot(env)
	root.SetArgs(args)
	root.SetOut(out)
	root.SetErr(errOut)
	err := root.Execute()
	if err == nil {
		if AfterRun != nil {
			AfterRun(env, args)
		}
		return 0
	}
	var fail *Fail
	var cfg *config.Error
	switch {
	case errors.As(err, &fail), errors.As(err, &cfg):
		if err.Error() != "" {
			_, _ = fmt.Fprintln(errOut, err.Error())
		}
		return 1
	default:
		_, _ = fmt.Fprintln(errOut, i18n.T("Usage error: {error}", "error", err))
		return 2
	}
}

func newRoot(env *Env) *cobra.Command {
	var showVersion bool
	root := &cobra.Command{
		Use:           progName,
		Short:         i18n.P("Velocity and capacity forecast for Scrum teams. Start with: `foresprint help`."),
		SilenceUsage:  true,
		SilenceErrors: true,
		Args:          cobra.ArbitraryArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if showVersion {
				env.Println(Version)
				return nil
			}
			if len(args) > 0 {
				return fmt.Errorf("%s", i18n.T("Unknown command {name!r}. Try: {help}", "name", args[0], "help", progName+" --help"))
			}
			return cmd.Help()
		},
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			if !cmd.Flags().Changed("as-of") && os.Getenv(AsOfEnv) != "" {
				env.AsOf = os.Getenv(AsOfEnv)
			}
			if env.Data == "" {
				env.Data = os.Getenv(DataEnv)
			}
			today, err := parseAsOf(env.AsOf)
			if err != nil {
				return err
			}
			env.Today = today
			return nil
		},
	}
	root.CompletionOptions.DisableDefaultCmd = true
	root.SetHelpCommand(&cobra.Command{Hidden: true, Use: "no-help"})
	root.PersistentFlags().StringVarP(&env.Data, "data", "d", "", i18n.P(
		"Folder with the team data (one subfolder per team). Default: current folder if it contains teams, otherwise the remembered data folder."))
	root.PersistentFlags().StringVar(&env.AsOf, "as-of", "", i18n.P(
		`Date (YYYY-MM-DD) treated as "today" – for retrospectives and tests.`))
	root.Flags().BoolVar(&showVersion, "version", false, i18n.P("Show version."))
	localize(root)
	for _, b := range builders {
		cmd := b(env)
		cmd.InitDefaultHelpFlag()
		cmd.Flags().Lookup("help").Usage = i18n.T("Help for {name}", "name", cmd.Name())
		root.AddCommand(cmd)
	}
	return root
}

func parseAsOf(value string) (time.Time, error) {
	if value == "" {
		now := time.Now()
		return time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC), nil
	}
	day, err := time.Parse("2006-01-02", value)
	if err != nil {
		return time.Time{}, errors.New(i18n.P("Date in the format YYYY-MM-DD expected"))
	}
	return day, nil
}

// localize sets help templates with translated headings.
func localize(root *cobra.Command) {
	root.InitDefaultHelpFlag()
	root.Flags().Lookup("help").Usage = i18n.T("Help for {name}", "name", progName)
	usage := i18n.P("Usage:")
	commands := i18n.P("Commands:")
	options := i18n.P("Options:")
	global := i18n.P("Global options:")
	more := i18n.T(`Use "{command} [command] --help" for more information about a command.`, "command", "{{.CommandPath}}")
	root.SetUsageTemplate(usage + `
{{if .Runnable}}  {{.UseLine}}
{{end}}{{if .HasAvailableSubCommands}}  {{.CommandPath}} [command]
{{end}}{{if .HasAvailableSubCommands}}
` + commands + `{{range .Commands}}{{if (or .IsAvailableCommand (eq .Name "help"))}}
  {{rpad .Name .NamePadding }} {{.Short}}{{end}}{{end}}{{end}}{{if .HasAvailableLocalFlags}}
` + options + `
{{.LocalFlags.FlagUsages | trimTrailingWhitespaces}}{{end}}{{if .HasAvailableInheritedFlags}}
` + global + `
{{.InheritedFlags.FlagUsages | trimTrailingWhitespaces}}{{end}}{{if .HasAvailableSubCommands}}
` + more + `{{end}}
`)
}
