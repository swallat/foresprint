package app

import (
	"math"
	"os"
	"strings"
	"testing"
)

// latestPast is the id of the newest finished sprint of the demo team.
func latestPast(t *testing.T, api *API, team string) string {
	t.Helper()
	o, err := api.SprintOverview(team, 1)
	if err != nil {
		t.Fatal(err)
	}
	for i := len(o.Rows) - 1; i >= 0; i-- {
		if o.Rows[i].State == SprintPast {
			return o.Rows[i].ID
		}
	}
	t.Fatal("no finished sprint")
	return ""
}

func TestReviewCloseReopen(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	id := latestPast(t, api, team)

	r, err := api.SprintReview(team, id)
	if err != nil {
		t.Fatal(err)
	}
	if !r.Started || !r.Reviewed || !r.Reopenable || r.Tickets {
		t.Fatalf("recorded review: %+v", r)
	}
	if r.Tag != team+"/"+id || len(r.Targets) < 2 {
		t.Fatalf("tag %q, targets %+v", r.Tag, r.Targets)
	}
	if _, err = api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if r, _ = api.SprintReview(team, id); r.Reviewed {
		t.Fatal("still reviewed after reopening")
	}

	in := ReviewInput{NotDone: 4, AdditionalDone: 2, RestNext: 3, FrozenDays: 47, Tag: team + "/" + id}
	for _, p := range r.Products {
		in.Products = append(in.Products, ReviewProduct{ID: p.ID, Done: 5, ProdDone: 1})
	}
	closed, err := api.CloseReview(team, id, in)
	if err != nil {
		t.Fatal(err)
	}
	c := closed.Review
	if !c.Reviewed || c.NotDone != 4 || c.AdditionalDone != 2 || c.RestNext != 3 || c.FrozenDays != 47 {
		t.Fatalf("closed: %+v", c)
	}
	if want := c.Commitment - 4 + 2; c.Velocity != want {
		t.Fatalf("velocity %v, want %v", c.Velocity, want)
	}
	if c.Rate == nil || math.Abs(*c.Rate-c.Velocity/47) > 1e-9 {
		t.Fatalf("rate %v", c.Rate)
	}
	if len(c.Products) == 0 || c.Products[0].Done != 5 || c.Products[0].ProdDone != 1 && c.ProductionOn {
		t.Fatalf("products %+v", c.Products)
	}
	if closed.Tag != team+"/"+id || len(api.pendingTags()) != 1 {
		t.Fatalf("tag %q, pending %v", closed.Tag, api.pendingTags())
	}
	if !strings.HasPrefix(closed.Minutes, "protokolle/") {
		t.Fatalf("minutes file %q", closed.Minutes)
	}
	text, err := api.MinutesText(team, closed.Minutes)
	if err != nil || !strings.Contains(text.Text, "47") {
		t.Fatalf("minutes text: %v\n%s", err, text.Text)
	}
	// Closing the same numbers again writes no further minutes.
	if _, err = api.CloseReview(team, id, in); err != nil {
		t.Fatal(err)
	}
	rows, err := api.SprintMinutes(team, id)
	if err != nil || len(rows) != 1 || rows[0].Kind != "review" || rows[0].Obsolete {
		t.Fatalf("minutes %+v %v", rows, err)
	}

	// Reopening keeps the file, marked obsolete, and drops the tag.
	if _, err = api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if rows, _ = api.SprintMinutes(team, id); len(rows) != 1 || !rows[0].Obsolete {
		t.Fatalf("after reopening: %+v", rows)
	}
	if len(api.pendingTags()) != 0 {
		t.Fatalf("tag kept: %v", api.pendingTags())
	}
	if all, _ := api.SprintMinutes(team, ""); len(all) != 1 {
		t.Fatalf("all minutes: %+v", all)
	}
}

