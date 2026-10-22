//go:build desktop

package main

import (
	"os"

	"github.com/swallat/foresprint/internal/cli"
	"github.com/swallat/foresprint/internal/desktop"
)

// A build with the tag "desktop" has the window: the program started without arguments (a
// double click) and "foresprint gui" open it.
func init() {
	cli.GUI = func(dataDir string) error {
		reportStart(os.Args[1:])
		err := desktop.Run(version, dataDir)
		if err != nil {
			// The Windows release has no console: show the problem where it can be seen.
			reportFailure("The window could not be opened.", err)
		}
		return err
	}
}
