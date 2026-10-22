package app

import (
	"math"
	"os"
	"os/exec"
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

func TestReviewTagsFollowTheReview(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	id := latestPast(t, api, team)
	if _, err := api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if _, err := api.CloseReview(team, id, ReviewInput{Tag: "-x"}); err == nil {
		t.Error("an invalid tag name was accepted")
	}
	// Closing again with another name replaces the wish; reopening takes it back.
	if _, err := api.CloseReview(team, id, ReviewInput{Tag: "release-1"}); err != nil {
		t.Fatal(err)
	}
	if _, err := api.CloseReview(team, id, ReviewInput{Tag: "release-2"}); err != nil {
		t.Fatal(err)
	}
	if got := api.pendingTags(); len(got) != 1 || got[0] != "release-2" {
		t.Fatalf("pending %v", got)
	}
	if _, err := api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if got := api.pendingTags(); len(got) != 0 {
		t.Fatalf("the custom tag stayed: %v", got)
	}
}

func TestReviewKeepsStoredNumbersAndCapacity(t *testing.T) {
	api := newAPI(t, copyDemo(t))
	team := api.Teams()[0].Key
	id := latestPast(t, api, team)
	r, _ := api.SprintReview(team, id)
	// The stored velocity is shown as it is, and the frozen days survive a reopen.
	frozen := r.FrozenDays
	if _, err := api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if after, _ := api.SprintReview(team, id); after.FrozenDays != frozen {
		t.Fatalf("frozen days %v, was %v", after.FrozenDays, frozen)
	}
	if _, err := api.CloseReview(team, id, ReviewInput{NotDone: 1, FrozenDays: 33}); err != nil {
		t.Fatal(err)
	}
	if _, err := api.ReopenReview(team, id); err != nil {
		t.Fatal(err)
	}
	if after, _ := api.SprintReview(team, id); after.FrozenDays != 33 {
		t.Fatalf("frozen days %v after reopen, the Review froze 33", after.FrozenDays)
	}
	// An older reviewed sprint cannot be closed again past a later one.
	o, _ := api.SprintOverview(team, 3)
	if len(o.Rows) > 2 {
		if _, err := api.CloseReview(team, o.Rows[0].ID, ReviewInput{}); err == nil {
			t.Error("an older reviewed sprint was closed again")
		}
	}
}

func TestPendingTagsAgainstGit(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git")
	}
	dir := copyDemo(t)
	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@example.com"}, args...)...)
		cmd.Dir = dir
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	run("init", "-q")
	run("add", "-A")
	run("commit", "-q", "-m", "start")
	api := newAPI(t, dir)
	api.addTag("t", "s1", "sprint-1")
	api.addTag("t", "s2", "has space")
	if got := api.usableTags(); len(got) != 1 || got[0] != "sprint-1" {
		t.Fatalf("usable %v: an invalid name must not reach the save", got)
	}
	run("tag", "sprint-1") // a save made the tag
	if got := api.usableTags(); len(got) != 0 {
		t.Fatalf("a tag that exists is offered again: %v", got)
	}
	api.dropSetTags()
	if got := api.pendingTags(); len(got) != 0 {
		t.Fatalf("pending %v after the tag exists and the invalid one can never be set", got)
	}
}
