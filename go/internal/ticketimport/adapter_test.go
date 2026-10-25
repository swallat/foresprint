package ticketimport

import (
	"reflect"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

func TestSourceSettings(t *testing.T) {
	url, est := "https://jira.example.org", "Story Points"
	tr := model.NewTrackerSettings()
	tr.Kind, tr.BaseURL, tr.Fields.Estimate = "jira", &url, &est
	tr.RuleFields.Set("team", "Team")
	tr.RuleFields.Set("area", "Area")
	got := SourceSettings(tr)
	want := sources.Settings{
		Kind: "jira", BaseURL: url, Fields: sources.Fields{Estimate: est}, LinkType: "Blocks",
		RuleFields: []sources.RuleField{{Name: "team", Display: "Team"}, {Name: "area", Display: "Area"}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}
