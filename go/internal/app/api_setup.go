package app

import (
	"errors"
	"os"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/swallat/foresprint/internal/calendar"
	"github.com/swallat/foresprint/internal/datasvc"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/holidays"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
)

// This file is the first-start wizard (flows.md F1 and D1): where the data lives, sign-in, the
// first team and where its work comes from. Each method is one step, so that the wizard can show
// the result and let the person go back. Nothing here holds a secret: a token goes straight to
// Git's credential helper.

// store is the storage of the data folder in use.
func (a *API) store() *datasvc.Store { return datasvc.New(a.DataDir()) }

// SetupState tells the wizard what is already there.
type SetupState struct {
	DataDir string        `json:"dataDir"`
	Teams   []TeamSummary `json:"teams"`
	// Name and Email are the identity saves are made with, "" = not set yet.
	Name  string `json:"name"`
	Email string `json:"email"`
	// SuggestedHelper is the credential helper this computer offers, "" = none or already set.
	SuggestedHelper string `json:"suggestedHelper"`
}

// SetupState returns the data folder, its teams and the identity.
func (a *API) SetupState() SetupState {
	s := a.store().Storage()
	return SetupState{DataDir: a.DataDir(), Teams: a.Teams(), Name: s.Name, Email: s.Email, SuggestedHelper: s.SuggestedHelper}
}

// SetupCheckServer tests the address of a repository (format and connection); it writes nothing.
func (a *API) SetupCheckServer(address string) datasvc.ServerCheck {
	return a.store().CheckServer(address, false)
}

// Opened is the result of SetupStorage: the folder now in use, or the problem.
type Opened = datasvc.Opened

// SetupStorage makes a data folder: kind "clone" copies the repository at address into folder,
// "open" uses the existing repository at folder, "new" starts an empty one there. On success the
// folder is remembered as the data folder.
func (a *API) SetupStorage(kind, address, folder string) Opened {
	if p := a.demoProblem(); p != nil {
		return Opened{Problem: p}
	}
	st := a.store()
	var out Opened
	switch kind {
	case "clone":
		out = st.CloneFrom(address, folder)
	case "open":
		out = st.OpenFolder(folder)
	case "new":
		out = st.CreateFolder(folder)
	default:
		return Opened{Problem: &datasvc.Problem{Kind: "error", Message: i18n.T("Unknown way to set up the storage: {kind}", "kind", kind)}}
	}
	if out.Problem != nil {
		return out
	}
	if err := a.SetDataDir(out.Folder); err != nil {
		return Opened{Problem: &datasvc.Problem{Kind: "error", Message: err.Error()}}
	}
	return out
}

// SetupGuide is how to get a token at the server of the address.
func (a *API) SetupGuide(address string) datasvc.SignInGuide {
	return a.store().SignInGuide(gitsync.DetectHost(address))
}

// SetupSignIn hands a token to the credential helper and checks that the server takes it. The
// token is neither kept nor logged; an empty result means success.
func (a *API) SetupSignIn(address, username, token string) *datasvc.Problem {
	return a.store().SignIn(address, username, token)
}

// SetupEnableHelper turns on the credential helper the computer offers.
func (a *API) SetupEnableHelper(name string) *datasvc.Problem { return a.store().EnableHelper(name) }

// SetupIdentity stores the name and email address that saves are made with.
func (a *API) SetupIdentity(name, email string) *datasvc.Problem {
	return a.store().SetIdentity(name, email)
}

// Region is a country with its regions, for the holiday calendar of a new team.
type Region struct {
	Country string   `json:"country"`
	Name    string   `json:"name"`
	Regions []string `json:"regions"`
}

