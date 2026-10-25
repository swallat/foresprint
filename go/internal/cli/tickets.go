package cli

import (
	"fmt"
	"os"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/preplan"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/ticketimport"
	"github.com/swallat/foresprint/internal/validate"
	"github.com/swallat/foresprint/internal/yamlx"
)

func init() { Register(ticketsCommand) }

type ticketOptions struct {
	file                             string
	fetch, testConnection, setToken  bool
	handover, overwrite, writeLabels bool
	apply, doCommit                  bool
	variant                          string
	sprints                          int
}

func ticketsCommand(env *Env) *cobra.Command {
	var o ticketOptions
	cmd := &cobra.Command{
		Use: "tickets TEAM",
		Short: i18n.T("Ticket pre-planning: read tickets from Jira or a CSV file, distribute them over " +
			"future sprints, project traffic light with range and refinement list; hand over to " +
			"the PO pre-planning."),
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !slices.Contains([]string{"median", "conservative", "optimistic"}, o.variant) {
				return fmt.Errorf("%s", i18n.T("Variant expected: median, conservative or optimistic"))
			}
			if o.sprints < 1 {
				return fmt.Errorf("%s", i18n.T("Number of future sprints shown."))
			}
			return runTickets(env, cmd, args[0], o)
		},
	}
	teamArg(env, cmd)
	f := cmd.Flags()
	f.StringVar(&o.file, "import", "", i18n.T("Read a CSV export of the ticket system (preview); also possible with Jira."))
	f.BoolVar(&o.fetch, "fetch", false, i18n.T("Read the tickets from Jira (tracker.kind: jira, read-only; preview)."))
	f.BoolVar(&o.testConnection, "test-connection", false, i18n.T(
		"Check the connection to Jira and show the account of the token (writes nothing)."))
	f.BoolVar(&o.setToken, "set-token", false, i18n.T("Store the Jira token (hidden input) in the keychain."))
	f.BoolVar(&o.handover, "handover", false, i18n.T("Propose the sums of the distributed tickets per sprint and product as the "+
		"PO pre-planning (median variant; write with --apply)."))
	f.BoolVar(&o.overwrite, "overwrite", false, i18n.T("With --handover, also replace PO pre-planning that is already entered."))
	f.StringVar(&o.variant, "variant", "median", i18n.T("Variant for the sprint table and the refinement list: median (Forecast "+
		"PLAN), conservative or optimistic."))
	f.BoolVar(&o.writeLabels, "write-labels", false, i18n.T("Write earmarks to Jira as the label planned_for_<sprint> "+
		"(tracker.write_labels; preview, write with --apply)."))
	f.BoolVar(&o.apply, "apply", false, i18n.T("Write the import or handover (otherwise preview only)."))
	commitFlag(cmd, &o.doCommit)
	f.IntVar(&o.sprints, "sprints", 6, i18n.T("Number of future sprints shown."))
	return cmd
}

func requireTickets(data *storage.TeamData, team string) error {
	if !data.Team.Features.Tickets {
		return Failf("Ticket pre-planning is switched off for this team. Switch it on with: {command}",
			"command", "foresprint settings "+team)
	}
	return nil
}

