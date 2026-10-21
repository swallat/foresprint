package sources

import (
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/zalando/go-keyring"
)

func TestCloseMatchesGolden(t *testing.T) {
	var want []struct {
		Word          string   `json:"word"`
		Possibilities []string `json:"possibilities"`
		OK            []string `json:"ok"`
	}
	golden.Load(t, &want, "sources", "jira", "close-matches.json")
	for _, c := range want {
		got := closeMatches(c.Word, c.Possibilities, 3, 0.6)
		golden.Compare(t, list(c.OK), list(got))
	}
}

func settingsFor(url string) Settings {
	return Settings{
		Kind: "jira", BaseURL: url, Query: "project = ABC",
		Fields: Fields{Estimate: "Story Points"},
	}
}

// jiraServer answers the three requests of a fetch with a ticket and records the headers.
func jiraServer(t *testing.T, tls bool) (*httptest.Server, *http.Header) {
	t.Helper()
	var seen http.Header
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.Header.Clone()
		if strings.HasPrefix(r.URL.Path, "/moved") {
			http.Redirect(w, r, "https://other.example.org/", http.StatusFound)
			return
		}
		switch r.URL.Path {
		case "/rest/api/2/field":
			_, _ = w.Write([]byte(`[{"id":"customfield_1","name":"Story Points","schema":{"type":"number","custom":"x"}}]`))
		case "/rest/api/2/search":
			_, _ = w.Write([]byte(`{"startAt":0,"total":1,"issues":[{"key":"A-1","fields":{"summary":"One","customfield_1":3}}]}`))
		default:
			http.NotFound(w, r)
		}
	})
	var srv *httptest.Server
	if tls {
		srv = httptest.NewTLSServer(handler)
	} else {
		srv = httptest.NewServer(handler)
	}
	t.Cleanup(srv.Close)
	return srv, &seen
}

