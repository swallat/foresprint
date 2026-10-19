# SPDX-License-Identifier: EUPL-1.2
"""Jira Data Center as a ticket source (docs/design/ticket-planning.md, section 7.1).

REST API v2, authenticated by a personal access token (``Authorization: Bearer``). Only reads
happen: every request goes through :meth:`JiraSource._request`, the one function that talks to
the network, and that function refuses anything but ``GET``. The token and the content of
responses never end up in messages, exceptions or logs; error texts say only what went wrong
and what to do.

``httpx`` (extra ``[jira]``) is imported lazily so that the core and the CSV path work without
it. The token comes from the environment variable ``SPRINTFORECAST_JIRA_TOKEN`` or, with the
optional package ``keyring``, from the operating system keychain."""

from __future__ import annotations

import difflib
import math
import os
import re
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sprintforecast import __version__
from sprintforecast.i18n import t
from sprintforecast.model import TrackerSettings, base_url_problem
from sprintforecast.sources import RawTicket, SourceError

if TYPE_CHECKING:  # pragma: no cover - typing only, httpx stays an optional import
    import httpx

TOKEN_ENV = "SPRINTFORECAST_JIRA_TOKEN"
KEYRING_SERVICE = "sprintforecast-jira"
USER_AGENT = f"sprintforecast/{__version__} (read-only Jira import)"
TIMEOUT = 30.0  # seconds, per request
PAGE_SIZE = 100

# The only HTTP method this module uses (spec section 7.1; step 5 adds one PUT for the label).
ALLOWED_METHODS = frozenset({"GET"})

# The fields Jira Software adds are found by their schema, not by their (localized) name.
SPRINT_SCHEMA = "com.pyxis.greenhopper.jira:gh-sprint"
RANK_SCHEMA = "com.pyxis.greenhopper.jira:gh-lexo-rank"
EPIC_LINK_SCHEMA = "com.pyxis.greenhopper.jira:gh-epic-link"
# Names of the issue type "Epic" (Jira returns the localized name of the standard type).
EPIC_TYPE_NAMES = ("epic", "epos")
# Fields every request asks for; the custom fields come from :class:`ResolvedFields`.
BASE_FIELDS = (
    "summary",
    "status",
    "issuetype",
    "labels",
    "components",
    "resolution",
    "issuelinks",
    "parent",
)
# The system field "parent" as value of ``tracker.fields.epic``: the parent issue is the epic.
PARENT_FIELD = "parent"
SEARCH_PATH = "/rest/api/2/search"

# The command that installs the extra: sprintforecast is not on PyPI, so it needs its address.
INSTALL_URL = "https://github.com/swallat/sprint-forecast/archive/refs/heads/main.zip"
INSTALL_COMMAND = f'uv tool install --force "sprintforecast[web,excel,jira] @ {INSTALL_URL}"'


# --- httpx, token ----------------------------------------------------------------------------


def _load_httpx() -> Any:
    """The ``httpx`` module, or a SourceError that names the extra to install."""
    try:
        import httpx
    except ImportError:
        httpx = None
    if httpx is None:
        raise SourceError(
            t(
                "Für Jira fehlt das Paket httpx. Installieren Sie das Extra [jira]: den "
                "Installer erneut ausführen oder {command} (Plugins dabei mit --with erneut "
                "angeben)",
                command=INSTALL_COMMAND,
            )
        )
    return httpx


def invalid_base_url_error() -> SourceError:
    return SourceError(
        t("tracker.base_url fehlt oder ist keine http- oder https-Adresse (team.yaml)")
    )


def keychain_user(base_url: str) -> str:
    """User name of the keychain entry: the host of the Jira address (the entry is per host,
    not per path or account)."""
    try:
        host = urlsplit(base_url.strip()).hostname
    except ValueError:
        host = None
    if not host:
        raise invalid_base_url_error()
    return host.lower()


def _keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def keyring_available() -> bool:
    """Is the optional package ``keyring`` installed?"""
    return _keyring() is not None


def jira_token(base_url: str | None = None) -> str | None:
    """The personal access token: ``SPRINTFORECAST_JIRA_TOKEN`` first, then the keychain entry
    of this Jira host (only with the optional package ``keyring``). None when there is none."""
    value = (os.environ.get(TOKEN_ENV) or "").strip()
    if value:
        return value
    keyring = _keyring()
    if keyring is None or not base_url:
        return None
    try:
        stored = keyring.get_password(KEYRING_SERVICE, keychain_user(base_url))
    except Exception:  # any backend problem simply means "no stored token"
        return None
    return (stored or "").strip() or None


