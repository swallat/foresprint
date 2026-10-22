package app

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/swallat/foresprint/internal/excel"
	"github.com/swallat/foresprint/internal/i18n"
	"github.com/swallat/foresprint/internal/products"
	"github.com/swallat/foresprint/internal/report"
	"github.com/swallat/foresprint/internal/storage"
	"github.com/swallat/foresprint/internal/textfmt"
	"github.com/swallat/foresprint/internal/yamlx"
)

const (
	// reportHistory is the number of completed sprints in the Markdown report.
	reportHistory = 8
	// productsHistory is the number of completed sprints in "Products over time".
	productsHistory = 4
	// importPreviewLimit is the number of changes the preview lists.
	importPreviewLimit = 200
)

// ForecastProducts returns the product table over the last completed and the coming sprints.
func (a *API) ForecastProducts(team string) (ProductsOverTime, error) {
	_, fc, err := a.forecastOf(team)
	if err != nil {
		return ProductsOverTime{}, err
	}
	out := ProductsOverTime{Sprints: []string{}, Lines: []ProductLine{}}
	if !fc.Data.Team.Features.Products || len(fc.Data.Products) < 2 {
		return out, nil
	}
	out.Enabled = true
	entries := append(fc.HistoryLast(productsHistory), fc.Upcoming()...)
	byProduct := map[string]*ProductLine{}
	var order []string
	lineOf := func(id, name string) *ProductLine {
		line := byProduct[id]
		if line == nil {
			line = &ProductLine{ID: id, Name: name, Cells: make([]ProductCell, len(entries))}
			byProduct[id] = line
			order = append(order, id)
		}
		return line
	}
	for _, p := range fc.Data.Products {
		lineOf(p.ID, p.Name)
	}
	for i, e := range entries {
		out.Sprints = append(out.Sprints, e.Sprint.ID)
		if cur := fc.Current(); cur != nil && cur.Sprint.ID == e.Sprint.ID {
			out.Current = e.Sprint.ID
		}
		for _, r := range products.Distribute(fc, e).Rows {
			// A value for a product that is not in the list stays visible (as in the report).
			lineOf(r.Product.ID, r.Product.Name).Cells[i] = ProductCell{Standard: r.Standard, Preplanned: r.Preplanned, Planned: r.Planned, Done: r.Done}
		}
	}
	for _, b := range products.BalanceOf(fc, fc.HistoryLast(productsHistory)) {
		if line := byProduct[b.Product.ID]; line != nil {
			line.Sprints, line.Standard, line.Done, line.Difference, line.Missing = b.Sprints, b.Standard, b.Done, b.Difference(), b.Missing
		}
	}
	for _, id := range order {
		out.Lines = append(out.Lines, *byProduct[id])
	}
	return out, nil
}

// ForecastReport returns the Markdown report of the team's forecast.
func (a *API) ForecastReport(team string) (string, error) {
	_, fc, err := a.forecastOf(team)
	if err != nil {
		return "", err
	}
	return report.Render(fc, reportHistory)
}

// ForecastSave writes the report ("markdown") or the workbook ("excel") into a folder the user
// picks and returns the file.
func (a *API) ForecastSave(team, kind string) (ReportFile, error) {
	_, fc, err := a.forecastOf(team)
	if err != nil {
		return ReportFile{}, err
	}
	var content []byte
	var name string
	switch kind {
	case "markdown":
		text, err := report.Render(fc, reportHistory)
		if err != nil {
			return ReportFile{}, err
		}
		content, name = []byte(text), team+"-forecast.md"
	case "excel":
		if content, err = excel.Build(fc); err != nil {
			return ReportFile{}, err
		}
		name = team + "-forecast.xlsx"
	default:
		return ReportFile{}, errors.New(i18n.T("Unknown export format."))
	}
	if a.ChooseFolder == nil {
		return ReportFile{}, errors.New(i18n.T("No folder dialog in this build."))
	}
	dir, err := a.ChooseFolder(i18n.T("Choose the folder for the export"))
	if err != nil {
		return ReportFile{}, err
	}
	if dir == "" {
		return ReportFile{Cancelled: true}, nil
	}
	path := reportFreeName(dir, name)
	if err := os.WriteFile(path, content, 0o644); err != nil {
		return ReportFile{}, err
	}
	return ReportFile{Path: path}, nil
}

// freeName is the path of name in dir; if the file exists, "name (2).ext" and so on, so that an
// export never replaces a file.
func reportFreeName(dir, name string) string {
	ext := filepath.Ext(name)
	base := strings.TrimSuffix(name, ext)
	path := filepath.Join(dir, name)
	for n := 2; ; n++ {
		if _, err := os.Lstat(path); err != nil {
			return path
		}
		path = filepath.Join(dir, fmt.Sprintf("%s (%d)%s", base, n, ext))
	}
}

// ExcelImportPreview lets the user pick a workbook and lists what importing it would change.
// Nothing is written.
func (a *API) ExcelImportPreview(team string) (ImportPreview, error) {
	if a.ChooseFile == nil {
		return ImportPreview{}, errors.New(i18n.T("No file dialog in this build."))
	}
	path, err := a.ChooseFile(i18n.T("Choose the Excel workbook"))
	if err != nil {
		return ImportPreview{}, err
	}
	if path == "" {
		return ImportPreview{Cancelled: true, Changes: []ImportChange{}, Untouched: []string{}}, nil
	}
	return a.previewImport(team, path)
}

func (a *API) previewImport(team, path string) (ImportPreview, error) {
	plan, noTeam, hash, err := a.planImport(team, path)
	if err != nil {
		return ImportPreview{}, err
	}
	out := ImportPreview{Path: path, Hash: hash, NoTeam: noTeam, Changes: []ImportChange{}, Untouched: plan.Untouched}
	if out.Untouched == nil {
		out.Untouched = []string{}
	}
	for i, c := range plan.Changes {
		if i == importPreviewLimit {
			out.More = len(plan.Changes) - importPreviewLimit
			break
		}
		out.Changes = append(out.Changes, ImportChange{
			File: textfmt.BlankControls(c.File), Path: textfmt.BlankControls(c.Path),
			Old: reportChangeText(c.Old), New: reportChangeText(c.New),
		})
	}
	return out, nil
}

func (a *API) planImport(team, path string) (*excel.ImportPlan, bool, string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, false, "", err
	}
	sum := sha256.Sum256(content)
	data, fileTeam, err := excel.ReadWorkbook(content, team)
	if err != nil {
		return nil, false, "", err
	}
	plan, err := excel.Plan(storage.NewRepository(a.DataDir()), data, today())
	if err != nil {
		return nil, false, "", err
	}
	return plan, fileTeam == nil, hex.EncodeToString(sum[:]), nil
}

// ExcelImportApply imports the workbook again and writes the changes; it returns the written
// files. The window shows the preview first; hash is the one the preview returned, so a file
// that changed in between is refused instead of writing values nobody saw.
func (a *API) ExcelImportApply(team, path, hash string) ([]string, error) {
	plan, _, current, err := a.planImport(team, path)
	if err != nil {
		return nil, err
	}
	if current != hash {
		return nil, errors.New(i18n.T("The workbook changed since the preview. Choose it again."))
	}
	files, err := excel.Apply(storage.NewRepository(a.DataDir()), plan)
	if err != nil {
		return nil, err
	}
	storage.ClearTeamCache()
	return files, nil
}

func reportChangeText(v any) string {
	if v == nil {
		return "–"
	}
	return textfmt.BlankControls(yamlx.PyStr(v))
}
