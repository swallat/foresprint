package excel

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"io"
	"math"
	"path"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// This file reads a workbook back into the structure of scripts/golden_ext/excel.py (cells with
// value, formula, cached result and look, column widths, row heights, frozen panes, conditional
// formats, charts, defined names, custom properties). It parses the package directly so that it
// does not share code with the writer.

type pkg struct {
	t     *testing.T
	files map[string][]byte
}

func openPackage(t *testing.T, data []byte) *pkg {
	t.Helper()
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	p := &pkg{t: t, files: map[string][]byte{}}
	for _, f := range r.File {
		rc, err := f.Open()
		if err != nil {
			t.Fatal(err)
		}
		b, err := io.ReadAll(rc)
		_ = rc.Close()
		if err != nil {
			t.Fatal(err)
		}
		p.files[f.Name] = b
	}
	return p
}

func (p *pkg) read(name string, v any) {
	p.t.Helper()
	b, ok := p.files[name]
	if !ok {
		p.t.Fatalf("part %s missing", name)
	}
	if err := xml.Unmarshal(b, v); err != nil {
		p.t.Fatalf("%s: %v", name, err)
	}
}

type xmlRel struct {
	ID     string `xml:"Id,attr"`
	Type   string `xml:"Type,attr"`
	Target string `xml:"Target,attr"`
}
type xmlRels struct {
	Rels []xmlRel `xml:"Relationship"`
}

func (p *pkg) rels(name string) map[string]xmlRel {
	out := map[string]xmlRel{}
	rel := path.Join(path.Dir(name), "_rels", path.Base(name)+".rels")
	if _, ok := p.files[rel]; !ok {
		return out
	}
	var r xmlRels
	p.read(rel, &r)
	for _, x := range r.Rels {
		out[x.ID] = x
	}
	return out
}

// resolve turns a relationship target into a part name.
func resolve(base, target string) string {
	if strings.HasPrefix(target, "/") {
		return strings.TrimPrefix(target, "/")
	}
	return path.Clean(path.Join(path.Dir(base), target))
}

type xmlStyles struct {
	NumFmts []struct {
		ID   int    `xml:"numFmtId,attr"`
		Code string `xml:"formatCode,attr"`
	} `xml:"numFmts>numFmt"`
	Fonts []struct {
		Bold *struct{} `xml:"b"`
		Size *struct {
			Val float64 `xml:"val,attr"`
		} `xml:"sz"`
		Color *struct {
			RGB string `xml:"rgb,attr"`
		} `xml:"color"`
	} `xml:"fonts>font"`
	Fills []struct {
		Pattern struct {
			Type string `xml:"patternType,attr"`
			FG   *struct {
				RGB string `xml:"rgb,attr"`
			} `xml:"fgColor"`
		} `xml:"patternFill"`
	} `xml:"fills>fill"`
	XFs []struct {
		NumFmt int `xml:"numFmtId,attr"`
		Font   int `xml:"fontId,attr"`
		Fill   int `xml:"fillId,attr"`
		Align  *struct {
			Wrap     string `xml:"wrapText,attr"`
			Vertical string `xml:"vertical,attr"`
		} `xml:"alignment"`
	} `xml:"cellXfs>xf"`
}

var dumpFormats = map[int]string{0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 14: "mm-dd-yy"}

func rgb6(s string) any {
	if len(s) < 6 {
		return nil
	}
	return strings.ToUpper(s[len(s)-6:])
}

func (s *xmlStyles) look(index int) map[string]any {
	xf := s.XFs[index]
	nf := dumpFormats[xf.NumFmt]
	for _, n := range s.NumFmts {
		if n.ID == xf.NumFmt {
			nf = n.Code
		}
	}
	font := s.Fonts[xf.Font]
	size := 11.0
	if font.Size != nil {
		size = font.Size.Val
	}
	var color, fill any
	if font.Color != nil && font.Color.RGB != "" {
		color = rgb6(font.Color.RGB)
	}
	if f := s.Fills[xf.Fill].Pattern; f.Type == "solid" && f.FG != nil && f.FG.RGB != "" {
		fill = rgb6(f.FG.RGB)
	}
	var valign any
	wrap := false
	if xf.Align != nil {
		wrap = xf.Align.Wrap == "1" || xf.Align.Wrap == "true"
		if xf.Align.Vertical != "" {
			valign = xf.Align.Vertical
		}
	}
	return map[string]any{"nf": nf, "bold": font.Bold != nil, "size": size, "fill": fill, "color": color, "wrap": wrap, "valign": valign}
}

