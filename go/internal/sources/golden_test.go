package sources

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
)

// The comparison with golden/expected/sources, written by scripts/golden_ext/sources.py from the
// Python sources.

const goldenToken = "tok-GOLDEN-9f8e7d6c5b4a3f2e"

// orderedPairs reads a JSON object into its pairs in file order (Go maps lose the order, which
// matters for the rule fields).
func orderedPairs(tb testing.TB, raw json.RawMessage) []RuleField {
	tb.Helper()
	dec := json.NewDecoder(bytes.NewReader(raw))
	tok, err := dec.Token()
	if err != nil || tok != json.Delim('{') {
		tb.Fatalf("not an object: %s", raw)
	}
	var out []RuleField
	for dec.More() {
		name, _ := dec.Token()
		var display string
		if err := dec.Decode(&display); err != nil {
			tb.Fatal(err)
		}
		out = append(out, RuleField{Name: name.(string), Display: display})
	}
	return out
}

type goldenFields struct {
	Estimate  *string `json:"estimate"`
	Remaining *string `json:"remaining"`
	Epic      *string `json:"epic"`
}

func (g goldenFields) fields() Fields {
	val := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	return Fields{Estimate: val(g.Estimate), Remaining: val(g.Remaining), Epic: val(g.Epic)}
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func floatOrNil(f *float64) any {
	if f == nil {
		return nil
	}
	return *f
}

func list(items []string) []string {
	if items == nil {
		return []string{}
	}
	return items
}

// ticketJSON is the structure of jsonable(RawTicket).
func ticketJSON(t RawTicket) map[string]any {
	extra := map[string][]string{}
	for k, v := range t.Extra {
		extra[k] = list(v)
	}
	return map[string]any{
		"key": t.Key, "title": t.Title, "status": nullable(t.Status),
		"issue_type": nullable(t.IssueType), "priority": nullable(t.Priority),
		"extra": extra, "estimate": floatOrNil(t.Estimate), "remaining": floatOrNil(t.Remaining),
		"sprint_name": nullable(t.SprintName), "rank": nullable(t.Rank), "epic": nullable(t.Epic),
		"labels": list(t.Labels), "components": list(t.Components),
		"blocked_by": list(t.BlockedBy), "resolved": t.Resolved,
	}
}

func ticketsJSON(tickets []RawTicket) []any {
	out := make([]any, len(tickets))
	for i, t := range tickets {
		out[i] = ticketJSON(t)
	}
	return out
}

// --- CSV ---

func TestCSVGolden(t *testing.T) {
	var names []string
	golden.Load(t, &names, "sources", "csv", "index.json")
	if len(names) < 10 {
		t.Fatalf("only %d CSV cases", len(names))
	}
	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			var want struct {
				Fields     goldenFields    `json:"fields"`
				RuleFields json.RawMessage `json:"rule_fields"`
				OK         any             `json:"ok"`
				Error      *string         `json:"error"`
			}
			golden.Load(t, &want, "sources", "csv", name, "case.json")
			// The messages name the path as "input.csv".
			dir := t.TempDir()
			input, err := os.ReadFile(golden.Path(t, "sources", "csv", name, "input.csv"))
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "input.csv")
			if err := os.WriteFile(path, input, 0o600); err != nil {
				t.Fatal(err)
			}
			source := NewCSVSource(path, want.Fields.fields(), orderedPairs(t, want.RuleFields))
			tickets, err := source.Fetch()
			var got map[string]any
			if err != nil {
				got = map[string]any{"error": stripDir(err.Error(), dir)}
			} else {
				got = map[string]any{"ok": ticketsJSON(tickets)}
			}
			wantAny := map[string]any{}
			if want.Error != nil {
				wantAny["error"] = *want.Error
			} else {
				wantAny["ok"] = want.OK
			}
			golden.Compare(t, wantAny, got)
		})
	}
}