func runTickets(env *Env, cmd *cobra.Command, key string, o ticketOptions) error {
	data, err := env.LoadTeam(key)
	if err != nil {
		return err
	}
	if err := requireTickets(data, key); err != nil {
		return err
	}
	given := func(name string) bool { return cmd.Flags().Changed(name) }
	importing := o.file != ""
	var actions []string
	for _, a := range []struct {
		name string
		on   bool
	}{{"--import", importing}, {"--fetch", o.fetch}, {"--test-connection", o.testConnection},
		{"--set-token", o.setToken}, {"--handover", o.handover}, {"--write-labels", o.writeLabels}} {
		if a.on {
			actions = append(actions, a.name)
		}
	}
	if len(actions) > 1 {
		return Failf("{options} are mutually exclusive.", "options", strings.Join(actions, " / "))
	}
	if o.testConnection || o.setToken {
		var refused []string
		for _, a := range []struct {
			name string
			on   bool
		}{{"--apply", o.apply}, {"--commit", o.doCommit}, {"--sprints", given("sprints")},
			{"--variant", given("variant")}, {"--overwrite", o.overwrite}} {
			if a.on {
				refused = append(refused, a.name)
			}
		}
		if len(refused) > 0 {
			return Failf("{options} do not belong to --test-connection and --set-token.", "options", strings.Join(refused, " / "))
		}
	}
	if o.overwrite && !o.handover {
		return Failf("--overwrite belongs to --handover.")
	}
	if o.handover && given("variant") {
		return Failf("--variant does not belong to --handover (it uses the median variant).")
	}
	if o.writeLabels {
		var refused []string
		if o.doCommit {
			refused = append(refused, "--commit")
		}
		if given("sprints") {
			refused = append(refused, "--sprints")
		}
		if len(refused) > 0 {
			return Failf("{options} do not go with --write-labels.", "options", strings.Join(refused, " / "))
		}
		return env.ticketWriteLabels(data, o.apply)
	}
	if o.setToken {
		return env.ticketSetToken(data)
	}
	if o.testConnection {
		return env.ticketTestConnection(data)
	}
	if o.handover {
		if o.doCommit && !o.apply {
			return Failf("--commit needs --apply.")
		}
		return env.ticketHandover(data, key, o.sprints, o.apply, o.overwrite, o.doCommit)
	}
	importing = importing || o.fetch
	if importing && o.doCommit && !o.apply {
		return Failf("--commit needs --apply.")
	}
	var printed []validate.Issue
	if importing {
		raws, name, err := env.ticketRead(data, o.file, o.fetch)
		if err != nil {
			return err
		}
		plan := ticketimport.PlanImport(ticketEnv(data, env.Today), raws, &name, true)
		env.ticketPreview(plan, 15)
		switch {
		case plan.Unchanged(data.Tickets, data.TicketsSource):
			// Nothing to write: no time-stamp-only rewrite of tickets.yaml.
			env.Println(i18n.P("No changes compared to the existing files."))
		case !o.apply:
			env.Println(i18n.P("Preview only – write with --apply."))
		default:
			paths, err := plan.Apply(planSaver{env.Repo()}, key, time.Now())
			if err != nil {
				return asFail(err)
			}
			for _, p := range paths {
				env.Println(p)
			}
			if printed, err = env.maybeCommitIssues(key, paths, i18n.T("{team}: Tickets imported",
				"team", textfmt.BlankControls(data.Team.Name)), "", o.doCommit); err != nil {
				return err
			}
			if data, err = env.LoadTeam(key); err != nil {
				return err
			}
		}
		if !o.apply {
			if given("variant") {
				env.Println(i18n.P("--variant takes effect only after writing (with --apply)."))
			}
			return nil
		}
	} else if o.apply || o.doCommit {
		return Failf("--apply and --commit belong to --import, --fetch and --handover.")
	}
	return env.ticketReport(data, o.sprints, printed, preplan.Variant(o.variant))
}

// planSaver writes the files of an import.
type planSaver struct{ repo *storage.Repository }

func (s planSaver) SaveTickets(team string, tickets []model.Ticket, now time.Time, source *string) (string, error) {
	return s.repo.SaveTickets(team, storage.TicketsFile{Tickets: tickets, Imported: &now, Source: source})
}

func (s planSaver) SavePreplan(team string, pp model.Preplan) (string, error) {
	return s.repo.SavePreplan(team, pp)
}

// knownSprints tells the import which sprints exist (recorded or generated up to 52 ahead).
type knownSprints struct{ data *storage.TeamData }

func (k knownSprints) End(id string) (time.Time, bool) {
	s, err := forecast.FindSprint(k.data, id, 52)
	if err != nil || s == nil {
		return time.Time{}, false
	}
	return s.End, true
}