def keyring_missing_error() -> SourceError:
    return SourceError(
        t(
            "Der Schlüsselbund ist nicht verfügbar: das Paket keyring fehlt (den Installer "
            "erneut ausführen oder {command} --with keyring; Plugins dabei mit --with erneut "
            "angeben). Alternativ die Umgebungsvariable {variable} setzen.",
            command=INSTALL_COMMAND,
            variable=TOKEN_ENV,
        )
    )


def store_token(base_url: str, token: str) -> None:
    """Writes the token to the keychain (user = host of ``base_url``)."""
    keyring = _keyring()
    if keyring is None:
        raise keyring_missing_error()
    _check_token(token)
    user = keychain_user(base_url)
    stored = False
    try:
        keyring.set_password(KEYRING_SERVICE, user, token)
        stored = True
    except Exception:  # the backend's message could contain anything: not shown
        pass
    if not stored:  # raised outside the except block: the backend's error is not reachable
        raise SourceError(
            t(
                "Der Schlüsselbund hat das Token nicht angenommen (kein Schlüsselbund-Dienst "
                "verfügbar?). Alternativ die Umgebungsvariable {variable} setzen.",
                variable=TOKEN_ENV,
            )
        )


def missing_token_error() -> SourceError:
    return SourceError(
        t(
            "Kein Jira-Token gefunden. Die Umgebungsvariable {variable} setzen oder das Token "
            "mit „sprintforecast tickets TEAM --set-token“ im Schlüsselbund ablegen "
            "(Jira: Profil > Persönliche Zugriffstoken).",
            variable=TOKEN_ENV,
        )
    )


def _check_token(token: str) -> str:
    """The token must be one printable word; anything else (a newline from copy and paste)
    would produce an invalid header whose error message contains the value."""
    if not token or not re.fullmatch(r"[\x21-\x7e]+", token):
        raise SourceError(
            t(
                "Das Jira-Token ist leer oder enthält Leerzeichen, Zeilenumbrüche oder "
                "Sonderzeichen – bitte erneut einfügen."
            )
        )
    return token