func TestFetchOverHTTP(t *testing.T) {
	srv, seen := jiraServer(t, false)
	source, err := NewJiraSource(settingsFor(srv.URL), "secret-token", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	tickets, err := source.Fetch()
	if err != nil {
		t.Fatal(err)
	}
	if len(tickets) != 1 || tickets[0].Key != "A-1" || tickets[0].Estimate == nil || *tickets[0].Estimate != 3 {
		t.Fatalf("tickets = %+v", tickets)
	}
	if got := seen.Get("Authorization"); got != "Bearer secret-token" {
		t.Errorf("Authorization = %q", got)
	}
	if got := seen.Get("Accept"); got != "application/json" {
		t.Errorf("Accept = %q", got)
	}
	if got := seen.Get("User-Agent"); !strings.HasPrefix(got, "foresprint/") {
		t.Errorf("User-Agent = %q", got)
	}
}

func TestRedirectIsReportedNotFollowed(t *testing.T) {
	srv, _ := jiraServer(t, false)
	source, err := NewJiraSource(settingsFor(srv.URL+"/moved"), "tok", nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = source.TestConnection()
	if err == nil || !strings.Contains(err.Error(), "redirects (other.example.org)") {
		t.Fatalf("err = %v", err)
	}
}

func writeCert(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "ca.pem")
	block := &pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}
	if err := os.WriteFile(path, pem.EncodeToMemory(block), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestTLSUsesSSLCertFile(t *testing.T) {
	srv, _ := jiraServer(t, true)
	t.Setenv("SSL_CERT_DIR", "")

	t.Setenv("SSL_CERT_FILE", "")
	source, _ := NewJiraSource(settingsFor(srv.URL), "tok", nil)
	_, err := source.TestConnection()
	if err == nil || !strings.Contains(err.Error(), "The TLS check of the certificate of") ||
		!strings.Contains(err.Error(), "never switched off") {
		t.Fatalf("without the CA: %v", err)
	}

	t.Setenv("SSL_CERT_FILE", writeCert(t, srv))
	source, _ = NewJiraSource(settingsFor(srv.URL), "tok", nil)
	if _, err := source.Fetch(); err != nil {
		t.Fatalf("with the CA file: %v", err)
	}

	t.Setenv("SSL_CERT_FILE", filepath.Join(t.TempDir(), "missing.pem"))
	source, _ = NewJiraSource(settingsFor(srv.URL), "tok", nil)
	_, err = source.TestConnection()
	if err == nil || !strings.Contains(err.Error(), "SSL_CERT_FILE") {
		t.Fatalf("unreadable CA file: %v", err)
	}
}

func TestTLSHandshakeAgainstPlainHTTP(t *testing.T) {
	srv, _ := jiraServer(t, false)
	source, _ := NewJiraSource(settingsFor(strings.Replace(srv.URL, "http://", "https://", 1)), "tok", nil)
	_, err := source.TestConnection()
	if err == nil || !strings.Contains(err.Error(), "TLS handshake") {
		t.Fatalf("err = %v", err)
	}
}

func TestUnreachableHost(t *testing.T) {
	srv, _ := jiraServer(t, false)
	url := srv.URL
	srv.Close()
	source, _ := NewJiraSource(settingsFor(url), "tok", nil)
	_, err := source.TestConnection()
	if err == nil || !strings.Contains(err.Error(), "is not reachable") {
		t.Fatalf("err = %v", err)
	}
}

func TestTokenNeverShows(t *testing.T) {
	const token = "tok-CANARY-9f8e7d6c"
	source, err := NewJiraSource(settingsFor("https://jira.example.org"), token, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, text := range []string{
		fmt.Sprintf("%v|%+v|%#v|%s|%q", source, source, source, source.token, source.token),
		fmt.Sprintf("%v %+v", source.token, &source.token),
	} {
		if strings.Contains(text, token) {
			t.Errorf("the token shows in %q", text)
		}
	}
	for _, bad := range []string{"", "a b", "a\nb", "ä"} {
		_, err := NewJiraSource(settingsFor("https://jira.example.org"), bad, nil)
		if err == nil || strings.Contains(err.Error(), bad+"\n") {
			t.Errorf("token %q: %v", bad, err)
		}
	}
}

func TestBaseURLErrors(t *testing.T) {
	for url, want := range map[string]string{
		"":                           "missing or not an http or https address",
		"https://u:p@jira.example":   "must not contain credentials",
		"https://jira.example?x=1":   "must not contain parameters",
		"ftp://jira.example":         "missing or not an http or https address",
		"https://jira.example#frag":  "must not contain parameters",
		"https://jira.example:99999": "missing or not an http or https address",
	} {
		_, err := NewJiraSource(settingsFor(url), "tok", nil)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v, want %q", url, err, want)
		}
		if err != nil && strings.Contains(err.Error(), "p@") {
			t.Errorf("%q: the address shows in the message", url)
		}
	}
}

func TestKeychain(t *testing.T) {
	keyring.MockInit()
	t.Setenv(TokenEnv, "")
	const base = "https://Jira.Example.org/jira"
	if JiraToken(base) != "" || StoredTokenExists(base) {
		t.Fatal("there should be no token yet")
	}
	if err := StoreToken(base, "abc123"); err != nil {
		t.Fatal(err)
	}
	if got := JiraToken("https://jira.example.org"); got != "abc123" { // per host, not per path
		t.Errorf("token = %q", got)
	}
	if !StoredTokenExists(base) {
		t.Error("the entry should exist")
	}
	t.Setenv(TokenEnv, "  from-env ")
	if got := JiraToken(base); got != "from-env" {
		t.Errorf("the environment variable should win, got %q", got)
	}
	t.Setenv(TokenEnv, "")
	if err := StoreToken(base, "bad token"); err == nil {
		t.Error("a token with a space should be refused")
	}
	if err := StoreToken("not a url", "abc"); err == nil {
		t.Error("an invalid address should be refused")
	}
	if err := DeleteToken(base); err != nil {
		t.Fatal(err)
	}
	if StoredTokenExists(base) {
		t.Error("the entry should be gone")
	}
	// a token stored before the rename is still found, and replaced on the next store
	if err := keyring.Set(legacyKeyringService, "jira.example.org", "old"); err != nil {
		t.Fatal(err)
	}
	if got := JiraToken(base); got != "old" {
		t.Errorf("legacy token = %q", got)
	}
	if err := StoreToken(base, "new"); err != nil {
		t.Fatal(err)
	}
	if _, err := keyring.Get(legacyKeyringService, "jira.example.org"); err == nil {
		t.Error("the legacy entry should be removed")
	}
	if !KeychainUsable() {
		t.Error("the mock keychain should count as usable")
	}
}

func TestOpen(t *testing.T) {
	keyring.MockInit()
	t.Setenv(TokenEnv, "")
	jira := settingsFor("https://jira.example.org")
	if _, err := Open(jira, "", "", nil); err == nil || !strings.Contains(err.Error(), "No Jira token found") {
		t.Errorf("without token: %v", err)
	}
	if src, err := Open(jira, "", "tok", nil); err != nil || src.Kind() != "jira" {
		t.Errorf("with token: %v %v", src, err)
	}
	if src, err := Open(jira, "export.csv", "", nil); err != nil || src.Kind() != "csv" {
		t.Errorf("csv fallback: %v %v", src, err)
	}
	if _, err := Open(Settings{Kind: "csv"}, "", "", nil); err == nil || !strings.Contains(err.Error(), "needs a file") {
		t.Errorf("csv without file: %v", err)
	}
	if _, err := Open(Settings{Kind: "gitlab"}, "", "", nil); err == nil || !strings.Contains(err.Error(), "Unknown ticket source") {
		t.Errorf("unknown kind: %v", err)
	}
}

func TestCSVFileErrors(t *testing.T) {
	dir := t.TempDir()
	fields := Fields{Estimate: "Story Points"}
	_, err := NewCSVSource(filepath.Join(dir, "missing.csv"), fields, nil).Fetch()
	if err == nil || !strings.Contains(err.Error(), "file not readable: No such file or directory") {
		t.Errorf("missing file: %v", err)
	}
	bad := filepath.Join(dir, "latin1.csv")
	if err := os.WriteFile(bad, []byte("Issue key,Summary\nA-1,K\xe4se\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = NewCSVSource(bad, fields, nil).Fetch()
	if err == nil || !strings.Contains(err.Error(), "is not UTF-8 encoded ('utf-8' codec can't decode byte 0xe4 in position 23") {
		t.Errorf("latin1 file: %v", err)
	}
}

func TestLabelHelpers(t *testing.T) {
	if PlannedLabel("2026.22") != "planned_for_2026.22" {
		t.Error("PlannedLabel")
	}
	got := LabelSprints([]string{"a", "planned_for_x", "planned_for_", "planned_for_y", "planned_for_x"})
	if strings.Join(got, ",") != "x,y" {
		t.Errorf("LabelSprints = %v", got)
	}
}

func TestCertPoolDirectory(t *testing.T) {
	srv, _ := jiraServer(t, true)
	dir := t.TempDir()
	pemPath := writeCert(t, srv)
	data, _ := os.ReadFile(pemPath)
	if err := os.WriteFile(filepath.Join(dir, "ca.pem"), data, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SSL_CERT_FILE", "")
	t.Setenv("SSL_CERT_DIR", dir)
	pool, err := rootCertificates()
	if err != nil || pool == nil {
		t.Fatalf("pool = %v, err = %v", pool, err)
	}
	if _, err := srv.Certificate().Verify(x509.VerifyOptions{Roots: pool}); err != nil {
		t.Errorf("the certificate should verify against the folder: %v", err)
	}
}
