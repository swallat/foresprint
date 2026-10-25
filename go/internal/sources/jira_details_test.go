package sources

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

const detailsJSON = `{"key":"A-1","fields":{"description":"  Do it\nnow ",
"subtasks":[{"key":"A-2","fields":{"summary":"Part  one","status":{"name":"Done","statusCategory":{"key":"done"}}}},
 {"key":"A-3","fields":{"summary":"Part two","status":{"name":"Open","statusCategory":{"key":"new"}}}}],
"issuelinks":[{"type":{"name":"Blocks","inward":"is blocked by","outward":"blocks"},
 "inwardIssue":{"key":"B-1","fields":{"summary":"Base","status":{"name":"Open"}}}},
 {"type":{"name":"Relates","inward":"relates to","outward":"relates to"},
 "outwardIssue":{"key":"B-2","fields":{"summary":"Side","status":{"name":"Done"}}}}],
"comment":{"comments":[{"author":{"displayName":"Ada"},"created":"2026-10-01T10:00:00.000+0000","body":"First"}]},
"attachment":[{"filename":"a.png","mimeType":"image/png","size":1234,"content":"https://j/secure/attachment/1/a.png"}]}}`

func TestFetchDetails(t *testing.T) {
	var path, fields string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path, fields = r.URL.Path, r.URL.Query().Get("fields")
		if r.Method != http.MethodGet {
			t.Errorf("method %s", r.Method)
		}
		_, _ = w.Write([]byte(detailsJSON))
	}))
	defer srv.Close()
	source, err := NewJiraSource(settingsFor(srv.URL), "tok", nil)
	if err != nil {
		t.Fatal(err)
	}
	d, err := source.FetchDetails("A-1")
	if err != nil {
		t.Fatal(err)
	}
	if path != "/rest/api/2/issue/A-1" || fields == "" {
		t.Fatalf("%s %s", path, fields)
	}
	if d.Description != "Do it\nnow" || len(d.Subtasks) != 2 || d.Subtasks[0].Title != "Part one" ||
		!d.Subtasks[0].Done || d.Subtasks[1].Done {
		t.Fatalf("%+v", d)
	}
	if len(d.Links) != 2 || d.Links[0].Direction != "inward" || d.Links[0].Text != "is blocked by" ||
		d.Links[0].Key != "B-1" || d.Links[1].Direction != "outward" || d.Links[1].Key != "B-2" {
		t.Fatalf("%+v", d.Links)
	}
	if len(d.Comments) != 1 || d.Comments[0].Author != "Ada" || len(d.Attachments) != 1 ||
		d.Attachments[0].Size != 1234 {
		t.Fatalf("%+v", d)
	}
	for _, bad := range []string{"", "a/../b", "A-1?x=1", "not a key"} {
		if _, err := source.FetchDetails(bad); err == nil {
			t.Errorf("key %q must be refused", bad)
		}
	}
}
