package planning_test

import (
	"math"
	"testing"

	"github.com/swallat/foresprint/internal/planning"
)

func TestSplitPlan(t *testing.T) {
	cases := []struct {
		plan, carry, share float64
		digits             int
		plannable, small   float64
		over               bool
	}{
		{30, 6, 0.8, 0, 19, 5, false}, // (30-6)*0.8 = 19.2 → 19, rest 5
		{30, 0, 0.8, 0, 24, 6, false},
		{30, 6, 0.8, 1, 19.2, 4.8, false},
		{10, 12, 0.8, 0, 0, 0, true},
		{10, 10, 0.8, 0, 0, 0, false},
		{25, 5, 1, 0, 20, 0, false},
	}
	for _, c := range cases {
		got := planning.SplitPlan(c.plan, c.carry, c.share, c.digits)
		if got.Plannable != c.plannable || got.Overbooked != c.over || diff(got.SmallStuff, c.small) {
			t.Errorf("SplitPlan(%v,%v,%v,%d) = %+v, want plannable %v small %v over %v",
				c.plan, c.carry, c.share, c.digits, got, c.plannable, c.small, c.over)
		}
	}
}

func diff(a, b float64) bool { return a-b > 1e-9 || b-a > 1e-9 }

func TestDemandAndCompare(t *testing.T) {
	items := []planning.Item{{Estimate: 10, ProductionShare: 1}, {Estimate: 8, ProductionShare: 0.5}, {Estimate: 5}, {Estimate: 4, ProductionShare: 2}}
	// 10 + 4 + 0 + 4 (share cut to 1) = 18 points at 3 points per PD = 6 PD
	demand, ok := planning.DemandOf(items, 3)
	if !ok || demand != 6 {
		t.Fatalf("demand = %v %v, want 6", demand, ok)
	}
	if _, ok := planning.DemandOf(items, 0); ok {
		t.Error("rate 0 must not give a demand")
	}
	for _, c := range []struct {
		demand, available float64
		want              planning.Status
	}{
		{6, 10, planning.StatusOK}, {8, 10, planning.StatusOK}, {8.1, 10, planning.StatusTight},
		{10, 10, planning.StatusTight}, {10.1, 10, planning.StatusOver}, {0, 0, planning.StatusOK}, {1, 0, planning.StatusOver},
	} {
		if got := planning.Compare(c.demand, c.available); got.Status != c.want {
			t.Errorf("Compare(%v,%v) = %s, want %s", c.demand, c.available, got.Status, c.want)
		}
	}
}

func TestRate(t *testing.T) {
	r := planning.Rate(2.5)
	if pd, ok := r.ToPD(10); !ok || pd != 4 {
		t.Errorf("ToPD = %v %v", pd, ok)
	}
	if pts, ok := r.ToPoints(4); !ok || pts != 10 {
		t.Errorf("ToPoints = %v %v", pts, ok)
	}
	if _, ok := planning.Rate(0).ToPD(1); ok {
		t.Error("rate 0 is invalid")
	}
}

// Hand calculation: capacity 63 PD, 18 PD of it with production access (share 2/7), plannable 9
// PD, no cap: 9 × 18/63 = 2.571 PD available. The planned tickets need 3.5 PD: 136 %, over.
func TestAvailableOfScalesThePlannableAmount(t *testing.T) {
	avail, share, ok := planning.AvailableOf(9, 18, 63, 100)
	if !ok || math.Abs(share-18.0/63) > 1e-12 || math.Abs(avail-9*18.0/63) > 1e-12 {
		t.Fatalf("available %v, share %v, ok %v", avail, share, ok)
	}
	if math.Abs(avail-2.5714285714) > 1e-9 {
		t.Errorf("available %v, want 2.57", avail)
	}
	cmp := planning.Compare(3.5, avail)
	if cmp.Status != planning.StatusOver || cmp.Load == nil || math.Abs(*cmp.Load-3.5/avail) > 1e-12 || *cmp.Load < 1.36 || *cmp.Load > 1.37 {
		t.Errorf("compare %+v", cmp)
	}
	// the cap lowers it, a share above 1 counts as 1, no capacity cannot be scaled
	if half, _, _ := planning.AvailableOf(9, 18, 63, 50); math.Abs(half-avail/2) > 1e-12 {
		t.Errorf("cap 50: %v", half)
	}
	if all, share, _ := planning.AvailableOf(9, 80, 63, 100); share != 1 || all != 9 {
		t.Errorf("share above 1: %v %v", all, share)
	}
	if _, _, ok := planning.AvailableOf(9, 18, 0, 100); ok {
		t.Error("scaled without a capacity")
	}
}
