package cli

import (
	"os"
	"strings"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/textfmt"
)

func init() { Register(storageCommand) }

// storageCommand is Settings > Storage and the Data area on the command line (flows D1 to D6).
// It is a thin layer over datasvc, the service the window uses, so both do the same.
func storageCommand(env *Env) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "storage",
		Short: i18n.T("Where the data is kept: server, sign-in, name, save, refresh and history."),
		Args:  cobra.NoArgs,
		RunE:  func(*cobra.Command, []string) error { return showStorage(env) },
	}
	cmd.AddCommand(storageServer(env), storageSignIn(env), storageIdentity(env), storageShare(env),
		storageBranch(env), storageSave(env), storageRefresh(env), storageHistory(env))
	return cmd
}

func (e *Env) store() *datasvc.Store { return datasvc.New(e.DataDir()) }

// problem turns a problem of the service into a failure.
func problem(p *datasvc.Problem) error {
	if p == nil {
		return nil
	}
	lines := []string{p.Title}
	if p.Message != "" {
		lines = append(lines, p.Message)
	}
	if p.Hint != "" {
		lines = append(lines, p.Hint)
	}
	return &Fail{Msg: strings.Join(lines, "\n")}
}

func yesNo(ok bool) string {
	if ok {
		return i18n.P("yes")
	}
	return i18n.P("no")
}

func showStorage(env *Env) error {
	s := env.store()
	st := s.Storage()
	if st.Problem != nil && !st.Ready {
		env.Println(i18n.P("Data folder: {path}", "path", st.Folder))
		return problem(st.Problem)
	}
	t := &Table{Title: i18n.P("Storage"), Header: []string{i18n.T("Setting"), i18n.T("Value")}}
	none := i18n.P("not set")
	or := func(v string) string {
		if v == "" {
			return none
		}
		return textfmt.BlankControls(v)
	}
	t.Add(i18n.P("Data folder"), st.Folder)
	t.Add(i18n.P("Server"), or(st.Server))
	t.Add(i18n.P("Branch"), or(st.Branch))
	t.Add(i18n.P("Way to share"), or(st.Share))
	t.Add(i18n.P("Name for saves"), or(st.Name))
	t.Add(i18n.P("Email for saves"), or(st.Email))
	t.Add(i18n.P("Credential helper"), or(st.Helper))
	t.Render(env.Out)
	for _, item := range st.Setup {
		mark := "[ ]"
		if item.OK {
			mark = "[x]"
		}
		env.Println(mark + " " + item.Detail)
	}
	status := s.Status()
	env.Println(i18n.P("Status: {text}", "text", status.Chip.Text))
	return nil
}

func storageServer(env *Env) *cobra.Command {
	var insecure, newBranch, offline bool
	cmd := &cobra.Command{
		Use:   "server ADDRESS",
		Short: i18n.T("Check the address of the server and set it for the data folder."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s := env.store()
			check := s.CheckServer(args[0], insecure)
			if check.Problem != nil && !offline {
				return problem(check.Problem)
			}
			if check.OK {
				switch {
				case check.Empty:
					env.Println(i18n.P("The server is reachable and has no data yet; the first save fills it."))
				case check.BranchMissing:
					env.Println(i18n.P("The server has data, but not under the branch of this folder; the first save creates it."))
				default:
					env.Println(i18n.P("The server is reachable."))
				}
			}
			saved := s.SaveServer(args[0], datasvc.ServerOptions{AllowInsecure: insecure, AcceptNewBranch: newBranch, AllowOffline: offline})
			if saved.Problem != nil {
				return problem(saved.Problem)
			}
			env.Println(i18n.P("Server set: {address}", "address", saved.Address))
			return nil
		},
	}
	f := cmd.Flags()
	f.BoolVar(&insecure, "allow-insecure", false, i18n.T("Allow an address without https."))
	f.BoolVar(&newBranch, "accept-new-branch", false, i18n.T("Accept that the first save creates the branch on the server."))
	f.BoolVar(&offline, "offline", false, i18n.T("Save the address although the server cannot be reached now."))
	return cmd
}

// secret reads a token: not shown on a terminal, one line from a pipe otherwise.
func (e *Env) secret(prompt string) (string, error) {
	if f, ok := e.In.(*os.File); ok && e.interactive() {
		e.Printf("%s: ", prompt)
		b, err := term.ReadPassword(int(f.Fd()))
		e.Println()
		return strings.TrimSpace(string(b)), err
	}
	line, err := e.readLineRaw()
	return strings.TrimSpace(line), err
}

func storageSignIn(env *Env) *cobra.Command {
	var user string
	var forget bool
	cmd := &cobra.Command{
		Use:   "sign-in ADDRESS",
		Short: i18n.T("Hand an access token to the credential helper of this computer (read from the terminal or standard input)."),
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s := env.store()
			if forget {
				if p := s.ForgetSignIn(args[0], user); p != nil {
					return problem(p)
				}
				env.Println(i18n.P("The stored sign-in was removed."))
				return nil
			}
			st := s.Storage()
			if st.Guide.Steps != "" {
				env.Println(st.Guide.Steps)
			}
			if user == "" {
				user = st.Guide.Username
			}
			token, err := env.secret(i18n.P("Access token"))
			if err != nil {
				return err
			}
			if token == "" {
				return Failf("No token entered.")
			}
			if p := s.SignIn(args[0], user, token); p != nil {
				return problem(p)
			}
			env.Println(i18n.P("Signed in; the credential helper keeps the token."))
			return nil
		},
	}
	cmd.Flags().StringVar(&user, "user", "", i18n.T("User name for the server (default: the one the server kind expects)."))
	cmd.Flags().BoolVar(&forget, "forget", false, i18n.T("Remove the stored sign-in instead."))
	return cmd
}

