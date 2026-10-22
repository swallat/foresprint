package git

import (
	"strings"
	"testing"
)

func TestSilentFailureNamesTheCallWithoutValues(t *testing.T) {
	got := SilentFailure([]string{
		"push", "--force-with-lease=refs/heads/x:abc", "-o", "merge_request.title=Secret",
		"https://user:token@host/r.git", "HEAD:refs/heads/x",
	}, 1)
	want := "git push --force-with-lease -o ended with exit code 1 and no message"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if strings.Contains(got, "token") || strings.Contains(got, "Secret") {
		t.Fatalf("leaks a value: %q", got)
	}
}
