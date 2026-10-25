package pyrand_test

import (
	"math/big"
	"strconv"
	"testing"

	"github.com/swallat/foresprint/internal/golden"
	"github.com/swallat/foresprint/internal/pyrand"
)

type stream struct {
	Seed         string              `json:"seed"`
	Random       []float64           `json:"random"`
	GetRandBits  map[string][]string `json:"getrandbits"`
	RandBelow    map[string][]uint64 `json:"randbelow"`
	ChoiceValues []float64           `json:"choice_indexes"`
}

type streams struct {
	Python  string   `json:"python"`
	Streams []stream `json:"streams"`
}

func load(t *testing.T) streams {
	t.Helper()
	var s streams
	golden.Load(t, &s, "rng", "streams.json")
	if len(s.Streams) == 0 {
		t.Fatal("no streams in the reference")
	}
	return s
}

func newFor(t *testing.T, seed string) *pyrand.Random {
	t.Helper()
	n, ok := new(big.Int).SetString(seed, 10)
	if !ok {
		t.Fatalf("bad seed %q", seed)
	}
	return pyrand.NewBig(n)
}

func TestFloat64(t *testing.T) {
	for _, s := range load(t).Streams {
		r := newFor(t, s.Seed)
		for i, want := range s.Random {
			if got := r.Float64(); got != want {
				t.Fatalf("seed %s: random() #%d = %v, Python %v", s.Seed, i, got, want)
			}
		}
	}
}

func TestGetRandBits(t *testing.T) {
	for _, s := range load(t).Streams {
		for k, wants := range s.GetRandBits {
			bits, _ := strconv.Atoi(k)
			r := newFor(t, s.Seed)
			for i, want := range wants {
				got := r.GetRandBitsBig(bits).String()
				if got != want {
					t.Fatalf("seed %s: getrandbits(%d) #%d = %s, Python %s", s.Seed, bits, i, got, want)
				}
			}
			if bits <= 64 {
				r = newFor(t, s.Seed)
				for i, want := range wants {
					got := strconv.FormatUint(r.GetRandBits(bits), 10)
					if got != want {
						t.Fatalf("seed %s: GetRandBits(%d) #%d = %s, Python %s", s.Seed, bits, i, got, want)
					}
				}
			}
		}
	}
}

func TestRandBelow(t *testing.T) {
	for _, s := range load(t).Streams {
		for n, wants := range s.RandBelow {
			limit, _ := strconv.ParseUint(n, 10, 64)
			r := newFor(t, s.Seed)
			for i, want := range wants {
				if got := r.RandBelow(limit); got != want {
					t.Fatalf("seed %s: _randbelow(%d) #%d = %d, Python %d", s.Seed, limit, i, got, want)
				}
			}
		}
	}
}

func TestChoice(t *testing.T) {
	values := []float64{3.5, 1.25, 9.0, 4.75, 6.0}
	for _, s := range load(t).Streams {
		r := newFor(t, s.Seed)
		for i, want := range s.ChoiceValues {
			if got := values[r.Choice(len(values))]; got != want {
				t.Fatalf("seed %s: choice #%d = %v, Python %v", s.Seed, i, got, want)
			}
		}
	}
}

func TestSmallSeedConstructor(t *testing.T) {
	// New(seed) is NewBig for seeds that fit; the golden file has 42 and -17 among its seeds.
	for _, s := range load(t).Streams {
		seed, err := strconv.ParseInt(s.Seed, 10, 64)
		if err != nil {
			continue
		}
		r := pyrand.New(seed)
		for i, want := range s.Random[:5] {
			if got := r.Float64(); got != want {
				t.Fatalf("seed %d: random() #%d = %v, Python %v", seed, i, got, want)
			}
		}
	}
}
