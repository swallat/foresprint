//go:build desktop

package desktop

import (
	"io/fs"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"github.com/swallat/foresprint/internal/app"
	"github.com/swallat/foresprint/internal/webui"
)

// windowOnly are the methods the page in the browser must not call while the window is open: they
// switch the data folder or the demo of the program that the window uses as well.
var windowOnly = []string{"SetDataDir", "PickDataDir", "EnterDemo", "LeaveDemo"}

// browserAccess starts and stops the local server that shows the window as a page of the browser.
type browserAccess struct {
	api    *app.API
	assets fs.FS
	mu     sync.Mutex
	srv    *webui.Server
}

func (b *browserAccess) start() (string, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.srv == nil {
		srv, err := webui.Start(b.api, b.assets, b.api.DataDir, windowOnly...)
		if err != nil {
			return "", err
		}
		b.srv = srv
	}
	return b.srv.URL(), nil
}

func (b *browserAccess) stop() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.srv != nil {
		b.srv.Close()
		b.srv = nil
	}
}

func (b *browserAccess) url() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.srv == nil {
		return ""
	}
	return b.srv.URL()
}

// Serve runs the page for the browser without a window ("foresprint serve") until interrupted.
func Serve(version, dataDir string, out func(string)) error {
	api := app.New(version, dataDir)
	dist, err := fs.Sub(assets, "frontend/dist")
	if err != nil {
		return err
	}
	srv, err := webui.Start(api, dist, api.DataDir)
	if err != nil {
		return err
	}
	defer srv.Close()
	out(srv.URL())
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(stop)
	<-stop
	return nil
}
