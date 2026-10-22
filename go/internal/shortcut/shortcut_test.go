package shortcut

import (
	"bytes"
	"image/png"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestLogo(t *testing.T) {
	logo := PNG(IconSize)
	img, err := png.Decode(bytes.NewReader(logo))
	if err != nil || img.Bounds().Dx() != IconSize {
		t.Fatalf("not a %d px PNG: %v", IconSize, err)
	}
	if _, _, _, a := img.At(0, 0).RGBA(); a != 0 {
		t.Error("the corner is rounded and transparent")
	}
	if r, g, b, _ := img.At(IconSize/2, 10).RGBA(); r>>8 != 91 || g>>8 != 91 || b>>8 != 240 {
		t.Errorf("the top middle is indigo, got %d %d %d", r>>8, g>>8, b>>8)
	}
	if ico := ICO(logo); len(ico) != 22+len(logo) || ico[2] != 1 {
		t.Error("ico header")
	}
	if icns := ICNS(logo); string(icns[:4]) != "icns" || string(icns[8:12]) != "ic08" || len(icns) != len(logo)+16 {
		t.Error("icns header")
	}
}

func TestLinux(t *testing.T) {
	home := t.TempDir()
	if err := os.Mkdir(filepath.Join(home, "Desktop"), 0o755); err != nil {
		t.Fatal(err)
	}
	paths, err := Create(Options{Program: "/opt/fs/foresprint", Home: home, GOOS: "linux", DataHome: filepath.Join(home, "share")})
	if err != nil || len(paths) != 2 {
		t.Fatalf("%v %v", paths, err)
	}
	text, _ := os.ReadFile(paths[0])
	if !strings.Contains(string(text), `Exec="/opt/fs/foresprint"`) || !strings.Contains(string(text), "Name=Foresprint") {
		t.Errorf("entry: %s", text)
	}
	if info, _ := os.Stat(paths[0]); runtime.GOOS != "windows" && info.Mode()&0o100 == 0 { // no execute bit there
		t.Error("the launcher must be executable")
	}
}

func TestMac(t *testing.T) {
	home := t.TempDir()
	if err := os.Mkdir(filepath.Join(home, "Desktop"), 0o755); err != nil {
		t.Fatal(err)
	}
	paths, err := Create(Options{Program: "/Applications/Foresprint/foresprint", Home: home, GOOS: "darwin"})
	if err != nil || len(paths) != 2 {
		t.Fatalf("%v %v", paths, err)
	}
	starter, _ := os.ReadFile(filepath.Join(paths[0], "Contents", "MacOS", AppName))
	if !strings.Contains(string(starter), `exec "/Applications/Foresprint/foresprint"`) {
		t.Errorf("starter: %s", starter)
	}
	if _, err := os.Stat(filepath.Join(paths[0], "Contents", "Resources", "foresprint.icns")); err != nil {
		t.Error(err)
	}
	if target, err := os.Readlink(paths[1]); err != nil || target != paths[0] {
		t.Errorf("alias: %q %v", target, err)
	}
	// A second run replaces the alias instead of failing.
	if _, err := Create(Options{Program: "/Applications/Foresprint/foresprint", Home: home, GOOS: "darwin"}); err != nil {
		t.Errorf("second run: %v", err)
	}
}

func TestWindows(t *testing.T) {
	home := t.TempDir()
	var script string
	paths, err := Create(Options{Program: `C:\Users\it's\foresprint.exe`, Home: home, GOOS: "windows",
		PowerShell: func(s string) (string, error) { script = s; return "C:\\a.lnk\r\nC:\\b.lnk\r\n", nil }})
	if err != nil || len(paths) != 2 || paths[0] != `C:\a.lnk` {
		t.Fatalf("%v %v", paths, err)
	}
	if !strings.Contains(script, `$link.TargetPath = 'C:\Users\it''s\foresprint.exe'`) ||
		!strings.Contains(script, "GetFolderPath('Programs')") {
		t.Errorf("script: %s", script)
	}
}

func TestNeedsAbsoluteProgram(t *testing.T) {
	if _, err := Create(Options{Program: "foresprint", Home: t.TempDir(), GOOS: "linux"}); err == nil {
		t.Error("a relative program path cannot be started from a launcher")
	}
}
