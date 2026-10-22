package cli

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/swallat/foresprint/internal/selfupdate"
)

func TestUpdateAuto(t *testing.T) {
	isolate(t)
	t.Setenv(selfupdate.ModeEnv, "")
	if code, out, errOut := run(t, "update", "--auto", "notice"); code != 0 || !strings.Contains(out, "notice") || errOut != "" {
		t.Errorf("auto: %d %q %q", code, out, errOut)
	}
	if got := selfupdate.CurrentMode(); got != selfupdate.Notice {
		t.Errorf("mode %q", got)
	}
	if code, _, errOut := run(t, "update", "--auto", "sometimes"); code != 1 || !strings.Contains(errOut, "on, notice or off") {
		t.Errorf("bad mode: %d %q", code, errOut)
	}
}

func TestUpdateDevelopmentBuild(t *testing.T) {
	isolate(t)
	if code, _, errOut := run(t, "update", "--check"); code != 1 || !strings.Contains(errOut, "development build") {
		t.Errorf("dev: %d %q", code, errOut)
	}
}

func TestUpdateCheck(t *testing.T) {
	isolate(t)
	Version = "1.0.0"
	t.Cleanup(func() { Version = "dev" })
	latest := "v1.1.0"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name":"` + latest + `","html_url":"x","assets":[]}`))
	}))
	defer srv.Close()
	u := &selfupdate.Updater{APIBase: srv.URL}
	env := &Env{}
	var out strings.Builder
	env.Out = &out
	if err := runUpdate(env, u, true, false); err != nil || !strings.Contains(out.String(), "1.1.0 is available") {
		t.Errorf("check: %v %q", err, out.String())
	}
	out.Reset()
	latest = "v1.0.0"
	if err := runUpdate(env, u, true, false); err != nil || !strings.Contains(out.String(), "is the latest") {
		t.Errorf("current: %v %q", err, out.String())
	}
}
