// Package pyrand reproduces the random number generator of Python's "random" module.
//
// The Monte Carlo simulation of the forecast draws with random.Random(seed).choice(...). The
// Go core has to draw the same numbers for the same seed, so this package implements the
// Mersenne Twister (MT19937) exactly as CPython seeds and reads it: init_by_array seeding from
// an integer, random(), getrandbits(k) and the rejection sampling of _randbelow().
//
// Only what the core needs is here. Seeds are integers (Python hashes strings and other types;
// that part is not reproduced).
package pyrand

import (
	"math/big"
	"math/bits"
)

const (
	stateSize = 624
	period    = 397
	matrixA   = 0x9908b0df
	upperMask = 0x80000000
	lowerMask = 0x7fffffff
)

// Random is the equivalent of random.Random. The zero value is not usable; create one with
// New or NewBig.
type Random struct {
	mt    [stateSize]uint32
	index int
}

// New returns a generator seeded like random.Random(seed). Python uses the absolute value of
// an integer seed.
func New(seed int64) *Random {
	n := new(big.Int).SetInt64(seed)
	return NewBig(n)
}

// NewBig is New for seeds beyond 64 bits.
func NewBig(seed *big.Int) *Random {
	r := &Random{}
	r.seedArray(keyOf(seed))
	return r
}

// keyOf splits |seed| into 32-bit words, least significant first, as CPython's random_seed
// does. Zero gives the single word 0.
func keyOf(seed *big.Int) []uint32 {
	abs := new(big.Int).Abs(seed)
	if abs.Sign() == 0 {
		return []uint32{0}
	}
	var key []uint32
	mask := big.NewInt(0xffffffff)
	word := new(big.Int)
	for abs.Sign() > 0 {
		key = append(key, uint32(word.And(abs, mask).Uint64()))
		abs.Rsh(abs, 32)
	}
	return key
}

func (r *Random) seedInt(s uint32) {
	r.mt[0] = s
	for i := 1; i < stateSize; i++ {
		r.mt[i] = 1812433253*(r.mt[i-1]^(r.mt[i-1]>>30)) + uint32(i)
	}
	r.index = stateSize
}

func (r *Random) seedArray(key []uint32) {
	r.seedInt(19650218)
	i, j := 1, 0
	k := stateSize
	if len(key) > k {
		k = len(key)
	}
	for ; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1664525)) + key[j] + uint32(j)
		i++
		j++
		if i >= stateSize {
			r.mt[0] = r.mt[stateSize-1]
			i = 1
		}
		if j >= len(key) {
			j = 0
		}
	}
	for k = stateSize - 1; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1566083941)) - uint32(i)
		i++
		if i >= stateSize {
			r.mt[0] = r.mt[stateSize-1]
			i = 1
		}
	}
	r.mt[0] = 0x80000000
	r.index = stateSize
}

func (r *Random) twist() {
	mag := [2]uint32{0, matrixA}
	var y uint32
	kk := 0
	for ; kk < stateSize-period; kk++ {
		y = (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
		r.mt[kk] = r.mt[kk+period] ^ (y >> 1) ^ mag[y&1]
	}
	for ; kk < stateSize-1; kk++ {
		y = (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
		r.mt[kk] = r.mt[kk+(period-stateSize)] ^ (y >> 1) ^ mag[y&1]
	}
	y = (r.mt[stateSize-1] & upperMask) | (r.mt[0] & lowerMask)
	r.mt[stateSize-1] = r.mt[period-1] ^ (y >> 1) ^ mag[y&1]
	r.index = 0
}

// Uint32 returns the next raw 32-bit output (genrand_uint32).
func (r *Random) Uint32() uint32 {
	if r.index >= stateSize {
		r.twist()
	}
	y := r.mt[r.index]
	r.index++
	y ^= y >> 11
	y ^= (y << 7) & 0x9d2c5680
	y ^= (y << 15) & 0xefc60000
	y ^= y >> 18
	return y
}

// Float64 is random.random(): a float in [0, 1) with 53 bits.
func (r *Random) Float64() float64 {
	a := r.Uint32() >> 5
	b := r.Uint32() >> 6
	return (float64(a)*67108864.0 + float64(b)) * (1.0 / 9007199254740992.0)
}

// GetRandBits is random.getrandbits(k) for k up to 64. It panics for k outside 1..64, like
// Python raises for k < 0; use GetRandBitsBig for wider values.
func (r *Random) GetRandBits(k int) uint64 {
	if k < 1 || k > 64 {
		panic("pyrand: GetRandBits needs 1 <= k <= 64")
	}
	if k <= 32 {
		return uint64(r.Uint32() >> (32 - k))
	}
	// Python fills 32-bit words from the least significant end; the last word is shifted down.
	low := uint64(r.Uint32())
	high := uint64(r.Uint32() >> (64 - k))
	return low | high<<32
}

// GetRandBitsBig is random.getrandbits(k) for any k >= 1.
func (r *Random) GetRandBitsBig(k int) *big.Int {
	if k < 1 {
		panic("pyrand: GetRandBitsBig needs k >= 1")
	}
	words := (k-1)/32 + 1
	out := new(big.Int)
	for i := 0; i < words; i++ {
		w := r.Uint32()
		if k < 32 {
			w >>= uint(32 - k)
		}
		out.Or(out, new(big.Int).Lsh(new(big.Int).SetUint64(uint64(w)), uint(32*i)))
		k -= 32
	}
	return out
}

// RandBelow is random.Random._randbelow(n): a uniform integer in [0, n) by rejection sampling
// on getrandbits(bit_length(n)). It returns 0 for n == 0.
func (r *Random) RandBelow(n uint64) uint64 {
	if n == 0 {
		return 0
	}
	k := bits.Len64(n)
	v := r.GetRandBits(k)
	for v >= n {
		v = r.GetRandBits(k)
	}
	return v
}

// Choice is the index random.choice(seq) picks in a sequence of length n; it panics for an
// empty sequence like Python raises IndexError.
func (r *Random) Choice(n int) int {
	if n <= 0 {
		panic("pyrand: Choice from an empty sequence")
	}
	return int(r.RandBelow(uint64(n)))
}