func ticketEnv(data *storage.TeamData, today time.Time) ticketimport.Env {
	return ticketimport.Env{Tracker: data.Team.Tracker, Projects: data.Projects, Products: data.Products, Tickets: data.Tickets,
		Preplan: data.Preplan, Sprints: knownSprints{data}, Today: today}
}

// sourceSettings are the tracker settings as the sources need them.
func sourceSettings(t model.TrackerSettings) sources.Settings { return ticketimport.SourceSettings(t) }

func sourceFailed(err error) error {
	if sources.IsSourceError(err) {
		return &Fail{Msg: err.Error()}
	}
	return err
}

func closeSource(s sources.Source) {
	if c, ok := s.(interface{ Close() }); ok {
		c.Close()
	}
}

func jiraTracker(data *storage.TeamData, option string) (model.TrackerSettings, error) {
	t := data.Team.Tracker
	if t.Kind != "jira" {
		return t, Failf("{option} needs tracker.kind: jira in team.yaml (currently: {kind}).", "option", option, "kind", t.Kind)
	}
	return t, nil
}

func (e *Env) ticketSetToken(data *storage.TeamData) error {
	tracker, err := jiraTracker(data, "--set-token")
	if err != nil {
		return err
	}
	if tracker.BaseURL == nil || *tracker.BaseURL == "" {
		return Failf("tracker.base_url is missing (team.yaml)")
	}
	base := *tracker.BaseURL
	user, err := sources.KeychainUser(base) // an unusable address fails before the prompt
	if err != nil {
		return sourceFailed(err)
	}
	if !sources.KeychainUsable() {
		return Failf("The keychain is not available on this computer. Set the environment variable {variable} "+
			"instead.", "variable", sources.TokenEnv)
	}
	if strings.TrimSpace(os.Getenv(sources.TokenEnv)) != "" {
		e.Println(i18n.P("Note: {variable} is set and takes precedence over the keychain.", "variable", sources.TokenEnv))
	}
	token, err := e.askHidden(i18n.P("Jira token (the input stays hidden)"))
	if err != nil {
		return err
	}
	if err := sources.StoreToken(base, strings.TrimSpace(token)); err != nil {
		return sourceFailed(err)
	}
	e.Println(i18n.P("Token for {host} stored in the keychain. Check it with: {command}",
		"host", textfmt.BlankControls(user), "command", "foresprint tickets "+data.Team.Key+" --test-connection"))
	return nil
}

// askHidden asks for a secret; on a terminal the input is not shown.
func (e *Env) askHidden(label string) (string, error) {
	e.Printf("%s: ", label)
	if f, ok := e.In.(*os.File); ok && term.IsTerminal(int(f.Fd())) {
		b, err := term.ReadPassword(int(f.Fd()))
		e.Println()
		if err != nil {
			return "", errAborted()
		}
		return string(b), nil
	}
	line, err := e.readLineRaw()
	if err != nil {
		e.Println()
		return "", errAborted()
	}
	return line, nil
}

func (e *Env) ticketTestConnection(data *storage.TeamData) error {
	tracker, err := jiraTracker(data, "--test-connection")
	if err != nil {
		return err
	}
	src, err := sources.Open(sourceSettings(tracker), "", "", nil)
	if err != nil {
		return sourceFailed(err)
	}
	defer closeSource(src)
	jira, ok := src.(*sources.JiraSource)
	if !ok {
		return Failf("{option} needs tracker.kind: jira in team.yaml (currently: {kind}).", "option", "--test-connection", "kind", src.Kind())
	}
	name, err := jira.TestConnection()
	if err != nil {
		return sourceFailed(err)
	}
	resolved, err := jira.ResolveFields()
	if err != nil {
		return sourceFailed(err)
	}
	e.Println(i18n.P("Connected to {host} as {name}.", "host", textfmt.BlankControls(jira.Host()), "name", textfmt.BlankControls(name)))
	for _, f := range []struct {
		setting string
		label   *string
		id      string
	}{{"estimate", tracker.Fields.Estimate, resolved.Estimate}, {"remaining", tracker.Fields.Remaining, resolved.Remaining},
		{"epic", tracker.Fields.Epic, resolved.Epic}} {
		if f.label != nil && *f.label != "" {
			e.Println(i18n.P("Field {setting}: “{name}” is {id}", "setting", f.setting, "name", textfmt.BlankControls(*f.label),
				"id", textfmt.BlankControls(f.id)))
		}
	}
	dash := func(l []string) string {
		if len(l) == 0 {
			return "–"
		}
		return strings.Join(l, ", ")
	}
	e.Println(i18n.P("Sprint field: {sprint} · rank field: {rank}", "sprint", textfmt.BlankControls(dash(resolved.Sprint)),
		"rank", textfmt.BlankControls(dash(resolved.Rank))))
	return nil
}

