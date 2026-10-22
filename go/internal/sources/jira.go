package sources

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// Version is the program version for the User-Agent header; the program sets it.
var Version = "dev"

const (
	// RequestTimeout is the time one request may take.
	RequestTimeout = 30 * time.Second
	pageSize       = 100
	searchPath     = "/rest/api/2/search"
)

// The fields Jira Software adds are found by their schema, not by their (localized) name.
const (
	sprintSchema   = "com.pyxis.greenhopper.jira:gh-sprint"
	rankSchema     = "com.pyxis.greenhopper.jira:gh-lexo-rank"
	epicLinkSchema = "com.pyxis.greenhopper.jira:gh-epic-link"
	// parentField as value of tracker.fields.epic: the parent issue is the epic.
	parentField = "parent"
)

// epicTypeNames are the names of the issue type "Epic" (Jira returns the localized name).
var epicTypeNames = []string{"epic", "epos"}

// baseFields are asked for by every request; the custom fields come from resolvedFields.
var baseFields = []string{
	"summary", "status", "issuetype", "priority", "labels", "components", "resolution",
	"issuelinks", "parent",
}

var issuePath = regexp.MustCompile(`^/rest/api/2/issue/[A-Za-z][A-Za-z0-9_]*-[0-9]+$`)

// isLabelWrite says whether a PUT is exactly a change of planned_for_* labels of one ticket,
// nothing else.
func isLabelWrite(path string, body any) bool {
	obj, ok := asObject(body)
	if !ok || !issuePath.MatchString(path) || len(obj) != 1 {
		return false
	}
	update, ok := asObject(obj["update"])
	if !ok || len(update) != 1 {
		return false
	}
	operations, ok := asList(update["labels"])
	if !ok || len(operations) == 0 {
		return false
	}
	for _, o := range operations {
		op, ok := asObject(o)
		if !ok || len(op) != 1 {
			return false
		}
		for verb, value := range op {
			label, isStr := asString(value)
			if verb != "add" && verb != "remove" || !isStr {
				return false
			}
			if !strings.HasPrefix(label, LabelPrefix) || len(label) == len(LabelPrefix) {
				return false
			}
			if strings.IndexFunc(label, pyIsSpace) >= 0 {
				return false
			}
		}
	}
	return true
}

// JiraSource reads tickets from a Jira Data Center query (JQL in Settings.Query). It only
// reads, with one exception: SetLabels changes planned_for_* labels of one ticket. Every request
// goes through request, the one function that talks to the network; the token and the content of
// answers never end up in messages.
type JiraSource struct {
	settings Settings
	baseURL  string
	host     string
	token    secret
	client   *http.Client
	fields   *resolvedFields
	// sprintWrite allows moving tickets between sprints (EnableSprintWrite); off by default.
	sprintWrite bool
	// seen are the sprints met in the sprint field of fetched tickets, by Jira id.
	seen map[string]SprintValue
	// transport replaces the network (tests); nil = the real one.
	transport http.RoundTripper
}

// secret holds the token so that it cannot leak through a format verb or a log line.
type secret struct{ value string }

func (secret) String() string               { return "<token hidden>" }
func (secret) GoString() string             { return "<token hidden>" }
func (s secret) Format(f fmt.State, _ rune) { _, _ = io.WriteString(f, s.String()) }
func (s secret) reveal() string             { return s.value }
func (j *JiraSource) String() string {
	return fmt.Sprintf("JiraSource(host=%q, query=%q)", j.host, j.settings.Query)
}

// GoString keeps the source readable and the token out of any output.
func (j *JiraSource) GoString() string { return j.String() }

// Format keeps the token out of any formatted output.
func (j *JiraSource) Format(f fmt.State, _ rune) { _, _ = io.WriteString(f, j.String()) }

func invalidBaseURLError() *Error {
	return errorf("tracker.base_url is missing or not an http or https address (team.yaml)")
}

// checkToken demands one printable word: anything else (a newline from copy and paste) would
// produce an invalid header.
func checkToken(token string) error {
	ok := token != ""
	for i := 0; i < len(token); i++ {
		if token[i] < 0x21 || token[i] > 0x7e {
			ok = false
		}
	}
	if !ok {
		return errorf("The Jira token is empty or contains spaces, line breaks or special " +
			"characters – please paste it again.")
	}
	return nil
}

