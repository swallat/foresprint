package webui

import (
	"errors"
	"io"
	"net/http"
	"net/http/cookiejar"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"
)

type fakeAPI struct{}

func (*fakeAPI) Add(a, b int) int                  { return a + b }
func (*fakeAPI) Fail() (string, error)             { return "", errors.New("nope") }
func (*fakeAPI) BrowserStop() string               { return "x" }
func (*fakeAPI) Hello(name string) (string, error) { return "hi " + name, nil }

func start(t *testing.T) *Server {
	t.Helper()
	dir := t.TempDir()
	assets := fstest.MapFS{"index.html": {Data: []byte("<html><head></head><body>app</body></html>")}}
	s, err := Start(&fakeAPI{}, assets, testHub(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	return s
}

func testHub(t *testing.T, dir string) *Hub {
	t.Helper()
	h := NewHub(func() string { return dir }, time.Hour)
	t.Cleanup(h.Close)
	return h
}

func client() *http.Client {
	jar, _ := cookiejar.New(nil)
	return &http.Client{Jar: jar}
}

func get(t *testing.T, c *http.Client, u string) (int, string) {
	t.Helper()
	res, err := c.Get(u)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = res.Body.Close() }()
	b, _ := io.ReadAll(res.Body)
	return res.StatusCode, string(b)
}

func post(t *testing.T, c *http.Client, u, body string) (int, string) {
	t.Helper()
	res, err := c.Post(u, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = res.Body.Close() }()
	b, _ := io.ReadAll(res.Body)
	return res.StatusCode, string(b)
}

func TestKeyIsRequiredAndSwappedForCookie(t *testing.T) {
	s := start(t)
	base := strings.SplitN(s.URL(), "/?k=", 2)[0]
	c := client()
	if code, _ := get(t, c, base+"/"); code != http.StatusUnauthorized {
		t.Fatalf("without key: %d", code)
	}
	if code, _ := get(t, c, base+"/?k=wrong"); code != http.StatusUnauthorized {
		t.Fatalf("wrong key: %d", code)
	}
	code, body := get(t, c, s.URL())
	if code != 200 || !strings.Contains(body, `<script src="/__bridge.js">`) {
		t.Fatalf("page: %d %q", code, body)
	}
	// The cookie now opens the page and the calls, without the key in the address.
	if code, _ := get(t, c, base+"/"); code != 200 {
		t.Fatalf("with cookie: %d", code)
	}
	if code, _ := post(t, client(), base+"/api/Add", "[1,2]"); code != http.StatusUnauthorized {
		t.Fatalf("call without cookie: %d", code)
	}
}

func TestCalls(t *testing.T) {
	s := start(t)
	base := strings.SplitN(s.URL(), "/?k=", 2)[0]
	c := client()
	get(t, c, s.URL())
	if code, body := post(t, c, base+"/api/Add", "[1,2]"); code != 200 || !strings.Contains(body, `"result":3`) {
		t.Fatalf("add: %d %s", code, body)
	}
	if _, body := post(t, c, base+"/api/Fail", "[]"); !strings.Contains(body, `"error":"nope"`) {
		t.Fatalf("fail: %s", body)
	}
	if _, body := post(t, c, base+"/api/Add", "[1]"); !strings.Contains(body, "expected 2 arguments") {
		t.Fatalf("arity: %s", body)
	}
	if code, _ := post(t, c, base+"/api/BrowserStop", "[]"); code != http.StatusNotFound {
		t.Fatalf("Browser* must not be callable: %d", code)
	}
	// A page of another site is refused, even with the cookie.
	req, _ := http.NewRequest("POST", base+"/api/Add", strings.NewReader("[1,2]"))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Origin", "https://evil.example")
	res, err := c.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = res.Body.Close()
	if res.StatusCode != http.StatusForbidden {
		t.Fatalf("foreign origin: %d", res.StatusCode)
	}
	// A form post (no JSON) is refused.
	res, err = c.Post(base+"/api/Add", "text/plain", strings.NewReader("[1,2]"))
	if err != nil {
		t.Fatal(err)
	}
	_ = res.Body.Close()
	if res.StatusCode != http.StatusBadRequest {
		t.Fatalf("text/plain: %d", res.StatusCode)
	}
}

func TestWrongHostIsRefused(t *testing.T) {
	s := start(t)
	req, _ := http.NewRequest("GET", strings.SplitN(s.URL(), "/?k=", 2)[0]+"/", nil)
	req.Host = "evil.example"
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = res.Body.Close()
	if res.StatusCode != http.StatusForbidden {
		t.Fatalf("rebinding: %d", res.StatusCode)
	}
}

func TestCloseVoidsTheLink(t *testing.T) {
	s := start(t)
	u := s.URL()
	s.Close()
	if res, err := http.Get(u); err == nil {
		_ = res.Body.Close()
		t.Fatal("server still answers")
	}
}

func TestFingerprintChanges(t *testing.T) {
	dir := t.TempDir()
	a := Fingerprint(dir)
	if err := os.WriteFile(filepath.Join(dir, "x.yaml"), []byte("a"), 0o644); err != nil {
		t.Fatal(err)
	}
	b := Fingerprint(dir)
	if a == b {
		t.Fatal("new file not seen")
	}
	if err := os.MkdirAll(filepath.Join(dir, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(filepath.Join(dir, ".git", "HEAD"), []byte("x"), 0o644)
	if Fingerprint(dir) != b {
		t.Fatal(".git must not count")
	}
}

func TestDeniedMethodsAndCookiePerPort(t *testing.T) {
	dir := t.TempDir()
	assets := fstest.MapFS{"index.html": {Data: []byte("<head></head>")}}
	a, err := Start(&fakeAPI{}, assets, testHub(t, dir), "Add")
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := Start(&fakeAPI{}, assets, testHub(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	c := client()
	get(t, c, a.URL())
	get(t, c, b.URL())
	baseA := strings.SplitN(a.URL(), "/?k=", 2)[0]
	baseB := strings.SplitN(b.URL(), "/?k=", 2)[0]
	if code, _ := post(t, c, baseA+"/api/Add", "[1,2]"); code != http.StatusNotFound {
		t.Fatalf("denied method: %d", code)
	}
	// Both keys live side by side in one browser.
	if code, _ := post(t, c, baseB+"/api/Add", "[1,2]"); code != 200 {
		t.Fatalf("second server: %d", code)
	}
	if code, _ := post(t, c, baseA+"/api/Hello", `["x"]`); code != 200 {
		t.Fatalf("first server: %d", code)
	}
}

func TestAssetName(t *testing.T) {
	for in, want := range map[string]string{
		"/":                        "index.html",
		"":                         "index.html",
		"/assets/index-x.js":       "assets/index-x.js",
		"//assets/index-x.js":      "assets/index-x.js",
		"/assets/../../etc/passwd": "etc/passwd",
		"/setup":                   "setup",
	} {
		if got := assetName(in); got != want {
			t.Errorf("assetName(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestAssetsAreServedWithTheirType(t *testing.T) {
	dir := t.TempDir()
	assets := fstest.MapFS{
		"index.html":      {Data: []byte("<head></head>")},
		"assets/index.js": {Data: []byte("1")},
		"assets/x.css":    {Data: []byte("a{}")},
	}
	s, err := Start(&fakeAPI{}, assets, testHub(t, dir))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	c := client()
	get(t, c, s.URL())
	base := strings.SplitN(s.URL(), "/?k=", 2)[0]
	for path, ct := range map[string]string{"/assets/index.js": "text/javascript", "/assets/x.css": "text/css"} {
		res, err := c.Get(base + path)
		if err != nil {
			t.Fatal(err)
		}
		_ = res.Body.Close()
		if res.StatusCode != 200 || !strings.HasPrefix(res.Header.Get("Content-Type"), ct) {
			t.Errorf("%s: %d %s", path, res.StatusCode, res.Header.Get("Content-Type"))
		}
	}
	if code, _ := get(t, c, base+"/assets/missing.js"); code != http.StatusNotFound {
		t.Errorf("missing asset must be 404, got %d", code)
	}
	if code, body := get(t, c, base+"/some/route"); code != 200 || !strings.Contains(body, "__bridge.js") {
		t.Errorf("route falls back to the page: %d", code)
	}
}

func TestHubTellsChangesAndServerStreamsThem(t *testing.T) {
	dir := t.TempDir()
	hub := NewHub(func() string { return dir }, 20*time.Millisecond)
	defer hub.Close()
	assets := fstest.MapFS{"index.html": {Data: []byte("<head></head>")}}
	s, err := Start(&fakeAPI{}, assets, hub)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	c := client()
	get(t, c, s.URL())
	base := strings.SplitN(s.URL(), "/?k=", 2)[0]
	res, err := c.Get(base + "/__events")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = res.Body.Close() }()
	if ct := res.Header.Get("Content-Type"); ct != "text/event-stream" {
		t.Fatalf("type %q", ct)
	}
	lines := make(chan string, 8)
	go func() {
		buf := make([]byte, 512)
		for {
			n, err := res.Body.Read(buf)
			if n > 0 {
				lines <- string(buf[:n])
			}
			if err != nil {
				close(lines)
				return
			}
		}
	}()
	first := <-lines
	if !strings.HasPrefix(first, "data: ") {
		t.Fatalf("first event %q", first)
	}
	if err := os.WriteFile(filepath.Join(dir, "p.yaml"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	select {
	case next := <-lines:
		if !strings.HasPrefix(next, "data: ") || next == first {
			t.Fatalf("change event %q", next)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no event after a change")
	}
}