// ticketRead reads the raw tickets from the CSV file or the tracker and the name of the source.
func (e *Env) ticketRead(data *storage.TeamData, file string, fetch bool) ([]sources.RawTicket, string, error) {
	tracker := data.Team.Tracker
	if fetch {
		if _, err := jiraTracker(data, "--fetch"); err != nil {
			return nil, "", err
		}
	}
	src, err := sources.Open(sourceSettings(tracker), file, "", nil)
	if err != nil {
		return nil, "", sourceFailed(err)
	}
	defer closeSource(src)
	raws, err := src.Fetch()
	if err != nil {
		return nil, "", sourceFailed(err)
	}
	name := ""
	if n, ok := src.(interface{ Name() string }); ok {
		name = n.Name()
	}
	if fetch {
		host := ""
		if j, ok := src.(*sources.JiraSource); ok {
			host = j.Host()
		}
		e.Println(i18n.P("Jira {host}: {count} tickets read", "host", textfmt.BlankControls(host), "count", len(raws)))
		if len(raws) == 0 && len(data.Tickets) > 0 {
			// "No result" never counts as "no work": do not wipe the last import.
			return nil, "", Failf("The query returned no tickets – nothing written. Check the JQL " +
				"(tracker.query) and the permissions of the token.")
		}
	}
	return raws, name, nil
}

func ticketNote(c ticketimport.Change) string {
	if c.Note == nil || *c.Note == "" {
		return ""
	}
	note := *c.Note
	switch c.Kind {
	case ticketimport.KindSprintUnresolved:
		return i18n.P(`Sprint name "{name}"`, "name", textfmt.BlankControls(note))
	case ticketimport.KindChanged:
		switch note {
		case "estimate":
			return i18n.T("Estimate")
		case "remaining":
			return i18n.T("Remaining")
		}
	case ticketimport.KindRefinedUnclear:
		switch note {
		case ticketimport.UnclearRule:
			return i18n.T("only via refined_also_if, label missing")
		case ticketimport.UnclearNoEstimate:
			return i18n.T("label without estimate")
		}
	case ticketimport.KindEarmarkDropped:
		if note == ticketimport.DroppedEnded {
			return i18n.T("sprint ended")
		}
	case ticketimport.KindMissing:
		return i18n.P("earmark for sprint {sprint} stays", "sprint", textfmt.BlankControls(note))
	}
	return textfmt.BlankControls(note)
}

// changeValue shows an old or new value of a change: a number, a sprint or a list; "–" for none.
func changeValue(v any) string {
	switch x := v.(type) {
	case nil:
		return "–"
	case string:
		if x == "" {
			return "–"
		}
		return textfmt.BlankControls(x)
	case []string:
		if len(x) == 0 {
			return "–"
		}
		items := make([]any, len(x))
		for i, s := range x {
			items[i] = s
		}
		return textfmt.BlankControls(yamlx.PyStr(items))
	case *float64:
		if x == nil {
			return "–"
		}
		return yamlx.PyStr(*x)
	case *string:
		if x == nil {
			return "–"
		}
		return textfmt.BlankControls(*x)
	}
	return textfmt.BlankControls(yamlx.PyStr(v))
}

