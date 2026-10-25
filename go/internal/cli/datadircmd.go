package cli

import (
	"context"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/config"
	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
)

func init() { Register(dataDirCommand) }

func dataDirCommand(env *Env) *cobra.Command {
	return &cobra.Command{
		Use: "data-dir [PATH]",
		Short: i18n.T("Show or set the remembered data folder (applies when the current directory contains no " +
			"teams and neither --data nor FORESPRINT_DATA is set)."),
		Args: cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				return showDataDir(env)
			}
			return setDataDir(cmd.Context(), env, args[0])
		},
	}
}

func absPath(p string) string {
	if abs, err := filepath.Abs(p); err == nil {
		if resolved, err := filepath.EvalSymlinks(abs); err == nil {
			return resolved
		}
		return abs
	}
	return p
}

func showDataDir(env *Env) error {
	if saved, ok := config.DataDir(); ok {
		env.Println(i18n.P("Remembered: {path}", "path", saved))
	} else {
		env.Println(i18n.P("No data folder saved."))
	}
	env.Println(i18n.P("Used (without --data): {path}", "path", absPath(env.DataDir())))
	return nil
}

func setDataDir(ctx context.Context, env *Env, path string) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if info, err := os.Stat(path); err != nil || !info.IsDir() {
		return Failf("Folder not found: {path}", "path", path)
	}
	if !git.Available() {
		return GitProblem(git.Classify("", git.ClassifyOpts{Missing: true}))
	}
	root, err := git.RepoRoot(ctx, path)
	if err != nil {
		return err
	}
	if root == "" {
		problem, err := git.RootProblem(ctx, path)
		if err != nil {
			return err
		}
		if problem != nil {
			return GitProblem(problem)
		}
		return Failf("{path} is not inside a Git repository (git init or git clone).", "path", path)
	}
	target := path
	if found := teamsDir(path); found != "" {
		target = found
	}
	if err := config.SaveDataDir(target); err != nil {
		return err
	}
	env.Println(i18n.P("Data folder saved: {path}", "path", absPath(target)))
	return nil
}