func TestReviewRefusals(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	id := latestPast(t, api, team)
	if _, err := api.CloseReview(team, id, ReviewInput{NotDone: -1}); err == nil {
		t.Error("negative accepted")
	}
	if _, err := api.CloseReview(team, id, ReviewInput{NotDone: 1e9}); err == nil {
		t.Error("not done above the commitment accepted")
	}
	if _, err := api.CloseReview(team, id, ReviewInput{NotDone: 1, RestNext: 2}); err == nil {
		t.Error("rest above not done accepted")
	}
	if _, err := api.MinutesText(team, "../team.yaml"); err == nil {
		t.Error("path outside the minutes accepted")
	}
	if _, err := api.MinutesText(team, "sprints/"+id+".yaml"); err == nil {
		t.Error("a sprint file accepted as minutes")
	}
	o, _ := api.SprintOverview(team, 0)
	for _, r := range o.Rows {
		if r.State == SprintFuture {
			if _, err := api.CloseReview(team, r.ID, ReviewInput{}); err == nil {
				t.Error("a sprint that has not begun was reviewed")
			}
			break
		}
	}
	// Only the latest reviewed sprint is reopened.
	if o, _ = api.SprintOverview(team, 3); len(o.Rows) > 2 {
		if _, err := api.ReopenReview(team, o.Rows[0].ID); err == nil {
			t.Error("an older sprint was reopened")
		}
	}
	if _, err := os.Stat(api.DataDir()); err != nil {
		t.Fatal(err)
	}
}

func TestReviewTickets(t *testing.T) {
	dir := copyDemo(t)
	api := newAPI(t, dir)
	team := api.Teams()[0].Key
	id := latestPast(t, api, team)
	if _, err := api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	// Turn on tickets and commit three of them to the sprint.
	teamFile := dir + "/" + team + "/team.yaml"
	write := func(path, text string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	b, _ := os.ReadFile(teamFile)
	write(teamFile, strings.Replace(string(b), "features:\n", "features:\n  tickets: true\n", 1))
	write(dir+"/"+team+"/tickets.yaml", `schema: 1
tickets:
- {key: T-1, title: First, estimate: 5, done: true}
- {key: T-2, title: Second, estimate: 3, remaining: 1}
- {key: T-3, title: Third, estimate: 8}
`)
	sprintFile := dir + "/" + team + "/sprints/" + id + ".yaml"
	sb, _ := os.ReadFile(sprintFile)
	write(sprintFile, string(sb)+"committed_tickets: [T-1, T-2, T-3]\n")

	r, err := api.SprintReview(team, id)
	if err != nil {
		t.Fatal(err)
	}
	if !r.Tickets || len(r.List) != 3 || !r.List[0].Done || r.List[1].Rest != 1 || r.List[2].Rest != 8 {
		t.Fatalf("tickets review: %+v", r)
	}
	if r.NotDone != 11 {
		t.Fatalf("not done %v, want the two open tickets (3 + 8)", r.NotDone)
	}
	// T-2 turns out done; T-3 continues with a rest of 4 in the backlog.
	in := ReviewInput{FrozenDays: 40, List: []ReviewTicket{
		{Key: "T-2", Done: true}, {Key: "T-3", Rest: 4, Target: "backlog"}}}
	closed, err := api.CloseReview(team, id, in)
	if err != nil {
		t.Fatal(err)
	}
	c := closed.Review
	if c.NotDone != 8 || c.Velocity != c.Commitment-8 {
		t.Fatalf("closed: %+v", c)
	}
	if c.List[1].Done != true || c.List[2].Done || c.List[2].Rest != 4 || c.List[2].Target != "backlog" {
		t.Fatalf("carry did not come back: %+v", c.List)
	}
	text, _ := api.MinutesText(team, closed.Minutes)
	if !strings.Contains(text.Text, "T-3") || !strings.Contains(text.Text, "T-1") {
		t.Fatalf("minutes without the tickets:\n%s", text.Text)
	}
}
