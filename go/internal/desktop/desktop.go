//go:build desktop

// Package desktop is the window of Foresprint: a Wails shell around the web frontend in
// frontend/ (built to frontend/dist and embedded here). It is only compiled with the build tag
// "desktop", because Wails needs cgo and the system web view on Linux (libwebkit2gtk); the
// command line and the core build and test without it.
//
//	cd internal/desktop/frontend && npm ci && npm run build
//	go build -tags desktop,production ./cmd/foresprint        # Linux: add webkit2_41
//
// The frontend talks to the core through internal/app (Wails binds app.API).
package desktop

import (
	"context"
	"embed"
	"io/fs"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
	"github.com/wailsapp/wails/v2/pkg/runtime"

	"github.com/swallat/foresprint/internal/app"
)

//go:embed all:frontend/dist
var assets embed.FS

// Run opens the window and returns when it is closed.
func Run(version, dataDir string) error {
	api := app.New(version, dataDir)
	dist, err := fs.Sub(assets, "frontend/dist")
	if err != nil {
		return err
	}
	return wails.Run(&options.App{
		Title:     "Foresprint",
		Width:     1360,
		Height:    860,
		MinWidth:  1100,
		MinHeight: 700,
		// The page paints its own background from the tokens; this colour only shows for the
		// moment before it loads.
		BackgroundColour: &options.RGBA{R: 242, G: 243, B: 248, A: 1},
		AssetServer:      &assetserver.Options{Assets: dist},
		Bind:             []any{api},
		OnStartup: func(ctx context.Context) {
			api.ChooseFolder = func(title string) (string, error) {
				return runtime.OpenDirectoryDialog(ctx, runtime.OpenDialogOptions{Title: title})
			}
			api.ChooseFile = func(title string) (string, error) {
				return runtime.OpenFileDialog(ctx, runtime.OpenDialogOptions{
					Title:   title,
					Filters: []runtime.FileFilter{{DisplayName: "Excel, CSV (*.xlsx, *.csv)", Pattern: "*.xlsx;*.csv"}},
				})
			}
			api.ChooseTable = func(title string) (string, error) {
				return runtime.OpenFileDialog(ctx, runtime.OpenDialogOptions{
					Title: title,
					Filters: []runtime.FileFilter{
						{DisplayName: "Excel / CSV (*.xlsx, *.csv)", Pattern: "*.xlsx;*.csv;*.txt"}},
				})
			}
		},
		Windows: &windows.Options{Theme: windows.SystemDefault},
	})
}
