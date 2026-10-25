package cli

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/config"
)

// teamsDir is dir itself if it holds teams, else its subfolder "teams" if that holds teams
// (the layout of a data repository), else the folder above a folder "teams" if that holds teams
// (a wrongly remembered folder), else "".
func teamsDir(dir string) string {
	if len(teamFolders(dir)) > 0 {
		return dir
	}
	if sub := filepath.Join(dir, "teams"); len(teamFolders(sub)) > 0 {
		return sub
	}
	// A folder remembered as "<repository>/teams" while the teams sit in the repository itself.
	if strings.EqualFold(filepath.Base(dir), "teams") && len(teamFolders(filepath.Dir(dir))) > 0 {
		return filepath.Dir(dir)
	}
	return ""
}

// DataDir is the folder with the team data: --data > FORESPRINT_DATA > the current folder, if
// it holds teams > the remembered folder > the current folder.
func (e *Env) DataDir() string {
	if e.Data != "" {
		return e.Data
	}
	if configured := os.Getenv(DataEnv); configured != "" {
		return configured
	}
	if found := teamsDir("."); found != "" {
		return found
	}
	if saved, ok := config.DataDir(); ok {
		if found := teamsDir(saved); found != "" {
			return found
		}
		return saved
	}
	return "."
}

// dataDirFor is DataDir for the shell completion, where the global options of the line typed
// so far are not parsed by the command: they are looked up in the flags that are set.
func dataDirFor(cmd *cobra.Command, env *Env) string {
	if f := cmd.Flags().Lookup("data"); f != nil && f.Value.String() != "" {
		return f.Value.String()
	}
	return env.DataDir()
}
