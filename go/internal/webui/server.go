// Package webui shows the window of Foresprint as a page of the browser: a small HTTP server on
// 127.0.0.1 serves the built frontend and answers the calls of the page by calling the methods
// of app.API, as Wails does for the window. Every start has a new secret key; the page needs it
// as cookie.
package webui

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed bridge.js
var bridgeJS []byte

// cookiePrefix starts the name of the cookie; the port is added, so that two servers on this
// computer (the window and "foresprint serve") do not overwrite each other's key.
const cookiePrefix = "foresprint_key_"

// Server is one running browser access.
type Server struct {
	api    any
	assets fs.FS
	hub    *Hub
	done   chan struct{}
	key    string
	cookie string
	ln     net.Listener
	srv    *http.Server
	hosts  map[string]bool
	calls  map[string]reflect.Value
	once   sync.Once
}

// Start serves assets (the built frontend) and the methods of api (a pointer to a struct) on a
// free port of 127.0.0.1. The hub tells the pages when the data folder changed.
// The methods named in deny cannot be called from the page.
func Start(api any, assets fs.FS, hub *Hub, deny ...string) (*Server, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return nil, err
	}
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	port := strconv.Itoa(ln.Addr().(*net.TCPAddr).Port)
	s := &Server{
		api: api, assets: assets, hub: hub, done: make(chan struct{}), ln: ln,
		key:    base64.RawURLEncoding.EncodeToString(raw),
		cookie: cookiePrefix + port,
		hosts:  map[string]bool{"127.0.0.1:" + port: true, "localhost:" + port: true},
		calls:  methodsOf(api),
	}
	for _, n := range deny {
		delete(s.calls, n)
	}
	s.srv = &http.Server{Handler: s, ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = s.srv.Serve(ln) }()
	return s, nil
}

// URL is the link that opens the page; it carries the key.
func (s *Server) URL() string {
	return "http://" + s.ln.Addr().String() + "/?k=" + s.key
}

// Close stops the server; the key is void afterwards.
func (s *Server) Close() {
	s.once.Do(func() {
		close(s.done)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		if err := s.srv.Shutdown(ctx); err != nil {
			_ = s.srv.Close()
		}
	})
}

func methodsOf(api any) map[string]reflect.Value {
	out := map[string]reflect.Value{}
	v := reflect.ValueOf(api)
	for i := 0; i < v.NumMethod(); i++ {
		name := v.Type().Method(i).Name
		// The access itself is not for the page in the browser (more is denied by Start).
		if strings.HasPrefix(name, "Browser") {
			continue
		}
		out[name] = v.Method(i)
	}
	return out
}

func (s *Server) authed(r *http.Request) bool {
	c, err := r.Cookie(s.cookie)
	return err == nil && subtle.ConstantTimeCompare([]byte(c.Value), []byte(s.key)) == 1
}

// ServeHTTP checks host and key, then serves the bridge, the page, the change check or a call.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// A wrong Host is a DNS rebinding attempt.
	if !s.hosts[r.Host] {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	// First visit with the key in the address: swap it for the cookie and remove it from the
	// address bar, so it is not visible while sharing the screen.
	if k := r.URL.Query().Get("k"); k != "" && r.Method == http.MethodGet {
		if subtle.ConstantTimeCompare([]byte(k), []byte(s.key)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		http.SetCookie(w, &http.Cookie{Name: s.cookie, Value: s.key, Path: "/", HttpOnly: true, SameSite: http.SameSiteStrictMode})
		q := r.URL.Query()
		q.Del("k")
		u := url.URL{Path: r.URL.Path, RawQuery: q.Encode()}
		http.Redirect(w, r, u.String(), http.StatusSeeOther)
		return
	}
	if !s.authed(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	switch {
	case r.URL.Path == "/__bridge.js":
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
		_, _ = w.Write(bridgeJS)
	case r.URL.Path == "/__events":
		s.events(w, r)
	case strings.HasPrefix(r.URL.Path, "/api/"):
		s.call(w, r, strings.TrimPrefix(r.URL.Path, "/api/"))
	default:
		s.page(w, r)
	}
}

// events streams the fingerprint of the data folder (server-sent events): first the current one,
// then one for every change. The page decides whether the change was its own.
func (s *Server) events(w http.ResponseWriter, r *http.Request) {
	fl, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "no streaming", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	ch, cancel := s.hub.Subscribe()
	defer cancel()
	send := func(fp string) bool {
		_, err := fmt.Fprintf(w, "data: %s\n\n", fp)
		fl.Flush()
		return err == nil
	}
	if !send(s.hub.Current()) {
		return
	}
	beat := time.NewTicker(15 * time.Second)
	defer beat.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-s.done:
			return
		case fp := <-ch:
			if !send(fp) {
				return
			}
		case <-beat.C:
			if _, err := fmt.Fprint(w, ": keep-alive\n\n"); err != nil {
				return
			}
			fl.Flush()
		}
	}
}

