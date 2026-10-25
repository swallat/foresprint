package shortcut

import (
	"bytes"
	"encoding/binary"
	"image"
	"image/color"
	"image/png"
	"math"
)

// The logo is drawn in code (no image files to ship): an indigo rounded square with a violet
// diagonal and a timeline of sprints: two solid blocks, then a dashed mint block for the
// forecast. The geometry is that of docs/assets/logo.svg on a 64 x 64 grid.
var (
	indigo = [3]float64{91, 91, 240}
	violet = [3]float64{162, 77, 240}
	white  = [3]float64{255, 255, 255}
	mint   = [3]float64{23, 195, 160}
)

type box struct{ x0, y0, x1, y1 float64 }

var (
	doneBlocks = []box{{6, 24, 20, 40}, {23, 24, 37, 40}}
	nextBlock  = box{40, 24, 54, 40}
	stub       = box{54, 30.5, 60, 33.5}
)

const (
	blockRadius = 3.0
	outline     = 2.5
	dash, gap   = 4.0, 2.0
	phase       = 4.0
	// IconSize is the edge length of the logo image.
	IconSize = 256
)

func band() [3]float64 {
	var out [3]float64
	for i := range out {
		out[i] = math.Round(violet[i]*0.85 + indigo[i]*0.15)
	}
	return out
}

func insideRounded(x, y, size, radius float64) bool {
	cx := math.Min(math.Max(x, radius), size-radius)
	cy := math.Min(math.Max(y, radius), size-radius)
	return (x-cx)*(x-cx)+(y-cy)*(y-cy) <= radius*radius
}

func inBlock(g, h float64, b box, inset float64) bool {
	x0, y0, x1, y1 := b.x0+inset, b.y0+inset, b.x1-inset, b.y1-inset
	if g < x0 || g > x1 || h < y0 || h > y1 {
		return false
	}
	r := math.Max(blockRadius-inset, 0)
	cx := math.Min(math.Max(g, x0+r), x1-r)
	cy := math.Min(math.Max(h, y0+r), y1-r)
	return (g-cx)*(g-cx)+(h-cy)*(h-cy) <= r*r
}

// alongOutline is the distance along the outline of b (clockwise from the top left) of the
// point nearest to (g, h).
func alongOutline(g, h float64, b box) float64 {
	w, ht := b.x1-b.x0, b.y1-b.y0
	top, right, bottom, left := h-b.y0, b.x1-g, b.y1-h, g-b.x0
	side, best := "top", top
	for _, c := range []struct {
		name string
		d    float64
	}{{"right", right}, {"bottom", bottom}, {"left", left}} {
		if c.d < best {
			side, best = c.name, c.d
		}
	}
	switch side {
	case "top":
		return g - b.x0
	case "right":
		return w + (h - b.y0)
	case "bottom":
		return w + ht + (b.x1 - g)
	}
	return 2*w + ht + (b.y1 - h)
}

// pixel is the colour (RGBA, alpha 0 or 255) at (x, y) of an image with edge length s.
func pixel(x, y, s float64) (c [3]float64, a float64) {
	if !insideRounded(x, y, s, s*0.2) {
		return c, 0
	}
	g, h := x/s*64, y/s*64
	for _, b := range doneBlocks {
		if inBlock(g, h, b, 0) {
			return white, 255
		}
	}
	if inBlock(g, h, nextBlock, 0) && !inBlock(g, h, nextBlock, outline) &&
		math.Mod(alongOutline(g, h, nextBlock)+phase, dash+gap) < dash {
		return mint, 255
	}
	if g >= stub.x0 && g <= stub.x1 && h >= stub.y0 && h <= stub.y1 {
		return mint, 255
	}
	if g+h >= 74 {
		return band(), 255
	}
	return indigo, 255
}

// PNG is the logo as a PNG of the given edge length (2 x 2 supersampling for smooth edges).
func PNG(size int) []byte {
	img := image.NewNRGBA(image.Rect(0, 0, size, size))
	offsets := []float64{0.25, 0.75}
	for py := range size {
		for px := range size {
			var sum [3]float64
			var alpha float64
			for _, oy := range offsets {
				for _, ox := range offsets {
					c, a := pixel(float64(px)+ox, float64(py)+oy, float64(size))
					for i := range sum {
						sum[i] += c[i] * a
					}
					alpha += a
				}
			}
			if alpha > 0 {
				img.SetNRGBA(px, py, color.NRGBA{
					R: uint8(sum[0] / alpha), G: uint8(sum[1] / alpha), B: uint8(sum[2] / alpha), A: uint8(alpha / 4),
				})
			}
		}
	}
	var b bytes.Buffer
	if err := png.Encode(&b, img); err != nil {
		panic("shortcut: " + err.Error()) // encoding into memory does not fail
	}
	return b.Bytes()
}

// ICO wraps a 256 x 256 PNG as a Windows icon (allowed since Windows Vista).
func ICO(image []byte) []byte {
	var b bytes.Buffer
	_ = binary.Write(&b, binary.LittleEndian, [3]uint16{0, 1, 1})
	b.Write([]byte{0, 0, 0, 0}) // 256 x 256 is written as 0, no palette, reserved
	_ = binary.Write(&b, binary.LittleEndian, [2]uint16{1, 32})
	_ = binary.Write(&b, binary.LittleEndian, [2]uint32{uint32(len(image)), 22})
	b.Write(image)
	return b.Bytes()
}

// ICNS wraps a 256 x 256 PNG as a macOS icon (type ic08).
func ICNS(image []byte) []byte {
	var b bytes.Buffer
	b.WriteString("icns")
	_ = binary.Write(&b, binary.BigEndian, uint32(len(image)+16))
	b.WriteString("ic08")
	_ = binary.Write(&b, binary.BigEndian, uint32(len(image)+8))
	b.Write(image)
	return b.Bytes()
}
