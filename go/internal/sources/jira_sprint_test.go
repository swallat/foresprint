package sources

import (
	"encoding/json"
	"testing"
)

func TestParseSprintIDForms(t *testing.T) {
	dc := "com.atlassian.greenhopper.service.sprint.Sprint@1a2b[id=1234,rapidViewId=3,state=FUTURE,name=2026.3,goal=]"
	if s, ok := ParseSprint(dc); !ok || s.ID != "1234" || s.Name != "2026.3" {
		t.Fatalf("%+v %v", s, ok)
	}
	cloud := map[string]any{"id": json.Number("1234"), "name": "2026.3", "state": "future"}
	if s, ok := ParseSprint(cloud); !ok || s.ID != "1234" {
		t.Fatalf("%+v %v", s, ok)
	}
}
