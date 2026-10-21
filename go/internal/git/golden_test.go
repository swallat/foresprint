package git

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"unicode/utf8"

	"github.com/swallat/foresprint/internal/golden"
)

// isolate gives the test an empty Git configuration and a working folder that is no repository,
// the setting in which the references were written (see scripts/golden_ext/git.py).
func isolate(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv("USERPROFILE", dir)
	t.Setenv("GIT_CONFIG_GLOBAL", os.DevNull)
	t.Setenv("GIT_CONFIG_SYSTEM", os.DevNull)
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	cwd := filepath.Join(dir, "cwd")
	if err := os.Mkdir(cwd, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(cwd)
	ResetGitCache()
	return cwd
}

func needGit(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git is not installed")
	}
}

// linuxOnly skips tests whose references contain texts that depend on the operating system.
func linuxOnly(t *testing.T) {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("the references with hints were written on Linux")
	}
}

type errorRef struct {
	Message  string `json:"message"`
	Kind     string `json:"kind"`
	Hint     string `json:"hint"`
	HintMD   string `json:"hint_md"`
	Raw      bool   `json:"raw"`
	RenderMD string `json:"render_md"`
	Full     string `json:"full"`
}

func errorOf(e *Error) errorRef {
	return errorRef{e.Error(), e.Kind, e.Hint(), e.HintMD(), e.Raw, e.Render(MDCodeLines), e.Full(nil)}
}

func checkError(t *testing.T, what string, got *Error, want errorRef) {
	t.Helper()
	if got == nil {
		t.Errorf("%s: no error, want kind %q", what, want.Kind)
		return
	}
	if g := errorOf(got); g != want {
		t.Errorf("%s:\n got  %+v\n want %+v", what, g, want)
	}
}

func TestTextHelpersMatchPython(t *testing.T) {
	var ref struct {
		PublicURL []struct {
			In    string `json:"in"`
			Out   string `json:"out"`
			Creds bool   `json:"creds"`
		} `json:"public_url"`
		Scrub         []struct{ In, Out string } `json:"scrub"`
		Blank         []struct{ In, Out string } `json:"blank"`
		MDPlain       []struct{ In, Out string } `json:"md_plain"`
		MDCode        []struct{ In, Out string } `json:"md_code"`
		MDCodeLines   []struct{ In, Out string } `json:"md_code_lines"`
		ConflictMarks []struct {
			In  string `json:"in"`
			Out bool   `json:"out"`
		} `json:"conflict_markers"`
	}
	golden.Load(t, &ref, "git", "text.json")
	for _, c := range ref.PublicURL {
		if got := PublicURL(c.In); got != c.Out {
			t.Errorf("PublicURL(%q) = %q, want %q", c.In, got, c.Out)
		}
		if got := HasCredentials(c.In); got != c.Creds {
			t.Errorf("HasCredentials(%q) = %v, want %v", c.In, got, c.Creds)
		}
	}
	for _, c := range ref.Scrub {
		if got := Scrub(c.In); got != c.Out {
			t.Errorf("Scrub(%q) = %q, want %q", c.In, got, c.Out)
		}
	}
	for _, c := range ref.Blank {
		if got := BlankControls(c.In); got != c.Out {
			t.Errorf("BlankControls(%q) = %q, want %q", c.In, got, c.Out)
		}
	}
	for _, c := range ref.MDPlain {
		if got := MDPlain(c.In); got != c.Out {
			t.Errorf("MDPlain(%q) = %q, want %q", c.In, got, c.Out)
		}
	}
	for _, c := range ref.MDCode {
		if got := MDCode(c.In); got != c.Out {
			t.Errorf("MDCode(%q) = %q, want %q", c.In, got, c.Out)
		}
	}
	for _, c := range ref.MDCodeLines {
		if got := MDCodeLines(c.In); got != c.Out {
			t.Errorf("MDCodeLines(%q) = %q, want %q", c.In, got, c.Out)
		}
	}
	for _, c := range ref.ConflictMarks {
		if got := HasConflictMarkers(c.In); got != c.Out {
			t.Errorf("HasConflictMarkers(%q) = %v, want %v", c.In, got, c.Out)
		}
	}
	if len(ref.PublicURL) == 0 || !utf8.ValidString(ref.Scrub[0].In) {
		t.Fatal("empty reference")
	}
}

func TestParseRemoteURLMatchesPython(t *testing.T) {
	linuxOnly(t) // absolute paths: "C:\x" is relative on Linux
	var ref []struct {
		In       string `json:"in"`
		Insecure bool   `json:"insecure"`
		OK       *struct {
			URL  string `json:"url"`
			Kind string `json:"kind"`
		} `json:"ok"`
		Error *errorRef `json:"error"`
	}
	golden.Load(t, &ref, "git", "parse_url.json")
	if len(ref) == 0 {
		t.Fatal("empty reference")
	}
	for _, c := range ref {
		got, err := ParseRemoteURL(c.In, c.Insecure)
		if c.OK != nil {
			if err != nil {
				t.Errorf("ParseRemoteURL(%q, %v): %v, want %+v", c.In, c.Insecure, err, *c.OK)
			} else if got.URL != c.OK.URL || got.Kind != c.OK.Kind {
				t.Errorf("ParseRemoteURL(%q, %v) = %+v, want %+v", c.In, c.Insecure, got, *c.OK)
			}
			continue
		}
		checkError(t, "ParseRemoteURL("+c.In[:min(len(c.In), 40)]+")", As(err), *c.Error)
	}
}