// NewJiraSource checks the settings and the token. A transport replaces the network (tests).
func NewJiraSource(settings Settings, token string, transport http.RoundTripper) (*JiraSource, error) {
	base := pyStrip(settings.BaseURL)
	switch BaseURLProblem(base) {
	case "credentials":
		return nil, errorf("tracker.base_url must not contain credentials (team.yaml)")
	case "extra":
		return nil, errorf("tracker.base_url must not contain parameters (?…) or a fragment (#…)")
	case "":
	default:
		return nil, invalidBaseURLError()
	}
	if settings.LinkType == "" {
		settings.LinkType = DefaultLinkType
	}
	if err := checkToken(token); err != nil {
		return nil, err
	}
	return &JiraSource{
		settings:  settings,
		baseURL:   strings.TrimRight(base, "/"),
		host:      hostOf(base),
		token:     secret{token},
		transport: transport,
	}, nil
}

// Host is the host name of the Jira address (for messages).
func (j *JiraSource) Host() string { return j.host }

// Kind is "jira".
func (j *JiraSource) Kind() string { return "jira" }

// Name is the name of the source as stored in tickets.yaml.
func (j *JiraSource) Name() string { return "jira " + j.host }

// Close releases idle connections.
func (j *JiraSource) Close() {
	if j.client != nil {
		j.client.CloseIdleConnections()
		j.client = nil
	}
}

func (j *JiraSource) newClient() (*http.Client, error) {
	transport := j.transport
	if transport == nil {
		pool, err := rootCertificates()
		if err != nil {
			return nil, err
		}
		base := http.DefaultTransport.(*http.Transport).Clone()
		// Timeouts per phase like httpx: a slow but steady answer is fine.
		base.DialContext = (&net.Dialer{Timeout: RequestTimeout}).DialContext
		base.ResponseHeaderTimeout = RequestTimeout
		base.TLSHandshakeTimeout = RequestTimeout
		base.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: pool}
		transport = base
	}
	return &http.Client{
		Transport: transport,
		// An answer that redirects is reported, not followed.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}, nil
}

// rootCertificates are the certificates the TLS check trusts: the file SSL_CERT_FILE or the
// folder SSL_CERT_DIR when set (for a company CA), else those of the operating system. The
// check itself is never switched off.
func rootCertificates() (*x509.CertPool, error) {
	unreadable := errorf("The CA file from SSL_CERT_FILE or SSL_CERT_DIR cannot be read – check " +
		"the environment variable and the file.")
	file, dir := os.Getenv("SSL_CERT_FILE"), os.Getenv("SSL_CERT_DIR")
	if file == "" && dir == "" {
		return nil, nil //nolint:nilnil // nil = the system pool
	}
	pool := x509.NewCertPool()
	var paths []string
	if file != "" {
		paths = append(paths, file)
	} else {
		entries, err := os.ReadDir(dir)
		if err != nil {
			return nil, unreadable
		}
		for _, e := range entries {
			if !e.IsDir() {
				paths = append(paths, filepath.Join(dir, e.Name()))
			}
		}
	}
	found := false
	for _, p := range paths {
		pem, err := os.ReadFile(p)
		if err != nil {
			if file != "" {
				return nil, unreadable
			}
			continue
		}
		if pool.AppendCertsFromPEM(pem) {
			found = true
		}
	}
	if !found {
		return nil, unreadable
	}
	return pool, nil
}

// request sends one request and returns the decoded JSON. Only GET and the label PUT are
// allowed; every failure is an *Error whose text contains neither the token nor the answer.
func (j *JiraSource) request(method, path string, params url.Values, body map[string]any) (any, error) {
	if method == http.MethodPost && j.sprintWrite && len(params) == 0 && isSprintWrite(path, any(body)) {
		return j.send(method, path, params, body)
	}
	if method != http.MethodGet && method != http.MethodPut {
		return nil, fmt.Errorf("HTTP method %q is not allowed: this source only reads", method)
	}
	if (method == http.MethodPut) != (body != nil) ||
		(method == http.MethodPut && (len(params) > 0 || !isLabelWrite(path, any(body)))) {
		return nil, errors.New("Only a label change of one ticket may be written") //nolint:staticcheck // shown to the user
	}
	return j.send(method, path, params, body)
}