// ticketPreview shows what an import would change, grouped by kind.
func (e *Env) ticketPreview(plan ticketimport.Plan, limit int) {
	titles := map[string]string{
		ticketimport.KindNew:              i18n.T("New tickets"),
		ticketimport.KindChanged:          i18n.T("Changed numbers"),
		ticketimport.KindDone:             i18n.T("Done"),
		ticketimport.KindMissing:          i18n.T("No longer in the import"),
		ticketimport.KindUnassigned:       i18n.T("Not assigned to a project yet"),
		ticketimport.KindUnknownEpic:      i18n.T("Unknown epics (candidates for a new project)"),
		ticketimport.KindRefinedUnclear:   i18n.T("Refined status unclear"),
		ticketimport.KindEarmarkDropped:   i18n.T("Earmark dropped"),
		ticketimport.KindEarmarkLabel:     i18n.T("Earmark taken from the label planned_for_…"),
		ticketimport.KindSprintUnresolved: i18n.T("Sprint not recognised (map it under tracker.sprint_names in team.yaml)"),
	}
	for _, kind := range ticketimport.Kinds {
		rows := plan.OfKind(kind)
		if len(rows) == 0 {
			continue
		}
		t := &Table{
			Title:  fmt.Sprintf("%s (%d)", titles[kind], len(rows)),
			Header: []string{i18n.T("Ticket"), i18n.T("Title"), i18n.T("before"), i18n.T("new"), i18n.T("Notice")},
		}
		for i, r := range rows {
			if i >= limit {
				break
			}
			t.Add(textfmt.BlankControls(r.Key), textfmt.BlankControls(r.Title), changeValue(r.Old), changeValue(r.New), ticketNote(r))
		}
		t.Render(e.Out)
		if len(rows) > limit {
			e.Println(i18n.P("… and {count} more", "count", len(rows)-limit))
		}
	}
	for _, w := range plan.Warnings {
		e.Println(textfmt.BlankControls(w))
	}
}

func (e *Env) noTickets(data *storage.TeamData) bool {
	if len(data.Tickets) > 0 {
		return false
	}
	how := "--import DATEI"
	if data.Team.Tracker.Kind == "jira" {
		how = "--fetch"
	}
	e.Println(i18n.P("No tickets yet – import first: foresprint tickets TEAM {how}", "how", how))
	return true
}

func (e *Env) printTicketIssues(data *storage.TeamData, printed []validate.Issue) {
	for _, i := range issuesFor(data, e, []string{"projects.yaml", "tickets.yaml", "preplan.yaml"}) {
		if slices.Contains(printed, i) {
			continue
		}
		e.Printf("%s %s: %s\n", i18n.T(string(i.Level)), textfmt.BlankControls(i.Where), textfmt.BlankControls(i.Message))
	}
}

func (e *Env) noBudgetWarning() {
	e.Println(i18n.P("No budget yet: without past sprints with velocity there is no forecast, so " +
		"the tickets cannot be distributed."))
}

func dash(s *string) string {
	if s == nil || *s == "" {
		return "–"
	}
	return textfmt.BlankControls(*s)
}