func storageIdentity(env *Env) *cobra.Command {
	var name, email string
	cmd := &cobra.Command{
		Use:   "identity --name NAME --email EMAIL",
		Short: i18n.T("Set the name and email address that saves are made with."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if name == "" || email == "" {
				return Failf("Both --name and --email are needed.")
			}
			if p := env.store().SetIdentity(name, email); p != nil {
				return problem(p)
			}
			env.Println(i18n.P("Saves are made as {name} <{email}>.", "name", name, "email", email))
			return nil
		},
	}
	cmd.Flags().StringVar(&name, "name", "", i18n.T("Name."))
	cmd.Flags().StringVar(&email, "email", "", i18n.T("Email address."))
	return cmd
}

func storageShare(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:       "share direct|merge_request",
		Short:     i18n.T("Choose how saves reach the server: directly or through a merge request."),
		Args:      cobra.ExactArgs(1),
		ValidArgs: []string{"direct", "merge_request"},
		RunE: func(cmd *cobra.Command, args []string) error {
			if p := env.store().SetShare(args[0]); p != nil {
				return problem(p)
			}
			env.Println(i18n.P("Way to share: {mode}", "mode", args[0]))
			return nil
		},
	}
}

func storageBranch(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:   "branch [NAME]",
		Short: i18n.T("List the branches or move the data to another one."),
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s := env.store()
			if len(args) == 1 {
				done := s.SwitchBranch(args[0])
				if done.Problem != nil {
					return problem(done.Problem)
				}
				env.Println(i18n.P("Now on branch {name}.", "name", args[0]))
				return nil
			}
			list, err := s.Branches()
			if err != nil {
				return asFail(err)
			}
			for _, b := range list {
				mark := "  "
				if b.Current {
					mark = "* "
				}
				env.Println(mark + textfmt.BlankControls(b.Name))
			}
			return nil
		},
	}
}

// printResult reports what Save or Refresh did.
func printResult(env *Env, r datasvc.Result) error {
	if r.Problem != nil {
		return problem(r.Problem)
	}
	for _, c := range r.Taken {
		env.Println(i18n.P("From {who}: {summary}", "who", c.Who, "summary", c.Summary))
	}
	for _, n := range r.Notes {
		env.Println(n)
	}
	switch r.Outcome {
	case datasvc.OutcomeSaved:
		env.Println(i18n.P("Saved."))
	case datasvc.OutcomeNothing:
		env.Println(i18n.P("Nothing to save."))
	case datasvc.OutcomeOffline:
		env.Println(i18n.P("Saved on this computer; the server is not reachable, the next refresh shares it."))
	case datasvc.OutcomeWaitingForReview:
		env.Println(i18n.P("Saved on the server's own branch; a merge request waits: {link}", "link", r.Link))
	case datasvc.OutcomeFindings:
		for _, f := range r.Findings {
			env.Println(f)
		}
		return Failf("Not saved – the data has errors (use --anyway to save anyway).")
	case datasvc.OutcomeConflict:
		return Failf("{count} file(s) wait for a decision about changes of two people.", "count", r.Conflicts)
	case datasvc.OutcomeReadOnly:
		return Failf("You may not write to this server.")
	default:
		env.Println(r.Status.Chip.Text)
	}
	return nil
}

func storageSave(env *Env) *cobra.Command {
	var message string
	var anyway bool
	cmd := &cobra.Command{
		Use:   "save",
		Short: i18n.T("Save the changes and share them (commit, take over the changes of others, push)."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			return printResult(env, env.store().Save(datasvc.SaveOptions{Message: message, SaveAnyway: anyway}))
		},
	}
	cmd.Flags().StringVarP(&message, "message", "m", "", i18n.T("Describe the save (default: a standard text)."))
	cmd.Flags().BoolVar(&anyway, "anyway", false, i18n.T("Save although the merged data has errors."))
	return cmd
}

func storageRefresh(env *Env) *cobra.Command {
	return &cobra.Command{
		Use:   "refresh",
		Short: i18n.T("Take over the changes of others and share saves that are still pending."),
		Args:  cobra.NoArgs,
		RunE:  func(cmd *cobra.Command, args []string) error { return printResult(env, env.store().Refresh()) },
	}
}

func storageHistory(env *Env) *cobra.Command {
	var scope string
	var limit int
	cmd := &cobra.Command{
		Use:   "history",
		Short: i18n.T("Who changed what and when (newest first)."),
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			list, err := env.store().History(scope, limit)
			if err != nil {
				return asFail(err)
			}
			t := &Table{Title: i18n.P("History"), Header: []string{i18n.T("Version"), i18n.T("Day"), i18n.T("Who"), i18n.T("What")}}
			for _, v := range list {
				t.Add(v.Short, v.Day, textfmt.BlankControls(v.Who), textfmt.BlankControls(v.Summary))
			}
			t.Render(env.Out)
			return nil
		},
	}
	cmd.Flags().StringVar(&scope, "scope", "", i18n.T("A team folder or file, relative to the data folder (default: everything)."))
	cmd.Flags().IntVar(&limit, "limit", 0, i18n.T("Number of entries (default 40)."))
	return cmd
}