type xmlCell struct {
	R string  `xml:"r,attr"`
	S int     `xml:"s,attr"`
	T string  `xml:"t,attr"`
	F *string `xml:"f"`
	V *string `xml:"v"`
	I *struct {
		T string `xml:"t"`
	} `xml:"is"`
}

type xmlSheet struct {
	Cols []struct {
		Min   int     `xml:"min,attr"`
		Max   int     `xml:"max,attr"`
		Width float64 `xml:"width,attr"`
	} `xml:"cols>col"`
	Rows []struct {
		R      int       `xml:"r,attr"`
		Height float64   `xml:"ht,attr"`
		Custom string    `xml:"customHeight,attr"`
		Cells  []xmlCell `xml:"c"`
	} `xml:"sheetData>row"`
	Pane *struct {
		TopLeft string `xml:"topLeftCell,attr"`
	} `xml:"sheetViews>sheetView>pane"`
	CF []struct {
		Range string `xml:"sqref,attr"`
		Rules []struct {
			Type string `xml:"type,attr"`
		} `xml:"cfRule"`
	} `xml:"conditionalFormatting"`
	Drawing *struct {
		ID string `xml:"id,attr"`
	} `xml:"drawing"`
}

type xmlShared struct {
	Items []struct {
		T string `xml:"t"`
		R []struct {
			T string `xml:"t"`
		} `xml:"r"`
	} `xml:"si"`
}

type xmlWorkbook struct {
	Sheets []struct {
		Name string `xml:"name,attr"`
		ID   string `xml:"id,attr"`
	} `xml:"sheets>sheet"`
	Names []struct {
		Name string `xml:"name,attr"`
		Ref  string `xml:",chardata"`
	} `xml:"definedNames>definedName"`
}

// dumpWorkbook is the structure of the Python reference.
func dumpWorkbook(t *testing.T, data []byte) map[string]any {
	t.Helper()
	p := openPackage(t, data)
	var styles xmlStyles
	p.read("xl/styles.xml", &styles)
	var shared xmlShared
	if _, ok := p.files["xl/sharedStrings.xml"]; ok {
		p.read("xl/sharedStrings.xml", &shared)
	}
	sharedText := func(i int) string {
		it := shared.Items[i]
		if len(it.R) == 0 {
			return it.T
		}
		var b strings.Builder
		for _, r := range it.R {
			b.WriteString(r.T)
		}
		return b.String()
	}
	var wb xmlWorkbook
	p.read("xl/workbook.xml", &wb)
	wbRels := p.rels("xl/workbook.xml")

	plain := map[string]any{"nf": "General", "bold": false, "size": 11.0, "fill": nil, "color": nil, "wrap": false, "valign": nil}
	var sheets []any
	for _, s := range wb.Sheets {
		part := resolve("xl/workbook.xml", wbRels[s.ID].Target)
		var sh xmlSheet
		p.read(part, &sh)
		widths := map[string]any{}
		for _, c := range sh.Cols {
			for i := c.Min; i <= c.Max; i++ {
				widths[strconv.Itoa(i)] = math.Round(c.Width*1e4) / 1e4
			}
		}
		heights := map[string]any{}
		cells := map[string]any{}
		for _, row := range sh.Rows {
			if row.Custom == "1" || row.Custom == "true" {
				heights[strconv.Itoa(row.R)] = row.Height
			}
			for _, c := range row.Cells {
				entry := styles.look(c.S)
				var value any
				switch {
				case c.F != nil:
					cached := ""
					if c.V != nil {
						cached = *c.V
					}
					entry["f"] = *c.F
					switch c.T {
					case "str":
						entry["c"], entry["ct"] = cached, "s"
					case "b":
						entry["c"], entry["ct"] = cached == "1", "b"
					case "e":
						entry["c"], entry["ct"] = cached, "e"
					default:
						f, err := strconv.ParseFloat(cached, 64)
						if err != nil {
							t.Fatalf("%s %s: cached %q", s.Name, c.R, cached)
						}
						entry["c"], entry["ct"] = f, "n"
					}
					value = true
				case c.V != nil || c.I != nil:
					switch c.T {
					case "s":
						i, _ := strconv.Atoi(*c.V)
						entry["v"], entry["t"] = sharedText(i), "s"
					case "inlineStr":
						entry["v"], entry["t"] = c.I.T, "s"
					case "str":
						entry["v"], entry["t"] = *c.V, "s"
					case "b":
						entry["v"], entry["t"] = *c.V == "1", "b"
					default:
						f, err := strconv.ParseFloat(*c.V, 64)
						if err != nil {
							t.Fatalf("%s %s: value %q", s.Name, c.R, *c.V)
						}
						entry["v"], entry["t"] = f, "n"
					}
					value = true
				}
				if value == nil {
					same := true
					for k, v := range plain {
						if entry[k] != v {
							same = false
						}
					}
					if same {
						continue
					}
				}
				cells[c.R] = entry
			}
		}
		var freeze any
		if sh.Pane != nil {
			freeze = sh.Pane.TopLeft
		}
		cond := []any{}
		for _, cf := range sh.CF {
			for _, r := range cf.Rules {
				cond = append(cond, map[string]any{"range": cf.Range, "type": r.Type})
			}
		}
		charts := []any{}
		if sh.Drawing != nil {
			charts = dumpCharts(t, p, part, sh.Drawing.ID)
		}
		sheets = append(sheets, map[string]any{
			"name": s.Name, "freeze": freeze, "widths": widths, "heights": heights,
			"conditional": cond, "charts": charts, "cells": cells,
		})
	}
	names := map[string]any{}
	for _, n := range wb.Names {
		names[n.Name] = n.Ref
	}
	props := map[string]any{}
	if _, ok := p.files["docProps/custom.xml"]; ok {
		var custom struct {
			Props []struct {
				Name string `xml:"name,attr"`
				Str  string `xml:"lpwstr"`
			} `xml:"property"`
		}
		p.read("docProps/custom.xml", &custom)
		for _, pr := range custom.Props {
			props[pr.Name] = pr.Str
		}
	}
	return map[string]any{"sheets": sheets, "names": names, "props": props,
		"full_calc": regexp.MustCompile(`<calcPr[^>]*fullCalcOnLoad="(1|true)"`).Match(p.files["xl/workbook.xml"])}
}

