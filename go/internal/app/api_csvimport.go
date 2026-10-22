package app

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/model"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/workpackages"
)

func isCSV(path string) bool {
	return strings.EqualFold(filepath.Ext(path), ".csv")
}

// packageImport is a CSV table read against the work packages of a team.
type packageImport struct {
	data    *storage.TeamData
	merged  []model.Ticket
	changes []workpackages.Change
	result  workpackages.Result
	hash    string
}

// planPackages reads the CSV table and merges it with the work packages of the team. Only a
// team that keeps its work packages in Foresprint takes a table; a tracker team gets its tickets
// from the tracker.
func (a *API) planPackages(team, path string) (*packageImport, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(raw)
	data, err := storage.NewRepository(a.DataDir()).Load(team)
	if err != nil {
		return nil, err
	}
	if data.Team.Source() == model.SourceNone {
		return nil, errors.New(i18n.T("The tickets are switched off for this team."))
	}
	if data.Team.Source() != model.SourcePackages {
		return nil, errors.New(i18n.T("This team gets its tickets from a tracker. A CSV table can only be imported as work packages."))
	}
	rows, err := workpackages.ReadCSV(raw)
	if err != nil {
		return nil, err
	}
	res := workpackages.ParseTable(rows, workpackages.Options{Tracker: data.Team.Tracker, Existing: data.Tickets})
	merged, changes := workpackages.Merge(data.Tickets, res.Packages)
	return &packageImport{data: data, merged: merged, changes: changes, result: res, hash: hex.EncodeToString(sum[:])}, nil
}

func (a *API) previewPackages(team, path string) (ImportPreview, error) {
	plan, err := a.planPackages(team, path)
	if err != nil {
		return ImportPreview{}, err
	}
	old := map[string]model.Ticket{}
	for _, t := range plan.data.Tickets {
		old[t.Key] = t
	}
	out := ImportPreview{Kind: "packages", Path: path, Hash: plan.hash, Changes: []ImportChange{}, Untouched: []string{}, Problems: []string{}, Unmapped: []string{}}
	file := storage.TicketFileName(plan.data.Team)
	for i, c := range plan.changes {
		if i == importPreviewLimit {
			out.More = len(plan.changes) - importPreviewLimit
			break
		}
		before := "–"
		if o, ok := old[c.Package.Key]; ok && c.Update {
			before = textfmt.BlankControls(o.Title)
		}
		out.Changes = append(out.Changes, ImportChange{
			File: file, Path: textfmt.BlankControls(c.Package.Key), Old: before, New: textfmt.BlankControls(c.Package.Title),
		})
	}
	for _, p := range plan.result.Problems {
		out.Problems = append(out.Problems, i18n.T("Row {row}: {msg}", "row", p.Row, "msg", textfmt.BlankControls(p.Msg)))
	}
	for _, u := range plan.result.Unmapped {
		out.Unmapped = append(out.Unmapped, textfmt.BlankControls(u))
	}
	return out, nil
}

func (a *API) applyPackages(team, path, hash string) ([]string, error) {
	plan, err := a.planPackages(team, path)
	if err != nil {
		return nil, err
	}
	if plan.hash != hash {
		return nil, errors.New(i18n.T("The file changed since the preview. Choose it again."))
	}
	if len(plan.changes) == 0 {
		return []string{}, nil
	}
	written, err := storage.NewRepository(a.DataDir()).SavePackages(team, storage.TicketsFile{
		Tickets: plan.merged, Imported: plan.data.TicketsImported, Source: plan.data.TicketsSource,
	})
	if err != nil {
		return nil, err
	}
	storage.ClearTeamCache()
	return []string{filepath.Base(written)}, nil
}