func stripDir(text, dir string) string {
	return string(bytes.ReplaceAll([]byte(text), []byte(dir+string(filepath.Separator)), nil))
}

func TestCSVNumbersGolden(t *testing.T) {
	var want struct {
		Numbers []struct {
			Text  string   `json:"text"`
			OK    *float64 `json:"ok"`
			Error bool     `json:"error"`
		} `json:"numbers"`
		Delimiters []struct {
			Line      string `json:"line"`
			Delimiter string `json:"delimiter"`
		} `json:"delimiters"`
	}
	golden.Load(t, &want, "sources", "csv", "numbers.json")
	for _, n := range want.Numbers {
		got, err := ParseNumber(n.Text)
		switch {
		case n.Error:
			if err == nil {
				t.Errorf("ParseNumber(%q) = %v, want an error", n.Text, got)
			}
		case err != nil:
			t.Errorf("ParseNumber(%q): %v", n.Text, err)
		case (got == nil) != (n.OK == nil):
			t.Errorf("ParseNumber(%q) = %v, want %v", n.Text, got, n.OK)
		case got != nil && !golden.Close(*got, *n.OK):
			t.Errorf("ParseNumber(%q) = %v, want %v", n.Text, *got, *n.OK)
		}
	}
	for _, d := range want.Delimiters {
		if got := string(SniffDelimiter(d.Line)); got != d.Delimiter {
			t.Errorf("SniffDelimiter(%q) = %q, want %q", d.Line, got, d.Delimiter)
		}
	}
}

// --- Jira ---

type route struct {
	Method  string            `json:"method"`
	Path    string            `json:"path"`
	Status  int               `json:"status"`
	Query   map[string]string `json:"query"`
	Headers map[string]string `json:"headers"`
	JSON    any               `json:"json"`
	Text    string            `json:"text"`
	Fault   string            `json:"fault"`
}

// replay answers from the recorded routes and logs what the client sent.
type replay struct {
	routes []route
	log    []any
}

type timeoutError struct{}

func (timeoutError) Error() string   { return "i/o timeout" }
func (timeoutError) Timeout() bool   { return true }
func (timeoutError) Temporary() bool { return true }

func (r *replay) RoundTrip(req *http.Request) (*http.Response, error) {
	query := map[string]any{}
	for k, v := range req.URL.Query() {
		query[k] = v[len(v)-1]
	}
	entry := map[string]any{
		"method": req.Method, "path": req.URL.Path, "query": query,
		"authorization": req.Header.Get("Authorization") == "Bearer "+goldenToken,
	}
	if req.Body != nil {
		raw, _ := io.ReadAll(req.Body)
		if len(raw) > 0 {
			var body any
			if err := json.Unmarshal(raw, &body); err != nil {
				return nil, err
			}
			entry["body"] = body
		}
	}
	r.log = append(r.log, entry)
	for _, rt := range r.routes {
		if rt.Method != req.Method || rt.Path != req.URL.Path {
			continue
		}
		matches := true
		for k, v := range rt.Query {
			if got, ok := query[k]; !ok || got != v {
				matches = false
			}
		}
		if !matches {
			continue
		}
		switch rt.Fault {
		case "timeout":
			return nil, &net.OpError{Op: "read", Err: timeoutError{}}
		case "connect":
			return nil, &net.OpError{Op: "dial", Err: errors.New("connection refused")}
		case "network":
			return nil, io.ErrUnexpectedEOF
		case "protocol":
			return nil, errors.New(`unsupported protocol scheme "x"`)
		}
		body := rt.Text
		if rt.JSON != nil {
			raw, err := json.Marshal(rt.JSON)
			if err != nil {
				return nil, err
			}
			body = string(raw)
		}
		resp := &http.Response{
			StatusCode: rt.Status, Header: http.Header{}, Request: req,
			Body: io.NopCloser(bytes.NewReader([]byte(body))),
		}
		for k, v := range rt.Headers {
			resp.Header.Set(k, v)
		}
		return resp, nil
	}
	return &http.Response{
		StatusCode: 404, Header: http.Header{}, Request: req,
		Body: io.NopCloser(bytes.NewReader([]byte(`{"message":"no such resource"}`))),
	}, nil
}

