package signin

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/git"
	"github.com/swallat/foresprint/internal/gitsync"
	"github.com/swallat/foresprint/internal/gittest"
)

var bg = context.Background()

const (
	serverURL = "https://git.example.com/team/sprint-daten.git"
	token     = "glpat-SECRET-12345"
)

// ownConfig keeps the global settings the tests write out of the computer's own.
func ownConfig(t *testing.T) {
	t.Helper()
	gittest.Need(t)
	home := t.TempDir()
	config := filepath.Join(home, "gitconfig")
	if err := os.WriteFile(config, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	t.Setenv("GIT_CONFIG_GLOBAL", config)
	t.Setenv("GCM_INTERACTIVE", "never")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	git.ResetGitCache()
	git.InvalidateStatus()
}

// helperLog registers a stand-in credential helper: it appends action and input to a file.
func helperLog(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the stand-in helper is a shell script")
	}
	dir := t.TempDir()
	log := filepath.Join(dir, "helper.log")
	script := filepath.Join(dir, "helper.sh")
	gittest.Write(t, script, "#!/bin/sh\necho \"== $1\" >> \""+log+"\"\ncat >> \""+log+"\"\n")
	if err := os.Chmod(script, 0o755); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, dir, "config", "--global", "credential.helper", "!"+script)
	return log
}

func readLog(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(b)
}

func TestHTTPSPartsAcceptsOnlyPlainHTTPS(t *testing.T) {
	host, path, err := HTTPSParts(serverURL)
	if err != nil || host != "git.example.com" || path != "team/sprint-daten.git" {
		t.Fatalf("got %q %q %v", host, path, err)
	}
	if host, _, _ := HTTPSParts("https://git.example.com:8443/a.git"); host != "git.example.com:8443" {
		t.Fatalf("host = %q", host)
	}
	for _, bad := range []string{"git@git.example.com:t/r.git", "http://h/r.git", "https://u:p@h/r.git", "/tmp/x", "https://h:abc/x", "https://h:99999/x"} {
		if _, _, err := HTTPSParts(bad); err == nil || IsHTTPS(bad) {
			t.Errorf("%q accepted", bad)
		}
	}
	if host, _, _ := HTTPSParts("https://[::1]:8443/x.git"); host != "[::1]:8443" {
		t.Fatalf("host = %q", host)
	}
}

func TestStoreTokenHandsItToTheHelper(t *testing.T) {
	ownConfig(t)
	log := helperLog(t)
	if err := StoreToken(bg, t.TempDir(), serverURL, "oauth2", token); err != nil {
		t.Fatal(err)
	}
	got := readLog(t, log)
	for _, want := range []string{"== store", "host=git.example.com", "username=oauth2", "password=" + token} {
		if !strings.Contains(got, want) {
			t.Errorf("log lacks %q: %q", want, got)
		}
	}
}

func TestStoreTokenRefusesWithoutHelper(t *testing.T) {
	ownConfig(t)
	err := StoreToken(bg, t.TempDir(), serverURL, "oauth2", token)
	e := git.As(err)
	if e == nil || strings.Contains(e.Error(), token) || strings.Contains(e.Hint(), token) {
		t.Fatalf("err = %v", err)
	}
}

func TestStoreTokenRefusesPlainTextHelper(t *testing.T) {
	ownConfig(t)
	dir := t.TempDir()
	gittest.Git(t, dir, "config", "--global", "credential.helper", "store")
	if HelperState(dir) != "plain" {
		t.Fatalf("state = %q", HelperState(dir))
	}
	err := StoreToken(bg, dir, serverURL, "oauth2", token)
	if err == nil || !strings.Contains(err.Error(), "plain text") {
		t.Fatalf("err = %v", err)
	}
	home, _ := os.UserHomeDir()
	if _, err := os.Stat(filepath.Join(home, ".git-credentials")); err == nil {
		t.Fatal("plain-text file written")
	}
}

func TestStoreTokenRejectsEmptyAndMultilineInput(t *testing.T) {
	ownConfig(t)
	log := helperLog(t)
	for _, c := range [][2]string{{"", token}, {"u", ""}, {"u", "a\nb"}, {"u\nhost=evil", token}, {"u", strings.Repeat("x", MaxTokenLength+1)}} {
		err := StoreToken(bg, t.TempDir(), serverURL, c[0], c[1])
		if err == nil || strings.Contains(err.Error(), token) {
			t.Errorf("%q accepted: %v", c, err)
		}
	}
	if readLog(t, log) != "" {
		t.Fatal("helper was called")
	}
}

