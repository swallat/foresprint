package app

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/workpackages"
)

// packageImportLimit is the number of changes the preview lists; the rest is counted.
const packageImportLimit = 200

// maxTableBytes keeps a wrong file (a video, a backup) from being read into memory.
const maxTableBytes = 20 << 20

// PackageImportPreview lets the user pick a CSV or Excel table of work packages and lists what
// importing it would do. Nothing is written.
func (a *API) PackageImportPreview(team string) (PackageImportPreview, error) {
	if a.ChooseTable == nil {
		return PackageImportPreview{}, errors.New(i18n.T("No file dialog in this build."))
	}
	path, err := a.ChooseTable(i18n.T("Choose the table of work packages"))
	if err != nil {
		return PackageImportPreview{}, err
	}
	if path == "" {
		return PackageImportPreview{Cancelled: true, Changes: []PackageImportChange{}, Problems: []PackageImportProblem{}, Unmapped: []string{}}, nil
	}
	plan, err := a.planPackages(team, path)
	if err != nil {
		return PackageImportPreview{}, err
	}
	out := PackageImportPreview{Path: path, Hash: plan.hash, Changes: []PackageImportChange{},
		Problems: []PackageImportProblem{}, Unmapped: []string{}}
	for _, c := range plan.changes {
		if c.Update {
			out.Updated++
		} else {
			out.New++
		}
		if len(out.Changes) == packageImportLimit {
			out.More++
			continue
		}
		out.Changes = append(out.Changes, PackageImportChange{
			Key: textfmt.BlankControls(c.Package.Key), Title: textfmt.BlankControls(c.Package.Title), Update: c.Update})
	}
	for _, p := range plan.problems {
		out.Problems = append(out.Problems, PackageImportProblem{Row: p.Row, Msg: textfmt.BlankControls(p.Msg)})
	}
	for _, u := range plan.unmapped {
		out.Unmapped = append(out.Unmapped, textfmt.BlankControls(u))
	}
	return out, nil
}

// PackageImportApply reads the table again and writes the packages (rows with problems are
// skipped). The window shows the preview first; hash is the one the preview returned, so a file
// that changed in between is refused instead of writing values nobody saw.
func (a *API) PackageImportApply(team, path, hash string) (Result, error) {
	plan, err := a.planPackages(team, path)
	if err != nil {
		return Result{}, err
	}
	if plan.hash != hash {
		return Result{}, bad("The table changed since the preview. Choose it again.")
	}
	if len(plan.changes) == 0 {
		return Result{OK: true, Message: i18n.T("No changes compared to the existing work packages.")}, nil
	}
	if _, err := plan.repo.SavePackages(team, storage.TicketsFile{Tickets: plan.merged}); err != nil {
		return Result{}, err
	}
	storage.ClearTeamCache()
	return Result{OK: true, Message: i18n.T("{count} work packages imported.", "count", len(plan.changes))}, nil
}

type packagePlan struct {
	repo     *storage.Repository
	hash     string
	merged   []model.Ticket
	changes  []workpackages.Change
	problems []workpackages.Problem
	unmapped []string
}

func (a *API) planPackages(team, path string) (*packagePlan, error) {
	repo, data, err := a.loadRepoTeam(team)
	if err != nil {
		return nil, err
	}
	if data.Team.Source() != model.SourcePackages {
		return nil, bad("This team does not keep work packages in Foresprint.")
	}
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if info.Size() > maxTableBytes {
		return nil, bad("The file is too large for a table of work packages.")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var rows [][]string
	if strings.EqualFold(filepath.Ext(path), ".xlsx") {
		rows, _, err = excel.Table(raw, "")
	} else {
		rows, err = workpackages.ReadCSV(raw)
	}
	if err != nil {
		return nil, err
	}
	res := workpackages.ParseTable(rows, workpackages.Options{Tracker: data.Team.Tracker, Existing: data.Tickets})
	merged, changes := workpackages.Merge(data.Tickets, res.Packages)
	sum := sha256.Sum256(raw)
	return &packagePlan{repo: repo, hash: hex.EncodeToString(sum[:]), merged: merged, changes: changes,
		problems: res.Problems, unmapped: res.Unmapped}, nil
}
