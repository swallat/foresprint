package gitsync

import (
	"context"
	"github.com/swallat/foresprint/internal/yamlx"
	"sync"
	"time"
)

// Codec reads and writes the YAML files of a data folder as value trees (see package yamlmerge).
// The storage layer provides it; it must write the bytes the Python core writes.
type Codec interface {
	// Parse reads one file. An empty document gives nil.
	Parse(text string) (any, error)
	// Dump writes a tree the way all files are written (merging and saving write the same).
	Dump(tree any) (string, error)
}

// Issue is one error of the data check: the area it belongs to, where, and the message.
type Issue struct {
	Key     string
	Where   string
	Message string
}

// Validator runs the full data check on a data folder and returns the issues of level error.
type Validator func(ctx context.Context, dir string, today time.Time) ([]Issue, error)

var (
	hookMu    sync.RWMutex
	codec     Codec
	validator Validator
)

// YAMLCodec reads and writes the data files exactly as the core does (package yamlx). It is the
// codec in use unless SetCodec sets another one (tests do).
type YAMLCodec struct{}

// Parse reads one file; an empty document gives nil.
func (YAMLCodec) Parse(text string) (any, error) { return yamlx.Load(text) }

// Dump writes a tree the way all files are written.
func (YAMLCodec) Dump(tree any) (string, error) { return yamlx.Dump(tree) }

// SetCodec sets the YAML codec used to merge files at key level (default: YAMLCodec).
func SetCodec(c Codec) {
	hookMu.Lock()
	codec = c
	hookMu.Unlock()
}

// SetValidator sets the data check that runs after a merge (new errors prevent the upload).
// Without one, no check runs.
func SetValidator(v Validator) {
	hookMu.Lock()
	validator = v
	hookMu.Unlock()
}

func currentCodec() Codec {
	hookMu.RLock()
	defer hookMu.RUnlock()
	if codec == nil {
		return YAMLCodec{}
	}
	return codec
}

func currentValidator() Validator {
	hookMu.RLock()
	defer hookMu.RUnlock()
	return validator
}