type scenario struct {
	Operation string `json:"operation"`
	Settings  struct {
		BaseURL    *string         `json:"base_url"`
		Query      *string         `json:"query"`
		Fields     goldenFields    `json:"fields"`
		RuleFields json.RawMessage `json:"rule_fields"`
		LinkType   string          `json:"link_type"`
	} `json:"settings"`
	Routes []route `json:"routes"`
	Args   struct {
		Key    string   `json:"key"`
		Add    []string `json:"add"`
		Remove []string `json:"remove"`
	} `json:"args"`
	Requests []any   `json:"requests"`
	OK       any     `json:"ok"`
	Error    *string `json:"error"`
	Refused  *string `json:"refused"`
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func candidatesJSON(cs []FieldCandidate) []any {
	out := make([]any, len(cs))
	for i, c := range cs {
		out[i] = map[string]any{"id": c.ID, "name": c.Name, "value": c.Value, "score": c.Score}
	}
	return out
}

func (s scenario) run(t *testing.T) (log []any, result map[string]any) {
	t.Helper()
	rp := &replay{routes: s.Routes}
	settings := Settings{
		Kind: "jira", BaseURL: str(s.Settings.BaseURL), Query: str(s.Settings.Query),
		Fields: s.Settings.Fields.fields(), RuleFields: orderedPairs(t, s.Settings.RuleFields),
		LinkType: s.Settings.LinkType,
	}
	source, err := NewJiraSource(settings, goldenToken, rp)
	if err != nil {
		t.Fatal(err)
	}
	var ok any
	switch s.Operation {
	case "fetch":
		var tickets []RawTicket
		tickets, err = source.Fetch()
		ok = ticketsJSON(tickets)
	case "test_connection":
		ok, err = source.TestConnection()
	case "count":
		ok, err = source.CountTickets()
	case "list_fields":
		ok, err = source.ListFields()
	case "resolve_fields":
		var r *ResolvedFields
		r, err = source.ResolveFields()
		if err == nil {
			extra := map[string]string{}
			for _, e := range r.Extra {
				extra[e.Name] = e.ID
			}
			ok = map[string]any{
				"estimate": nullable(r.Estimate), "remaining": nullable(r.Remaining),
				"epic": nullable(r.Epic), "epic_link": list(r.EpicLink),
				"sprint": list(r.Sprint), "rank": list(r.Rank), "extra": extra,
			}
		}
	case "suggest":
		var fields []map[string]any
		fields, err = source.ListFields()
		if err == nil {
			sg := SuggestFields(fields)
			ok = map[string]any{
				"estimate":  candidatesJSON(sg.Estimate),
				"remaining": candidatesJSON(sg.Remaining),
				"epic":      candidatesJSON(sg.Epic),
			}
		}
	case "set_labels":
		err = source.SetLabels(s.Args.Key, s.Args.Add, s.Args.Remove)
		ok = nil
	default:
		t.Fatalf("unknown operation %q", s.Operation)
	}
	result = map[string]any{}
	switch {
	case err == nil:
		result["ok"] = ok
	case IsSourceError(err):
		result["error"] = err.Error()
	default:
		result["refused"] = err.Error()
	}
	if rp.log == nil {
		rp.log = []any{}
	}
	return rp.log, result
}

func TestJiraGolden(t *testing.T) {
	var names []string
	golden.Load(t, &names, "sources", "jira", "index.json")
	if len(names) < 50 {
		t.Fatalf("only %d Jira scenarios", len(names))
	}
	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			var want scenario
			golden.Load(t, &want, "sources", "jira", name+".json")
			log, got := want.run(t)
			wantResult := map[string]any{}
			switch {
			case want.Error != nil:
				wantResult["error"] = *want.Error
			case want.Refused != nil:
				wantResult["refused"] = *want.Refused
			default:
				wantResult["ok"] = want.OK
			}
			golden.Compare(t, wantResult, got)
			if want.Requests == nil {
				want.Requests = []any{}
			}
			golden.Compare(t, want.Requests, log)
		})
	}
}

