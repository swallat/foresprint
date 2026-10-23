package selfupdate

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestNewer(t *testing.T) {
	for _, c := range []struct {
		current, latest string
		want            bool
	}{
		{"1.0.0", "1.0.1", true},
		{"1.0.1", "1.0.0", false},
		{"1.0.0", "1.0.0", false},
		{"1.9.0", "1.10.0", true},
		{"1.0.0-beta.1", "1.0.0", true},
		{"1.0.0", "1.0.0-beta.2", false},
		{"v1.0.0", "v1.1.0", true},
		{"1.0.0-beta.9", "1.0.0-beta.10", true},
		{"1.0.0-beta.10", "1.0.0-beta.9", false},
		{"1.0.0-beta.2", "1.0.0-rc.1", true},
		{"dev", "9.9.9", false},
		{"1.0.0", "weird", false},
	} {
		if got := Newer(c.current, c.latest); got != c.want {
			t.Errorf("Newer(%q, %q) = %v, want %v", c.current, c.latest, got, c.want)
		}
	}
}

func zipOf(t *testing.T, name, content string) []byte {
	var b bytes.Buffer
	zw := zip.NewWriter(&b)
	w, err := zw.Create(name)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = w.Write([]byte(content))
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

func tarGzOf(t *testing.T, name, content string) []byte {
	var b bytes.Buffer
	gz := gzip.NewWriter(&b)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	_, _ = tw.Write([]byte(content))
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

// release serves a fake GitHub with one release 2.0.0 and returns an updater for it.
func release(t *testing.T, goos string, tamper bool) (*Updater, string) {
	t.Helper()
	u := &Updater{GOOS: goos, GOARCH: "amd64"}
	name := u.AssetName("2.0.0")
	var archive []byte
	if goos == "windows" {
		archive = zipOf(t, "foresprint.exe", "NEW")
	} else {
		archive = tarGzOf(t, "foresprint_2.0.0/foresprint", "NEW")
	}
	sum := sha256.Sum256(archive)
	if tamper {
		sum[0] ^= 0xff
	}
	mux := http.NewServeMux()
	var srv *httptest.Server
	mux.HandleFunc("/repos/swallat/foresprint/releases/latest", func(w http.ResponseWriter, r *http.Request) {
		_, _ = fmt.Fprintf(w, `{"tag_name":"v2.0.0","html_url":"%s/r","assets":[
			{"name":%q,"browser_download_url":"%s/dl/%s"},
			{"name":"checksums.txt","browser_download_url":"%s/dl/checksums.txt"}]}`,
			srv.URL, name, srv.URL, name, srv.URL)
	})
	mux.HandleFunc("/dl/checksums.txt", func(w http.ResponseWriter, r *http.Request) {
		_, _ = fmt.Fprintf(w, "%s  %s\n", hex.EncodeToString(sum[:]), name)
	})
	mux.HandleFunc("/dl/"+name, func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write(archive) })
	srv = httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	u.APIBase = srv.URL
	exe := filepath.Join(t.TempDir(), "foresprint")
	if goos == "windows" {
		exe += ".exe"
	}
	if err := os.WriteFile(exe, []byte("OLD"), 0o755); err != nil {
		t.Fatal(err)
	}
	u.ExePath = exe
	return u, exe
}

func TestInstall(t *testing.T) {
	for _, goos := range []string{"linux", "windows"} {
		t.Run(goos, func(t *testing.T) {
			u, exe := release(t, goos, false)
			ctx := context.Background()
			rel, err := u.Latest(ctx)
			if err != nil {
				t.Fatal(err)
			}
			if rel.Version != "2.0.0" || !Newer("1.0.0", rel.Version) {
				t.Fatalf("release: %+v", rel)
			}
			if err := u.Install(ctx, rel); err != nil {
				t.Fatal(err)
			}
			if got, _ := os.ReadFile(exe); string(got) != "NEW" {
				t.Errorf("program is %q", got)
			}
			if goos == "windows" {
				if old, _ := os.ReadFile(exe + OldSuffix); string(old) != "OLD" {
					t.Errorf("old program is %q", old)
				}
			}
			if _, err := os.Stat(exe + ".new"); err == nil {
				t.Error("temporary file left behind")
			}
		})
	}
}

func TestInstallRefusesWrongChecksum(t *testing.T) {
	u, exe := release(t, "linux", true)
	rel, err := u.Latest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err := u.Install(context.Background(), rel); err == nil {
		t.Fatal("installed a file with a wrong checksum")
	}
	if got, _ := os.ReadFile(exe); string(got) != "OLD" {
		t.Errorf("program changed to %q", got)
	}
}

func TestInstallNeedsAssetAndChecksums(t *testing.T) {
	u := &Updater{GOOS: "linux", GOARCH: "amd64"}
	if err := u.Install(context.Background(), &Release{Version: "2.0.0", Assets: map[string]string{}}); err == nil {
		t.Error("no asset")
	}
	rel := &Release{Version: "2.0.0", Assets: map[string]string{u.AssetName("2.0.0"): "http://invalid.example/x"}}
	if err := u.Install(context.Background(), rel); err == nil {
		t.Error("no checksums.txt")
	}
}

func TestModeAndState(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("APPDATA", t.TempDir())
	t.Setenv("HOME", t.TempDir())
	t.Setenv(ModeEnv, "")
	if CurrentMode() != On {
		t.Error("default is on")
	}
	if err := (State{Mode: "notice"}).Save(); err != nil {
		t.Fatal(err)
	}
	if CurrentMode() != Notice {
		t.Error("saved notice")
	}
	t.Setenv(ModeEnv, "0")
	if CurrentMode() != Off {
		t.Error("environment wins")
	}
}

func TestAssetNameOfTheCLIVariant(t *testing.T) {
	cases := []struct {
		goos string
		cli  bool
		want string
	}{
		{"linux", false, "foresprint_2.0.0_linux_amd64.tar.gz"},
		{"linux", true, "foresprint-cli_2.0.0_linux_amd64.tar.gz"},
		{"darwin", true, "foresprint_2.0.0_darwin_amd64.tar.gz"},
		{"windows", true, "foresprint_2.0.0_windows_amd64.zip"},
	}
	for _, c := range cases {
		u := &Updater{GOOS: c.goos, GOARCH: "amd64", CLI: c.cli}
		if got := u.AssetName("2.0.0"); got != c.want {
			t.Errorf("%s cli=%v: %s, want %s", c.goos, c.cli, got, c.want)
		}
	}
}

func TestLatestForPreReleaseLooksAtAllReleases(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/repos/swallat/foresprint/releases/latest", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name":"v0.8.0","html_url":"u","assets":[]}`))
	})
	mux.HandleFunc("/repos/swallat/foresprint/releases", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`[{"tag_name":"v1.0.0-beta.4","html_url":"u4","assets":[]},
			{"tag_name":"v1.0.0-beta.9","draft":true,"assets":[]},
			{"tag_name":"v1.0.0-beta.3","html_url":"u3","assets":[]},{"tag_name":"v0.8.0","assets":[]}]`))
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	for current, want := range map[string]string{"1.0.0-beta.3": "1.0.0-beta.4", "0.8.0": "0.8.0", "": "0.8.0"} {
		rel, err := (&Updater{APIBase: srv.URL, Current: current}).Latest(context.Background())
		if err != nil || rel.Version != want {
			t.Errorf("current %q: got %+v, %v; want %s", current, rel, err, want)
		}
	}
}
