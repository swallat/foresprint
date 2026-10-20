# SPDX-License-Identifier: EUPL-1.2
"""Sign-in to the Git server with an access token (https), guided by the app.

The app never stores the token itself: it hands it over once with ``git credential approve`` to
Git's credential helper (Credential Manager, keychain, libsecret …), writes it to no file and no
log, and never shows it again. A plain-text store (``credential.helper store``) is neither set
nor used for saving. The app does not create SSH keys.
"""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import git as gitmod
from .git import GitError, _git, _git_result, credential_helpers, parse_remote_url, probe_remote
from .gitsync import cached_remote_info, git_available
from .i18n import t

# Credential helpers for which ``git credential approve`` stores a secret in plain text.
# Anything unknown (“custom”) is allowed (up to the computer), ``store`` never.
_PLAIN_TEXT = {"store"}
# More time than a credential helper needs (Windows starts it cold).
HELPER_TIMEOUT = 30.0
MAX_TOKEN_LENGTH = 4096


@dataclass(frozen=True)
class HostGuide:
    """How to create a token at a host; ``username`` is the default for the field
    (empty = the person enters their own user name)."""

    kind: str
    username: str
    steps: str


def host_guide(kind: str) -> HostGuide:
    """Guide per kind of server (``gitsync.HOST_*``); anything unknown gets the generic one."""
    if kind == "gitlab":
        return HostGuide(
            kind,
            "oauth2",
            t(
                "GitLab: in the project (or in your own settings) under “Access tokens” "
                "create a token with the role “Developer” or higher and the permission "
                "“write_repository”. Copy the token once."
            ),
        )
    if kind == "github":
        return HostGuide(
            kind,
            "x-access-token",
            t(
                "GitHub: under Settings › Developer settings › Personal access tokens "
                "create a fine-grained token for this repository with the permission "
                "“Contents: Read and write”. Copy the token once."
            ),
        )
    if kind == "forgejo":
        return HostGuide(
            kind,
            "",
            t(
                "Forgejo/Gitea/Codeberg: under Settings › Applications create an access "
                "token with the permission “write:repository”. The user name is your own "
                "account name."
            ),
        )
    return HostGuide(
        kind,
        "",
        t(
            "Create an access token (personal access token) with read and write permission "
            "on the repository at the server and enter the user name the server expects "
            "for it."
        ),
    )


def https_parts(url: str) -> tuple[str, str]:
    """``(host, path)`` of an https address for the credential helper. Other addresses (SSH, folder,
    http) are not meant here: :class:`GitError`."""
    problem = GitError(
        t("Token sign-in applies only to https addresses without credentials in the address.")
    )
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise problem
        parts.port  # noqa: B018  (raises ValueError for an invalid port)
    except ValueError as e:
        raise problem from e
    return parts.netloc, parts.path.lstrip("/")


def is_https(url: str) -> bool:
    try:
        https_parts(url)
    except GitError:
        return False
    return True


def _credential_input(url: str, username: str = "", token: str = "") -> str:
    """Input for ``git credential``: ``key=value`` lines, ending with an empty line."""
    host, path = https_parts(url)
    lines = ["protocol=https", f"host={host}"]
    if path:
        lines.append(f"path={path}")
    if username:
        lines.append(f"username={username}")
    if token:
        lines.append(f"password={token}")
    return "\n".join(lines) + "\n\n"


def _clean(value: str, what: str) -> str:
    value = value.strip()
    if not value or any(ch in value for ch in "\r\n\0"):
        raise GitError(t("Please enter {what} (without a line break).", what=what))
    return value


# --- Credential helper -------------------------------------------------------------------------


def _helper_exists(name: str) -> bool:
    """Is there a ``git-credential-<name>`` on the PATH or in the folder of the Git programs?"""
    command = f"git-credential-{name}"
    if shutil.which(command):
        return True
    try:
        out = _git_result(Path.home(), "--exec-path", timeout=10).stdout.strip()
    except GitError, OSError:
        return False
    folder = Path(out) if out else None
    return bool(folder and any((folder / (command + ext)).exists() for ext in ("", ".exe", ".cmd")))


def suggested_helper() -> str | None:
    """The credential helper the app may offer for this computer, or ``None`` (then hints only).
    Windows: ``manager`` (Git Credential Manager), macOS: ``osxkeychain``, Linux:
    ``libsecret`` or ``manager``, if the helper is present. Never ``store``."""
    if sys.platform == "win32":
        candidates = ["manager", "wincred"]
    elif sys.platform == "darwin":
        candidates = ["osxkeychain", "manager"]
    else:
        candidates = ["libsecret", "manager"]
    return next((name for name in candidates if _helper_exists(name)), None)