// ticketReport shows the distribution of the tickets: project traffic light with the range of the
// variants, sprints, refinement list.
func (e *Env) ticketReport(data *storage.TeamData, sprintCount int, printed []validate.Issue, variant preplan.Variant) error {
	if e.noTickets(data) {
		return nil
	}
	e.printTicketIssues(data, printed)
	variants, err := preplan.DistributeVariants(data, e.Today, preplan.DefaultMaxSprints)
	if err != nil {
		return asFail(err)
	}
	dist := variants.Median
	if dist.NoForecast {
		e.noBudgetWarning()
	}
	if !variants.Available() {
		e.Println(i18n.P("No range: fewer than two sprints with velocity. Only the median variant is shown."))
	}
	shown := variants.Get(variant)
	if shown == nil {
		shown = dist
	}
	if shown == dist && variant != preplan.Median {
		e.Println(i18n.P("The {variant} variant is not available (no range) – showing the median.",
			"variant", i18n.T(preplan.VariantNames[variant])))
	}
	last := []string{i18n.T("Last sprint")}
	if variants.Available() {
		last = []string{i18n.T("Last sprint optimistic"), i18n.T("Last sprint median"), i18n.T("Last sprint conservative")}
	}
	header := append([]string{i18n.T("Project"), i18n.T("Target"), i18n.T("Target sprint")}, last...)
	header = append(header, i18n.T("Traffic light"), i18n.T("Outstanding"), i18n.T("Not distributable"))
	right := make([]bool, len(header))
	right[len(header)-2], right[len(header)-1] = true, true
	projects := &Table{Title: i18n.P("Projects"), Header: header, Right: right}
	for _, row := range dist.Projects {
		name, target := row.Project, "–"
		if p := data.ProjectByID(row.Project); p != nil {
			name = p.Name
			if p.Target != nil {
				target = day(*p.Target)
			}
		}
		light := i18n.T(preplan.Lights[row.Light])
		var lastSprints []string
		if variants.Available() {
			span, err := preplan.ProjectRangeOf(variants, row.Project)
			if err != nil {
				return asFail(err)
			}
			if !span.Uniform() {
				light += fmt.Sprintf(" (%s – %s)", i18n.T(preplan.Lights[span.BestLight]), i18n.T(preplan.Lights[span.WorstLight]))
			}
			for _, v := range []preplan.Variant{preplan.Optimistic, preplan.Median, preplan.Conservative} {
				lastSprints = append(lastSprints, dash(span.LastSprint[v]))
			}
		} else {
			lastSprints = []string{dash(row.LastSprint)}
		}
		cells := append([]string{textfmt.BlankControls(name), target, dash(row.TargetSprint)}, lastSprints...)
		cells = append(cells, light, strconv.Itoa(row.OpenTickets), strconv.Itoa(row.NotDistributable))
		projects.Add(cells...)
	}
	projects.Render(e.Out)
	if shown != dist {
		e.Println(i18n.P("Sprints, refinement list and tickets that cannot be distributed: {variant} variant",
			"variant", i18n.T(preplan.VariantNames[shown.Variant])))
	}
	dist = shown

	titles := map[string]string{}
	for _, tk := range data.Tickets {
		titles[tk.Key] = tk.Title
	}
	sprints := &Table{Title: i18n.P("Sprints"),
		Header: []string{i18n.T("Sprint"), i18n.T("Budget"), i18n.T("Used"), i18n.T("Free"), i18n.T("Tickets")},
		Right:  []bool{false, true, true, true, false}}
	limit := min(sprintCount, len(dist.Sprints))
	for _, id := range dist.Sprints[:limit] {
		var base, used float64
		for _, b := range dist.Budgets {
			if b.Sprint == id {
				base += b.Base
				used += b.Fixed + b.Placed
			}
		}
		var keys []string
		for _, p := range dist.InSprint(id) {
			if p.Size != nil {
				keys = append(keys, fmt.Sprintf("%s (%s)", p.Ticket, plainNumber(*p.Size)))
			} else {
				keys = append(keys, p.Ticket)
			}
		}
		list := strings.Join(keys, ", ")
		if list == "" {
			list = "–"
		}
		sprints.Add(textfmt.BlankControls(id), plainNumber(base), plainNumber(used), plainNumber(base-used), textfmt.BlankControls(list))
	}
	sprints.Render(e.Out)

	refine := &Table{Title: i18n.P("To refine"),
		Header: []string{i18n.T("Sprint"), i18n.T("Latest by"), i18n.T("Ticket"), i18n.T("Estimate")}}
	shownSprints := dist.Sprints[:limit]
	rows := 0
	for _, item := range dist.Refinement {
		if !slices.Contains(shownSprints, item.Sprint) {
			continue
		}
		rows++
		refine.Add(textfmt.BlankControls(item.Sprint), day(item.Deadline),
			textfmt.BlankControls(strings.TrimSpace(item.Ticket+" "+titles[item.Ticket])), i18n.T(preplan.Sources[item.Source]))
	}
	if rows > 0 {
		refine.Render(e.Out)
	}
	if open := dist.NotDistributable(); len(open) > 0 {
		t := &Table{Title: i18n.P("Not distributable"), Header: []string{i18n.T("Ticket"), i18n.T("Reason")}}
		for _, p := range open {
			t.Add(textfmt.BlankControls(p.Ticket), i18n.T(preplan.Reasons[p.Reason]))
		}
		t.Render(e.Out)
	}
	if len(dist.Unclear) > 0 {
		e.Println(i18n.P("Refined status unclear (counts as rough): {keys}", "keys", textfmt.BlankControls(strings.Join(dist.Unclear, ", "))))
	}
	for _, cycle := range dist.Cycles {
		e.Println(i18n.P("circular dependencies") + ": " + textfmt.BlankControls(strings.Join(cycle, " → ")))
	}
	return nil
}

