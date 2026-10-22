package storage

// Reason is the cause of a file error as a sentence start ("Permission denied"), for messages
// that other packages build around a failed file operation.
func Reason(err error) string { return reason(err) }

// NotReadable is the failure to read a file, with the advice to check the permissions.
func NotReadable(path string, err error) error { return notReadable(path, err) }
