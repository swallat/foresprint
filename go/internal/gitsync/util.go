package gitsync

import (
	"os"
	"strconv"
)

func statDir(path string) (bool, error) {
	info, err := os.Stat(path)
	if err != nil {
		return false, err
	}
	return info.IsDir(), nil
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func itoa(n int) string { return strconv.Itoa(n) }
