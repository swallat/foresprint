// Command foresprint is the Go core of Foresprint. It is a scaffold: the calculation core, the
// command line and the window shell (Wails) are ported in the following steps of the 1.0 plan
// (go/README.md).
package main

import (
	"fmt"
	"os"

	"github.com/swallat/foresprint/internal/holidays"
)

// version is set at build time: -ldflags "-X main.version=1.0.0".
var version = "dev"

func main() {
	if len(os.Args) > 1 && (os.Args[1] == "version" || os.Args[1] == "--version") {
		info := holidays.Info()
		fmt.Printf("foresprint %s (go core, holidays %s, %d-%d)\n",
			version, info.HolidaysVersion, info.FirstYear, info.LastYear)
		return
	}
	fmt.Fprintln(os.Stderr, "foresprint (go core) is not usable yet: run `foresprint version`")
	os.Exit(2)
}