// send does the request after request has checked that it is allowed.
func (j *JiraSource) send(method, path string, params url.Values, body map[string]any) (any, error) {
	if j.client == nil {
		client, err := j.newClient()
		if err != nil {
			return nil, err
		}
		j.client = client
	}
	target := j.baseURL + path
	if len(params) > 0 {
		target += "?" + params.Encode()
	}
	var payload io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		payload = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(context.Background(), method, target, payload)
	if err != nil {
		return nil, j.invalidAddress()
	}
	req.Header.Set("Authorization", "Bearer "+j.token.reveal())
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "foresprint/"+Version+" (read-only Jira import)")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := j.client.Do(req)
	if err != nil {
		// Only the classified text leaves: the transport error may carry the request.
		return nil, errorf("{text}", "text", j.failureText(err))
	}
	defer func() { _ = resp.Body.Close() }()
	data, readErr := io.ReadAll(io.LimitReader(resp.Body, 1<<30))
	if readErr != nil {
		return nil, errorf("{text}", "text", j.failureText(readErr))
	}
	if method == http.MethodPut || method == http.MethodPost {
		return j.decodeWrite(resp, data, method)
	}
	return j.decode(resp, data, path)
}

func (j *JiraSource) invalidAddress() *Error {
	return errorf("The address {host} is invalid (tracker.base_url in team.yaml)", "host", j.host)
}

// failureText turns a transport error into the text for the user.
func (j *JiraSource) failureText(err error) string {
	var netErr net.Error
	switch {
	case errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &netErr) && netErr.Timeout()):
		return T("No answer from {host} within {seconds} seconds (network, VPN or firewall?)",
			"host", j.host, "seconds", int(RequestTimeout/time.Second))
	case strings.Contains(err.Error(), "unsupported protocol scheme") || isURLParseError(err):
		return j.invalidAddress().Msg
	case isCertificateError(err):
		return T("The TLS check of the certificate of {host} failed. The check is never "+
			"switched off. If the certificate was issued by a company CA, give its "+
			"certificate file in the environment variable SSL_CERT_FILE (or "+
			"SSL_CERT_DIR).", "host", j.host)
	case isTLSError(err):
		return T("The TLS handshake with {host} failed (http instead of https, wrong port, "+
			"or a proxy interfering with TLS?). The check is never switched off.", "host", j.host)
	}
	var opErr *net.OpError
	var dnsErr *net.DNSError
	if (errors.As(err, &opErr) && opErr.Op == "dial") || errors.As(err, &dnsErr) {
		return T("{host} is not reachable (check the address, network, VPN, proxy or firewall)",
			"host", j.host)
	}
	return T("The connection to {host} failed (network, proxy or firewall?)", "host", j.host)
}

func isURLParseError(err error) bool {
	var ue *url.Error
	return errors.As(err, &ue) && strings.HasPrefix(ue.Error(), "parse ")
}

func isCertificateError(err error) bool {
	var unknown x509.UnknownAuthorityError
	var invalid x509.CertificateInvalidError
	var hostname x509.HostnameError
	var verify *tls.CertificateVerificationError
	return errors.As(err, &unknown) || errors.As(err, &invalid) || errors.As(err, &hostname) ||
		errors.As(err, &verify) || strings.Contains(strings.ToUpper(err.Error()), "CERTIFICATE_VERIFY")
}

func isTLSError(err error) bool {
	var record tls.RecordHeaderError
	var alert *tls.AlertError
	return errors.As(err, &record) || errors.As(err, &alert) || strings.Contains(err.Error(), "tls:") ||
		strings.Contains(err.Error(), "server gave HTTP response to HTTPS client")
}

// decodeWrite handles the answer to the label PUT: 204 is success; 403 and 404 get texts that
// fit a write.
func (j *JiraSource) decodeWrite(resp *http.Response, data []byte, method string) (any, error) {
	movingIssues := method == http.MethodPost
	switch resp.StatusCode {
	case http.StatusNoContent:
		return nil, nil //nolint:nilnil // success has no content
	case http.StatusForbidden:
		if movingIssues {
			return nil, errorf("Jira refuses the write (403): the account may not edit sprints (needs the right to manage sprints).")
		}
		return nil, errorf("Jira refuses the write (403): the account may not change labels of this ticket.")
	case http.StatusNotFound:
		if movingIssues {
			return nil, errorf("The sprint or a ticket does not exist or is not visible to the account (404)")
		}
		return nil, errorf("The ticket does not exist or is not visible to the account (404)")
	case http.StatusBadRequest:
		if movingIssues {
			return nil, errorf("Jira refuses to move the tickets (400): the sprint may be closed or a ticket is not on the board of the sprint")
		}
	}
	return j.decode(resp, data, "")
}