func (s *Server) page(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	name := assetName(r.URL.Path)
	data, err := fs.ReadFile(s.assets, name)
	if err != nil {
		// A file with an extension that is missing is an error, not a page of the app; the
		// page answers the other addresses (a route of the app).
		if path.Ext(name) != "" {
			http.NotFound(w, r)
			return
		}
		name = "index.html"
		if data, err = fs.ReadFile(s.assets, name); err != nil {
			http.NotFound(w, r)
			return
		}
	}
	if name == "index.html" {
		// The bridge must run before the page looks for window.go.
		data = []byte(strings.Replace(string(data), "<head>", `<head><script src="/__bridge.js"></script>`, 1))
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
	} else if ct := contentType(name); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	_, _ = w.Write(data)
}

// assetName turns the address into a name inside the embedded files ("index.html" for the root).
// It uses package path, not filepath: on Windows filepath.Clean reads "//assets/x" as a network
// path and the lookup finds nothing.
func assetName(urlPath string) string {
	name := strings.TrimPrefix(path.Clean("/"+urlPath), "/")
	if name == "" {
		return "index.html"
	}
	return name
}

func contentType(name string) string {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".js", ".mjs":
		return "text/javascript; charset=utf-8"
	case ".css":
		return "text/css; charset=utf-8"
	case ".svg":
		return "image/svg+xml"
	case ".woff2":
		return "font/woff2"
	case ".png":
		return "image/png"
	}
	return ""
}

type answer struct {
	Result any    `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

// call runs one method like Wails does: the body is the list of arguments; the answer is the
// result or the error text.
func (s *Server) call(w http.ResponseWriter, r *http.Request, name string) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	// Only the own page may call: it sends JSON (a form of another site cannot) and, if the
	// browser says where it comes from, that is this server.
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if o := r.Header.Get("Origin"); o != "" {
		if u, err := url.Parse(o); err != nil || !s.hosts[u.Host] {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
	}
	m, ok := s.calls[name]
	if !ok {
		http.Error(w, "unknown method", http.StatusNotFound)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 32<<20))
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	res, err := invoke(m, body)
	a := answer{Result: res}
	if err != nil {
		a = answer{Error: err.Error()}
	}
	// Encode first: a result that cannot be encoded (NaN) becomes an error, not an empty body.
	out, merr := json.Marshal(a)
	if merr != nil {
		out, _ = json.Marshal(answer{Error: merr.Error()})
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(out)
}

var errorType = reflect.TypeOf((*error)(nil)).Elem()

func invoke(m reflect.Value, body []byte) (res any, err error) {
	defer func() {
		if p := recover(); p != nil {
			err = fmt.Errorf("%v", p)
		}
	}()
	t := m.Type()
	var raw []json.RawMessage
	if len(strings.TrimSpace(string(body))) > 0 {
		if err := json.Unmarshal(body, &raw); err != nil {
			return nil, err
		}
	}
	if len(raw) != t.NumIn() {
		return nil, fmt.Errorf("expected %d arguments, got %d", t.NumIn(), len(raw))
	}
	in := make([]reflect.Value, t.NumIn())
	for i := range in {
		p := reflect.New(t.In(i))
		if err := json.Unmarshal(raw[i], p.Interface()); err != nil {
			return nil, err
		}
		in[i] = p.Elem()
	}
	out := m.Call(in)
	for i, o := range out {
		if t.Out(i) == errorType {
			if !o.IsNil() {
				return nil, o.Interface().(error)
			}
			continue
		}
		res = o.Interface()
	}
	return res, nil
}

// Fingerprint changes when a file of the data folder changes (names, sizes, times; the .git
// folder is left out). The page compares it to see changes made in the window.
func Fingerprint(dir string) string {
	if dir == "" {
		return ""
	}
	var sum uint64
	_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if d.Name() == ".git" {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		sum += hashOf(p, info)
		return nil
	})
	return strconv.FormatUint(sum, 36)
}

func hashOf(p string, info os.FileInfo) uint64 {
	h := uint64(14695981039346656037)
	for _, c := range []byte(p + "|" + strconv.FormatInt(info.Size(), 10) + "|" + strconv.FormatInt(info.ModTime().UnixNano(), 10)) {
		h = (h ^ uint64(c)) * 1099511628211
	}
	return h
}