func TestClassifyMatchesPython(t *testing.T) {
	linuxOnly(t)
	needGit(t)
	cwd := isolate(t)
	var ref []struct {
		In   string `json:"in"`
		URL  string `json:"url"`
		Flag string `json:"flag"`
		errorRef
	}
	golden.Load(t, &ref, "git", "classify.json")
	for _, c := range ref {
		opts := ClassifyOpts{URL: c.URL, Cwd: cwd}
		switch c.Flag {
		case "missing":
			opts.Missing = true
		case "timeout":
			opts.Timeout = true
		}
		got := errorOf(Classify(c.In, opts))
		if c.Flag == "missing" { // the hint lists places of this computer
			got.Hint, got.HintMD, got.Full = "", "", ""
		}
		if got != c.errorRef {
			t.Errorf("Classify(%q, %q, %s):\n got  %+v\n want %+v", c.In, c.URL, c.Flag, got, c.errorRef)
		}
	}
}

func TestKindsMatchPython(t *testing.T) {
	linuxOnly(t)
	needGit(t)
	isolate(t)
	var ref []struct{ Kind, Title, Hint string }
	golden.Load(t, &ref, "git", "kinds.json")
	for _, c := range ref {
		if got := TitleFor(c.Kind); got != c.Title {
			t.Errorf("TitleFor(%q) = %q, want %q", c.Kind, got, c.Title)
		}
		if got := HintFor(c.Kind); got != c.Hint {
			t.Errorf("HintFor(%q) = %q, want %q", c.Kind, got, c.Hint)
		}
	}
}

func TestProbeErrorMatchesPython(t *testing.T) {
	linuxOnly(t)
	needGit(t)
	cwd := isolate(t)
	var ref []struct {
		In       string `json:"in"`
		TimedOut bool   `json:"timed_out"`
		URL      string `json:"url"`
		errorRef
	}
	golden.Load(t, &ref, "git", "probe_error.json")
	for _, c := range ref {
		got := errorOf(probeError(c.In, RemoteAddress{URL: c.URL, Kind: "https"}, c.TimedOut, cwd))
		if got != c.errorRef {
			t.Errorf("probeError(%q, %q, %v):\n got  %+v\n want %+v", c.In, c.URL, c.TimedOut, got, c.errorRef)
		}
	}
}

func TestErrorTextsMatchPython(t *testing.T) {
	linuxOnly(t)
	var ref []struct {
		What string `json:"what"`
		errorRef
		Text string `json:"text"`
	}
	golden.Load(t, &ref, "git", "errors.json")
	heads := []string{"main", "dev", "a", "b", "c", "d", "e"}
	built := map[string]*Error{
		"secret":  SecretInURLError(),
		"special": RemoteSpecialError(),
		"nothing": NothingToShareError(),
	}
	n := 0
	for _, c := range ref {
		switch c.What {
		case "new_branch":
			var e *Error
			switch n {
			case 0:
				e = NewBranchError("main", []string{"dev"}, false)
			case 1:
				e = NewBranchError("main", heads, true)
			default:
				e = NewBranchError("x", nil, false)
			}
			n++
			checkError(t, "new_branch", e, c.errorRef)
		case "unrelated":
			checkError(t, "unrelated", UnrelatedHistoriesError("https://u:p@h/x.git?x=1", "main"), c.errorRef)
		case "unwritable":
			if got := UnwritableFileHint(); got != c.Text {
				t.Errorf("UnwritableFileHint() = %q, want %q", got, c.Text)
			}
		default:
			checkError(t, c.What, built[c.What], c.errorRef)
		}
	}
}

func TestSplittersMatchPython(t *testing.T) {
	var ref struct {
		TagNames []struct {
			In      string `json:"in"`
			OK      bool   `json:"ok"`
			Message string `json:"message"`
		} `json:"tag_names"`
		Records []struct {
			In    string   `json:"in"`
			Count int      `json:"count"`
			Out   []string `json:"out"`
		} `json:"records"`
		SplitZ []struct {
			In  string   `json:"in"`
			Out []string `json:"out"`
		} `json:"split_z"`
	}
	golden.Load(t, &ref, "git", "misc.json")
	for _, c := range ref.TagNames {
		err := CheckName(c.In)
		if (err == nil) != c.OK {
			t.Errorf("CheckName(%q): %v, want ok=%v", c.In, err, c.OK)
		} else if err != nil && err.Error() != c.Message {
			t.Errorf("CheckName(%q) message %q, want %q", c.In, err.Error(), c.Message)
		}
	}
	for _, c := range ref.Records {
		golden.Compare(t, c.Out, SplitRecord(c.In, c.Count, "\x1f"))
	}
	for _, c := range ref.SplitZ {
		got := SplitZ(c.In)
		if got == nil {
			got = []string{}
		}
		golden.Compare(t, c.Out, got)
	}
}

func TestCredentialHelpersMatchPython(t *testing.T) {
	linuxOnly(t)
	needGit(t)
	cwd := isolate(t)
	var ref []struct {
		Name    string   `json:"name"`
		Config  string   `json:"config"`
		Helpers []string `json:"helpers"`
		Advice  string   `json:"advice"`
	}
	golden.Load(t, &ref, "git", "credential.json")
	for _, c := range ref {
		cfg := filepath.Join(t.TempDir(), "config")
		if err := os.WriteFile(cfg, []byte(c.Config), 0o644); err != nil {
			t.Fatal(err)
		}
		t.Setenv("GIT_CONFIG_GLOBAL", cfg)
		got := CredentialHelpers(cwd)
		if got == nil {
			got = []string{}
		}
		golden.Compare(t, c.Helpers, got)
		if advice := CredentialAdvice(cwd); advice != c.Advice {
			t.Errorf("%s: CredentialAdvice =\n%q\nwant\n%q", c.Name, advice, c.Advice)
		}
	}
}
