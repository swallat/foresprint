package holidays

import (
	"sync"
	"testing"
	"time"
)

// BenchmarkFirstUse measures the cost of the first question to a country (decoding the file).
func BenchmarkFirstUse(b *testing.B) {
	for i := 0; i < b.N; i++ {
		loadOnce, loadErr, doc, archive = sync.Once{}, nil, nil, nil
		cacheMu.Lock()
		cache = map[string]*country{}
		cacheMu.Unlock()
		IsHoliday("DE", "NW", time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC))
	}
}
