package app

import (
	"os"
	"sort"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/forecast"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/rules"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/ticketimport"
)

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// optional is the pointer to a trimmed text, nil for an empty one.
func optional(s string) *string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	return &s
}

func by(mapped *string) string {
	if mapped != nil {
		return "field"
	}
	return "rule"
}

// TrackerSettings returns the settings of Settings > Tickets and tracker. The token is never part
// of it, only where it is.
func (a *API) TrackerSettings(team string) (TrackerSettings, error) {
	_, data, err := a.loadRepoTeam(team)
	if err != nil {
		return TrackerSettings{}, err
	}
	t := data.Team.Tracker
	out := TrackerSettings{
		Source:  string(data.Team.Source()),
		Kind:    t.Kind,
		BaseURL: deref(t.BaseURL), Query: deref(t.Query),
		Fields: TrackerFields{
			Estimate: deref(t.Fields.Estimate), Remaining: deref(t.Fields.Remaining), Epic: deref(t.Fields.Epic),
			Status: deref(t.Fields.Status), Acceptance: deref(t.Fields.Acceptance),
			Product: deref(t.Fields.Product), Project: deref(t.Fields.Project),
			Refined: deref(t.Fields.Refined), Production: deref(t.Fields.Production),
		},
		ProductBy: by(t.Fields.Product), ProjectBy: by(t.Fields.Project), RefinedBy: by(t.Fields.Refined),
		RefinedLabel:    deref(t.RefinedLabel),
		RefinedRule:     rules.FormatRule(t.RefinedAlsoIf),
		ProductionLabel: deref(t.ProductionLabel),
		ProdRules:       []ProdRule{},
		RuleFields:      []RuleField{},
		FixedSources:    append([]string{}, model.RuleSources...),
		WriteSprint:     t.WriteSprint, RemovedTarget: t.RemovedTarget, WriteLabels: t.WriteLabels,
		PackagePrefix: t.PackagePrefix,
		BoardID:       trackerBoardOf(t.BoardID),
		Token:         tokenState(t.BaseURL),
		Tickets:       len(data.Tickets),
	}
	if out.Kind != "csv" {
		out.Kind = "jira" // work packages keep their kind in the file; the page shows Jira then
	}
	if data.TicketsImported != nil {
		out.Imported = data.TicketsImported.Format(time.RFC3339)
	}
	switch {
	case t.Fields.Production != nil:
		out.ProductionBy = "field+rule"
	case len(t.ProductionRules) > 0 || t.ProductionLabel != nil:
		out.ProductionBy = "rule"
	default:
		out.ProductionBy = "manual"
	}
	for _, r := range t.ProductionRules {
		out.ProdRules = append(out.ProdRules, ProdRule{Rule: rules.FormatRule(r.Match), Percent: r.Percent})
	}
	for _, e := range t.RuleFields.Entries {
		out.RuleFields = append(out.RuleFields, RuleField{Name: e.Key, Display: e.Value})
	}
	return out, nil
}

func tokenState(base *string) TokenState {
	s := TokenState{KeychainUsable: sources.KeychainUsable(), Variable: sources.TokenEnv,
		FromEnv: strings.TrimSpace(os.Getenv(sources.TokenEnv)) != ""}
	if base != nil {
		if host, err := sources.KeychainUser(*base); err == nil {
			s.Host = host
			s.Stored = sources.StoredTokenExists(*base)
		}
	}
	return s
}

func parseRule(text string, srcs []string) (*model.Rule, error) {
	if strings.TrimSpace(text) == "" {
		return nil, nil
	}
	return rules.ParseRule(text, srcs)
}

// SaveTrackerSettings checks and writes the settings of Tickets and tracker to team.yaml. The
// source of the work (tracker, work packages, none) lives here only (decision 15); the fields
// of the connection are only applied while the source is a tracker.
func (a *API) SaveTrackerSettings(team string, in TrackerSettings) error {
	repo, data, err := a.loadRepoTeam(team)
	if err != nil {
		return err
	}
	t := data.Team
	prefix := strings.TrimSpace(in.PackagePrefix)
	if t.TrackerRaw != nil && in.Source != "none" {
		return bad("The tracker section of team.yaml cannot be read. Fix it by hand first; Foresprint does not overwrite it.")
	}
	switch in.Source {
	case "none":
		t.Features.Tickets = false
	case "packages":
		t.Features.Tickets = true
		t.Tracker.Kind = model.PackagesKind
		t.Tracker.PackagePrefix = prefix
		if prefix != "" && !prefixOK(prefix) {
			return bad("The prefix of work packages is letters and digits only.")
		}
	case "tracker":
		if in.Kind != "jira" && in.Kind != "csv" {
			return bad("Unknown kind of tracker: {value}", "value", in.Kind)
		}
		if err := a.applyTracker(&t, data, in); err != nil {
			return err
		}
		t.Features.Tickets = true
	default:
		return bad("Unknown source of the work: {value}", "value", in.Source)
	}
	t.Features.Explicit = true
	if _, err := repo.SaveTeam(t); err != nil {
		return err
	}
	storage.ClearTeamCache()
	return nil
}

