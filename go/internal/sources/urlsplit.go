package sources

import (
	"errors"
	"net/netip"
	"strings"
)

// urlParts is what the sources need of Python's urllib.parse.urlsplit.
type urlParts struct {
	scheme   string
	netloc   string
	query    string
	fragment string
}

var errInvalidURL = errors.New("invalid URL")

// splitURL is urlsplit(url) for an address; the error is Python's ValueError (a malformed
// bracketed host).
func splitURL(raw string) (urlParts, error) {
	url := strings.TrimLeftFunc(raw, func(r rune) bool { return r <= ' ' })
	url = strings.NewReplacer("\t", "", "\r", "", "\n", "").Replace(url)
	var p urlParts
	if i := strings.IndexByte(url, ':'); i > 0 && isASCIIAlpha(url[0]) && isSchemeChars(url[:i]) {
		p.scheme = strings.ToLower(url[:i])
		url = url[i+1:]
	}
	if strings.HasPrefix(url, "//") {
		end := len(url)
		for _, c := range "/?#" {
			if i := strings.IndexRune(url[2:], c); i >= 0 && i+2 < end {
				end = i + 2
			}
		}
		p.netloc = url[2:end]
		url = url[end:]
		open, closed := strings.Contains(p.netloc, "["), strings.Contains(p.netloc, "]")
		if open != closed {
			return p, errInvalidURL
		}
		if open {
			_, rest, _ := strings.Cut(p.netloc, "[")
			host, _, _ := strings.Cut(rest, "]")
			if !strings.HasPrefix(host, "v") && !strings.HasPrefix(host, "V") {
				if _, err := netip.ParseAddr(host); err != nil {
					return p, errInvalidURL
				}
			}
		}
	}
	if i := strings.IndexByte(url, '#'); i >= 0 {
		p.fragment = url[i+1:]
		url = url[:i]
	}
	if i := strings.IndexByte(url, '?'); i >= 0 {
		p.query = url[i+1:]
	}
	return p, nil
}

func isASCIIAlpha(c byte) bool { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }

func isSchemeChars(s string) bool {
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !isASCIIAlpha(c) && (c < '0' || c > '9') && c != '+' && c != '-' && c != '.' {
			return false
		}
	}
	return true
}

// hostInfo returns the lower-cased host name ("" when there is none) and the port text of the
// netloc (userinfo dropped), like the properties hostname and the text behind port.
func (p urlParts) hostInfo() (host, port string) {
	info := p.netloc
	if i := strings.LastIndexByte(info, '@'); i >= 0 {
		info = info[i+1:]
	}
	if _, rest, ok := strings.Cut(info, "["); ok {
		var after string
		host, after, _ = strings.Cut(rest, "]")
		_, port, _ = strings.Cut(after, ":")
	} else {
		host, port, _ = strings.Cut(info, ":")
	}
	return strings.ToLower(host), port
}

// portValid mirrors the check of urlsplit(...).port: digits only, 0..65535.
func portValid(port string) bool {
	if port == "" {
		return true
	}
	n := 0
	for i := 0; i < len(port); i++ {
		if port[i] < '0' || port[i] > '9' {
			return false
		}
		n = n*10 + int(port[i]-'0')
		if n > 65535 {
			return false
		}
	}
	return true
}

// BaseURLProblem says why tracker.base_url is unusable, or "": "invalid" (no http/https address,
// not parseable), "credentials" (user or password in the address) or "extra" (query or
// fragment). It never returns the address.
func BaseURLProblem(raw string) string {
	p, err := splitURL(pyStrip(raw))
	if err != nil {
		return "invalid"
	}
	host, port := p.hostInfo()
	if !portValid(port) {
		return "invalid"
	}
	if (p.scheme != "http" && p.scheme != "https") || host == "" {
		return "invalid"
	}
	if strings.Contains(p.netloc, "@") {
		return "credentials"
	}
	if p.query != "" || p.fragment != "" || strings.ContainsAny(raw, "?#") {
		return "extra"
	}
	return ""
}

// hostOf is urlsplit(url).hostname, or "" (also for an address that does not parse).
func hostOf(raw string) string {
	p, err := splitURL(raw)
	if err != nil {
		return ""
	}
	host, _ := p.hostInfo()
	return host
}