func (j *JiraSource) decode(resp *http.Response, data []byte, path string) (any, error) {
	status := resp.StatusCode
	switch {
	case status == http.StatusOK:
		if value, ok := parseJSON(data); ok {
			return value, nil
		}
		return nil, errorf("{host} does not answer with JSON – is tracker.base_url the address of "+
			"Jira (without a login page in front)?", "host", j.host)
	case status == http.StatusUnauthorized:
		return nil, errorf("Jira rejects the token (401): it is invalid or has expired. Create a " +
			"new token (Jira: profile > Personal Access Tokens).")
	case status == http.StatusForbidden:
		return nil, errorf("Jira denies access (403): the account may not read this data, or Jira " +
			"temporarily blocks the login.")
	case status == http.StatusNotFound:
		return nil, errorf("Jira not found at {host} (404): check tracker.base_url (a context "+
			"path such as /jira is part of it).", "host", j.host)
	case status == http.StatusBadRequest && path == searchPath:
		return nil, &Error{Msg: badRequestText(data)}
	case status == http.StatusBadRequest:
		return nil, errorf("Jira rejects the request (400) – check the Jira version and tracker.base_url")
	case status == http.StatusProxyAuthRequired:
		return nil, errorf("The proxy requires authentication (407) – check the proxy and its " +
			"credentials (HTTPS_PROXY).")
	case status == http.StatusTooManyRequests:
		wait := pyStrip(resp.Header.Get("Retry-After"))
		if wait != "" && len(wait) <= 6 && isASCIIDigits(wait) {
			seconds, _ := strconv.Atoi(wait)
			return nil, errorf("Jira reports too many requests (429) – please try again in "+
				"{seconds} seconds", "seconds", seconds)
		}
		return nil, errorf("Jira reports too many requests (429) – please try again later")
	case status >= 300 && status < 400:
		target := ""
		if host := hostOf(resp.Header.Get("Location")); host != "" {
			target = " (" + host + ")"
		}
		return nil, errorf("{host} redirects{target} – change tracker.base_url to the final address.",
			"host", j.host, "target", target)
	case status >= 500:
		return nil, errorf("Jira reports a server error ({status}) – please try again later", "status", status)
	}
	return nil, errorf("Unexpected answer from Jira (HTTP {status})", "status", status)
}

func isASCIIDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return s != ""
}

// parseJSON decodes a whole body; numbers stay json.Number so that integers and floats can be
// told apart as in Python.
func parseJSON(data []byte) (any, bool) {
	if !utf8.Valid(data) { // Python's json.loads fails on invalid UTF-8
		return nil, false
	}
	data = bytes.TrimPrefix(data, []byte{0xEF, 0xBB, 0xBF})
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var value any
	if err := dec.Decode(&value); err != nil {
		return nil, false
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, false
	}
	return value, true
}

// badRequestText is the text of a 400 on the search: Jira's errorMessages (the JQL problem; they
// hold no ticket data), cut off.
func badRequestText(data []byte) string {
	var messages []string
	if body, ok := parseJSON(data); ok {
		if obj, ok := asObject(body); ok {
			if list, ok := asList(obj["errorMessages"]); ok {
				for _, m := range list {
					if s, ok := asString(m); ok && pyStrip(s) != "" {
						messages = append(messages, pyStrip(s))
					}
				}
			}
		}
	}
	detail := strings.Join(messages, " ")
	if utf8.RuneCountInString(detail) > 300 {
		detail = string([]rune(detail)[:299]) + "…"
	}
	if detail == "" {
		return T("Jira rejects the query (400) – check tracker.query (JQL)")
	}
	return T("Jira rejects the query (400): {detail}", "detail", detail)
}

func (j *JiraSource) shapeError() *Error {
	return errorf("The answer from {host} does not have the expected format (check the Jira "+
		"version or tracker.base_url)", "host", j.host)
}

// SetLabels adds and removes planned_for_* labels of one ticket (PUT /rest/api/2/issue/KEY). The
// update operations touch only the named labels, never the other labels of the ticket.
func (j *JiraSource) SetLabels(key string, add, remove []string) error {
	operations := make([]any, 0, len(remove)+len(add))
	for _, x := range remove {
		operations = append(operations, map[string]any{"remove": x})
	}
	for _, x := range add {
		operations = append(operations, map[string]any{"add": x})
	}
	body := map[string]any{"update": map[string]any{"labels": operations}}
	_, err := j.request(http.MethodPut, "/rest/api/2/issue/"+key, nil, body)
	return err
}

