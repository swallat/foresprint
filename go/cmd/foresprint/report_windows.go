//go:build windows

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

// The Windows release has no console of its own (-H windowsgui), so an error that only goes to
// the standard error stream is never seen. Start problems therefore go to a log file and, when
// the program was started without arguments (a double click), to a message box.

// startedAt is when the program began, so that the log shows where the time of a slow start goes.
var startedAt = time.Now()

// logPath is the log of the last starts: %LOCALAPPDATA%\Foresprint\logs\start.log.
func logPath() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		var err error
		if base, err = os.UserCacheDir(); err != nil {
			return ""
		}
	}
	return filepath.Join(base, "Foresprint", "logs", "start.log")
}

// logLine appends a line with the time to the start log; failures here are ignored.
func logLine(format string, args ...any) {
	path := logPath()
	if path == "" {
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	// A log that grew beyond 256 KiB starts over.
	if st, err := os.Stat(path); err == nil && st.Size() > 256<<10 {
		_ = os.Remove(path)
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer func() { _ = f.Close() }()
	_, _ = fmt.Fprintf(f, "%s (+%.1fs) %s\n", time.Now().Format("2006-01-02 15:04:05"),
		time.Since(startedAt).Seconds(), fmt.Sprintf(format, args...))
}

// reportFailure logs a failure and shows it in a message box (the window or the console may not
// exist). Errors of a command line call with arguments stay on the standard error stream.
func reportFailure(what string, err error) {
	logLine("%s: %v", what, err)
	text := fmt.Sprintf("%s\n\n%v\n\nLog: %s", what, err, logPath())
	title, _ := syscall.UTF16PtrFromString("Foresprint")
	body, _ := syscall.UTF16PtrFromString(text)
	const mbOK, mbIconError, mbSetForeground = 0x0, 0x10, 0x10000
	box := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	_, _, _ = box.Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), mbOK|mbIconError|mbSetForeground)
}

// reportBegin is the first entry of a start without arguments (a double click, the launcher):
// when the window never opens, the entries after it show how far the program came.
func reportBegin(args []string) {
	if len(args) > 0 {
		return
	}
	wd, _ := os.Getwd()
	logLine("program start: cwd=%q exe=%q", wd, os.Args[0])
}

// reportEnd notes how a start without arguments ended.
func reportEnd(args []string, code int) {
	if len(args) == 0 {
		logLine("program end: exit code %d", code)
	}
}

// reportLog notes a line in the start log without showing anything.
func reportLog(format string, args ...any) { logLine(format, args...) }