func (e *Env) ticketHandover(data *storage.TeamData, key string, sprintCount int, apply, overwrite, doCommit bool) error {
	if err := requireProducts(data, key); err != nil {
		return err
	}
	if len(data.Products) == 0 {
		return Failf("No products recorded. First: {command}", "command", "foresprint product-list "+key)
	}
	if e.noTickets(data) {
		return nil
	}
	e.printTicketIssues(data, nil)
	dist, err := preplan.Distribute(data, e.Today, preplan.DefaultMaxSprints, preplan.Median)
	if err != nil {
		return asFail(err)
	}
	if dist.NoForecast {
		e.noBudgetWarning()
	}
	rows := preplan.HandoverRows(data, dist, sprintCount)
	if len(rows) == 0 {
		e.Println(i18n.P("Nothing to hand over: no ticket is distributed in the sprints shown."))
		return nil
	}
	names := map[string]string{}
	for _, p := range data.Products {
		names[p.ID] = p.Name
	}
	pick := func(apply bool, ifApply, otherwise string) string {
		if apply {
			return ifApply
		}
		return otherwise
	}
	notes := map[string]string{
		preplan.ActionWrite:     pick(apply, i18n.T("will be written"), i18n.T("new")),
		preplan.ActionSame:      i18n.T("unchanged"),
		preplan.ActionKeep:      i18n.T("PO value stays (--overwrite replaces it)"),
		preplan.ActionOverwrite: pick(apply, i18n.T("will be replaced"), i18n.T("would be replaced (--overwrite)")),
	}
	t := &Table{Title: i18n.P("Handover to the PO pre-planning (median variant)"),
		Header: []string{i18n.T("Sprint"), i18n.T("Product"), products.MeasureLabel("preplanned"), i18n.T("Proposal"), i18n.T("Notice")}}
	var writable []preplan.HandoverRow
	for _, r := range rows {
		name := r.Product
		if n, ok := names[r.Product]; ok {
			name = n
		}
		current := "–"
		if r.Current != nil {
			current = plainNumber(*r.Current)
		}
		t.Add(textfmt.BlankControls(r.Sprint), textfmt.BlankControls(name), current, plainNumber(r.Proposed), notes[r.Action(overwrite)])
		if r.Writes(overwrite) {
			writable = append(writable, r)
		}
	}
	t.Render(e.Out)
	if !apply {
		e.Println(i18n.P("Preview only – write with --apply."))
		return nil
	}
	if len(writable) == 0 {
		e.Println(i18n.P("Nothing to write: the PO pre-planning is already in place."))
		return nil
	}
	changed := map[string]*model.Sprint{}
	var order []string
	for _, r := range writable {
		sprint := changed[r.Sprint]
		if sprint == nil {
			found, err := findOrCreateSprint(data, e, r.Sprint, forecast.PurposePlanning)
			if err != nil {
				return err
			}
			c := found.Clone()
			sprint = &c
			changed[r.Sprint] = sprint
			order = append(order, r.Sprint)
		}
		if sprint.Products == nil {
			sprint.Products = map[string]model.ProductValues{}
		}
		values := sprint.Products[r.Product]
		values.Preplanned = model.Ptr(r.Proposed)
		sprint.Products[r.Product] = values
	}
	// The sprint sequence must stay gapless: also create the calendar-only sprints in between.
	pending := map[string]bool{}
	for id := range changed {
		if data.SprintByID(id) == nil {
			pending[id] = true
		}
	}
	var lastSprint *model.Sprint
	if n := len(data.Sprints); n > 0 {
		lastSprint = &data.Sprints[n-1]
	}
	chain := calendar.NewChain(&data.Team, data.Sprints)
	for len(pending) > 0 {
		next, err := chain.After(lastSprint)
		if err != nil {
			return asFail(err)
		}
		lastSprint = &next
		delete(pending, next.ID)
		if data.SprintByID(next.ID) == nil && changed[next.ID] == nil {
			c := next.Clone()
			changed[next.ID] = &c
			order = append(order, next.ID)
		}
	}
	after := data
	var list []model.Sprint
	for _, id := range order {
		after = withSprint(after, changed[id])
		list = append(list, *changed[id])
	}
	if err := e.refuseInvalid(data, after, "sprints/"); err != nil {
		return err
	}
	return saveSprintsWith(e, key, list, i18n.T("{team}: PO pre-planning from the tickets", "team", data.Team.Name), doCommit)
}

