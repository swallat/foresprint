package app

import (
	"errors"
	"testing"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
)

type fakeDetails struct{ d *sources.Details }

func (f fakeDetails) FetchDetails(string) (*sources.Details, error) { return f.d, nil }
func (fakeDetails) Close()                                          {}

func TestTicketTrackerDetails(t *testing.T) {
	api, team := planTeam(t)
	// A CSV team has nothing to read: empty lists, not Available.
	d, err := api.TicketTracker(team, "T-1")
	if err != nil || d.Available {
		t.Fatalf("csv: %+v %v", d, err)
	}
	assertNoNilLists(t, "TicketTracker(csv)", d)

	repo, data, err := api.loadTickets(team)
	if err != nil {
		t.Fatal(err)
	}
	tm := data.Team
	tm.Tracker.Kind = "jira"
	base := "https://jira.example.org/"
	tm.Tracker.BaseURL = &base
	if _, err := repo.SaveTeam(tm); err != nil {
		t.Fatal(err)
	}
	old := detailsOpen
	detailsOpen = func(model.TrackerSettings) (detailsTracker, error) {
		return fakeDetails{&sources.Details{
			Description: "Text",
			Subtasks:    []sources.DetailSubtask{{Key: "T-9", Title: "Part", Status: "Done", Done: true}},
			Links:       []sources.DetailLink{{Type: "Blocks", Direction: "inward", Text: "is blocked by", Key: "T-2", Title: "Other"}},
			Comments:    []sources.DetailComment{{Author: "Ada", At: "2026-10-01T10:00:00.000+0000", Text: "Hi"}},
			Attachments: []sources.DetailAttachment{{Name: "a.png", Size: 12, URL: "https://jira.example.org/secure/attachment/1/a.png"}},
		}}, nil
	}
	t.Cleanup(func() { detailsOpen = old })
	d, err = api.TicketTracker(team, "T-1")
	if err != nil || !d.Available || d.Description != "Text" || len(d.Subtasks) != 1 || !d.Subtasks[0].Done ||
		len(d.Links) != 1 || d.Links[0].URL != "https://jira.example.org/browse/T-2" ||
		len(d.Comments) != 1 || len(d.Attachments) != 1 {
		t.Fatalf("jira: %+v %v", d, err)
	}
	// A ticket the team does not know is not read from the tracker.
	if d, _ = api.TicketTracker(team, "NOPE-1"); d.Available {
		t.Fatal("unknown ticket must not reach the tracker")
	}
	// No token is "not available", any other failure is an error.
	detailsOpen = func(model.TrackerSettings) (detailsTracker, error) { return nil, sources.MissingTokenError() }
	if d, err = api.TicketTracker(team, "T-1"); err != nil || d.Available {
		t.Fatalf("no token: %+v %v", d, err)
	}
	detailsOpen = func(model.TrackerSettings) (detailsTracker, error) { return nil, errors.New("down") }
	if _, err = api.TicketTracker(team, "T-1"); err == nil {
		t.Fatal("a failing tracker must be an error")
	}
	// A Jira answer without lists still gives empty lists.
	detailsOpen = func(model.TrackerSettings) (detailsTracker, error) { return fakeDetails{&sources.Details{}}, nil }
	d, _ = api.TicketTracker(team, "T-1")
	assertNoNilLists(t, "TicketTracker(empty)", d)
}
