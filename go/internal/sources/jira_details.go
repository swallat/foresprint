package sources

import (
	"net/http"
	"net/url"
	"strings"
)

// Details are the parts of one ticket that the sync does not read: they are fetched on demand
// when the ticket panel opens (read only). Lists are empty, never nil.
type Details struct {
	// Description is the text as Jira keeps it (wiki markup), shown as plain text.
	Description string
	Subtasks    []DetailSubtask
	Links       []DetailLink
	Comments    []DetailComment
	Attachments []DetailAttachment
}

// DetailSubtask is a sub-task of the ticket.
type DetailSubtask struct {
	Key, Title, Status string
	Done               bool
}

// DetailLink is a link to another ticket. Direction is "inward" or "outward"; Text is how Jira
// words the link from this ticket's side ("is blocked by", "relates to").
type DetailLink struct {
	Type, Direction, Text, Key, Title, Status string
}

// DetailComment is a comment on the ticket.
type DetailComment struct {
	Author, At, Text string
}

// DetailAttachment is a file attached to the ticket; URL opens it in Jira.
type DetailAttachment struct {
	Name, Mime, URL string
	Size            int64
}

const maxDetailComments = 50

func text(v any) string {
	s, _ := asString(v)
	return s
}

// FetchDetails reads description, sub-tasks, links, comments and attachments of one ticket.
func (j *JiraSource) FetchDetails(key string) (*Details, error) {
	if !issueKeyPattern.MatchString(key) {
		return nil, errorf("{key} is not a ticket key.", "key", key)
	}
	page, err := j.request(http.MethodGet, "/rest/api/2/issue/"+url.PathEscape(key), url.Values{
		"fields": {"description,subtasks,issuelinks,comment,attachment"},
	}, nil)
	if err != nil {
		return nil, err
	}
	obj, ok := asObject(page)
	if !ok {
		return nil, j.shapeError()
	}
	data, ok := asObject(obj["fields"])
	if !ok {
		return nil, j.shapeError()
	}
	d := &Details{
		Description: pyStrip(text(data["description"])),
		Subtasks:    []DetailSubtask{}, Links: []DetailLink{},
		Comments: []DetailComment{}, Attachments: []DetailAttachment{},
	}
	subs, _ := asList(data["subtasks"])
	for _, s := range subs {
		o, ok := asObject(s)
		if !ok {
			continue
		}
		f, _ := asObject(o["fields"])
		status, _ := asObject(f["status"])
		category, _ := asObject(status["statusCategory"])
		d.Subtasks = append(d.Subtasks, DetailSubtask{
			Key: text(o["key"]), Title: collapse(text(f["summary"])), Status: text(status["name"]),
			Done: strings.EqualFold(text(category["key"]), "done"),
		})
	}
	links, _ := asList(data["issuelinks"])
	for _, l := range links {
		o, ok := asObject(l)
		if !ok {
			continue
		}
		typ, _ := asObject(o["type"])
		for _, side := range []string{"inward", "outward"} {
			other, ok := asObject(o[side+"Issue"])
			if !ok {
				continue
			}
			f, _ := asObject(other["fields"])
			status, _ := asObject(f["status"])
			d.Links = append(d.Links, DetailLink{
				Type: text(typ["name"]), Direction: side, Text: text(typ[side]),
				Key: text(other["key"]), Title: collapse(text(f["summary"])), Status: text(status["name"]),
			})
		}
	}
	comments, _ := asObject(data["comment"])
	list, _ := asList(comments["comments"])
	if len(list) > maxDetailComments {
		list = list[len(list)-maxDetailComments:]
	}
	for _, c := range list {
		o, ok := asObject(c)
		if !ok {
			continue
		}
		author, _ := asObject(o["author"])
		d.Comments = append(d.Comments, DetailComment{
			Author: text(author["displayName"]), At: text(o["created"]), Text: pyStrip(text(o["body"])),
		})
	}
	files, _ := asList(data["attachment"])
	for _, a := range files {
		o, ok := asObject(a)
		if !ok {
			continue
		}
		size, _ := asInt(o["size"])
		d.Attachments = append(d.Attachments, DetailAttachment{
			Name: text(o["filename"]), Mime: text(o["mimeType"]), URL: text(o["content"]), Size: size,
		})
	}
	return d, nil
}