func dumpCharts(t *testing.T, p *pkg, sheetPart, drawingRel string) []any {
	t.Helper()
	rel := p.rels(sheetPart)[drawingRel]
	drawing := resolve(sheetPart, rel.Target)
	dRels := p.rels(drawing)
	var doc struct {
		Anchors []struct {
			From struct {
				Col int `xml:"col"`
				Row int `xml:"row"`
			} `xml:"from"`
			To struct {
				Col int `xml:"col"`
				Row int `xml:"row"`
			} `xml:"to"`
			Chart *struct {
				ID string `xml:"id,attr"`
			} `xml:"graphicFrame>graphic>graphicData>chart"`
		} `xml:",any"`
	}
	p.read(drawing, &doc)
	type text struct {
		T []string `xml:"p>r>t"`
	}
	type title struct {
		Rich text `xml:"tx>rich"`
	}
	type ser struct {
		Name string `xml:"tx>strRef>f"`
		Cat  string `xml:"cat>numRef>f"`
		CatS string `xml:"cat>strRef>f"`
		Val  string `xml:"val>numRef>f"`
	}
	var out []any
	for _, a := range doc.Anchors {
		if a.Chart == nil {
			continue
		}
		var ch struct {
			Title  *title  `xml:"chart>title"`
			Series []ser   `xml:"chart>plotArea>lineChart>ser"`
			CatAx  []title `xml:"chart>plotArea>catAx>title"`
			ValAx  []title `xml:"chart>plotArea>valAx>title"`
			Legend struct {
				Pos struct {
					Val string `xml:"val,attr"`
				} `xml:"legendPos"`
			} `xml:"chart>legend"`
			Blanks *struct {
				Val string `xml:"val,attr"`
			} `xml:"chart>dispBlanksAs"`
		}
		chartPart := resolve(drawing, dRels[a.Chart.ID].Target)
		p.read(chartPart, &ch)
		join := func(t *title) string {
			if t == nil {
				return ""
			}
			return strings.Join(t.Rich.T, "")
		}
		var series []any
		for _, s := range ch.Series {
			cat := s.Cat
			if cat == "" {
				cat = s.CatS
			}
			series = append(series, map[string]any{"name": s.Name, "categories": cat, "values": s.Val})
		}
		axes := []any{}
		for _, ax := range append(ch.CatAx, ch.ValAx...) {
			ax := ax
			axes = append(axes, join(&ax))
		}
		blanks := "gap"
		if ch.Blanks != nil {
			blanks = ch.Blanks.Val
		}
		out = append(out, map[string]any{
			"title": join(ch.Title), "series": series, "axes": axes,
			"from": []any{a.From.Col, a.From.Row}, "to": []any{a.To.Col, a.To.Row},
			"legend": ch.Legend.Pos.Val, "blanks": blanks, "na_blank": strings.Contains(string(p.files[chartPart]), "dispNaAsBlank"),
		})
	}
	return out
}
