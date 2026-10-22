//go:build desktop

package main

import (
	"github.com/swallat/foresprint/internal/cli"
	"github.com/swallat/foresprint/internal/desktop"
)

// A build with the tag "desktop" has the window: the program started without arguments (a
// double click) and "foresprint gui" open it.
func init() {
	cli.GUI = func(dataDir string) error { return desktop.Run(version, dataDir) }
}
