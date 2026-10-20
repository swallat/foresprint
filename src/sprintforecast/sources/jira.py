# SPDX-License-Identifier: EUPL-1.2
"""Jira Data Center as a ticket source (docs/design/ticket-planning.md, section 7.1).

REST API v2, authenticated by a personal access token (``Authorization: Bearer``). Only reads
happen, with one exception (step 5): every request goes through :meth:`JiraSource._request`, the
one function that talks to the network. It refuses anything but ``GET`` and the single ``PUT``
that adds or removes a ``planned_for_<sprint_id>`` label of one ticket. The token and the content of
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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sprintforecast import __version__
from sprintforecast.i18n import t
from sprintforecast.model import TrackerSettings, base_url_problem
from sprintforecast.sources import LABEL_PREFIX, RawTicket, SourceError

if TYPE_CHECKING:  # pragma: no cover - typing only, httpx stays an optional import
    import httpx

TOKEN_ENV = "SPRINTFORECAST_JIRA_TOKEN"
KEYRING_SERVICE = "sprintforecast-jira"
USER_AGENT = f"sprintforecast/{__version__} (read-only Jira import)"
TIMEOUT = 30.0  # seconds, per request
PAGE_SIZE = 100

# The only HTTP methods this module uses (spec section 7.1): reads, and the one label PUT.
ALLOWED_METHODS = frozenset({"GET", "PUT"})
# The one thing PUT may do: change labels of one ticket (``_is_label_write`` checks the body).
ISSUE_PATH = re.compile(r"/rest/api/2/issue/[A-Za-z][A-Za-z0-9_]*-[0-9]+")

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


def _is_label_write(path: str, body: Any) -> bool:
    """Is this PUT exactly a change of ``planned_for_*`` labels of one ticket, nothing else?"""
    if not ISSUE_PATH.fullmatch(path) or not isinstance(body, dict) or set(body) != {"update"}:
        return False
    update = body["update"]
    if not isinstance(update, dict) or set(update) != {"labels"}:
        return False
    operations = update["labels"]
    if not isinstance(operations, list) or not operations:
        return False
    for op in operations:
        if not isinstance(op, dict) or len(op) != 1:
            return False
        ((verb, label),) = op.items()
        if verb not in ("add", "remove") or not isinstance(label, str):
            return False
        if not label.startswith(LABEL_PREFIX) or len(label) == len(LABEL_PREFIX):
            return False
        if any(c.isspace() for c in label):
            return False
    return True


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
                (
                    "The package httpx is missing for Jira. Install the extra [jira]: run the "
                    "installer again or {command} (give plugins again with --with)"
                ),
                command=INSTALL_COMMAND,
            )
        )
    return httpx


def invalid_base_url_error() -> SourceError:
    return SourceError(t("tracker.base_url is missing or not an http or https address (team.yaml)"))


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
            (
                "The keychain is not available: the package keyring is missing (run the "
                "installer again or {command} --with keyring; give plugins again with --with). "
                "Alternatively set the environment variable {variable}."
            ),
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
                (
                    "The keychain did not accept the token (no keychain service available?). "
                    "Alternatively set the environment variable {variable}."
                ),
                variable=TOKEN_ENV,
            )
        )


def missing_token_error() -> SourceError:
    return SourceError(
        t(
            (
                "No Jira token found. Set the environment variable {variable} or store the "
                "token in the keychain with “sprintforecast tickets TEAM --set-token” (Jira: "
                "profile > Personal Access Tokens)."
            ),
            variable=TOKEN_ENV,
        )
    )


def _check_token(token: str) -> str:
    """The token must be one printable word; anything else (a newline from copy and paste)
    would produce an invalid header whose error message contains the value."""
    if not token or not re.fullmatch(r"[\x21-\x7e]+", token):
        raise SourceError(
            t(
                "The Jira token is empty or contains spaces, line breaks or special "
                "characters – please paste it again."
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
                (
                    "The field “{name}” (tracker.fields.{setting}) is ambiguous in {host}: "
                    "{ids}. Please enter the field ID instead of the name in team.yaml."
                ),
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
            "The field “{name}” (tracker.fields.{setting}) does not exist in {host}.{hint}",
            name=name,
            setting=setting,
            host=host,
            hint=(" " + t("Similar names: {names}", names=", ".join(close))) if close else "",
        )
    )


def _ids_by_schema(fields: list[dict[str, Any]], schema: str) -> tuple[str, ...]:
    found = []
    for f in fields:
        info = f.get("schema")
        if isinstance(info, dict) and info.get("custom") == schema and f.get("id"):
            found.append(str(f["id"]))
    return tuple(sorted(found))


# --- Field suggestions (setup page) ----------------------------------------------------------


@dataclass(frozen=True)
class FieldCandidate:
    """A field of the instance that could serve as one of ``tracker.fields``."""

    id: str
    name: str
    # The text for ``team.yaml``: the display name, or the id when another field has that name.
    value: str
    # Higher = more likely (a hint from the name); 0 = no hint, only the type fits.
    score: int = 0


@dataclass
class FieldSuggestions:
    """Candidates per setting, best first (the first is only a suggestion when its score > 0)."""

    estimate: list[FieldCandidate] = field(default_factory=list)
    remaining: list[FieldCandidate] = field(default_factory=list)
    epic: list[FieldCandidate] = field(default_factory=list)


# Fragments of (localized) field names that point at the kind of number a field holds.
_POINT_HINTS = ("story point", "storypoint", "story-punkt", "storypunkt", "punkte", "points")
_ESTIMATE_HINTS = ("original", "initial", "ursprüng", "estimate", "schätz", "refine")
_REMAINING_HINTS = ("remaining", "rest", "verbleib")


def _score(name: str, hints: tuple[str, ...]) -> int:
    lowered = name.casefold()
    points = 1 if any(h in lowered for h in _POINT_HINTS) else 0
    return points + (2 if any(h in lowered for h in hints) else 0)


def suggest_fields(fields: list[dict[str, Any]]) -> FieldSuggestions:
    """Candidates for ``tracker.fields`` from the answer of ``/rest/api/2/field``: number fields
    for the estimate and the remaining work (ordered by hints in the name), the epic link fields
    and the parent link for the epic."""
    names = [str(f.get("name", "")).strip() for f in fields]

    def candidate(f: dict[str, Any], hints: tuple[str, ...]) -> FieldCandidate | None:
        field_id, name = str(f.get("id") or ""), str(f.get("name") or "").strip()
        if not field_id or not name:
            return None
        value = name if names.count(name) == 1 else field_id
        return FieldCandidate(field_id, name, value, _score(name, hints))

    def ordered(found: list[FieldCandidate]) -> list[FieldCandidate]:
        return sorted(found, key=lambda c: (-c.score, c.name.casefold(), c.id))

    numbers = [
        f
        for f in fields
        if isinstance(f.get("schema"), dict)
        and f["schema"].get("type") == "number"
        and f["schema"].get("custom")
    ]
    result = FieldSuggestions()
    for setting, hints in (("estimate", _ESTIMATE_HINTS), ("remaining", _REMAINING_HINTS)):
        found = [c for f in numbers if (c := candidate(f, hints))]
        setattr(result, setting, ordered(found))
    links = [
        c
        for f in fields
        if isinstance(f.get("schema"), dict)
        and f["schema"].get("custom") == EPIC_LINK_SCHEMA
        and (c := candidate(f, ()))
    ]
    result.epic = ordered(links)
    if any(f.get("id") == PARENT_FIELD for f in fields):
        result.epic.append(FieldCandidate(PARENT_FIELD, PARENT_FIELD, PARENT_FIELD))
    return result


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
            raise SourceError(t("tracker.base_url must not contain credentials (team.yaml)"))
        if problem == "extra":
            raise SourceError(
                t("tracker.base_url must not contain parameters (?…) or a fragment (#…)")
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

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Sends one request and returns the decoded JSON. Only ``GET`` and the label ``PUT``
        are allowed; every failure becomes a SourceError whose text contains neither the token
        nor the response."""
        if method not in ALLOWED_METHODS:
            raise ValueError(f"HTTP method {method!r} is not allowed: this source only reads")
        if (method == "PUT") != (body is not None) or (
            method == "PUT" and (params or not _is_label_write(path, body))
        ):
            raise ValueError("Only a label change of one ticket may be written")
        httpx = self._httpx
        failure: str | None = None
        response = None
        if self._client is None:
            try:
                self._client = self._new_client()
            except OSError:  # includes ssl.SSLError: the CA bundle could not be loaded
                failure = t(
                    "The CA file from SSL_CERT_FILE or SSL_CERT_DIR cannot be read – check "
                    "the environment variable and the file."
                )
        if failure is None and self._client is not None:
            try:
                response = self._client.request(
                    method, self.base_url + path, params=params, json=body
                )
            except httpx.TimeoutException:
                failure = self._timeout_text()
            except httpx.InvalidURL, httpx.UnsupportedProtocol:
                failure = t(
                    "The address {host} is invalid (tracker.base_url in team.yaml)",
                    host=self.host,
                )
            except httpx.ConnectError as e:
                failure = self._connect_text(e)
            except httpx.HTTPError:
                failure = t(
                    "The connection to {host} failed (network, proxy or firewall?)",
                    host=self.host,
                )
        if failure is not None or response is None:
            # Raised outside the except blocks: the transport error (and the request headers
            # with the token that it may reference) is neither __cause__ nor __context__.
            raise SourceError(failure or "")
        if method == "PUT":
            return self._decode_write(response)
        return self._decode(response, path)

    def _decode_write(self, response: httpx.Response) -> None:
        """The answer to the label PUT: 204 is success; 403/404 get texts that fit a write."""
        if response.status_code == 204:
            return None
        if response.status_code == 403:
            raise SourceError(
                t("Jira refuses the write (403): the account may not change labels of this ticket.")
            )
        if response.status_code == 404:
            raise SourceError(t("The ticket does not exist or is not visible to the account (404)"))
        return self._decode(response)

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
            "No answer from {host} within {seconds} seconds (network, VPN or firewall?)",
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
                (
                    "The TLS check of the certificate of {host} failed. The check is never "
                    "switched off. If the certificate was issued by a company CA, give its "
                    "certificate file in the environment variable SSL_CERT_FILE (or "
                    "SSL_CERT_DIR)."
                ),
                host=self.host,
            )
        if any(isinstance(e, ssl.SSLError) for e in chain) or "SSL:" in text or "[SSL" in text:
            return t(
                (
                    "The TLS handshake with {host} failed (http instead of https, wrong port, "
                    "or a proxy interfering with TLS?). The check is never switched off."
                ),
                host=self.host,
            )
        return t(
            "{host} is not reachable (check the address, network, VPN, proxy or firewall)",
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
                    (
                        "{host} does not answer with JSON – is tracker.base_url the address of "
                        "Jira (without a login page in front)?"
                    ),
                    host=self.host,
                )
            )
        if status == 401:
            raise SourceError(
                t(
                    "Jira rejects the token (401): it is invalid or has expired. Create a "
                    "new token (Jira: profile > Personal Access Tokens)."
                )
            )
        if status == 403:
            raise SourceError(
                t(
                    "Jira denies access (403): the account may not read this data, or Jira "
                    "temporarily blocks the login."
                )
            )
        if status == 404:
            raise SourceError(
                t(
                    (
                        "Jira not found at {host} (404): check tracker.base_url (a context "
                        "path such as /jira is part of it)."
                    ),
                    host=self.host,
                )
            )
        if status == 400 and path == SEARCH_PATH:
            raise SourceError(self._bad_request_text(response))
        if status == 400:
            raise SourceError(
                t("Jira rejects the request (400) – check the Jira version and tracker.base_url")
            )
        if status == 407:
            raise SourceError(
                t(
                    "The proxy requires authentication (407) – check the proxy and its "
                    "credentials (HTTPS_PROXY)."
                )
            )
        if status == 429:
            wait = response.headers.get("retry-after", "").strip()
            if wait.isascii() and wait.isdigit() and len(wait) <= 6:
                raise SourceError(
                    t(
                        (
                            "Jira reports too many requests (429) – please try again in "
                            "{seconds} seconds"
                        ),
                        seconds=int(wait),
                    )
                )
            raise SourceError(t("Jira reports too many requests (429) – please try again later"))
        if 300 <= status < 400:
            target = urlsplit(response.headers.get("location", "")).hostname
            raise SourceError(
                t(
                    "{host} redirects{target} – change tracker.base_url to the final address.",
                    host=self.host,
                    target=f" ({target})" if target else "",
                )
            )
        if status >= 500:
            raise SourceError(
                t(
                    "Jira reports a server error ({status}) – please try again later",
                    status=status,
                )
            )
        raise SourceError(t("Unexpected answer from Jira (HTTP {status})", status=status))

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
            return t("Jira rejects the query (400) – check tracker.query (JQL)")
        return t("Jira rejects the query (400): {detail}", detail=detail)

    # --- Operations ---

    def set_labels(self, key: str, add: list[str], remove: list[str]) -> None:
        """Adds and removes ``planned_for_*`` labels of one ticket (PUT /rest/api/2/issue/KEY).
        The update operations touch only the named labels, never the other labels of the
        ticket."""
        operations: list[dict[str, str]] = [{"remove": x} for x in remove]
        operations += [{"add": x} for x in add]
        self._request("PUT", f"/rest/api/2/issue/{key}", body={"update": {"labels": operations}})

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
                (
                    "The answer from {host} does not have the expected format (check the Jira "
                    "version or tracker.base_url)"
                ),
                host=self.host,
            )
        )

    def list_fields(self) -> list[dict[str, Any]]:
        """All fields of the instance (GET /rest/api/2/field), for suggestions."""
        fields = self._request("GET", "/rest/api/2/field")
        if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
            raise self._shape_error()
        return fields

    def count_tickets(self) -> int:
        """Number of tickets the query matches, without reading them (GET /rest/api/2/search
        with one ticket per page)."""
        jql = (self.settings.query or "").strip()
        if not jql:
            raise SourceError(t("tracker.query is missing (JQL query of the tickets, team.yaml)"))
        page = self._request(
            "GET", SEARCH_PATH, {"jql": jql, "fields": "key", "startAt": 0, "maxResults": 1}
        )
        total = page.get("total") if isinstance(page, dict) else None
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise self._shape_error()
        return total

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
            raise SourceError(t("tracker.query is missing (JQL query of the tickets, team.yaml)"))
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
                "The result of the query changed while reading or was incomplete – please "
                "try again. Nothing was written."
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
                    (
                        "Ticket {key}: the field “{field}” does not contain a valid "
                        "non-negative number"
                    ),
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
