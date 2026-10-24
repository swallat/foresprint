package app

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/storage"
)

// A small Jira on a local port: who am I, the fields, and a search with the tickets it holds now.
type fakeJira struct {
	srv     *httptest.Server
	tickets atomic.Value // []string of keys the search returns
	denied  atomic.Bool
}

func newFakeJira(t *testing.T, keys ...string) *fakeJira {
	t.Helper()
	f := &fakeJira{}
	f.tickets.Store(keys)
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if f.denied.Load() {
			http.Error(w, "no", http.StatusUnauthorized)
			return
		}
		switch r.URL.Path {
		case "/rest/api/2/myself":
			_, _ = w.Write([]byte(`{"displayName":"Test User"}`))
		case "/rest/api/2/field":
			_, _ = w.Write([]byte(`[{"id":"customfield_1","name":"Story Points","schema":{"type":"number","custom":"x"}},{"id":"summary","name":"Summary","schema":{"type":"string"}}]`))
		case "/rest/api/2/search":
			keys := f.tickets.Load().([]string)
			var issues []string
			if r.URL.Query().Get("maxResults") != "0" {
				for _, k := range keys {
					issues = append(issues, `{"key":"`+k+`","fields":{"summary":"Ticket `+k+`","customfield_1":3}}`)
				}
			}
			body := `{"startAt":0,"total":` + strconv.Itoa(len(keys)) + `,"issues":[` + strings.Join(issues, ",") + `]}`
			_, _ = w.Write([]byte(body))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(f.srv.Close)
	return f
}

// jiraTeam turns the plan team into a Jira team that reads from the fake and has a token.
func jiraTeam(t *testing.T, f *fakeJira) (*API, string) {
	t.Helper()
	api, team := planTeam(t)
	repo := storage.NewRepository(api.DataDir())
	data, err := repo.Load(team)
	if err != nil {
		t.Fatal(err)
	}
	tm := data.Team
	url, query, est := f.srv.URL, "project = ABC", "Story Points"
	tm.Tracker.Kind, tm.Tracker.BaseURL, tm.Tracker.Query = "jira", &url, &query
	tm.Tracker.Fields.Estimate = &est
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	storage.ClearTeamCache()
	t.Setenv(sources.TokenEnv, "secret-token")
	return api, team
}

func TestTrackerConnectionNamesTheUserAndFailsWithoutAccess(t *testing.T) {
	f := newFakeJira(t, "A-1")
	api, team := jiraTeam(t, f)
	c := api.TestTrackerConnection(team, "")
	if !c.OK || c.User != "Test User" || !strings.Contains(c.Message, "Test User") {
		t.Fatalf("connection = %+v", c)
	}
	f.denied.Store(true)
	if c := api.TestTrackerConnection(team, ""); c.OK || c.Message == "" {
		t.Fatalf("a refused token must not be reported as connected: %+v", c)
	}
	t.Setenv(sources.TokenEnv, "")
	f.denied.Store(false)
	if c := api.TestTrackerConnection(team, ""); c.OK {
		t.Fatalf("without a token the test must fail: %+v", c)
	}
}

func TestTrackerQueryCountsAndFieldNamesAreSorted(t *testing.T) {
	f := newFakeJira(t, "A-1", "A-2")
	api, team := jiraTeam(t, f)
	if q := api.TestTrackerQuery(team, "", "project = ABC"); !q.OK || q.Count != 2 {
		t.Fatalf("query = %+v", q)
	}
	names := api.TrackerFieldNames(team, "")
	if len(names) != 2 || names[0] != "Story Points" || names[1] != "Summary" {
		t.Fatalf("field names = %v", names)
	}
	f.denied.Store(true)
	if names := api.TrackerFieldNames(team, ""); names == nil || len(names) != 0 {
		t.Fatalf("no connection must give an empty list, got %#v", names)
	}
}

func TestSyncTrackerWritesTicketsAndNeverWipesWithAnEmptyAnswer(t *testing.T) {
	f := newFakeJira(t, "A-1", "A-2")
	api, team := jiraTeam(t, f)
	res, err := api.SyncTracker(team)
	if err != nil || !res.OK {
		t.Fatalf("sync = %+v, %v", res, err)
	}
	keys := func() map[string]bool {
		_, data, err := api.loadRepoTeam(team)
		if err != nil {
			t.Fatal(err)
		}
		out := map[string]bool{}
		for _, tk := range data.Tickets {
			out[tk.Key] = true
		}
		return out
	}
	if got := keys(); !got["A-1"] || !got["A-2"] {
		t.Fatalf("tickets after sync = %v", got)
	}
	if info := api.TrackerInfo(team); !info.Enabled || info.Last == "" || info.Failed != "" || info.Syncing {
		t.Fatalf("info = %+v", info)
	}
	// Same answer again: nothing to write.
	if res, err := api.SyncTracker(team); err != nil || !strings.Contains(res.Message, "no changes") {
		t.Fatalf("second sync = %+v, %v", res, err)
	}
	// A query that matches nothing (wrong query, lost permission) must not wipe the import.
	f.tickets.Store([]string{})
	if _, err := api.SyncTracker(team); err == nil {
		t.Fatal("an empty answer must be refused")
	}
	if got := keys(); !got["A-1"] || !got["A-2"] {
		t.Fatalf("the import was wiped: %v", got)
	}
	if info := api.TrackerInfo(team); info.Failed == "" {
		t.Fatalf("the chip must show the failure: %+v", info)
	}
	// A working sync clears the failure again.
	f.tickets.Store([]string{"A-1", "A-2"})
	if _, err := api.SyncTracker(team); err != nil {
		t.Fatal(err)
	}
	if info := api.TrackerInfo(team); info.Failed != "" {
		t.Fatalf("failure not cleared: %+v", info)
	}
}

func TestSyncTrackerRefusesAFileTeamAndAServerError(t *testing.T) {
	api, team := planTeam(t) // a CSV team
	if _, err := api.SyncTracker(team); err == nil {
		t.Fatal("a team without Jira must not sync")
	}
	if info := api.TrackerInfo(team); info.Enabled {
		t.Fatalf("a CSV team has nothing to sync: %+v", info)
	}
	f := newFakeJira(t, "A-1")
	api, team = jiraTeam(t, f)
	f.denied.Store(true)
	if _, err := api.SyncTracker(team); err == nil {
		t.Fatal("a refused token must fail the sync")
	}
}
