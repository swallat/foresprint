// Package shortcut creates the launchers that start the program with a double-click:
// Windows desktop and Start menu (.lnk through PowerShell), macOS ~/Applications/Foresprint.app
// plus an alias on the desktop, Linux a .desktop file in the applications folder and on the
// desktop.
package shortcut

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
)

// AppName is the name of the launchers.
const AppName = "Foresprint"

// Options are the places and the program a launcher is made for; the zero value of every
// field except Program is the real system.
type Options struct {
	Program    string                              // the program to start (absolute path)
	Home       string                              // default: the home folder
	DataHome   string                              // Linux: XDG_DATA_HOME, default ~/.local/share
	IconDir    string                              // where the logo is written, default: next to the settings
	GOOS       string                              // default runtime.GOOS
	PowerShell func(script string) (string, error) // Windows: runs a script, default: powershell
}

// Create makes the launchers and returns their paths.
func Create(o Options) ([]string, error) {
	if o.Home == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		o.Home = home
	}
	if o.GOOS == "" {
		o.GOOS = runtime.GOOS
	}
	if !isAbs(o.GOOS, o.Program) {
		return nil, errors.New(i18n.P("The program path is unknown."))
	}
	if o.IconDir == "" {
		o.IconDir = filepath.Join(o.Home, ".local", "share", "foresprint")
	}
	if err := os.MkdirAll(o.IconDir, 0o755); err != nil {
		return nil, err
	}
	logo := PNG(IconSize)
	switch o.GOOS {
	case "windows":
		return createWindows(o, logo)
	case "darwin":
		return createMac(o, logo)
	}
	return createLinux(o, logo)
}

// isAbs tells an absolute path of the target system (not of the one running the test).
func isAbs(goos, p string) bool {
	if goos == "windows" {
		return len(p) > 2 && (p[1] == ':' && (p[2] == '\\' || p[2] == '/') || strings.HasPrefix(p, `\\`))
	}
	return strings.HasPrefix(p, "/")
}

func writeIcon(dir, kind string, content []byte) (string, error) {
	path := filepath.Join(dir, "foresprint."+kind)
	return path, os.WriteFile(path, content, 0o644)
}

func psQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

// WindowsScript is the PowerShell that creates the shortcuts on the desktop and in the Start
// menu and prints their paths.
func WindowsScript(program, workdir, icon string) string {
	lines := []string{"$shell = New-Object -ComObject WScript.Shell"}
	for _, folder := range []string{"Desktop", "Programs"} {
		lines = append(lines,
			fmt.Sprintf("$path = Join-Path ([Environment]::GetFolderPath('%s')) '%s.lnk'", folder, AppName),
			"$link = $shell.CreateShortcut($path)",
			"$link.TargetPath = "+psQuote(program),
			"$link.WorkingDirectory = "+psQuote(workdir),
			"$link.Description = '"+AppName+"'",
		)
		if icon != "" {
			lines = append(lines, "$link.IconLocation = "+psQuote(icon))
		}
		lines = append(lines, "$link.Save()", "Write-Output $path")
	}
	return strings.Join(lines, "\n")
}

func createWindows(o Options, logo []byte) ([]string, error) {
	icon, err := writeIcon(o.IconDir, "ico", ICO(logo))
	if err != nil {
		return nil, err
	}
	run := o.PowerShell
	if run == nil {
		run = runPowerShell
	}
	out, err := run(WindowsScript(o.Program, o.Home, icon))
	if err != nil {
		return nil, err
	}
	var paths []string
	for _, line := range strings.Split(out, "\n") {
		if line = strings.TrimSpace(line); line != "" {
			paths = append(paths, line)
		}
	}
	return paths, nil
}

func runPowerShell(script string) (string, error) {
	cmd := exec.Command("powershell", "-NoProfile", "-Command", script)
	out, err := cmd.Output()
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) && len(ee.Stderr) > 0 {
			return "", errors.New(strings.TrimSpace(string(ee.Stderr)))
		}
		return "", errors.New(i18n.P("Shortcut not created"))
	}
	return string(out), nil
}

// DesktopEntry is the content of the Linux launcher.
func DesktopEntry(program, icon string) string {
	return "[Desktop Entry]\n" +
		"Type=Application\n" +
		"Name=" + AppName + "\n" +
		"Comment=" + i18n.P("Velocity and capacity forecast") + "\n" +
		`Exec="` + program + `"` + "\n" +
		"Icon=" + icon + "\n" +
		"Terminal=false\n" +
		"Categories=Office;ProjectManagement;\n"
}

func createLinux(o Options, logo []byte) ([]string, error) {
	icon, err := writeIcon(o.IconDir, "png", logo)
	if err != nil {
		return nil, err
	}
	dataHome := o.DataHome
	if dataHome == "" {
		dataHome = os.Getenv("XDG_DATA_HOME")
	}
	if dataHome == "" {
		dataHome = filepath.Join(o.Home, ".local", "share")
	}
	targets := []string{filepath.Join(dataHome, "applications", "foresprint.desktop")}
	if info, err := os.Stat(filepath.Join(o.Home, "Desktop")); err == nil && info.IsDir() {
		targets = append(targets, filepath.Join(o.Home, "Desktop", "foresprint.desktop"))
	}
	entry := DesktopEntry(o.Program, icon)
	for _, t := range targets {
		if err := os.MkdirAll(filepath.Dir(t), 0o755); err != nil {
			return nil, err
		}
		if err := os.WriteFile(t, []byte(entry), 0o755); err != nil {
			return nil, err
		}
	}
	return targets, nil
}

func plist(icon string) string {
	s := `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>` + AppName + `</string>
<key>CFBundleExecutable</key><string>` + AppName + `</string>
<key>CFBundleIdentifier</key><string>de.foresprint.app</string>
<key>CFBundlePackageType</key><string>APPL</string>
`
	if icon != "" {
		s += "<key>CFBundleIconFile</key><string>" + icon + "</string>\n"
	}
	return s + "</dict></plist>\n"
}

func createMac(o Options, logo []byte) ([]string, error) {
	bundle := filepath.Join(o.Home, "Applications", AppName+".app")
	contents := filepath.Join(bundle, "Contents")
	for _, d := range []string{"MacOS", "Resources"} {
		if err := os.MkdirAll(filepath.Join(contents, d), 0o755); err != nil {
			return nil, err
		}
	}
	if err := os.WriteFile(filepath.Join(contents, "Info.plist"), []byte(plist("foresprint")), 0o644); err != nil {
		return nil, err
	}
	if err := os.WriteFile(filepath.Join(contents, "Resources", "foresprint.icns"), ICNS(logo), 0o644); err != nil {
		return nil, err
	}
	// Apps from the Finder do not inherit the shell PATH, hence the absolute path.
	starter := "#!/bin/sh\ncd \"$HOME\"\nexec \"" + o.Program + "\"\n"
	if err := os.WriteFile(filepath.Join(contents, "MacOS", AppName), []byte(starter), 0o755); err != nil {
		return nil, err
	}
	paths := []string{bundle}
	if info, err := os.Stat(filepath.Join(o.Home, "Desktop")); err == nil && info.IsDir() {
		alias := filepath.Join(o.Home, "Desktop", AppName+".app")
		_ = os.Remove(alias)
		if err := os.Symlink(bundle, alias); err != nil {
			return nil, err
		}
		paths = append(paths, alias)
	}
	return paths, nil
}