func TestHelperGivenByFullPathIsStillRecognised(t *testing.T) {
	ownConfig(t)
	dir := t.TempDir()
	for _, value := range []string{
		"/usr/lib/git-core/git-credential-store --file=x",
		"C:/Program Files/Git/git-credential-store.exe",
		`C:\Git\git-credential-store.exe`,
	} {
		gittest.Git(t, dir, "config", "--global", "credential.helper", value)
		git.ResetGitCache()
		if HelperState(dir) != "plain" {
			t.Errorf("%q: state = %q", value, HelperState(dir))
		}
	}
}

func TestForgetToken(t *testing.T) {
	ownConfig(t)
	log := helperLog(t)
	if err := ForgetToken(bg, t.TempDir(), serverURL, "oauth2", token); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(readLog(t, log), "password="+token) {
		t.Fatal("exact entry not named")
	}
	if err := os.WriteFile(log, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ForgetToken(bg, t.TempDir(), serverURL, "", ""); err != nil {
		t.Fatal(err)
	}
	got := readLog(t, log)
	if !strings.Contains(got, "== erase") || !strings.Contains(got, "host=git.example.com") || strings.Contains(got, "password") {
		t.Fatalf("log = %q", got)
	}
}

func TestVerifyListsBranches(t *testing.T) {
	ownConfig(t)
	gittest.Isolate(t)
	dir := t.TempDir()
	server := gittest.MakeServer(t, dir, "server.git", "main")
	heads, err := Verify(bg, dir, server)
	if err != nil || len(heads) != 1 || heads[0] != "main" {
		t.Fatalf("heads = %v err = %v", heads, err)
	}
}

func TestEnableHelperOnlyOffersTheSuggestedOne(t *testing.T) {
	ownConfig(t)
	if runtime.GOOS == "windows" || runtime.GOOS == "darwin" {
		t.Skip("the suggestion depends on the platform")
	}
	real := helperAvailable
	t.Cleanup(func() { helperAvailable = real })
	helperAvailable = func(_ context.Context, name string) bool { return name == "libsecret" }
	if got := SuggestedHelper(bg); got != "libsecret" {
		t.Fatalf("suggested = %q", got)
	}
	for _, bad := range []string{"store", "cache", "!rm -rf", ""} {
		if err := EnableHelper(bg, bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
	if err := EnableHelper(bg, "libsecret"); err != nil {
		t.Fatal(err)
	}
	if got := gittest.Git(t, t.TempDir(), "config", "--global", "credential.helper"); got != "libsecret" {
		t.Fatalf("helper = %q", got)
	}
	helperAvailable = func(context.Context, string) bool { return false }
	if got := SuggestedHelper(bg); got != "" {
		t.Fatalf("suggested = %q", got)
	}
}

func TestSetupItemsFollowTheState(t *testing.T) {
	ownConfig(t)
	helperLog(t)
	root := gittest.MakeLocal(t, t.TempDir(), "work", true)
	items := func() map[string]SetupItem {
		out := map[string]SetupItem{}
		for _, i := range SetupItems(bg, root) {
			out[i.Key] = i
		}
		return out
	}
	got := items()
	if !got["git"].OK || !got["folder"].OK || got["server"].OK {
		t.Fatalf("items = %+v", got)
	}
	gittest.Git(t, root, "remote", "add", "origin", serverURL)
	git.InvalidateStatus()
	if got = items(); !got["server"].OK || !got["login"].OK {
		t.Fatalf("items = %+v", got)
	}
	gittest.Git(t, root, "config", "--global", "--unset", "credential.helper")
	git.ResetGitCache()
	git.InvalidateStatus()
	if got = items(); got["login"].OK {
		t.Fatalf("login ok without a helper: %+v", got["login"])
	}
	gittest.Git(t, root, "remote", "set-url", "origin", "git@git.example.com:team/data.git")
	git.InvalidateStatus()
	if got = items(); !got["login"].OK {
		t.Fatalf("ssh needs no token: %+v", got["login"])
	}
}

func TestSetupItemsWithoutRepository(t *testing.T) {
	ownConfig(t)
	items := SetupItems(bg, t.TempDir())
	if len(items) != 2 || items[0].Key != "git" || items[1].Key != "folder" || items[1].OK {
		t.Fatalf("items = %+v", items)
	}
}

func TestGuideForGenericNamesBothUserNames(t *testing.T) {
	g := GuideFor(gitsync.HostGeneric)
	if g.Username != "" || !strings.Contains(g.Steps, "oauth2") || !strings.Contains(g.Steps, "Gitea") {
		t.Errorf("generic guide = %+v", g)
	}
}

func TestGuideFor(t *testing.T) {
	if g := GuideFor(gitsync.HostGitLab); g.Username != "oauth2" {
		t.Fatalf("gitlab = %+v", g)
	}
	if g := GuideFor(gitsync.HostGitHub); g.Username != "x-access-token" {
		t.Fatalf("github = %+v", g)
	}
	if g := GuideFor("unknown"); g.Username != "" || g.Steps == "" {
		t.Fatalf("generic = %+v", g)
	}
}