// SetupRegions lists the countries and regions the holiday calendar knows.
func (a *API) SetupRegions() []Region {
	var out []Region
	for _, c := range holidays.Countries() {
		out = append(out, Region{Country: c.Code, Name: c.Name, Regions: holidays.Subdivisions(c.Code)})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// NewTeam is what the wizard asks for to create a team.
type NewTeam struct {
	Name    string `json:"name"`
	Country string `json:"country"` // "DE"
	Region  string `json:"region"`  // "NW", "" = none
	// FirstSprintID and FirstStart (YYYY-MM-DD) are the sprint that runs now or starts next.
	FirstSprintID string `json:"firstSprintId"`
	FirstStart    string `json:"firstStart"`
	// NamingPattern is the sprint naming pattern ("Team {JJJJ}.{N}") the first sprint's name
	// follows; empty = read it from the name of the first sprint when that is not a plain number.
	NamingPattern string `json:"namingPattern"`
	LengthDays    int    `json:"lengthDays"` // 0 = 14
	// Source is one of the Source constants; with SourceTracker, TrackerURL and TrackerQuery
	// are needed. The token and the field mapping are set under Settings > Tickets and tracker.
	Source       string `json:"source"`
	TrackerURL   string `json:"trackerUrl"`
	TrackerQuery string `json:"trackerQuery"`
}

// sprintIDForm is the form of a sprint ID with yearly numbering: 2026.22.
var sprintIDForm = regexp.MustCompile(`^\d{4}\.\d{1,3}$`)

var notKey = regexp.MustCompile(`[^a-z0-9]+`)

var germanKey = strings.NewReplacer("ä", "ae", "ö", "oe", "ü", "ue", "ß", "ss")

// teamKey makes the folder name of a team from its name: "Team Nord" gives "team-nord", with a
// number behind it if the folder exists.
func teamKey(name string, repo *storage.Repository) string {
	key := strings.Trim(notKey.ReplaceAllString(germanKey.Replace(strings.ToLower(name)), "-"), "-")
	if len(key) > 48 {
		key = strings.Trim(key[:48], "-")
	}
	if key == "" {
		key = "team"
	}
	candidate := key
	for n := 2; ; n++ {
		if _, clash := repo.ClashingTeam(candidate); !clash {
			return candidate
		}
		candidate = key + "-" + strconv.Itoa(n)
	}
}

// applySource sets where the work of the team comes from (decision 15 of flows.md).
func applySource(team *model.Team, source, url, query string) error {
	switch source {
	case SourceTracker:
		if strings.TrimSpace(url) == "" || strings.TrimSpace(query) == "" {
			return errors.New(i18n.T("Enter the address of the tracker and the query that selects the tickets."))
		}
		if problem := model.BaseURLProblem(url); problem != "" {
			return errors.New(i18n.T("The tracker address must be an http or https address without credentials."))
		}
		team.Features.Tickets, team.Features.Projects = true, true
		team.Tracker.Kind = "jira"
		u, q := strings.TrimSpace(url), strings.TrimSpace(query)
		team.Tracker.BaseURL, team.Tracker.Query = &u, &q
	case SourcePackages:
		team.Features.Tickets, team.Features.Projects = true, true
		team.Tracker.Kind = model.PackagesKind
	case SourceNone:
		team.Features.Tickets, team.Features.Projects = false, true
	default:
		return errors.New(i18n.T("Unknown source of work: {source}", "source", source))
	}
	return nil
}

// SetupCreateTeam creates a team with its first sprints in the data folder and returns it.
func (a *API) SetupCreateTeam(req NewTeam) (TeamSummary, error) {
	name := strings.TrimSpace(req.Name)
	if name == "" {
		return TeamSummary{}, errors.New(i18n.T("Enter a name for the team."))
	}
	repo := storage.NewRepository(a.DataDir())
	team := model.NewTeam(teamKey(name, repo), name)
	if req.LengthDays < 0 || req.LengthDays > 56 {
		return TeamSummary{}, errors.New(i18n.T("A sprint lasts between 1 and 56 days."))
	}
	if req.LengthDays > 0 {
		team.Sprint.LengthDays = req.LengthDays
	}
	if req.Country != "" {
		if !knownCountry(req.Country) {
			return TeamSummary{}, errors.New(i18n.T("Unknown country: {country}", "country", req.Country))
		}
		team.Capacity.Country = req.Country
	}
	if req.Region != "" {
		if !slices.Contains(holidays.Subdivisions(team.Capacity.Country), req.Region) {
			return TeamSummary{}, errors.New(i18n.T("Unknown region: {region}", "region", req.Region))
		}
		r := req.Region
		team.Capacity.Region = &r
	}
	start, err := time.Parse("2006-01-02", req.FirstStart)
	if err != nil {
		return TeamSummary{}, errors.New(i18n.T("Enter the start of the first sprint as a date (YYYY-MM-DD)."))
	}
	id := strings.TrimSpace(req.FirstSprintID)
	if id == "" {
		return TeamSummary{}, errors.New(i18n.T("Enter the ID of the first sprint."))
	}
	pattern := strings.TrimSpace(req.NamingPattern)
	next := start.AddDate(0, 0, team.Sprint.LengthDays)
	if pattern == "" && !sprintIDForm.MatchString(id) {
		// A free name ("Team Sprint 2026.16"): the pattern comes from the name itself.
		if derived, ok := calendar.DerivePattern(id, start); ok {
			pattern = derived
		}
	}
	if pattern != "" {
		if bad := model.NamingProblem(pattern); bad != "" {
			return TeamSummary{}, errors.New(i18n.T("Unknown placeholder {placeholder} in the sprint naming pattern.", "placeholder", bad))
		}
		if !calendar.NameMatchesPattern(pattern, id) {
			return TeamSummary{}, errors.New(i18n.T("Sprint name {id} does not fit the pattern {pattern}.", "id", id, "pattern", pattern))
		}
		team.Sprint.Naming = []model.NamingRule{{Pattern: pattern}}
	} else if !sprintIDForm.MatchString(id) || !calendar.IDFitsNumbering(id, next, team.Sprint.Numbering) {
		// Yearly numbering lets any ID pass (it restarts), but a new team should start in form.
		return TeamSummary{}, errors.New(i18n.T("Sprint ID {id} does not match the numbering (expected {expected}).",
			"id", id, "expected", calendar.ExpectedIDForm(i18n.Language(), team.Sprint.Numbering)))
	}
	team.Sprint.FirstID, team.Sprint.FirstStart = &id, &start
	if err := applySource(&team, req.Source, req.TrackerURL, req.TrackerQuery); err != nil {
		return TeamSummary{}, err
	}
	// All sprints are made before anything is written, and a failed write leaves nothing behind.
	var sprints []model.Sprint
	chain := calendar.NewChain(&team, nil)
	for i := 0; i < 3; i++ {
		s, err := chain.Next()
		if err != nil {
			return TeamSummary{}, err
		}
		sprints = append(sprints, s)
	}
	if err := writeNewTeam(repo, team, sprints); err != nil {
		_ = os.RemoveAll(repo.TeamDir(team.Key))
		storage.ClearTeamCache()
		return TeamSummary{}, err
	}
	storage.ClearTeamCache()
	for _, t := range a.Teams() {
		if t.Key == team.Key {
			return t, nil
		}
	}
	return TeamSummary{Key: team.Key, Name: team.Name}, nil
}

// writeNewTeam saves the team, its empty people list and its first sprints.
func writeNewTeam(repo *storage.Repository, team model.Team, sprints []model.Sprint) error {
	if _, err := repo.SaveTeam(team); err != nil {
		return err
	}
	if _, err := repo.SavePeople(team.Key, nil); err != nil {
		return err
	}
	for i := range sprints {
		if _, err := repo.SaveSprint(team.Key, &sprints[i]); err != nil {
			return err
		}
	}
	return nil
}

func knownCountry(code string) bool {
	for _, c := range holidays.Countries() {
		if c.Code == code {
			return true
		}
	}
	return false
}
