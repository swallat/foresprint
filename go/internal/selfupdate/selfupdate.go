// Package selfupdate updates the program from the releases on GitHub: it finds the newest
// release, downloads the archive for this system, checks its SHA-256 sum against checksums.txt
// of the release and replaces the running program.
//
// Release layout (written by the release workflow): the archive foresprint_<version>_<os>_<arch>
// (.zip on Windows, .tar.gz elsewhere) holds the program foresprint (foresprint.exe on Windows)
// at its top level; checksums.txt lists "<sha256>  <archive name>" lines.
package selfupdate

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// DefaultRepo is the repository the releases come from.
const DefaultRepo = "swallat/foresprint"

// ChecksumsAsset is the name of the file with the SHA-256 sums in a release.
const ChecksumsAsset = "checksums.txt"

// maxDownload limits the size of what is read from the network.
const maxDownload = 512 << 20

// Release is a published version.
type Release struct {
	Version string            // without the leading "v"
	URL     string            // page of the release
	Assets  map[string]string // download URL by file name
}

// Updater finds and installs releases. The zero value of the optional fields is the real
// system; tests set them.
type Updater struct {
	Repo    string       // "owner/name", default DefaultRepo
	APIBase string       // default https://api.github.com
	Client  *http.Client // default: 30 s timeout
	GOOS    string       // default runtime.GOOS
	GOARCH  string       // default runtime.GOARCH
	ExePath string       // the program to replace, default: the running one
}

func (u *Updater) repo() string {
	if u.Repo != "" {
		return u.Repo
	}
	return DefaultRepo
}

func (u *Updater) client() *http.Client {
	if u.Client != nil {
		return u.Client
	}
	return &http.Client{Timeout: 30 * time.Second}
}

func (u *Updater) goos() string {
	if u.GOOS != "" {
		return u.GOOS
	}
	return runtime.GOOS
}

func (u *Updater) goarch() string {
	if u.GOARCH != "" {
		return u.GOARCH
	}
	return runtime.GOARCH
}

func (u *Updater) get(ctx context.Context, url string, limit int64) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "foresprint-update")
	req.Header.Set("Accept", "application/octet-stream, application/vnd.github+json")
	resp, err := u.client().Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: HTTP %d", url, resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("%s: larger than %d bytes", url, limit)
	}
	return data, nil
}