class _Secret:
    """Holds the token so that it cannot leak through ``repr``, ``str`` or a log record."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<token hidden>"

    __str__ = __repr__


# --- Field resolution ------------------------------------------------------------------------


@dataclass
class ResolvedFields:
    """Field ids of the instance. ``estimate``, ``remaining`` and ``epic`` come from the display
    names in ``tracker.fields``; sprint, rank and epic link from the schema of the field."""

    estimate: str | None = None
    remaining: str | None = None
    # ``customfield_…``, or ``parent`` when the configured epic field is the parent link.
    epic: str | None = None
    epic_link: tuple[str, ...] = ()
    sprint: tuple[str, ...] = ()
    rank: tuple[str, ...] = ()

    def requested(self) -> list[str]:
        """The ``fields=`` list of a search: only what is needed."""
        wanted = list(BASE_FIELDS)
        for name in (self.estimate, self.remaining, self.epic):
            if name:
                wanted.append(name)
        wanted += [*self.epic_link, *self.sprint, *self.rank]
        return list(dict.fromkeys(wanted))


def _resolve_name(name: str, fields: list[dict[str, Any]], setting: str, host: str) -> str:
    """Field id of the field with this display name (or this id). Raises for an unknown or an
    ambiguous name; the ids of the candidates are in the message."""
    wanted = name.strip().casefold()
    exact = [f for f in fields if str(f.get("name", "")).strip() == name.strip()]
    found = exact or [f for f in fields if str(f.get("name", "")).strip().casefold() == wanted]
    if not found:
        by_id = [f for f in fields if str(f.get("id", "")) == name.strip()]
        if by_id:
            return str(by_id[0]["id"])
    if len(found) == 1:
        return str(found[0]["id"])
    if found:
        raise SourceError(
            t(
                "Das Feld „{name}“ (tracker.fields.{setting}) ist in {host} mehrdeutig: {ids}. "
                "Bitte in team.yaml die Feld-ID statt des Namens eintragen.",
                name=name,
                setting=setting,
                host=host,
                ids=", ".join(sorted(str(f["id"]) for f in found)),
            )
        )
    names = [str(f.get("name", "")) for f in fields if f.get("name")]
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.6)
    raise SourceError(
        t(
            "Das Feld „{name}“ (tracker.fields.{setting}) gibt es in {host} nicht.{hint}",
            name=name,
            setting=setting,
            host=host,
            hint=(" " + t("Ähnliche Namen: {names}", names=", ".join(close))) if close else "",
        )
    )


def _ids_by_schema(fields: list[dict[str, Any]], schema: str) -> tuple[str, ...]:
    found = []
    for f in fields:
        info = f.get("schema")
        if isinstance(info, dict) and info.get("custom") == schema and f.get("id"):
            found.append(str(f["id"]))
    return tuple(sorted(found))


# --- Sprint field ----------------------------------------------------------------------------

# Keys of ``com.atlassian.greenhopper.service.sprint.Sprint@1a2b[id=12,rapidViewId=3,...]``.
# Only these are recognised as separators, so that commas and brackets in a name are harmless.
_SPRINT_KEYS = (
    "id|rapidViewId|boardId|originBoardId|state|name|goal|startDate|endDate|completeDate|"
    "activatedDate|sequence|autoStartStop"
)
_SPRINT_KEY = re.compile(rf"(?:(?<=\[)|(?<=,))({_SPRINT_KEYS})=")


@dataclass
class SprintValue:
    """One entry of the sprint field of a ticket."""

    name: str
    state: str = ""
    id: str = ""


def parse_sprint(value: Any) -> SprintValue | None:
    """A sprint entry in the Data Center ``toString`` form or as an object; None when it is
    neither or has no name."""
    if isinstance(value, dict):
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        return SprintValue(
            name.strip(), str(value.get("state") or "").upper(), str(value.get("id", ""))
        )
    if not isinstance(value, str):
        return None
    start = value.find("[")
    if start < 0 or not value.rstrip().endswith("]"):
        return None
    body = value[start : value.rstrip().rfind("]")]  # starts with "[", no closing bracket
    matches = list(_SPRINT_KEY.finditer(body))
    parts: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() - 1 if i + 1 < len(matches) else len(body)
        parts.setdefault(match.group(1), body[match.end() : end])
    name = parts.get("name", "").strip()
    if not name or name == "<null>":
        return None
    return SprintValue(name, parts.get("state", "").strip().upper(), parts.get("id", "").strip())


def choose_sprint(values: Any) -> str | None:
    """The sprint to use for a ticket: the ACTIVE one, else the first FUTURE, else the last
    listed (Jira lists the sprints of a ticket chronologically)."""
    if isinstance(values, (str, dict)):
        values = [values]
    if not isinstance(values, list):
        return None
    sprints = [s for s in (parse_sprint(v) for v in values) if s is not None]
    if not sprints:
        return None
    for state in ("ACTIVE", "FUTURE"):
        for sprint in sprints:
            if sprint.state == state:
                return sprint.name
    return sprints[-1].name


# --- The source ------------------------------------------------------------------------------


class JiraSource:
    """Tickets from a Jira Data Center query (JQL in ``tracker.query``)."""

    kind = "jira"

    def __init__(
        self,
        settings: TrackerSettings,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._httpx = _load_httpx()
        base = (settings.base_url or "").strip()
        problem = base_url_problem(base)
        if problem == "credentials":
            raise SourceError(t("tracker.base_url darf keine Zugangsdaten enthalten (team.yaml)"))
        if problem == "extra":
            raise SourceError(
                t("tracker.base_url darf keine Parameter (?…) und kein Fragment (#…) enthalten")
            )
        if problem is not None:
            raise invalid_base_url_error()
        self.settings = settings
        self.base_url = base.rstrip("/")
        self.host = urlsplit(base).hostname or ""
        self._token = _Secret(_check_token(token))
        self._transport = transport
        self._client: httpx.Client | None = None
        self._fields: ResolvedFields | None = None

    def __repr__(self) -> str:
        # also usable when __init__ failed early (a traceback may show the half-built object)
        settings = getattr(self, "settings", None)
        return (
            f"JiraSource(host={getattr(self, 'host', None)!r}, "
            f"query={getattr(settings, 'query', None)!r})"
        )

    @property
    def name(self) -> str:
        """Name of the source as stored in tickets.yaml."""
        return f"jira {self.host}"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> JiraSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- The one function that talks to the network ---

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        """Sends one request and returns the decoded JSON. Only ``GET`` is allowed; every
        failure becomes a SourceError whose text contains neither the token nor the response."""
        if method not in ALLOWED_METHODS:
            raise ValueError(f"HTTP method {method!r} is not allowed: this source only reads")
        httpx = self._httpx
        failure: str | None = None
        response = None
        if self._client is None:
            try:
                self._client = self._new_client()
            except OSError:  # includes ssl.SSLError: the CA bundle could not be loaded
                failure = t(
                    "Die Zertifikatsdatei aus SSL_CERT_FILE bzw. SSL_CERT_DIR kann nicht gelesen "
                    "werden – Umgebungsvariable und Datei prüfen."
                )
        if failure is None and self._client is not None:
            try:
                response = self._client.request(method, self.base_url + path, params=params)
            except httpx.TimeoutException:
                failure = self._timeout_text()
            except httpx.InvalidURL, httpx.UnsupportedProtocol:
                failure = t(
                    "Die Adresse {host} ist ungültig (tracker.base_url in team.yaml)",
                    host=self.host,
                )
            except httpx.ConnectError as e:
                failure = self._connect_text(e)
            except httpx.HTTPError:
                failure = t(
                    "Die Verbindung zu {host} ist fehlgeschlagen (Netzwerk, Proxy oder Firewall?)",
                    host=self.host,
                )
        if failure is not None or response is None:
            # Raised outside the except blocks: the transport error (and the request headers
            # with the token that it may reference) is neither __cause__ nor __context__.
            raise SourceError(failure or "")
        return self._decode(response, path)

    def _new_client(self) -> httpx.Client:
        return self._httpx.Client(
            headers={
                "Authorization": f"Bearer {self._token.reveal()}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
            transport=self._transport,
            follow_redirects=False,
        )

    def _timeout_text(self) -> str:
        return t(
            "Keine Antwort von {host} innerhalb von {seconds} Sekunden (Netzwerk, VPN oder "
            "Firewall?)",
            host=self.host,
            seconds=int(TIMEOUT),
        )

    def _connect_text(self, error: BaseException) -> str:
        """TLS problems are named as such; everything else is 'unreachable'."""
        chain: list[BaseException] = []
        current: BaseException | None = error
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__
        text = " ".join(str(e) for e in chain).upper()
        if any(isinstance(e, ssl.SSLCertVerificationError) for e in chain) or (
            "CERTIFICATE_VERIFY" in text
        ):
            return t(
                "Die TLS-Prüfung des Zertifikats von {host} ist fehlgeschlagen. Die Prüfung wird "
                "nie abgeschaltet. Ist das Zertifikat von einer Firmen-CA ausgestellt, deren "
                "Zertifikatsdatei in der Umgebungsvariable SSL_CERT_FILE (bzw. SSL_CERT_DIR) "
                "angeben.",
                host=self.host,
            )
        if any(isinstance(e, ssl.SSLError) for e in chain) or "SSL:" in text or "[SSL" in text:
            return t(
                "Der TLS-Verbindungsaufbau zu {host} ist fehlgeschlagen (http statt https, "
                "falscher Port oder ein Proxy, der TLS stört?). Die Prüfung wird nie "
                "abgeschaltet.",
                host=self.host,
            )
        return t(
            "{host} ist nicht erreichbar (Adresse, Netzwerk, VPN, Proxy oder Firewall prüfen)",
            host=self.host,
        )

    def _decode(self, response: httpx.Response, path: str = "") -> Any:
        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError:
                pass  # the error object holds the whole body: raise outside the except block
            raise SourceError(
                t(
                    "{host} antwortet nicht mit JSON – ist tracker.base_url die Adresse von "
                    "Jira (ohne Anmeldeseite davor)?",
                    host=self.host,
                )
            )
        if status == 401:
            raise SourceError(
                t(
                    "Jira lehnt das Token ab (401): es ist ungültig oder abgelaufen. Ein neues "
                    "Token anlegen (Jira: Profil > Persönliche Zugriffstoken)."
                )
            )
        if status == 403:
            raise SourceError(
                t(
                    "Jira verweigert den Zugriff (403): Das Konto darf diese Daten nicht lesen "
                    "oder Jira sperrt die Anmeldung vorübergehend."
                )
            )
        if status == 404:
            raise SourceError(
                t(
                    "Jira nicht gefunden unter {host} (404): tracker.base_url prüfen "
                    "(ein Kontextpfad wie /jira gehört dazu).",
                    host=self.host,
                )
            )
        if status == 400 and path == SEARCH_PATH:
            raise SourceError(self._bad_request_text(response))
        if status == 400:
            raise SourceError(
                t("Jira weist die Anfrage ab (400) – Jira-Version und tracker.base_url prüfen")
            )
        if status == 407:
            raise SourceError(
                t(
                    "Der Proxy verlangt eine Anmeldung (407) – Proxy und seine Zugangsdaten "
                    "(HTTPS_PROXY) prüfen."
                )
            )
        if status == 429:
            wait = response.headers.get("retry-after", "").strip()
            if wait.isascii() and wait.isdigit() and len(wait) <= 6:
                raise SourceError(
                    t(
                        "Jira meldet zu viele Anfragen (429) – bitte in {seconds} Sekunden "
                        "erneut versuchen",
                        seconds=int(wait),
                    )
                )
            raise SourceError(
                t("Jira meldet zu viele Anfragen (429) – bitte später erneut versuchen")
            )
        if 300 <= status < 400:
            target = urlsplit(response.headers.get("location", "")).hostname
            raise SourceError(
                t(
                    "{host} leitet um{target} – tracker.base_url auf die endgültige Adresse "
                    "ändern.",
                    host=self.host,
                    target=f" ({target})" if target else "",
                )
            )
        if status >= 500:
            raise SourceError(
                t(
                    "Jira meldet einen Serverfehler ({status}) – bitte später erneut versuchen",
                    status=status,
                )
            )
        raise SourceError(t("Unerwartete Antwort von Jira (HTTP {status})", status=status))

    @staticmethod
    def _bad_request_text(response: httpx.Response) -> str:
        """400: Jira's ``errorMessages`` (the JQL problem; they hold no ticket data), cut off."""
        messages: list[str] = []
        try:
            body = response.json()
        except ValueError:
            body = None
        raw = body.get("errorMessages") if isinstance(body, dict) else None
        if isinstance(raw, list):
            messages = [m.strip() for m in raw if isinstance(m, str) and m.strip()]
        detail = " ".join(messages)
        if len(detail) > 300:
            detail = detail[:299] + "…"
        if not detail:
            return t("Jira weist die Abfrage ab (400) – tracker.query (JQL) prüfen")
        return t("Jira weist die Abfrage ab (400): {detail}", detail=detail)

    # --- Operations ---

    def test_connection(self) -> str:
        """Display name of the account the token belongs to (GET /rest/api/2/myself)."""
        me = self._request("GET", "/rest/api/2/myself")
        if not isinstance(me, dict):
            raise self._shape_error()
        name = me.get("displayName") or me.get("name")
        if not isinstance(name, str) or not name:
            raise self._shape_error()
        return name

    def _shape_error(self) -> SourceError:
        return SourceError(
            t(
                "Die Antwort von {host} hat nicht das erwartete Format (Jira-Version oder "
                "tracker.base_url prüfen)",
                host=self.host,
            )
        )

    def resolve_fields(self) -> ResolvedFields:
        """Resolves the display names of ``tracker.fields`` and finds the sprint, rank and epic
        link fields by their schema (GET /rest/api/2/field)."""
        if self._fields is not None:
            return self._fields
        fields = self._request("GET", "/rest/api/2/field")
        if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
            raise self._shape_error()
        configured = self.settings.fields
        resolved = ResolvedFields(
            sprint=_ids_by_schema(fields, SPRINT_SCHEMA),
            rank=_ids_by_schema(fields, RANK_SCHEMA),
            epic_link=_ids_by_schema(fields, EPIC_LINK_SCHEMA),
        )
        for setting in ("estimate", "remaining", "epic"):
            name = getattr(configured, setting)
            if name:
                setattr(resolved, setting, _resolve_name(name, fields, setting, self.host))
        self._fields = resolved
        return resolved

    def fetch(self) -> list[RawTicket]:
        """All tickets of ``tracker.query`` (paged, GET /rest/api/2/search)."""
        jql = (self.settings.query or "").strip()
        if not jql:
            raise SourceError(t("tracker.query fehlt (JQL-Abfrage der Tickets, team.yaml)"))
        resolved = self.resolve_fields()
        wanted = ",".join(resolved.requested())
        tickets: dict[str, RawTicket] = {}
        start = 0
        expected: int | None = None
        while True:
            page = self._request(
                "GET",
                SEARCH_PATH,
                {"jql": jql, "fields": wanted, "startAt": start, "maxResults": PAGE_SIZE},
            )
            if not isinstance(page, dict) or not isinstance(page.get("issues"), list):
                raise self._shape_error()
            total = page.get("total")
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise self._shape_error()
            if expected is None:
                expected = total
            elif total != expected:
                raise self._changed_error()
            issues = page["issues"]
            added = 0
            for issue in issues:
                ticket = self._ticket(issue, resolved)
                if ticket.key not in tickets:
                    tickets[ticket.key] = ticket
                    added += 1
            start += len(issues)
            if start >= expected:
                break
            if not issues or not added:  # short read, or the server ignores startAt
                raise self._changed_error()
        if len(tickets) != expected:  # a ticket moved between pages: one read twice, one missed
            raise self._changed_error()
        return list(tickets.values())

    def _changed_error(self) -> SourceError:
        return SourceError(
            t(
                "Das Ergebnis der Abfrage hat sich beim Lesen geändert oder war unvollständig – "
                "bitte erneut versuchen. Es wurde nichts geschrieben."
            )
        )

    # --- Mapping ---

    def _ticket(self, issue: Any, resolved: ResolvedFields) -> RawTicket:
        if not isinstance(issue, dict) or not isinstance(issue.get("key"), str):
            raise self._shape_error()
        data = issue.get("fields")
        if not isinstance(data, dict):
            raise self._shape_error()
        key = issue["key"]

        def number(field_id: str | None, label: str) -> float | None:
            return self._number(data.get(field_id) if field_id else None, key, label)

        def named(value: Any) -> str | None:
            name = value.get("name") if isinstance(value, dict) else None
            return name if isinstance(name, str) and name else None

        def first(ids: tuple[str, ...]) -> Any:
            return next((data[i] for i in ids if data.get(i) not in (None, "", [])), None)

        rank = first(resolved.rank)
        return RawTicket(
            key=key,
            title=" ".join(str(data.get("summary") or "").split()),
            status=named(data.get("status")),
            issue_type=named(data.get("issuetype")),
            estimate=number(resolved.estimate, "estimate"),
            remaining=number(resolved.remaining, "remaining"),
            sprint_name=choose_sprint(first(resolved.sprint)),
            rank=rank if isinstance(rank, str) else None,
            epic=self._epic(data, resolved),
            labels=list(dict.fromkeys(x for x in data.get("labels") or [] if isinstance(x, str))),
            components=list(
                dict.fromkeys(c for c in map(named, data.get("components") or []) if c)
            ),
            blocked_by=self._blocked_by(data.get("issuelinks")),
            resolved=data.get("resolution") is not None,
        )

    def _number(self, value: Any, key: str, label: str) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, dict):  # a select list: {"value": "5"}
            value = value.get("value")
        try:
            if isinstance(value, bool):
                raise ValueError(value)
            number = float(value)
            valid = math.isfinite(number) and number >= 0
        except TypeError, ValueError:
            valid = False
        if not valid:
            raise SourceError(
                t(
                    "Ticket {key}: Das Feld „{field}“ enthält keine gültige nicht negative Zahl",
                    key=key,
                    field=getattr(self.settings.fields, label) or label,
                )
            )
        return number + 0.0

    @staticmethod
    def _epic(data: dict[str, Any], resolved: ResolvedFields) -> str | None:
        def key_of(value: Any) -> str | None:
            if isinstance(value, dict):
                value = value.get("key")
            return value if isinstance(value, str) and value else None

        parent = data.get("parent")
        if resolved.epic == PARENT_FIELD:
            return key_of(parent)  # configured: the parent is the epic
        for field_id in (resolved.epic, *resolved.epic_link):
            if field_id and (found := key_of(data.get(field_id))):
                return found
        if isinstance(parent, dict):
            info = (parent.get("fields") or {}).get("issuetype")
            name = info.get("name") if isinstance(info, dict) else None
            if isinstance(name, str) and name.strip().casefold() in EPIC_TYPE_NAMES:
                return key_of(parent)
        return None

    def _blocked_by(self, links: Any) -> list[str]:
        """Keys on the inward side of the configured link type ("is blocked by")."""
        wanted = self.settings.link_type.strip().casefold()
        keys = []
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            kind = link.get("type")
            name = kind.get("name") if isinstance(kind, dict) else None
            inward = link.get("inwardIssue")
            if (
                isinstance(name, str)
                and name.strip().casefold() == wanted
                and (isinstance(inward, dict) and isinstance(inward.get("key"), str))
            ):
                keys.append(inward["key"])
        return list(dict.fromkeys(keys))


__all__ = [
    "ALLOWED_METHODS",
    "KEYRING_SERVICE",
    "TOKEN_ENV",
    "JiraSource",
    "ResolvedFields",
    "SprintValue",
    "choose_sprint",
    "jira_token",
    "keyring_available",
    "keyring_missing_error",
    "parse_sprint",
    "store_token",
]
