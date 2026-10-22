//go:build !windows

package main

import "fmt"

// Only the Windows release runs without a console; here the standard streams are enough.

func reportStart([]string) {}

func reportFailure(what string, err error) { fmt.Printf("%s: %v\n", what, err) }