def enable_helper(name: str) -> None:
    """Registers the credential helper for the user (``git config --global``, never in the
    repository). Only the names from :func:`suggested_helper`; ``store`` is excluded."""
    if name != suggested_helper():
        raise GitError(t("The app does not set up this credential helper."))
    _git(Path.home(), "config", "--global", "credential.helper", name)


def helper_state(root: Path) -> str:
    """``"none"`` (no helper), ``"plain"`` (plain-text store) or ``"ok"``."""
    names = credential_helpers(root)
    if any(name in _PLAIN_TEXT for name in names):
        return "plain"
    return "ok" if names else "none"


# --- Store, verify, delete the token ------------------------------------------------------


def store_token(root: Path, url: str, username: str, token: str) -> None:
    """Hands the token to the credential helper (``git credential approve``). If there is no
    helper or it is a plain-text store, nothing happens and a :class:`GitError` is raised.
    The token appears in no message."""
    username = _clean(username, t("the user name"))
    token = _clean(token, t("the token"))
    if len(token) > MAX_TOKEN_LENGTH:
        raise GitError(t("The token is too long."))
    state = helper_state(root)
    if state == "plain":
        raise GitError(
            t("Git stores sign-ins here in plain text (`credential.helper store`)."),
            "auth",
            t(
                "The app does not use that for tokens. Please set up a credential helper "
                "of the computer (see above) and remove `store`."
            ),
        )
    if state == "none":
        raise GitError(
            t("No Git credential helper is configured on this computer yet."),
            "auth",
            t("Please switch on the credential helper first (see above)."),
        )
    proc = _git_result(
        root,
        "credential",
        "approve",
        timeout=HELPER_TIMEOUT,
        stdin_text=_credential_input(url, username, token),
    )
    if proc.returncode != 0:
        # The helper’s output may contain the token: only the return code counts.
        raise GitError(
            t("The Git credential helper did not accept the token."),
            "auth",
            t(
                "Check the credential helper and the permissions of the user account, then "
                "try again."
            ),
        )


def verify(root: Path, url: str) -> tuple[str, ...]:
    """Checks the sign-in with ``git ls-remote`` (changes nothing) and returns the branches.
    Errors (rejected, expired, wrong permission) come with a hint as :class:`GitError`."""
    return probe_remote(root, parse_remote_url(url))


def forget_token(root: Path, url: str, username: str = "", token: str = "") -> None:
    """Removes the stored sign-in from the credential helper (``git credential reject``).
    With ``username`` and ``token`` it hits exactly that entry; without both, all sign-ins
    of this server (most helpers ignore the path of the address)."""
    if username:
        username = _clean(username, t("the user name"))
    if token:
        token = _clean(token, t("the token"))
    proc = _git_result(
        root,
        "credential",
        "reject",
        timeout=HELPER_TIMEOUT,
        stdin_text=_credential_input(url, username, token),
    )
    if proc.returncode != 0:
        raise GitError(t("The Git credential helper did not delete the sign-in."))


# --- Setup checklist ---------------------------------------------------------------


@dataclass(frozen=True)
class SetupItem:
    key: str
    ok: bool
    detail: str
    page: str  # page where it is done ("" = none)


def setup_items(root: Path | None) -> list[SetupItem]:
    """Read-only checks for the checklist on the start page (no network, no prompts).
    ``root`` is the data folder or ``None``."""
    items: list[SetupItem] = []
    git_ok = git_available()
    items.append(
        SetupItem(
            "git", git_ok, t("Git is installed.") if git_ok else t("Git is missing."), "hilfe"
        )
    )
    top = gitmod.repo_root(root) if git_ok and root is not None else None
    items.append(
        SetupItem(
            "folder",
            top is not None,
            t("The data folder is a Git repository.")
            if top
            else t("The data folder is not a Git repository yet."),
            "datenordner",
        )
    )
    if top is None:
        return items
    try:
        info = cached_remote_info(top)
    except GitError:
        return items
    items.append(
        SetupItem(
            "server",
            info.name is not None,
            t("A server is configured.") if info.name else t("No server is configured yet."),
            "datenordner",
        )
    )
    if info.name:
        if is_https(info.url):
            state = helper_state(top)
            ok = state == "ok"
            detail = (
                t("A credential helper is configured.")
                if ok
                else t("Token sign-in for the server is still missing.")
            )
        else:
            ok, detail = True, t("The address needs no token sign-in.")
        items.append(SetupItem("login", ok, detail, "datenordner"))
    name = _git(top, "config", "--get", "user.name", check=False)
    email = _git(top, "config", "--get", "user.email", check=False)
    items.append(
        SetupItem(
            "identity",
            bool(name and email),
            t("Name and email address for changes are set.")
            if name and email
            else t("Name and email address for changes are missing."),
            "datenordner",
        )
    )
    return items