// saveSprintsWith writes sprints and offers the commit with this message.
func saveSprintsWith(e *Env, key string, sprints []model.Sprint, message string, doCommit bool) error {
	var paths, names []string
	for i := range sprints {
		path, err := e.Repo().SaveSprint(key, &sprints[i])
		if err != nil {
			return asFail(err)
		}
		paths = append(paths, path)
		names = append(names, baseName(path))
	}
	e.Println(i18n.P("Saved: {path}", "path", strings.Join(names, ", ")))
	return e.maybeCommit(key, paths, message, "", doCommit)
}

func (e *Env) ticketWriteLabels(data *storage.TeamData, apply bool) error {
	tracker, err := jiraTracker(data, "--write-labels")
	if err != nil {
		return err
	}
	if !tracker.WriteLabels {
		return Failf("--write-labels needs tracker.write_labels: true in team.yaml.")
	}
	src, err := sources.Open(sourceSettings(tracker), "", "", nil)
	if err != nil {
		return sourceFailed(err)
	}
	defer closeSource(src)
	raws, err := src.Fetch()
	if err != nil {
		return sourceFailed(err)
	}
	if len(raws) == 0 {
		return Failf("The query returned no tickets – nothing written. Check the JQL " +
			"(tracker.query) and the permissions of the token.")
	}
	plan := ticketimport.PlanImport(ticketEnv(data, e.Today), raws, nil, false)
	labels := ticketimport.PlanLabelWrites(plan.Tickets, plan.Preplan)
	for _, w := range labels.Warnings {
		e.Println(textfmt.BlankControls(w))
	}
	if len(labels.Writes) == 0 {
		e.Println(i18n.P("No label changes needed."))
		return nil
	}
	t := &Table{Header: []string{i18n.T("Ticket"), i18n.T("Title"), i18n.T("Add label"), i18n.T("Remove label")}}
	for _, w := range labels.Writes {
		t.Add(textfmt.BlankControls(w.Key), textfmt.BlankControls(w.Title), dashList(w.Add), dashList(w.Remove))
	}
	t.Render(e.Out)
	if !apply {
		e.Println(i18n.P("Preview only – write to Jira with --apply."))
		return nil
	}
	setter, ok := src.(ticketimport.LabelSetter)
	if !ok {
		return Failf("{option} needs tracker.kind: jira in team.yaml (currently: {kind}).", "option", "--write-labels", "kind", src.Kind())
	}
	written, err := ticketimport.ApplyLabelWrites(setter, labels)
	if err != nil {
		return sourceFailed(err)
	}
	e.Println(i18n.P("{count} tickets changed in Jira. Then run --fetch --apply to read the new state.", "count", written))
	return nil
}

func dashList(l []string) string {
	if len(l) == 0 {
		return "–"
	}
	return textfmt.BlankControls(strings.Join(l, ", "))
}

var _ = sort.Strings