// TestConnection returns the display name of the account the token belongs to
// (GET /rest/api/2/myself).
func (j *JiraSource) TestConnection() (string, error) {
	me, err := j.request(http.MethodGet, "/rest/api/2/myself", nil, nil)
	if err != nil {
		return "", err
	}
	obj, ok := asObject(me)
	if !ok {
		return "", j.shapeError()
	}
	for _, key := range []string{"displayName", "name"} {
		if pyTruthy(obj[key]) {
			if name, ok := asString(obj[key]); ok {
				return name, nil
			}
			return "", j.shapeError()
		}
	}
	return "", j.shapeError()
}

// ListFields returns all fields of the instance (GET /rest/api/2/field), for suggestions.
func (j *JiraSource) ListFields() ([]map[string]any, error) {
	raw, err := j.request(http.MethodGet, "/rest/api/2/field", nil, nil)
	if err != nil {
		return nil, err
	}
	list, ok := asList(raw)
	if !ok {
		return nil, j.shapeError()
	}
	fields := make([]map[string]any, len(list))
	for i, f := range list {
		obj, ok := asObject(f)
		if !ok {
			return nil, j.shapeError()
		}
		fields[i] = obj
	}
	return fields, nil
}

func (j *JiraSource) jql() (string, error) {
	jql := pyStrip(j.settings.Query)
	if jql == "" {
		return "", errorf("tracker.query is missing (JQL query of the tickets, team.yaml)")
	}
	return jql, nil
}

// CountTickets returns the number of tickets the query matches, without reading them.
func (j *JiraSource) CountTickets() (int, error) {
	jql, err := j.jql()
	if err != nil {
		return 0, err
	}
	page, err := j.request(http.MethodGet, searchPath, url.Values{
		"jql": {jql}, "fields": {"key"}, "startAt": {"0"}, "maxResults": {"1"},
	}, nil)
	if err != nil {
		return 0, err
	}
	obj, _ := asObject(page)
	total, ok := asInt(obj["total"])
	if !ok || total < 0 {
		return 0, j.shapeError()
	}
	return int(total), nil
}

// Fetch reads all tickets of the query (paged, GET /rest/api/2/search).
func (j *JiraSource) Fetch() ([]RawTicket, error) {
	jql, err := j.jql()
	if err != nil {
		return nil, err
	}
	resolved, err := j.ResolveFields()
	if err != nil {
		return nil, err
	}
	wanted := strings.Join(resolved.requested(), ",")
	tickets := map[string]RawTicket{}
	j.seen = nil
	var order []string
	start, expected := 0, -1
	for {
		page, err := j.request(http.MethodGet, searchPath, url.Values{
			"jql": {jql}, "fields": {wanted},
			"startAt": {strconv.Itoa(start)}, "maxResults": {strconv.Itoa(pageSize)},
		}, nil)
		if err != nil {
			return nil, err
		}
		obj, ok := asObject(page)
		if !ok {
			return nil, j.shapeError()
		}
		issues, ok := asList(obj["issues"])
		if !ok {
			return nil, j.shapeError()
		}
		total64, ok := asInt(obj["total"])
		if !ok || total64 < 0 {
			return nil, j.shapeError()
		}
		total := int(total64)
		if expected < 0 {
			expected = total
		} else if total != expected {
			return nil, j.changedError()
		}
		added := 0
		for _, issue := range issues {
			ticket, err := j.ticket(issue, resolved)
			if err != nil {
				return nil, err
			}
			if _, seen := tickets[ticket.Key]; !seen {
				tickets[ticket.Key] = ticket
				order = append(order, ticket.Key)
				added++
			}
		}
		start += len(issues)
		if start >= expected {
			break
		}
		if len(issues) == 0 || added == 0 { // short read, or the server ignores startAt
			return nil, j.changedError()
		}
	}
	if len(tickets) != expected { // a ticket moved between pages: one read twice, one missed
		return nil, j.changedError()
	}
	out := make([]RawTicket, len(order))
	for i, key := range order {
		out[i] = tickets[key]
	}
	return out, nil
}

func (j *JiraSource) changedError() *Error {
	return errorf("The result of the query changed while reading or was incomplete – please " +
		"try again. Nothing was written.")
}
