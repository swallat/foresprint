package sources

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestIsSprintWrite(t *testing.T) {
	ok := map[string]any{"issues": []any{"A-1", "B_2-30"}}
	cases := []struct {
		path string
		body any
		want bool
	}{
		{"/rest/agile/1.0/sprint/12/issue", ok, true},
		{"/rest/agile/1.0/backlog/issue", ok, true},
		{"/rest/agile/1.0/sprint/x/issue", ok, false},
		{"/rest/agile/1.0/sprint/12/issue/../../x", ok, false},
		{"/rest/api/2/issue/A-1", ok, false},
		{"/rest/agile/1.0/sprint/12/issue", map[string]any{"issues": []any{}}, false},
		{"/rest/agile/1.0/sprint/12/issue", map[string]any{"issues": []any{"A-1"}, "rankBeforeIssue": "A-2"}, false},
		{"/rest/agile/1.0/sprint/12/issue", map[string]any{"issues": []any{"not a key"}}, false},
		{"/rest/agile/1.0/sprint/12/issue", map[string]any{"issues": []any{1}}, false},
	}
	for _, c := range cases {
		if got := isSprintWrite(c.path, c.body); got != c.want {
			t.Errorf("isSprintWrite(%q, %v) = %v", c.path, c.body, got)
		}
	}
}

func TestMoveIssues(t *testing.T) {
	var seen []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		seen = append(seen, r.Method+" "+r.URL.Path+" "+strings.TrimSpace(string(body)))
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()
	source, err := NewJiraSource(settingsFor(srv.URL), "tok", nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := source.MoveToSprint(7, []string{"A-1"}); err == nil || len(seen) != 0 {
		t.Fatalf("not enabled: %v %v", err, seen)
	}
	source.EnableSprintWrite()
	keys := make([]string, 0, 120)
	for i := 1; i <= 120; i++ {
		keys = append(keys, "A-"+itoaPad(i))
	}
	if err := source.MoveToSprint(7, keys); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 3 || !strings.HasPrefix(seen[0], "POST /rest/agile/1.0/sprint/7/issue ") {
		t.Fatalf("batches: %v", seen)
	}
	seen = nil
	if err := source.MoveToBacklog([]string{"A-1", "A-2"}); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 1 || seen[0] != `POST /rest/agile/1.0/backlog/issue {"issues":["A-1","A-2"]}` {
		t.Fatalf("backlog: %v", seen)
	}
	// Other writes stay refused even with the switch on.
	if _, err := source.request(http.MethodPost, "/rest/api/2/issue", nil, map[string]any{"issues": []any{"A-1"}}); err == nil {
		t.Fatal("POST to another path must be refused")
	}
	if _, err := source.request(http.MethodDelete, "/rest/api/2/issue/A-1", nil, nil); err == nil {
		t.Fatal("DELETE must be refused")
	}
}

func itoaPad(i int) string {
	s := ""
	for ; i > 0; i /= 10 {
		s = string(rune('0'+i%10)) + s
	}
	return s
}

func TestKnownSprints(t *testing.T) {
	source, _ := NewJiraSource(settingsFor("https://jira.example.org"), "tok", nil)
	source.rememberSprints([]any{
		"com.atlassian.greenhopper.service.sprint.Sprint@1a[id=12,state=ACTIVE,name=2026.1]",
		map[string]any{"id": json.Number("5"), "name": "2025.26", "state": "closed"},
	})
	got := source.KnownSprints()
	if len(got) != 2 || got[0].ID != "12" && got[0].ID != "5" {
		t.Fatalf("%+v", got)
	}
	if got[0].ID != "5" || got[1].Name != "2026.1" || got[0].State != "CLOSED" {
		t.Fatalf("%+v", got)
	}
}
