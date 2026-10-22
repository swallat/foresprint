package cli

import (
	"context"
	"fmt"
	"os"
	"slices"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/selfupdate"
)

func init() { Register(updateCommand) }

// AfterRun is a hook the program sets; it runs after a command that succeeded and is used
// for the daily check for a new version.
var AfterRun func(env *Env, args []string)

func updateCommand(env *Env) *cobra.Command {
	var check, force bool
	var auto string
	cmd := &cobra.Command{
		Use:   "update",
		Short: i18n.T("Update foresprint to the latest version."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if cmd.Flags().Changed("auto") {
				return setAutoUpdate(env, auto)
			}
			return runUpdate(env, &selfupdate.Updater{}, check, force)
		},
	}
	f := cmd.Flags()
	f.BoolVar(&check, "check", false, i18n.T("Only check, do not install."))
	f.BoolVar(&force, "force", false, i18n.T("Reinstall even without a new version."))
	f.StringVar(&auto, "auto", "", i18n.T("Set automatic mode: on (installs itself), notice (only report), off."))
	return cmd
}

func setAutoUpdate(env *Env, value string) error {
	mode, ok := selfupdate.ParseMode(value)
	if !ok {
		return Failf("--auto: on, notice or off")
	}
	state := selfupdate.LoadState()
	state.Mode = string(mode)
	if err := state.Save(); err != nil {
		return Failf("The settings could not be saved ({path}): {error}", "path", selfupdate.StateFile(), "error", err.Error())
	}
	env.Println(i18n.P("Automatic update: [bold]{mode}[/bold]", "mode", string(mode)))
	if os.Getenv(selfupdate.ModeEnv) != "" {
		env.Println(i18n.P("Note: {name} takes precedence.", "name", selfupdate.ModeEnv))
	}
	return nil
}

func runUpdate(env *Env, u *selfupdate.Updater, check, force bool) error {
	if selfupdate.IsDevelopment(Version) {
		return Failf("Version {version} – a development build does not update itself. Install a release from "+
			"https://github.com/{repo}/releases.", "version", Version, "repo", selfupdate.DefaultRepo)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	rel, err := u.Latest(ctx)
	if err != nil {
		return Failf("The newest version could not be determined: {error}", "error", err.Error())
	}
	state := selfupdate.LoadState()
	state.LastCheck, state.Latest = time.Now().UTC(), rel.Version
	_ = state.Save()
	newer := selfupdate.Newer(Version, rel.Version)
	switch {
	case !newer && !force:
		env.Println(i18n.P("Version {version} is the latest.", "version", Version))
		return nil
	case check:
		env.Println(i18n.P("Version {latest} is available (installed: {version}). Update with: {command}",
			"latest", rel.Version, "version", Version, "command", progName+" update"))
		return nil
	}
	env.Println(i18n.P("Installing version {latest} …", "latest", rel.Version))
	if err := u.Install(ctx, rel); err != nil {
		return Failf("The update failed: {error}", "error", err.Error())
	}
	env.Println(i18n.P("Updated to version {latest}. The next start uses it.", "latest", rel.Version))
	return nil
}

// AutoUpdate is the daily check after a command: it installs a newer version (mode on) or
// reports it (mode notice). It never makes the command fail and stays silent without a
// connection.
func AutoUpdate(env *Env, args []string) {
	if selfupdate.IsDevelopment(Version) || slices.Contains([]string{"update", "completion", "version"}, firstWord(args)) {
		return
	}
	mode := selfupdate.CurrentMode()
	state := selfupdate.LoadState()
	if mode == selfupdate.Off || !state.Due(time.Now()) {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	u := &selfupdate.Updater{}
	rel, err := u.Latest(ctx)
	state.LastCheck = time.Now().UTC()
	if err != nil {
		_ = state.Save() // try again tomorrow, not at every command
		return
	}
	state.Latest = rel.Version
	_ = state.Save()
	if !selfupdate.Newer(Version, rel.Version) {
		return
	}
	if mode == selfupdate.Notice {
		_, _ = fmt.Fprintln(env.Err, i18n.P("Version {latest} is available (installed: {version}). Update with: {command}",
			"latest", rel.Version, "version", Version, "command", progName+" update"))
		return
	}
	if err := u.Install(ctx, rel); err != nil {
		_, _ = fmt.Fprintln(env.Err, i18n.P("The update failed: {error}", "error", err.Error()))
		return
	}
	_, _ = fmt.Fprintln(env.Err, i18n.P("Updated to version {latest}. The next start uses it.", "latest", rel.Version))
}

// firstWord is the command name: the first argument that is not an option.
func firstWord(args []string) string {
	for _, a := range args {
		if !strings.HasPrefix(a, "-") {
			return a
		}
	}
	return ""
}