// Latest asks GitHub for the newest published release (no draft, no pre-release).
func (u *Updater) Latest(ctx context.Context) (*Release, error) {
	base := u.APIBase
	if base == "" {
		base = "https://api.github.com"
	}
	data, err := u.get(ctx, fmt.Sprintf("%s/repos/%s/releases/latest", strings.TrimRight(base, "/"), u.repo()), 8<<20)
	if err != nil {
		return nil, err
	}
	var raw struct {
		Tag    string `json:"tag_name"`
		URL    string `json:"html_url"`
		Assets []struct {
			Name string `json:"name"`
			URL  string `json:"browser_download_url"`
		} `json:"assets"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("release information: %w", err)
	}
	rel := &Release{Version: strings.TrimPrefix(raw.Tag, "v"), URL: raw.URL, Assets: map[string]string{}}
	if _, ok := parseVersion(rel.Version); !ok {
		return nil, fmt.Errorf("release tag %q is not a version", raw.Tag)
	}
	for _, a := range raw.Assets {
		rel.Assets[a.Name] = a.URL
	}
	return rel, nil
}

// AssetName is the archive of a version for this system.
func (u *Updater) AssetName(version string) string {
	ext := ".tar.gz"
	if u.goos() == "windows" {
		ext = ".zip"
	}
	return fmt.Sprintf("foresprint_%s_%s_%s%s", version, u.goos(), u.goarch(), ext)
}

// binaryName is the file name of the program inside the archive.
func (u *Updater) binaryName() string {
	if u.goos() == "windows" {
		return "foresprint.exe"
	}
	return "foresprint"
}

// Install downloads the release for this system, checks it and replaces the program.
func (u *Updater) Install(ctx context.Context, rel *Release) error {
	name := u.AssetName(rel.Version)
	archiveURL, ok := rel.Assets[name]
	if !ok {
		return fmt.Errorf("the release %s has no file %s for this system", rel.Version, name)
	}
	sumsURL, ok := rel.Assets[ChecksumsAsset]
	if !ok {
		return fmt.Errorf("the release %s has no %s; not installing an unchecked file", rel.Version, ChecksumsAsset)
	}
	sums, err := u.get(ctx, sumsURL, 1<<20)
	if err != nil {
		return err
	}
	want, err := checksumOf(sums, name)
	if err != nil {
		return err
	}
	archive, err := u.get(ctx, archiveURL, maxDownload)
	if err != nil {
		return err
	}
	if got := sha256.Sum256(archive); hex.EncodeToString(got[:]) != want {
		return fmt.Errorf("%s: the checksum does not match; nothing was changed", name)
	}
	binary, err := extract(archive, name, u.binaryName())
	if err != nil {
		return err
	}
	exe := u.ExePath
	if exe == "" {
		if exe, err = os.Executable(); err != nil {
			return err
		}
		if resolved, err := filepath.EvalSymlinks(exe); err == nil {
			exe = resolved
		}
	}
	return replace(exe, binary, u.goos() == "windows")
}

// checksumOf finds the sum of a file in the text of checksums.txt.
func checksumOf(sums []byte, name string) (string, error) {
	for _, line := range strings.Split(string(sums), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && strings.TrimPrefix(fields[1], "*") == name {
			return strings.ToLower(fields[0]), nil
		}
	}
	return "", fmt.Errorf("%s has no sum for %s", ChecksumsAsset, name)
}

// extract returns the program from a .zip or .tar.gz archive.
func extract(archive []byte, archiveName, binary string) ([]byte, error) {
	if strings.HasSuffix(archiveName, ".zip") {
		zr, err := zip.NewReader(bytes.NewReader(archive), int64(len(archive)))
		if err != nil {
			return nil, err
		}
		for _, f := range zr.File {
			if path.Base(f.Name) == binary && !f.FileInfo().IsDir() {
				rc, err := f.Open()
				if err != nil {
					return nil, err
				}
				defer func() { _ = rc.Close() }()
				return io.ReadAll(io.LimitReader(rc, maxDownload))
			}
		}
		return nil, fmt.Errorf("%s does not contain %s", archiveName, binary)
	}
	gz, err := gzip.NewReader(bytes.NewReader(archive))
	if err != nil {
		return nil, err
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("%s does not contain %s", archiveName, binary)
		}
		if err != nil {
			return nil, err
		}
		if h.Typeflag == tar.TypeReg && path.Base(h.Name) == binary {
			return io.ReadAll(io.LimitReader(tr, maxDownload))
		}
	}
}

// OldSuffix marks the previous program after an update on Windows, where a running program
// cannot be overwritten but can be renamed.
const OldSuffix = ".old"

// replace writes the new program next to the old one and swaps them. On a failure the old
// program stays.
func replace(exe string, content []byte, windows bool) error {
	next := exe + ".new"
	if err := os.WriteFile(next, content, 0o755); err != nil {
		return err
	}
	if !windows {
		if err := os.Rename(next, exe); err != nil {
			_ = os.Remove(next)
			return err
		}
		return nil
	}
	old := exe + OldSuffix
	_ = os.Remove(old)
	if err := os.Rename(exe, old); err != nil {
		_ = os.Remove(next)
		return err
	}
	if err := os.Rename(next, exe); err != nil {
		_ = os.Rename(old, exe)
		_ = os.Remove(next)
		return err
	}
	return nil
}

// CleanupOld removes the program left behind by the last update (call it at start).
func CleanupOld() {
	if exe, err := os.Executable(); err == nil {
		_ = os.Remove(exe + OldSuffix)
	}
}

// IsDevelopment reports whether a version is not a release version (a local build).
func IsDevelopment(version string) bool {
	_, ok := parseVersion(version)
	return !ok
}

// Newer reports whether latest is a higher version than current. A current version that is not
// a release version ("dev") is never older.
func Newer(current, latest string) bool {
	c, ok := parseVersion(current)
	if !ok {
		return false
	}
	l, ok := parseVersion(latest)
	if !ok {
		return false
	}
	for i := range c.nums {
		if l.nums[i] != c.nums[i] {
			return l.nums[i] > c.nums[i]
		}
	}
	switch { // 1.0.0-beta.1 < 1.0.0
	case c.pre == "" && l.pre != "":
		return false
	case c.pre != "" && l.pre == "":
		return true
	}
	return l.pre > c.pre
}

type version struct {
	nums [3]int
	pre  string
}

func parseVersion(s string) (version, bool) {
	s = strings.TrimPrefix(strings.TrimSpace(s), "v")
	if i := strings.IndexByte(s, '+'); i >= 0 {
		s = s[:i]
	}
	var v version
	if i := strings.IndexByte(s, '-'); i >= 0 {
		s, v.pre = s[:i], s[i+1:]
	}
	parts := strings.Split(s, ".")
	if len(parts) != 3 {
		return version{}, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return version{}, false
		}
		v.nums[i] = n
	}
	return v, true
}