func prefixOK(s string) bool {
	for _, r := range s {
		if (r < 'A' || r > 'Z') && (r < 'a' || r > 'z') && (r < '0' || r > '9') {
			return false
		}
	}
	return true
}

// applyTracker puts the tracker part of the page into the team after checking it.
func (a *API) applyTracker(t *model.Team, data *storage.TeamData, in TrackerSettings) error {
	tr := t.Tracker
	tr.Kind = in.Kind
	if in.Kind == "jira" {
		if base := strings.TrimSpace(in.BaseURL); base != "" {
			switch model.BaseURLProblem(base) {
			case model.URLInvalid:
				return bad("The address of the tracker must be a web address (https://…).")
			case model.URLCredentials:
				return bad("The address must not contain a user name or password. The token is kept in the keychain.")
			case model.URLExtra:
				return bad("The address must not contain parameters (?…) or a fragment (#…).")
			}
		}
	}
	tr.BaseURL = optional(in.BaseURL)
	tr.Query = optional(in.Query)

	// Rule fields first: the rules below may name them.
	var fields model.OrderedMap[string]
	for _, f := range in.RuleFields {
		name, display := strings.TrimSpace(f.Name), strings.TrimSpace(f.Display)
		switch {
		case name == "" && display == "":
			continue
		case !model.RuleFieldName.MatchString(name):
			return bad("The name {name} is not allowed: lower-case letters, digits and _, starting with a letter.", "name", name)
		case contains(model.RuleSources, name) || contains(model.RuleReserved, name):
			return bad("The name {name} is taken by Foresprint.", "name", name)
		case display == "":
			return bad("Name the field of the tracker for {name}.", "name", name)
		}
		if _, dup := fields.Get(name); dup {
			return bad("{name} is listed twice.", "name", name)
		}
		fields.Set(name, display)
	}
	srcs := model.RuleSourcesWith(fields)

	refined, err := parseRule(in.RefinedRule, srcs)
	if err != nil {
		return bad("Rule for “refined”: {problem}", "problem", err.Error())
	}
	var prod []model.ProductionRule
	for i, r := range in.ProdRules {
		if in.ProductionBy == "manual" {
			break // hidden and removed on apply: no reason to check them
		}
		if !(r.Percent >= 0 && r.Percent <= 100) {
			return bad("Production share of rule {number}: between 0 and 100 percent.", "number", i+1)
		}
		m, err := parseRule(r.Rule, srcs)
		if err != nil {
			return bad("Production rule {number}: {problem}", "number", i+1, "problem", err.Error())
		}
		if m == nil {
			return bad("Production rule {number} is empty.", "number", i+1)
		}
		prod = append(prod, model.ProductionRule{Match: m, Percent: r.Percent})
	}

	// A field that a rule uses cannot be removed (decision 21).
	used := map[string]bool{}
	note := func(r *model.Rule) {
		if r != nil {
			for _, src := range r.LeafSources() {
				used[src] = true
			}
		}
	}
	note(refined)
	for _, r := range prod {
		note(r.Match)
	}
	for _, p := range data.Products {
		note(p.Match)
	}
	for _, p := range data.Projects {
		note(p.Match)
	}
	for _, name := range tr.RuleFields.Keys() {
		if _, kept := fields.Get(name); !kept && used[name] {
			return bad("The field {name} is used by a rule and cannot be removed yet.", "name", name)
		}
	}

	f := in.Fields
	mapped := func(by, value string) *string {
		if by == "field" {
			return optional(value)
		}
		return nil
	}
	tr.Fields = model.TrackerFields{
		Estimate: optional(f.Estimate), Remaining: optional(f.Remaining), Epic: optional(f.Epic),
		Status: optional(f.Status), Acceptance: optional(f.Acceptance),
		Product: mapped(in.ProductBy, f.Product), Project: mapped(in.ProjectBy, f.Project),
		Refined: mapped(in.RefinedBy, f.Refined),
	}
	tr.RuleFields = fields
	tr.RefinedLabel = optional(in.RefinedLabel)
	tr.RefinedAlsoIf = refined
	switch in.ProductionBy {
	case "manual":
		tr.ProductionLabel, tr.ProductionRules = nil, nil
	case "rule", "field+rule":
		if in.ProductionBy == "field+rule" {
			tr.Fields.Production = optional(f.Production)
		}
		tr.ProductionLabel = optional(in.ProductionLabel)
		tr.ProductionRules = prod
	default:
		return bad("Unknown source of the production share: {value}", "value", in.ProductionBy)
	}
	if in.RemovedTarget != "" && !contains(model.RemovedTargets, in.RemovedTarget) {
		return bad("Unknown place for removed tickets: {value}", "value", in.RemovedTarget)
	}
	if in.BoardID < 0 {
		return bad("The board number is a positive whole number.")
	}
	if in.Kind == "jira" { // the board belongs to Jira; another kind keeps what is there
		tr.BoardID = nil
		if in.BoardID > 0 {
			n := in.BoardID
			tr.BoardID = &n
		}
	}
	tr.WriteSprint, tr.RemovedTarget, tr.WriteLabels = in.WriteSprint, in.RemovedTarget, in.WriteLabels
	t.Tracker = tr
	return nil
}

