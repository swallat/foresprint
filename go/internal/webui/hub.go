package webui

import (
	"sync"
	"time"
)

// Hub watches the data folder and tells everyone who listens when it changed (a write of the
// window, of a browser page or of another program). The window and the browser pages show the
// same folder, so each of them reloads its page when the other one changed something.
type Hub struct {
	dir  func() string
	stop chan struct{}
	once sync.Once

	mu   sync.Mutex
	last string
	subs map[chan string]struct{}
	cbs  []func(string)
}

// NewHub starts watching the folder dir returns; every interval it compares a fingerprint.
func NewHub(dir func() string, interval time.Duration) *Hub {
	h := &Hub{dir: dir, stop: make(chan struct{}), subs: map[chan string]struct{}{}, last: Fingerprint(dir())}
	go h.run(interval)
	return h
}

func (h *Hub) run(interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-h.stop:
			return
		case <-t.C:
			fp := Fingerprint(h.dir())
			h.mu.Lock()
			if fp == h.last {
				h.mu.Unlock()
				continue
			}
			h.last = fp
			subs := make([]chan string, 0, len(h.subs))
			for c := range h.subs {
				subs = append(subs, c)
			}
			cbs := append([]func(string){}, h.cbs...)
			h.mu.Unlock()
			for _, c := range subs {
				select {
				case c <- fp:
				default: // a slow listener gets the next change
				}
			}
			for _, f := range cbs {
				f(fp)
			}
		}
	}
}

// OnChange calls f (in the goroutine of the hub) with the new fingerprint after every change.
func (h *Hub) OnChange(f func(string)) {
	h.mu.Lock()
	h.cbs = append(h.cbs, f)
	h.mu.Unlock()
}

// Subscribe returns a channel of fingerprints and a function that ends the subscription.
func (h *Hub) Subscribe() (<-chan string, func()) {
	c := make(chan string, 1)
	h.mu.Lock()
	h.subs[c] = struct{}{}
	h.mu.Unlock()
	return c, func() {
		h.mu.Lock()
		delete(h.subs, c)
		h.mu.Unlock()
	}
}

// Current is the fingerprint seen last.
func (h *Hub) Current() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.last
}

// Close stops watching.
func (h *Hub) Close() { h.once.Do(func() { close(h.stop) }) }
