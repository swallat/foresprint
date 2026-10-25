package cli

import (
	"strings"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
)

// cliGitHints are command line hints for error kinds whose hint from the Git layer addresses
// the window (sidebar, buttons).
func cliGitHints() map[string]string {
	return map[string]string{
		"identity": i18n.T("Git does not know your name yet. Set it up with `git config --global " +
			"user.name \"Your Name\"` and `git config --global user.email " +
			"\"you@example.org\"`."),
		"conflict": i18n.T("The markers come from an incomplete merge: remove them in an editor and run " +
			"the command again with --commit."),
		"tag_exists": i18n.T("Remove the existing tag first (`git tag -d <name>`) and run the command again " +
			"with --commit. The data is saved, just not committed."),
	}
}

// GitProblem turns a Git error into a failure with heading, message and next step.
func GitProblem(e *git.Error) *Fail {
	lines := []string{git.TitleFor(e.Kind)}
	if msg := e.Error(); msg != "" {
		lines = append(lines, msg)
	}
	hint := cliGitHints()[e.Kind]
	if hint == "" {
		hint = e.Hint()
	}
	if hint != "" {
		lines = append(lines, hint)
	}
	return &Fail{Msg: strings.Join(lines, "\n")}
}
