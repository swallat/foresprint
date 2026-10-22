package sources

import (
	"errors"
	"net/http"
	"os"

	"github.com/zalando/go-keyring"
)

// The Jira token comes from the environment variable FORESPRINT_JIRA_TOKEN or from the keychain
// of the operating system (entry per Jira host).
const (
	TokenEnv             = "FORESPRINT_JIRA_TOKEN"
	KeyringService       = "foresprint-jira"
	legacyKeyringService = "sprintforecast-jira" // tokens stored before the rename
)

// KeychainUser is the user name of the keychain entry: the host of the Jira address (the entry
// is per host, not per path or account).
func KeychainUser(baseURL string) (string, error) {
	host := hostOf(pyStrip(baseURL))
	if host == "" {
		return "", invalidBaseURLError()
	}
	return host, nil
}

// JiraToken is the personal access token: FORESPRINT_JIRA_TOKEN first, then the keychain entry
// of this Jira host. It is empty when there is none.
func JiraToken(baseURL string) string {
	if value := pyStrip(os.Getenv(TokenEnv)); value != "" {
		return value
	}
	if baseURL == "" {
		return ""
	}
	user, err := KeychainUser(baseURL)
	if err != nil {
		return ""
	}
	for _, service := range []string{KeyringService, legacyKeyringService} {
		if stored, err := keyring.Get(service, user); err == nil && pyStrip(stored) != "" {
			return pyStrip(stored)
		}
	}
	return ""
}

// KeychainUsable says whether the operating system has a keychain that can hold a token (not the
// case on a headless Linux without a Secret Service).
func KeychainUsable() bool {
	_, err := keyring.Get(KeyringService, "foresprint-probe")
	return err == nil || errors.Is(err, keyring.ErrNotFound)
}

// StoredTokenExists says whether there is a keychain entry for the host of baseURL. It never
// returns the token.
func StoredTokenExists(baseURL string) bool {
	if baseURL == "" {
		return false
	}
	user, err := KeychainUser(baseURL)
	if err != nil {
		return false
	}
	for _, service := range []string{KeyringService, legacyKeyringService} {
		if stored, err := keyring.Get(service, user); err == nil && stored != "" {
			return true
		}
	}
	return false
}

// StoreToken writes the token to the keychain (user = host of baseURL).
func StoreToken(baseURL, token string) error {
	if err := checkToken(token); err != nil {
		return err
	}
	user, err := KeychainUser(baseURL)
	if err != nil {
		return err
	}
	// The error of the backend could contain anything: it is not shown.
	if keyring.Set(KeyringService, user, token) != nil {
		return errorf("The keychain did not accept the token (no keychain service available?). "+
			"Alternatively set the environment variable {variable}.", "variable", TokenEnv)
	}
	_ = keyring.Delete(legacyKeyringService, user) // the old entry would be stale
	return nil
}

// DeleteToken removes the keychain entry of the host of baseURL (no error if there is none).
func DeleteToken(baseURL string) error {
	user, err := KeychainUser(baseURL)
	if err != nil {
		return err
	}
	for _, service := range []string{KeyringService, legacyKeyringService} {
		_ = keyring.Delete(service, user) // "no entry" is fine
	}
	if StoredTokenExists(baseURL) { // a locked or denied keychain must not look like success
		return errorf("The keychain did not remove the token.")
	}
	return nil
}

// MissingTokenError is the error for a Jira source without a token.
func MissingTokenError() *Error {
	return errorf("No Jira token found. Set the environment variable {variable} or store the "+
		"token in the keychain with “foresprint tickets TEAM --set-token” (Jira: "+
		"profile > Personal Access Tokens).", "variable", TokenEnv)
}

// Open returns the source for these tracker settings. A path is a CSV export (also when the
// tracker is Jira: the offline fallback); without one, Settings.Kind decides. Jira needs a token
// (the argument, else the environment or the keychain); a transport replaces the network (tests).
func Open(settings Settings, path, token string, transport http.RoundTripper) (Source, error) {
	if path != "" {
		return NewCSVSource(path, settings.Fields, settings.RuleFields), nil
	}
	switch settings.Kind {
	case "jira":
		if token == "" {
			token = JiraToken(settings.BaseURL)
		}
		if token == "" {
			return nil, MissingTokenError()
		}
		return NewJiraSource(settings, token, transport)
	case "csv":
		return nil, errorf("The source “csv” needs a file: --import FILE")
	}
	return nil, errorf("Unknown ticket source “{kind}” (tracker.kind)", "kind", settings.Kind)
}