func TestSprintsGolden(t *testing.T) {
	var want struct {
		Parse []struct {
			Value any `json:"value"`
			OK    any `json:"ok"`
		} `json:"parse"`
		Choose []struct {
			Values any     `json:"values"`
			OK     *string `json:"ok"`
		} `json:"choose"`
	}
	golden.Load(t, &want, "sources", "jira", "sprints.json")
	for i, c := range want.Parse {
		var got any
		if s, ok := ParseSprint(c.Value); ok {
			got = map[string]any{"name": s.Name, "state": s.State, "id": s.ID}
		}
		golden.Compare(t, c.OK, got)
		_ = i
	}
	for _, c := range want.Choose {
		got := ChooseSprint(c.Values)
		if (c.OK == nil && got != "") || (c.OK != nil && got != *c.OK) {
			t.Errorf("ChooseSprint(%v) = %q, want %v", c.Values, got, c.OK)
		}
	}
}

func TestFieldTextsGolden(t *testing.T) {
	var want []struct {
		Value any      `json:"value"`
		OK    []string `json:"ok"`
	}
	golden.Load(t, &want, "sources", "jira", "field-texts.json")
	for _, c := range want {
		golden.Compare(t, list(c.OK), list(FieldTexts(c.Value)))
	}
}

func TestLabelWritesGolden(t *testing.T) {
	var want []struct {
		Path string `json:"path"`
		Body any    `json:"body"`
		OK   bool   `json:"ok"`
	}
	golden.Load(t, &want, "sources", "jira", "label-writes.json")
	if len(want) == 0 {
		t.Fatal("no label write cases")
	}
	for _, c := range want {
		if got := isLabelWrite(c.Path, c.Body); got != c.OK {
			t.Errorf("isLabelWrite(%q, %v) = %v, want %v", c.Path, c.Body, got, c.OK)
		}
	}
}

func TestURLsAndTokensGolden(t *testing.T) {
	var want struct {
		URLs []struct {
			URL          string  `json:"url"`
			Problem      *string `json:"problem"`
			KeychainUser *string `json:"keychain_user"`
			KeychainErr  *string `json:"keychain_error"`
		} `json:"urls"`
		Tokens []struct {
			Token string  `json:"token"`
			OK    bool    `json:"ok"`
			Error *string `json:"error"`
		} `json:"tokens"`
	}
	golden.Load(t, &want, "sources", "jira", "urls.json")
	for _, c := range want.URLs {
		if got := BaseURLProblem(c.URL); got != str(c.Problem) {
			t.Errorf("BaseURLProblem(%q) = %q, want %q", c.URL, got, str(c.Problem))
		}
		user, err := KeychainUser(c.URL)
		switch {
		case c.KeychainErr != nil:
			if err == nil || err.Error() != *c.KeychainErr {
				t.Errorf("KeychainUser(%q) error = %v, want %q", c.URL, err, *c.KeychainErr)
			}
		case err != nil || user != *c.KeychainUser:
			t.Errorf("KeychainUser(%q) = %q, %v, want %q", c.URL, user, err, *c.KeychainUser)
		}
	}
	for _, c := range want.Tokens {
		err := checkToken(c.Token)
		switch {
		case c.Error != nil:
			if err == nil || err.Error() != *c.Error {
				t.Errorf("checkToken(%q) error = %v, want %q", c.Token, err, *c.Error)
			}
		case err != nil:
			t.Errorf("checkToken(%q): %v", c.Token, err)
		}
	}
}