// --- Token, tests and sync ---------------------------------------------------------------

// trackerOf returns the stored tracker settings with the address of the page, for tests that
// run before the page is applied.
func (a *API) trackerOf(team, base string) (model.TrackerSettings, error) {
	_, data, err := a.loadRepoTeam(team)
	if err != nil {
		return model.TrackerSettings{}, err
	}
	t := data.Team.Tracker
	t.Kind = "jira"
	if base = strings.TrimSpace(base); base != "" {
		t.BaseURL = &base
	}
	if t.BaseURL == nil {
		return t, bad("Enter the address of the tracker first.")
	}
	return t, nil
}

// SetTrackerToken stores the token in the keychain of the operating system (per host of the
// address). The token is not kept anywhere else and never returned.
func (a *API) SetTrackerToken(team, baseURL, token string) error {
	t, err := a.trackerOf(team, baseURL)
	if err != nil {
		return err
	}
	if !sources.KeychainUsable() {
		return bad("The keychain is not available on this computer. Set the environment variable {variable} instead.",
			"variable", sources.TokenEnv)
	}
	return sources.StoreToken(*t.BaseURL, strings.TrimSpace(token))
}

// RemoveTrackerToken deletes the token of the host from the keychain.
func (a *API) RemoveTrackerToken(team, baseURL string) error {
	t, err := a.trackerOf(team, baseURL)
	if err != nil {
		return err
	}
	return sources.DeleteToken(*t.BaseURL)
}

func openJira(t model.TrackerSettings) (*sources.JiraSource, error) {
	src, err := sources.Open(ticketimport.SourceSettings(t), "", "", nil)
	if err != nil {
		return nil, err
	}
	jira, ok := src.(*sources.JiraSource)
	if !ok {
		return nil, bad("Only Jira can be tested here.")
	}
	return jira, nil
}

// TestTrackerConnection checks address and token (GET /myself) and the mapped fields.
func (a *API) TestTrackerConnection(team, baseURL string) Connection {
	t, err := a.trackerOf(team, baseURL)
	if err != nil {
		return Connection{Message: err.Error()}
	}
	jira, err := openJira(t)
	if err != nil {
		return Connection{Message: err.Error()}
	}
	defer jira.Close()
	user, err := jira.TestConnection()
	if err != nil {
		return Connection{Message: err.Error()}
	}
	if _, err := jira.ResolveFields(); err != nil {
		return Connection{Message: err.Error(), User: user}
	}
	return Connection{OK: true, User: user,
		Message: i18n.T("Connected to {host} as {name}.", "host", jira.Host(), "name", user)}
}

// TestTrackerQuery counts the tickets a query matches without reading them.
func (a *API) TestTrackerQuery(team, baseURL, query string) QueryCheck {
	t, err := a.trackerOf(team, baseURL)
	if err != nil {
		return QueryCheck{Message: err.Error()}
	}
	t.Query = optional(query)
	jira, err := openJira(t)
	if err != nil {
		return QueryCheck{Message: err.Error()}
	}
	defer jira.Close()
	n, err := jira.CountTickets()
	if err != nil {
		return QueryCheck{Message: err.Error()}
	}
	return QueryCheck{OK: true, Count: n, Message: i18n.T("The query matches {count} tickets.", "count", n)}
}

