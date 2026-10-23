package app

import (
	"strings"

	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/sources"
	"github.com/swallat/foresprint/internal/ticketimport"
)

// detailsTracker is the tracker as the panel needs it; tests replace detailsOpen by a fake.
type detailsTracker interface {
	FetchDetails(key string) (*sources.Details, error)
	Close()
}

var detailsOpen = func(t model.TrackerSettings) (detailsTracker, error) {
	src, err := sources.Open(ticketimport.SourceSettings(t), "", "", nil)
	if err != nil {
		return nil, err
	}
	jira, ok := src.(*sources.JiraSource)
	if !ok {
		return nil, nil //nolint:nilnil // no Jira: nothing to read
	}
	return jira, nil
}

// TicketTracker reads description, sub-tasks, links, comments and attachments of one tracker
// ticket from the tracker (read only), for the ticket panel. Without Jira the answer is empty
// with Available false; a failed read is returned as an error the panel shows in place.
func (a *API) TicketTracker(team, key string) (*TrackerDetails, error) {
	out := &TrackerDetails{
		Subtasks: []TrackerSubtask{}, Links: []TrackerLink{},
		Comments: []Comment{}, Attachments: []TrackerAttachment{},
	}
	_, data, err := a.loadTickets(team)
	if err != nil {
		return nil, err
	}
	tracker := data.Team.Tracker
	if tracker.Kind != "jira" || data.TicketByKey(key) == nil {
		return out, nil
	}
	src, err := detailsOpen(tracker)
	if err != nil {
		if err.Error() == sources.MissingTokenError().Error() {
			return out, nil // no token yet: the panel shows what it has, Settings > Tickets explains
		}
		return nil, err
	}
	if src == nil {
		return out, nil
	}
	defer src.Close()
	d, err := src.FetchDetails(key)
	if err != nil {
		return nil, err
	}
	base := ""
	if tracker.BaseURL != nil {
		base = strings.TrimRight(*tracker.BaseURL, "/")
	}
	out.Available = true
	out.Description = d.Description
	for _, s := range d.Subtasks {
		out.Subtasks = append(out.Subtasks, TrackerSubtask{Key: s.Key, Title: s.Title, Status: s.Status, Done: s.Done})
	}
	for _, l := range d.Links {
		out.Links = append(out.Links, TrackerLink{
			Type: l.Type, Text: l.Text, Key: l.Key, Title: l.Title, Status: l.Status, URL: base + "/browse/" + l.Key,
		})
	}
	for _, c := range d.Comments {
		out.Comments = append(out.Comments, Comment{Author: c.Author, At: c.At, Text: c.Text})
	}
	for _, f := range d.Attachments {
		out.Attachments = append(out.Attachments, TrackerAttachment{Name: f.Name, Mime: f.Mime, Size: f.Size, URL: f.URL})
	}
	return out, nil
}
