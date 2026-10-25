//go:build !windows

package main

// Only the Windows release runs without a console; elsewhere the error is printed by cli.Execute.

func reportFailure(string, error) {}

func reportLog(string, ...any) {}

func reportBegin([]string) {}

func reportEnd([]string, int) {}