// TrackerFieldNames lists the names of all fields of the tracker, for suggestions in the field
// mapping. Empty (no error) while there is no connection yet.
func (a *API) TrackerFieldNames(team, baseURL string) []string {
	t, err := a.trackerOf(team, baseURL)
	if err != nil {
		return []string{}
	}
	jira, err := openJira(t)
	if err != nil {
		return []string{}
	}
	defer jira.Close()
	list, err := jira.ListFields()
	if err != nil {
		return []string{}
	}
	seen := map[string]bool{}
	names := []string{}
	for _, f := range list {
		if n, ok := f["name"].(string); ok && n != "" && !seen[n] {
			seen[n] = true
			names = append(names, n)
		}
	}
	sort.Strings(names)
	return names
}

// trackerRun is what the top bar shows of the last attempts to sync, kept per run of the program.
type trackerRun struct {
	syncing map[string]bool
	failed  map[string]string
}

// TrackerInfo is the state of the tracker sync of a team for the chip in the top bar.
func (a *API) TrackerInfo(team string) TrackerStatus {
	_, data, err := a.loadRepoTeam(team)
	if err != nil || data.Team.Source() != model.SourceTracker || data.Team.Tracker.Kind != "jira" {
		return TrackerStatus{} // a CSV export is read in by hand: nothing to sync
	}
	out := TrackerStatus{Enabled: true, Name: "Jira"}
	if data.TicketsImported != nil {
		out.Last = data.TicketsImported.Format(time.RFC3339)
	}
	a.mu.Lock()
	out.Syncing, out.Failed = a.run.syncing[team], a.run.failed[team]
	a.mu.Unlock()
	return out
}

// SyncTracker reads the tickets from Jira now (query, fields and token as saved) and writes
// tickets.yaml and, if the reconciliation needs it, preplan.yaml. A query without tickets never
// wipes the last import.
func (a *API) SyncTracker(team string) (Result, error) {
	a.mu.Lock()
	if a.run.syncing[team] {
		a.mu.Unlock()
		return Result{Message: i18n.T("A sync is already running.")}, nil
	}
	if a.run.syncing == nil {
		a.run.syncing = map[string]bool{}
	}
	a.run.syncing[team] = true
	a.mu.Unlock()
	res, err := a.syncTracker(team)
	a.mu.Lock()
	delete(a.run.syncing, team)
	if a.run.failed == nil {
		a.run.failed = map[string]string{}
	}
	if err != nil {
		a.run.failed[team] = err.Error()
	} else {
		delete(a.run.failed, team)
	}
	a.mu.Unlock()
	return res, err
}

func (a *API) syncTracker(team string) (Result, error) {
	_, data, err := a.loadRepoTeam(team)
	if err != nil {
		return Result{}, err
	}
	if data.Team.Source() != model.SourceTracker || data.Team.Tracker.Kind != "jira" {
		return Result{}, bad("This team does not read its tickets from Jira.")
	}
	jira, err := openJira(data.Team.Tracker)
	if err != nil {
		return Result{}, err
	}
	defer jira.Close()
	raws, err := jira.Fetch()
	if err != nil {
		return Result{}, err
	}
	// Edits of the PO during the fetch (pro-forma, earmarks, order) must not be written over:
	// work from the files as they are now.
	backlogMu.Lock()
	defer backlogMu.Unlock()
	repo, data, err := a.loadRepoTeam(team)
	if err != nil {
		return Result{}, err
	}
	if len(raws) == 0 && len(data.Tickets) > 0 {
		return Result{}, bad("The query returned no tickets – nothing written. Check the query and the permissions of the token.")
	}
	name := jira.Name()
	env := ticketimport.Env{Tracker: data.Team.Tracker, Projects: data.Projects, Tickets: data.Tickets,
		Preplan: data.Preplan, Sprints: knownSprints{data}, Today: time.Now()}
	plan := ticketimport.PlanImport(env, raws, &name, true)
	if plan.Unchanged(data.Tickets, data.TicketsSource) {
		return Result{OK: true, Message: i18n.T("{count} tickets read, no changes.", "count", len(raws))}, nil
	}
	if _, err := plan.Apply(planSaver{repo}, team, time.Now()); err != nil {
		return Result{}, err
	}
	storage.ClearTeamCache()
	return Result{OK: true, Message: i18n.T("{count} tickets read, {changes} changes.", "count", len(raws), "changes", len(plan.Changes))}, nil
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

// TokenInfo says where the token of the address is, for the page after it stored or removed one.
func (a *API) TokenInfo(team, baseURL string) TokenState {
	if base := strings.TrimSpace(baseURL); base != "" {
		return tokenState(&base)
	}
	return tokenState(nil)
}

// trackerBoardOf is the board number of the settings, 0 when none is set.
func trackerBoardOf(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}
