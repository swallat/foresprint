package cli

import (
	"context"
	"strings"

	"github.com/spf13/cobra"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/validate"
)

// commitFlag adds --commit to a command that changes data.
func commitFlag(cmd *cobra.Command, do *bool) {
	cmd.Flags().BoolVar(do, "commit", false, i18n.T("Commit the change in Git."))
}

// saved reports a written file.
func (e *Env) saved(path string) {
	e.Println(i18n.P("Saved: {path}", "path", path))
}

// issuesFor are the findings of the data that concern one of the named files.
func issuesFor(data *storage.TeamData, e *Env, files []string) []validate.Issue {
	var out []validate.Issue
	for _, i := range validate.CheckTeam(data, e.Today) {
		for _, name := range files {
			if strings.Contains(i.Where, name) {
				out = append(out, i)
				break
			}
		}
	}
	return out
}

// maybeCommit shows the findings for the changed files and commits when asked to.
func (e *Env) maybeCommit(team string, paths []string, message, tag string, doCommit bool) error {
	data, err := e.LoadTeam(team)
	if err != nil {
		return err
	}
	names := make([]string, len(paths))
	for i, p := range paths {
		names[i] = baseName(p)
	}
	hasErrors := false
	for _, i := range issuesFor(data, e, names) {
		e.Printf("%s %s: %s\n", i18n.T(string(i.Level)), textfmt.BlankControls(i.Where), textfmt.BlankControls(i.Message))
		hasErrors = hasErrors || i.Level == validate.Error
	}
	if !doCommit {
		e.Println(i18n.P("Tip: with --commit the change is committed to Git right away."))
		return nil
	}
	if hasErrors {
		e.Warnf("%s", i18n.P("Not committed – please fix the errors first."))
		return errExit1
	}
	rev, err := git.Commit(context.Background(), paths, message, tag)
	if err != nil {
		if ge := git.As(err); ge != nil {
			return GitProblem(ge)
		}
		return err
	}
	suffix := ""
	if tag != "" {
		suffix = i18n.P(", tag {tag}", "tag", tag)
	}
	e.Println(i18n.P("Committed ({rev}){suffix}.", "rev", rev, "suffix", suffix))
	return nil
}

func baseName(path string) string {
	if i := strings.LastIndexAny(path, `/\`); i >= 0 {
		return path[i+1:]
	}
	return path
}

// refuseInvalid stops a write that would add errors to the affected files (where is the start of
// the file name); errors that existed before do not block the change.
func (e *Env) refuseInvalid(before, after *storage.TeamData, where string) error {
	known := map[[2]string]bool{}
	for _, i := range validate.CheckTeam(before, e.Today) {
		known[[2]string{i.Where, i.Message}] = true
	}
	found := false
	for _, i := range validate.CheckTeam(after, e.Today) {
		if i.Level == validate.Error && strings.HasPrefix(i.Where, where) && !known[[2]string{i.Where, i.Message}] {
			e.Warnf("%s: %s", textfmt.BlankControls(i.Where), textfmt.BlankControls(i.Message))
			found = true
		}
	}
	if found {
		e.Warnf("%s", i18n.P("Not saved – please fix the errors."))
		return errExit1
	}
	return nil
}
