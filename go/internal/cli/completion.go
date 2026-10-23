package cli

import (
	"path/filepath"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(completionCommand) }

var shells = []string{"bash", "zsh", "fish", "powershell"}

func completionCommand(env *Env) *cobra.Command {
	var prog string
	cmd := &cobra.Command{
		Use:       "completion {bash|zsh|fish|powershell}",
		Short:     i18n.T("Print the Tab completion script for a shell (bash, zsh, fish, powershell)."),
		Args:      cobra.ExactArgs(1),
		ValidArgs: shells,
		// The script is not a team command: no data folder is looked at.
		PersistentPreRunE: func(*cobra.Command, []string) error { return nil },
		RunE: func(cmd *cobra.Command, args []string) error {
			root := cmd.Root()
			if prog == "" {
				prog = progName
			}
			root.Use = prog // the script registers this name and calls `<prog> __complete`
			switch args[0] {
			case "bash":
				return root.GenBashCompletionV2(env.Out, true)
			case "zsh":
				return root.GenZshCompletion(env.Out)
			case "fish":
				return root.GenFishCompletion(env.Out, true)
			case "powershell":
				return root.GenPowerShellCompletionWithDesc(env.Out)
			}
			return Failf("Shell the script is written for.")
		},
	}
	cmd.Flags().StringVar(&prog, "prog-name", "", i18n.T("Command name the script is registered for (default: the name used now)."))
	return cmd
}

// TeamNames completes the argument "team": the teams of the data folder (--data as typed, else
// the usual folder), found by their team.yaml. Nothing heavy is loaded.
func TeamNames(env *Env) func(*cobra.Command, []string, string) ([]string, cobra.ShellCompDirective) {
	return func(cmd *cobra.Command, args []string, prefix string) ([]string, cobra.ShellCompDirective) {
		if len(args) > 0 {
			return nil, cobra.ShellCompDirectiveNoFileComp
		}
		return filterPrefix(teamFolders(dataDirFor(cmd, env)), prefix), cobra.ShellCompDirectiveNoFileComp
	}
}

// SprintIDs completes the argument after the team: the file names in <team>/sprints.
func SprintIDs(env *Env) func(*cobra.Command, []string, string) ([]string, cobra.ShellCompDirective) {
	return func(cmd *cobra.Command, args []string, prefix string) ([]string, cobra.ShellCompDirective) {
		if len(args) != 1 {
			return nil, cobra.ShellCompDirectiveNoFileComp
		}
		files, _ := filepath.Glob(filepath.Join(dataDirFor(cmd, env), args[0], "sprints", "*.yaml"))
		var ids []string
		for _, f := range files {
			ids = append(ids, strings.TrimSuffix(filepath.Base(f), ".yaml"))
		}
		sort.Slice(ids, func(i, j int) bool { return textfmt.NaturalLess(ids[i], ids[j]) })
		return filterPrefix(ids, prefix), cobra.ShellCompDirectiveNoFileComp
	}
}

func filterPrefix(names []string, prefix string) []string {
	var out []string
	for _, n := range names {
		if strings.HasPrefix(n, prefix) {
			out = append(out, n)
		}
	}
	return out
}

func teamFolders(root string) []string {
	files, _ := filepath.Glob(filepath.Join(root, "*", "team.yaml"))
	var names []string
	for _, f := range files {
		names = append(names, filepath.Base(filepath.Dir(f)))
	}
	sort.Strings(names)
	return names
}
