package golden

import (
	"path/filepath"
	"testing"
)

// Case is a team data folder with the date the references were calculated for ("today").
type Case struct {
	Name        string `json:"name"`
	Root        string `json:"root"` // relative to the repository root
	Team        string `json:"team"`
	Today       string `json:"today"` // YYYY-MM-DD
	Description string `json:"description"`
	YAML        string `json:"yaml"` // manifest of the YAML round trip, below golden/expected
}

type manifest struct {
	Cases []Case `json:"cases"`
}

// Cases lists the cases of the manifest (demo team and the synthetic teams).
func Cases(tb testing.TB) []Case {
	tb.Helper()
	var m manifest
	Load(tb, &m, "manifest.json")
	if len(m.Cases) == 0 {
		tb.Fatal("golden: the manifest lists no cases")
	}
	return m.Cases
}

// RepoRoot is the repository root (the folder that contains golden/).
func RepoRoot(tb testing.TB) string {
	tb.Helper()
	return filepath.Dir(Dir(tb))
}

// TeamDir is the folder of the team's files (team.yaml, sprints/ ...).
func (c Case) TeamDir(tb testing.TB) string {
	tb.Helper()
	return filepath.Join(RepoRoot(tb), filepath.FromSlash(c.Root), c.Team)
}

// Expected is the path of a reference of the case, e.g. Expected(tb, "forecast.json").
func (c Case) Expected(tb testing.TB, file string) string {
	tb.Helper()
	return Path(tb, "cases", c.Name, file)
}

// LoadExpected reads a reference of the case into out; it reports false (and does not load) when
// the case has no such reference, e.g. no ticket distribution for a team without tickets.
func (c Case) LoadExpected(tb testing.TB, out any, file string) bool {
	tb.Helper()
	if !exists(c.Expected(tb, file)) {
		return false
	}
	Load(tb, out, "cases", c.Name, file)
	return true
}
