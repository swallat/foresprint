# SPDX-License-Identifier: EUPL-1.2
"""Kleine Git-Helfer für Commit und Sprint-Tag."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, NamedTuple

from sprintforecast import proctree
from sprintforecast.i18n import t

_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://")
_NAME_START = re.compile(r"[A-Za-z0-9._~-]+")
_SCP_PASSWORD = re.compile(r"([^@/\\\s:]+):[^@/\\\s]*@")  # benutzer:kennwort@host:pfad
# Der Rückblick statt ``\b`` ist wichtig: Ein Versuch beginnt nur am Anfang eines Wortes aus
# Schema-Zeichen, nicht hinter jedem Punkt oder Bindestrich. Sonst läuft der Treffer bei langen
# Zeilen wie „a.a.a.a. …“ an jeder Stelle bis zum Ende und zurück (quadratische Laufzeit).
_URL_IN_TEXT = re.compile(r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^\s'\"<>]+")


def public_url(url: str) -> str:
    """Adresse ohne Zugangsdaten und ohne Zusätze nach ``?`` oder ``#`` (nur zur Anzeige).
    Wirft nie und ist idempotent. Bei ssh bleibt der Benutzername erhalten, das Kennwort fällt
    weg; lokale Pfade und jede von :func:`parse_remote_url` akzeptierte Adresse bleiben
    unverändert."""
    if scheme := _SCHEME.match(url):
        rest = url[scheme.end() :]
        if (at := rest.rfind("@")) >= 0:  # alles bis zum letzten „@“ (auch im Pfad) fällt weg
            removed, rest = rest[:at], rest[at + 1 :]
            if scheme.group(1).lower() == "ssh" and (user := _NAME_START.match(removed)):
                rest = f"{user.group(0)}@{rest}"
        cut = [i for i in (rest.find("?"), rest.find("#")) if i >= 0]
        return url[: scheme.end()] + (rest[: min(cut)] if cut else rest)
    if password := _SCP_PASSWORD.match(url):  # benutzer:kennwort@host:pfad
        return f"{password.group(1)}@{url[password.end() :]}"
    return url


def has_credentials(text: str) -> bool:
    """Steckt in der Adresse etwas, das :func:`public_url` entfernen würde?"""
    return public_url(text.strip()) != text.strip()


def scrub(text: str) -> str:
    """Ersetzt jede Adresse (``schema://…``) im Text durch ihre Anzeigefassung."""
    return _URL_IN_TEXT.sub(lambda m: public_url(m.group(0)), text)


def md_code(text: str) -> str:
    """Text als Code-Span für Markdown. Namen und Adressen, die von außen kommen (Server,
    Konfiguration), gehören nie als Fließtext in die Oberfläche: Dort würden Auszeichnungen
    wirken und Webadressen wie ``www.beispiel.de/x`` zu Links. Backticks im Text lassen den
    Span nicht enden; Steuer- und unsichtbare Zeichen werden zu Leerzeichen."""
    text = "".join(
        " " if unicodedata.category(c)[0] == "C" or unicodedata.category(c) in {"Zl", "Zp"} else c
        for c in text
    )
    if not text:
        return ""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


class GitError(Exception):
    """Fehler eines Git-Aufrufs. ``kind`` benennt die Art (siehe :func:`classify`), ``hint`` ist
    der nächste Schritt in Alltagssprache; ``str(error)`` bleibt die kurze Meldung. Meldung und
    Hinweis enthalten nie Zugangsdaten aus einer Adresse (:func:`scrub`)."""

    def __init__(self, message: str, kind: str = "error", hint: str = "") -> None:
        super().__init__(scrub(message))
        self.kind = kind
        self.hint = scrub(hint)

    def full(self) -> str:
        """Meldung samt nächstem Schritt – für Stellen ohne Überschrift (``title_for``). Bei
        einem Anmeldefehler steht die Ursache voran: Der Hinweis (:func:`auth_help`) beginnt
        gleich mit dem nächsten Schritt, weil die Überschrift sie sonst nennt."""
        cause = f"{title_for(self.kind)}." if self.kind == "auth" and self.hint else ""
        return " ".join(part for part in (cause, str(self), self.hint) if part).strip()


# Tabellenkalkulationen dürfen nie committet werden (können echte Team-Daten enthalten).
FORBIDDEN = re.compile(r"\.xls[xm]?$", re.IGNORECASE)
# Datendateien, die nie mit Konfliktmarkierungen committet werden.
DATA_FILES = re.compile(r"\.ya?ml$", re.IGNORECASE)


# Windows: keine Konsolenfenster für Hilfsprozesse (sonst blitzt bei jedem Aufruf eines auf).
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

_ROOT_CACHE: dict[Path, tuple[float, Path | None]] = {}
_ROOT_TTL = 30.0


# Netzwerkaufrufe (fetch, push, clone) dürfen nie ewig hängen oder im Hintergrund nach einem
# Kennwort fragen: Es gibt kein Terminal, in dem man antworten könnte.
NETWORK_TIMEOUT = 90.0


def _env(network: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung für Git: englische Meldungen (damit sie sich erkennen lassen) und bei
    Netzwerkaufrufen keine Rückfrage im Terminal. Anmeldehelfer (Credential Manager) laufen
    weiter. Ablaufprotokolle (``GIT_TRACE*``, ``GIT_CURL_VERBOSE``) werden entfernt: Sie würden
    Anmelde-Kopfzeilen in die Fehlerausgabe schreiben. ``extra`` kommt zuletzt dazu."""
    # Pfade sind nie Suchmuster: Dateinamen mit *, ? oder [ bleiben wörtlich gemeint.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("GIT_TRACE", "GIT_CURL_VERBOSE"))
    }
    env |= {"LC_ALL": "C", "LANGUAGE": "C", "GIT_LITERAL_PATHSPECS": "1"}
    if network:
        env["GIT_TERMINAL_PROMPT"] = "0"
    return env | (extra or {})


def _git_result(
    cwd: Path,
    *args: str,
    network: bool = False,
    timeout: float | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Führt ``git`` aus und liefert das Ergebnis samt Rückgabecode (ohne Fehlerprüfung); nur
    „git fehlt“ und Zeitüberschreitung kommen als :class:`GitError`."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            env=_env(network, env_extra),
            timeout=timeout or (NETWORK_TIMEOUT if network else 120),
            **NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise classify("", missing=True) from e
    except subprocess.TimeoutExpired as e:
        raise classify("", timeout=True) from e


def _git(
    cwd: Path,
    *args: str,
    strip: bool = True,
    network: bool = False,
    check: bool = True,
    timeout: float | None = None,
    env_extra: dict[str, str] | None = None,
) -> str:
    """Führt ``git`` aus. Bei Fehlern :class:`GitError` mit erkannter Art und nächstem Schritt;
    mit ``check=False`` wird bei Fehlern statt einer Ausnahme ein leerer Text geliefert."""
    proc = _git_result(cwd, *args, network=network, timeout=timeout, env_extra=env_extra)
    if proc.returncode != 0:
        if not check:
            return ""
        raise classify(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip() if strip else proc.stdout


def split_z(out: str) -> list[str]:
    """Zerlegt NUL-getrennte Git-Ausgabe (``-z``) in ihre Einträge. Nur so bleiben Pfade mit
    Umlauten, Anführungszeichen oder Tabulatoren unverändert (ohne ``-z`` setzt Git sie in
    Anführungszeichen und maskiert Sonderzeichen)."""
    return [item for item in out.split("\0") if item]


def check_name(name: str) -> str:
    """Prüft einen Tag-Namen, der an Git übergeben wird: er darf nicht mit ``-`` beginnen (Git
    läse ihn sonst als Option), nicht ``HEAD`` oder ``@`` heißen (für Git mehrdeutig) und keine
    Leerzeichen am Anfang oder Ende haben (sie werden nicht still entfernt, sonst entstünde ein
    anderer Name als der eingegebene). Gibt den Namen unverändert zurück."""
    if not name.strip() or name != name.strip() or name.startswith("-") or name in {"HEAD", "@"}:
        raise GitError(t("Ungültiger Tag-Name: {name}", name=name))
    return name


def valid_tag_name(root: Path, name: str) -> str:
    """Wie :func:`check_name`, prüft aber zusätzlich mit Git, ob der Referenzname gültig ist."""
    name = check_name(name)
    if _git_result(root, "check-ref-format", f"refs/tags/{name}").returncode != 0:
        raise GitError(t("Ungültiger Tag-Name: {name}", name=name))
    return name


def tag_commit(root: Path, name: str) -> str:
    """Voller Hash des Commits, auf den der lokale Tag zeigt (leer = es gibt ihn nicht)."""
    return _git(
        root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}", check=False
    )


def check_new_tags(root: Path, tags: list[str] | None) -> list[str]:
    """Prüft Tag-Namen VOR einem Commit: gültig und lokal noch nicht vergeben (ein vorhandener
    Tag zeigt nie auf den neuen Commit). Bei einem Konflikt :class:`GitError`; dann ist noch
    nichts verändert. Gibt die Namen ohne Doppelte zurück."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    for name in names:
        if existing := tag_commit(root, name):
            raise GitError(
                t(
                    "Der Tag {name} gibt es auf diesem Rechner schon (er zeigt auf {rev}). "
                    "Es wurde nichts committet.",
                    name=name,
                    rev=existing[:7],
                ),
                "tag_exists",
                hint_for("tag_exists"),
            )
    return names


def ensure_tags(root: Path, tags: list[str] | None, message: str) -> tuple[list[str], list[str]]:
    """Setzt fehlende Tags auf den aktuellen Stand (HEAD), ohne neuen Commit – etwa wenn ein
    früherer Versuch den Commit schrieb, den Tag aber nicht. Liefert (neu gesetzte Tags, Tags,
    die schon auf einem anderen Stand liegen und unverändert bleiben)."""
    names = list(dict.fromkeys(valid_tag_name(root, tag) for tag in tags or []))
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    created: list[str] = []
    elsewhere: list[str] = []
    if not head:
        return created, elsewhere
    try:
        for name in names:
            existing = tag_commit(root, name)
            if not existing:
                _git(root, "tag", "-a", "-m", message, "--", name)
                created.append(name)
            elif existing != head:
                elsewhere.append(name)
    finally:
        invalidate_status()
    return created, elsewhere


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Wie :func:`_git`, liefert aber die rohe Ausgabe (z. B. ein Archiv)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_env(False),
            timeout=120,
            **NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise classify("", missing=True) from e
    except subprocess.TimeoutExpired as e:
        raise classify("", timeout=True) from e
    if proc.returncode != 0:
        raise classify(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


# Erkennungsmuster in der Reihenfolge der Prüfung (englische Git-Meldungen, siehe _env).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "identity",
        re.compile(
            r"tell me who you are|unable to auto-detect email|empty ident|"
            r"auto-detection is disabled",
            re.I,
        ),
    ),
    (
        "locked",
        re.compile(
            r"index\.lock|\.lock'?: File exists|unable to unlink|Device or resource busy|"
            r"being used by another process|Unable to create '.*\.lock'",
            re.I,
        ),
    ),
    (
        "auth",
        re.compile(
            r"Authentication failed|could not read Username|could not read Password|"
            r"terminal prompts disabled|Permission denied \(publickey|"
            r"Invalid username or password|The requested URL returned error: 40[13]|"
            r"HTTP Basic: Access denied|Host key verification failed|"
            r"Support for password authentication was removed",
            re.I,
        ),
    ),
    (
        "offline",
        re.compile(
            r"Could not resolve host|Failed to connect|Connection (timed out|refused|reset)|"
            r"Network is unreachable|unable to access|Operation timed out|Temporary failure in "
            r"name resolution|Could not read from remote repository|ssh: connect to host|"
            r"Connection closed by|SSL certificate problem",
            re.I,
        ),
    ),
    (
        "denied",
        re.compile(
            r"remote rejected|hook declined|protected branch|pre-receive hook|"
            r"Permission to .* denied",
            re.I,
        ),
    ),
    (
        "rejected",
        re.compile(
            r"\[rejected\]|non-fast-forward|failed to push some refs|fetch first|"
            r"Updates were rejected",
            re.I,
        ),
    ),
    (
        "merge_in_progress",
        re.compile(
            r"You have not concluded your merge|MERGE_HEAD exists|"
            r"Exiting because of an unresolved conflict|Pulling is not possible because you "
            r"have unmerged",
            re.I,
        ),
    ),
    ("conflict", re.compile(r"CONFLICT|Automatic merge failed|fix conflicts", re.I)),
    (
        "dirty",
        re.compile(
            r"would be overwritten by (merge|checkout|revert)|"
            r"Please commit your changes or stash them",
            re.I,
        ),
    ),
    ("detached", re.compile(r"You are not currently on a branch|detached HEAD", re.I)),
    (
        "no_upstream",
        re.compile(r"no tracking information|has no upstream branch|no upstream configured", re.I),
    ),
    (
        "no_remote",
        re.compile(
            r"No configured push destination|No remote repository specified|No such remote", re.I
        ),
    ),
    ("not_found", re.compile(r"Repository not found|remote: Not Found", re.I)),
]


def classify(message: str, missing: bool = False, timeout: bool = False) -> GitError:
    """Macht aus einer Git-Fehlermeldung eine :class:`GitError` mit Art und nächstem Schritt."""
    if missing:
        return GitError(
            t("git ist nicht installiert oder nicht im PATH"),
            "git_missing",
            t(
                "Git installieren (Windows: https://git-scm.com/download/win, macOS: "
                "`xcode-select --install`, Linux: Paketverwaltung) und die App neu starten."
            ),
        )
    if timeout:
        return GitError(
            t("Der Server antwortet nicht rechtzeitig."),
            "offline",
            t("Internetverbindung und VPN prüfen und später noch einmal versuchen."),
        )
    for kind, pattern in _PATTERNS:
        if pattern.search(message):
            return GitError(message or kind, kind, hint_for(kind))
    return GitError(message or t("Unbekannter Git-Fehler"), "error")


def title_for(kind: str) -> str:
    """Kurze Überschrift zu einer Fehlerart."""
    titles = {
        "git_missing": t("Git ist nicht installiert"),
        "identity": t("Name und E-Mail-Adresse fehlen"),
        "locked": t("Eine Datei ist gesperrt"),
        "auth": t("Anmeldung fehlt oder wurde abgelehnt"),
        "offline": t("Server nicht erreichbar"),
        "denied": t("Server lehnt das Hochladen ab"),
        "rejected": t("Hochladen abgelehnt, weil inzwischen etwas Neues da ist"),
        "merge_in_progress": t("Zusammenführen ist unvollständig"),
        "conflict": t("Konflikt beim Zusammenführen"),
        "invalid": t("Zusammengeführte Daten sind nicht gültig"),
        "dirty": t("Offene Änderungen außerhalb des Datenordners"),
        "detached": t("Kein Branch ausgewählt (detached HEAD)"),
        "no_upstream": t("Branch ist nicht mit dem Server verbunden"),
        "no_remote": t("Kein Server eingerichtet"),
        "not_repo": t("Kein Git-Repository"),
        "not_found": t("Repository nicht gefunden"),
        "unrelated_histories": t("Server hat eine andere Historie"),
        "tag_exists": t("Tag-Name ist schon vergeben"),
        "bad_url": t("Ungültige Adresse"),
        "secret_in_url": t("Zugangsdaten gehören nicht in die Adresse"),
        "insecure_url": t("Unverschlüsselte Verbindung"),
        "new_branch": t("Branch fehlt auf dem Server"),
        "remote_special": t("Ungewöhnliche Server-Einstellung"),
        "certificate": t("Zertifikat des Servers nicht anerkannt"),
        "folder": t("Ordner nicht nutzbar"),
        "nothing_to_share": t("Noch nichts zu teilen"),
    }
    return titles.get(kind, t("Git-Fehler"))


def hint_for(kind: str, url: str = "") -> str:
    """Nächster Schritt in Alltagssprache zu einer Fehlerart (leer, wenn es keinen gibt)."""
    if kind == "auth":
        return auth_help(url)
    hints = {
        "identity": t(
            "Git kennt deinen Namen noch nicht. Bitte in der Seitenleiste Name und "
            "E-Mail-Adresse eintragen."
        ),
        "locked": t(
            "Eine Datei ist gesperrt, weil ein anderes Programm (Git-Client, Editor, "
            "Virenscanner, Synchronisationsdienst) sie benutzt. Andere Programme schließen und "
            "noch einmal versuchen."
        ),
        "offline": t(
            "Der Server ist nicht erreichbar. Deine Änderungen bleiben lokal gesichert; "
            "Internetverbindung bzw. VPN prüfen und später erneut „Speichern und teilen“ wählen."
        ),
        "denied": t(
            "Der Server hat das Hochladen abgelehnt, etwa wegen eines geschützten Branches "
            "oder fehlender Schreibrechte. Deine Änderungen sind lokal gesichert; bitte "
            "bei der Betreuung des Repositorys nachfragen."
        ),
        "rejected": t(
            "Jemand anderes hat inzwischen Änderungen hochgeladen. Noch einmal "
            "„Speichern und teilen“ wählen, dann werden sie zuerst übernommen."
        ),
        "merge_in_progress": t(
            "Ein Zusammenführen ist unvollständig. Es kann abgebrochen werden; die eigenen "
            "Änderungen bleiben dabei erhalten."
        ),
        "conflict": t(
            "Dieselbe Stelle wurde von zwei Personen geändert. Auf der Seite „Konflikte "
            "lösen“ je Eintrag „meine“ oder „andere“ Änderung wählen, oder das "
            "Zusammenführen abbrechen. Es ist nichts verloren."
        ),
        "invalid": t(
            "Die Zusammenführung war technisch möglich, aber die Daten sind nun fachlich "
            "ungültig (siehe Liste). Nichts wurde hochgeladen. Bitte die Werte korrigieren und "
            "erneut „Speichern und teilen“ wählen – oder bewusst „Trotzdem teilen“."
        ),
        "dirty": t(
            "Es gibt nicht gesicherte Änderungen außerhalb des Datenordners, die mit den "
            "neuen Änderungen kollidieren. Diese bitte zuerst committen oder verwerfen."
        ),
        "detached": t(
            "Das Repository steht auf keinem Branch (detached HEAD). In der Seitenleiste "
            "„Zurück auf den Branch“ wählen."
        ),
        "no_upstream": t(
            "Der Branch ist noch nicht mit dem Server verbunden. „Speichern und teilen“ "
            "richtet das beim ersten Mal ein."
        ),
        "no_remote": t(
            "Zu diesem Datenordner gehört noch kein Server. Auf der Seite „Datenordner“ unter "
            "„Server (Remote)“ die Adresse des gemeinsamen Daten-Repositorys eintragen; bis "
            "dahin bleiben alle Änderungen auf diesem Rechner. Wer einem bestehenden Team "
            "beitritt, wählt dort „Repository klonen“."
        ),
        "not_repo": t(
            "Der Datenordner muss in einem Git-Repository liegen: mit `git init` ein neues "
            "anlegen oder mit `git clone` ein bestehendes holen."
        ),
        "not_found": t(
            "Das Repository wurde nicht gefunden oder du hast keinen Zugriff. Adresse und "
            "Berechtigung prüfen; die Adresse lässt sich auf der Seite „Datenordner“ unter "
            "„Server (Remote)“ ändern."
        ),
        "unrelated_histories": t(
            "Der Server enthält eine andere Historie als dieser Datenordner – vermutlich ist "
            "ein falsches Repository verbunden (z. B. ein Code-Repository). Es wurde nichts "
            "zusammengeführt und nichts hochgeladen; deine Änderungen sind lokal gesichert. "
            "Ist es das falsche Repository, lässt sich die Adresse auf der Seite „Datenordner“ "
            "unter „Server (Remote)“ ändern. Ist das Daten-Repository auf dem Server richtig, "
            "muss das Zusammenführen ausdrücklich bestätigt werden."
        ),
        "tag_exists": t(
            "Einen anderen Namen wählen oder den vorhandenen Tag zuerst entfernen. Die "
            "Änderungen sind unverändert und noch nicht gespeichert."
        ),
    }
    return hints.get(kind, "")


def auth_help(url: str = "") -> str:
    """Anmelde-Hilfe passend zur Adresse des Servers (https oder SSH). Der Text beginnt gleich
    mit dem nächsten Schritt und wiederholt die Ursache nicht: Wo der Hinweis unter der
    Überschrift (``title_for``) steht („Anmeldung fehlt oder wurde abgelehnt“), nennt sie schon
    diese; wo es keine gibt, stellt :meth:`GitError.full` sie voran."""
    if url.lower().startswith("ssh://") or _SCP_FORM.match(url):
        return t(
            "Diese Adresse nutzt die Anmeldung per SSH-Schlüssel. Dafür einen Schlüssel anlegen "
            "(`ssh-keygen -t ed25519`), den öffentlichen Teil (Datei `.pub`) beim Server "
            "(GitHub, GitLab …) unter „SSH-Schlüssel“ hinterlegen und den Schlüssel im "
            "ssh-agent ohne Kennwortabfrage verfügbar machen. Danach noch einmal versuchen."
        )
    return t(
        "Bei https braucht der Server meist einen Zugangstoken statt des Kennworts (GitHub: "
        "Settings › Developer settings › Personal access tokens; GitLab: Zugriffstoken mit dem "
        "Recht „write_repository“). Wer die GitHub-CLI nutzt, richtet die Anmeldung mit "
        "`gh auth setup-git` ein; sonst den Token im Anmeldedienst des Rechners hinterlegen "
        "oder beim nächsten Anmeldefenster als Kennwort eingeben. Danach noch einmal versuchen."
    )


# --- Server-Adresse prüfen ------------------------------------------------------------------

MAX_URL_LENGTH = 2048
# Übertragungswege, die Git für Adressen der App benutzen darf (kein ext::, fd:: oder git://).
SAFE_PROTOCOLS = "https:http:ssh:file"
PROBE_TIMEOUT = 30.0
# Bei http(s) bricht Git ab, wenn zehn Sekunden lang kaum etwas ankommt (Server nimmt an,
# antwortet aber nie).
_PROBE_ENV = {
    "GIT_ALLOW_PROTOCOL": SAFE_PROTOCOLS,
    "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
    "GIT_HTTP_LOW_SPEED_TIME": "10",
}
# Höchstens so viel Ausgabe (Zeichen) liest die Verbindungsprüfung je Strom.
_PROBE_OUTPUT_LIMIT = 64 * 1024

_HOST = r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[0-9A-Fa-f:.]+\])"
_SSH_USER = r"[A-Za-z0-9_][A-Za-z0-9._~-]*"
_HOST_PORT = re.compile(rf"({_HOST})(?::([^:]*))?")
_SCP_FORM = re.compile(rf"{_SSH_USER}@{_HOST}:")
_SCP_ADDRESS = re.compile(rf"({_SSH_USER})@({_HOST}):(\S+)")
_SCP_SECRET = re.compile(r"[^@/\\\s]*:[^@/\\\s]*@")  # u:kennwort@host:pfad
_HELPER = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*::")  # ext::, fd:: und andere Remote-Helfer
_URL_SCHEMES = {"https", "http", "ssh"}
_HOST_KEY = re.compile(r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED", re.I)
# Der Server antwortet, aber es gibt das Repository unter dieser Adresse nicht (oder er
# verschweigt es mangels Berechtigung): GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, https-404.
_NOT_FOUND = re.compile(
    r"does not appear to be a git repository|repository '[^']*' not found|"
    r"returned error: 404|Repository not found|Project not found|remote: Not Found|"
    r"project you were looking for could not be found|repository does not exist|"
    r"TF401019|does not exist or you do not have permission",
    re.I,
)
# Das Zertifikat des Servers wird vom Rechner nicht anerkannt (Firmenzertifikat, selbst
# ausgestellt): Der Server antwortet, Internet oder VPN zu prüfen nützt nichts.
_CERTIFICATE = re.compile(
    r"SSL certificate problem|certificate verification failed|SEC_E_UNTRUSTED_ROOT|"
    r"SEC_E_CERT_|CRYPT_E_|no alternative certificate subject name",
    re.I,
)
# Nur diese Meldungen belegen, dass der Server nicht erreichbar ist. „Could not read from remote
# repository“ allein tut das nicht: Git hängt es auch an, wenn der Server das Repository
# verweigert.
_UNREACHABLE = re.compile(
    r"Could not resolve|Couldn't resolve|Name or service not known|No such host is known|"
    r"Failed to connect|Couldn't connect|Connection (was )?(timed out|refused|reset|closed)|"
    r"Network is (unreachable|down)|No route to host|timed out|Operation too slow|"
    r"Temporary failure in name resolution|ssh: connect to host|Connection closed by|"
    r"Empty reply from server|Recv failure|Send failure|Timeout was reached",
    re.I,
)


@dataclass(frozen=True)
class RemoteAddress:
    """Eine geprüfte Server-Adresse. ``kind``: ``https``, ``http``, ``ssh`` (auch die Form
    ``benutzer@host:pfad``) oder ``local`` (vollständiger Ordnerpfad)."""

    url: str
    kind: str


def secret_in_url_error() -> GitError:
    """Fehler für eine Adresse mit Zugangsdaten oder Zusätzen nach ``?`` bzw. ``#`` (ohne die
    Eingabe zu wiederholen)."""
    return GitError(
        t(
            "Die Adresse enthält einen Benutzernamen, ein Kennwort, einen Token oder "
            "Parameter (alles ab „?“ oder „#“). Bitte nur die reine Adresse eintragen, z. B. "
            "https://server/team/daten.git; die Anmeldung übernimmt der Anmeldedienst des "
            "Rechners, fehlt sie, erklärt die App den nächsten Schritt (siehe Hilfe, "
            "„Anmeldung“)."
        ),
        "secret_in_url",
    )


def remote_special_error() -> GitError:
    """Fehler für einen Server mit mehreren Adressen oder eigener Upload-Adresse."""
    return GitError(
        t(
            "Für diesen Server sind mehrere Adressen oder eine eigene Upload-Adresse "
            "eingetragen. Das lässt sich hier nicht ändern – bitte mit einem Git-Programm "
            "bereinigen."
        ),
        "remote_special",
    )


class NewBranchError(GitError):
    """Der Server hat Branches, aber nicht den lokalen. ``str(error)`` ist Klartext; für die
    Oberfläche liefert :meth:`render` mit :func:`md_code` die Namen als Code, denn sie kommen
    vom Server bzw. aus der Konfiguration (siehe :func:`md_code`)."""

    def __init__(self, branch: str, heads: tuple[str, ...], unborn: bool = False) -> None:
        self.branch, self.heads, self.unborn = branch, heads, unborn
        super().__init__(self.render(), "new_branch")

    def __reduce__(self):  # kopier- und speicherbar trotz anderer Argumente als GitError
        return (NewBranchError, (self.branch, self.heads, self.unborn))

    def render(self, quote: Callable[[str], str] = str) -> str:
        """Meldung (höchstens fünf Servernamen genannt); ``quote`` wird auf jeden Namen
        angewendet."""
        names = ", ".join(quote(h) for h in self.heads[:5]) + (", …" if len(self.heads) > 5 else "")
        if self.unborn:
            text = t(
                "Dieser Datenordner enthält noch keine gespeicherten Daten, der Server aber "
                "schon (vorhanden: {heads}). Beim ersten Teilen würde dort ein neuer Branch "
                "„{branch}“ angelegt, ohne dass die Daten des Teams ankommen. Wer einem "
                "bestehenden Team beitritt, wählt stattdessen „Repository klonen“ weiter unten "
                "auf dieser Seite.",
                branch=quote(self.branch),
                heads=names,
            )
        else:
            text = t(
                "Auf dem Server gibt es den Branch „{branch}“ nicht (vorhanden: {heads}). Beim "
                "ersten Teilen würde er dort neu angelegt. Das ist nur richtig, wenn dies "
                "wirklich das Daten-Repository ist. Wer einem bestehenden Team beitritt, wählt "
                "stattdessen „Repository klonen“ weiter unten auf dieser Seite.",
                branch=quote(self.branch),
                heads=names,
            )
        return scrub(text)


def new_branch_error(branch: str, heads: tuple[str, ...], unborn: bool = False) -> NewBranchError:
    """Fehler, wenn der Server den lokalen Branch nicht hat. ``unborn``: Der Datenordner hat
    noch keinen Commit (Beitritt zu einem Team ist dann der häufige Grund)."""
    return NewBranchError(branch, heads, unborn)


def nothing_to_share_error() -> GitError:
    """Fehler, wenn „Speichern und teilen“ gewählt wird, obwohl der Datenordner noch nichts
    Gespeichertes enthält (kein Commit): Es gäbe nichts hochzuladen."""
    return GitError(
        t(
            "Der Datenordner enthält noch keine gespeicherten Daten, deshalb gibt es nichts zu "
            "teilen."
        ),
        "nothing_to_share",
        t(
            "Zuerst Daten anlegen (z. B. ein Team) und speichern. Wer einem bestehenden Team "
            "beitritt, wählt auf der Seite „Datenordner“ „Repository klonen“."
        ),
    )


def _bad_url(message: str) -> GitError:
    return GitError(message, "bad_url")


def _parse_url_form(text: str, scheme: str, rest: str, allow_insecure: bool) -> RemoteAddress:
    """Adresse der Form ``schema://…`` (https, http, ssh); ``text`` hat keine Steuerzeichen."""
    if scheme not in _URL_SCHEMES:
        raise _bad_url(
            t(
                "Dieses Verfahren wird nicht unterstützt. Erlaubt sind "
                "https://, ssh://, git@server:pfad und vollständige Ordnerpfade."
            )
        )
    if "\\" in text or not all("!" <= c <= "~" for c in text):
        raise _bad_url(t("Sie enthält Leerzeichen oder unzulässige Zeichen."))
    if "?" in rest or "#" in rest:
        raise secret_in_url_error()
    authority, _, path = rest.partition("/")
    if "@" in path:  # fängt auch https://u:12/ss@host/x
        raise secret_in_url_error()
    user, at, host_port = authority.rpartition("@")
    if at:
        if scheme != "ssh" or ":" in user:  # bei http(s) immer; bei ssh der Kennwortteil
            raise secret_in_url_error()
        if not re.fullmatch(_SSH_USER, user):
            raise _bad_url(t("Sie enthält Leerzeichen oder unzulässige Zeichen."))
    found = _HOST_PORT.fullmatch(host_port)
    if found is None:
        raise _bad_url(t("Der Servername ist ungültig."))
    port = found.group(2)
    if port is not None and not (port.isascii() and port.isdigit() and 0 < int(port) < 65536):
        raise _bad_url(t("Die Portnummer ist ungültig."))
    if not path.strip("/"):
        raise _bad_url(t("Es fehlt der Pfad zum Repository, z. B. …/team/sprint-daten.git."))
    if scheme == "http" and not allow_insecure:
        raise GitError(
            t(
                "Die Adresse beginnt mit http:// – Daten und Anmeldung würden unverschlüsselt "
                "übertragen. Besser https:// verwenden oder die unverschlüsselte Verbindung "
                "ausdrücklich bestätigen."
            ),
            "insecure_url",
        )
    return RemoteAddress(f"{scheme}://{rest}", scheme)


def parse_remote_url(raw: str, *, allow_insecure: bool = False) -> RemoteAddress:
    """Prüft eine Server-Adresse, bevor sie Git übergeben wird. Erlaubt sind ``https://``,
    ``ssh://``, ``benutzer@host:pfad``, vollständige lokale Ordnerpfade und (nur mit
    ``allow_insecure``) ``http://``. Alles andere – ``git://``, ``file://``, relative Pfade,
    Remote-Helfer (``ext::``), Zugangsdaten in der Adresse – wirft :class:`GitError` mit festem
    Text, der die Eingabe nie wiederholt."""
    text = raw.strip()
    if not text:
        raise _bad_url(t("Bitte eine Adresse eintragen."))
    if len(text) > MAX_URL_LENGTH:
        raise _bad_url(t("Sie ist zu lang."))
    # Steuerzeichen, Zeilentrenner und unsichtbare Zeichen (Zero-Width, Bidi, BOM).
    if any(
        unicodedata.category(c) in {"Zl", "Zp"} or unicodedata.category(c)[0] == "C" for c in text
    ):
        raise _bad_url(t("Sie enthält Zeilenumbrüche oder Steuerzeichen."))
    if text.startswith("-"):  # Git läse die Adresse sonst als Option
        raise _bad_url(t("Sie darf nicht mit „-“ beginnen."))
    if _HELPER.match(text):
        raise _bad_url(t("Spezielle Übertragungswege (z. B. „ext::“) sind nicht erlaubt."))
    if scheme := _SCHEME.match(text):
        return _parse_url_form(text, scheme.group(1).lower(), text[scheme.end() :], allow_insecure)
    if Path(text).is_absolute():  # die Plattform entscheidet, was „vollständig“ ist
        return RemoteAddress(text, "local")
    if _SCP_SECRET.match(text):
        raise secret_in_url_error()
    if found := _SCP_ADDRESS.fullmatch(text):
        if found.group(3).startswith("-"):
            raise _bad_url(t("Sie enthält Leerzeichen oder unzulässige Zeichen."))
        return RemoteAddress(text, "ssh")
    raise _bad_url(
        t(
            "Das Format wird nicht erkannt. Beispiele: "
            "https://server/team/daten.git, git@server:team/daten.git oder ein vollständiger "
            "Ordnerpfad."
        )
    )


class _ProbeRun(NamedTuple):
    """Ergebnis von :func:`_probe_run`. ``code``: ``None`` = Zeitüberschreitung (der
    Prozessbaum ist dann beendet). ``truncated``: Die Ausgabe war länger als das Limit."""

    code: int | None
    out: str
    err: str
    truncated: bool = False


def _read_output(file: IO[bytes]) -> tuple[str, bool]:
    """Die ersten 64 KB der Ausgabe als Text und ob es mehr gab."""
    file.seek(0)
    data = file.read(_PROBE_OUTPUT_LIMIT + 1)
    text = data[:_PROBE_OUTPUT_LIMIT].decode("utf-8", errors="replace")
    return text, len(data) > _PROBE_OUTPUT_LIMIT


def _probe_run(root: Path, args: tuple[str, ...], timeout: float) -> _ProbeRun:
    """Führt ``git`` für die Verbindungsprüfung aus: Rückgabecode, Ausgabe und Fehlerausgabe
    (je höchstens 64 KB, siehe :class:`_ProbeRun`).

    Ausgabe über Zwischendateien statt Pipes: Unter Windows hält ein Hilfsprozess von Git
    (``git-remote-http``) die Pipes offen, auch wenn der Aufruf längst beendet ist; ein Lesen
    bis zum Ende hinge dann. Bei Zeitüberschreitung wird der ganze Baum beendet."""
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(
                ["git", *args],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=_env(True, _PROBE_ENV),
                **{**proctree.popen_options(), **NO_WINDOW},
            )
            try:
                code: int | None = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proctree.terminate_tree(process)
                code = None
            text, truncated = _read_output(out)
            return _ProbeRun(code, text, _read_output(err)[0], truncated)
    except FileNotFoundError as e:
        raise classify("", missing=True) from e


def _heads_of(run: _ProbeRun) -> list[str]:
    """Branch-Namen aus der Ausgabe von ``git ls-remote --heads``. Ist die Ausgabe abgeschnitten,
    fällt die letzte (unvollständige) Zeile weg."""
    lines = run.out.split("\n")
    if run.truncated:
        lines = lines[:-1]
    prefix = "refs/heads/"
    heads = []
    for line in lines:
        _, _, ref = line.partition("\t")
        if ref.startswith(prefix):
            heads.append(ref[len(prefix) :].strip())
    return heads


def probe_remote(
    root: Path,
    address: RemoteAddress,
    timeout: float = PROBE_TIMEOUT,
    branch: str | None = None,
) -> tuple[str, ...]:
    """Fragt den Server nach seinen Branches (``git ls-remote``, ändert nichts) und liefert
    deren Namen. Ein leerer Server ist gültig (leere Liste). Fehler kommen als
    :class:`GitError` mit verständlichem Hinweis (siehe :func:`_probe_error`).

    Die Liste ist nicht gekürzt, solange die Ausgabe ins Limit passt (64 KB, rund 900 Branches).
    Bei mehr Branches fragt eine zweite Anfrage gezielt nach ``branch``: Der Name steht in der
    Liste, genau wenn der Server ihn hat. Das Kürzen für die Anzeige ist Sache der Oberfläche."""
    run = _probe_run(root, ("ls-remote", "--heads", "--", address.url), timeout)
    if run.code != 0:
        raise _probe_failure(run, address)
    heads = _heads_of(run)
    if branch and run.truncated and branch not in heads:
        wanted = _probe_run(
            root, ("ls-remote", "--heads", "--", address.url, f"refs/heads/{branch}"), timeout
        )
        if wanted.code != 0:
            raise _probe_failure(wanted, address)
        if branch in _heads_of(wanted):  # das Muster passt auch auf …/refs/heads/NAME
            heads.append(branch)
    return tuple(heads)


def _probe_failure(run: _ProbeRun, address: RemoteAddress) -> GitError:
    message = (run.err.strip() or run.out.strip())[:4000]
    return _probe_error(message, address, timed_out=run.code is None)


def _probe_error(message: str, address: RemoteAddress, timed_out: bool = False) -> GitError:
    """Macht aus der Fehlerausgabe der Verbindungsprüfung einen verständlichen Fehler. Die
    Zuordnung steht nur hier (classify bleibt unverändert): Git meldet ein nicht vorhandenes
    Repository oder eine verweigerte Berechtigung mit „Could not read from remote repository“,
    das classify als „offline“ liest; als „Server nicht erreichbar“ (``offline``) gilt hier nur,
    was einen Netzwerkfehler belegt (:data:`_UNREACHABLE`) oder die Zeitüberschreitung. Nur
    dann bietet die Oberfläche an, die Adresse ungeprüft zu speichern. Der Text von Git bleibt
    in ``str(error)`` (erscheint als „Technische Meldung“); es gibt immer einen Hinweis."""
    err = classify(message, timeout=timed_out)
    if timed_out:
        err.hint = _unreachable_hint()
    elif _HOST_KEY.search(message):
        err.kind = "auth"
        err.hint = t(
            "Der Rechner kennt diesen SSH-Server noch nicht (oder sein Schlüssel hat sich "
            "geändert). Die App kann das nicht bestätigen: Bitte einmal mit einem SSH- oder "
            "Git-Programm zum Server verbinden und den Fingerabdruck bestätigen, oder die "
            "https-Adresse des Repositorys verwenden. Danach hier noch einmal prüfen."
        )
    elif err.kind == "auth":
        err.hint = auth_help(address.url)
    elif _NOT_FOUND.search(message):
        err.kind = "not_found"
        err.hint = hint_for("not_found")
    elif _CERTIFICATE.search(message):
        err.kind = "certificate"
        err.hint = t(
            "Der Server antwortet, aber sein Sicherheitszertifikat wird von diesem Rechner nicht "
            "anerkannt (häufig ein Firmenzertifikat oder ein selbst ausgestelltes Zertifikat). "
            "Bitte die IT bitten, das Zertifikat auf dem Rechner zu hinterlegen. Die App ändert "
            "keine Git-Einstellungen und speichert die Adresse so nicht."
        )
    elif err.kind == "offline" and _UNREACHABLE.search(message):
        err.hint = _unreachable_hint()
    elif err.kind == "offline":  # z. B. „Could not read from remote repository“ ohne Grund
        err.kind = "error"
        err.hint = t(
            "Der Server hat die Anfrage nicht erfüllt. Bitte die Adresse (Tippfehler im "
            "Projektnamen?) und die Berechtigung prüfen. Die Meldung von Git steht unter "
            "„Technische Meldung“."
        )
    else:
        err.hint = t(
            "Die Verbindung zum Server ist fehlgeschlagen. Die Meldung von Git steht unter "
            "„Technische Meldung“."
        )
    return err


def _unreachable_hint() -> str:
    return t(
        "Der Server ist unter dieser Adresse nicht erreichbar. Bitte die Adresse "
        "(Tippfehler?), die Internetverbindung und das VPN prüfen. Ein Anmeldefenster des "
        "Rechners kann den Vorgang verzögern."
    )


def repo_root(path: Path) -> Path | None:
    """Wurzel des Git-Repositorys, in dem ``path`` liegt – oder None."""
    path = path.resolve()
    cached = _ROOT_CACHE.get(path)
    if cached and time.monotonic() - cached[0] < _ROOT_TTL:
        return cached[1]
    start = path
    while not start.exists():
        start = start.parent
    try:
        root = Path(_git(start if start.is_dir() else start.parent, "rev-parse", "--show-toplevel"))
    except GitError:
        root = None
    _ROOT_CACHE[path] = (time.monotonic(), root)
    return root


def forget_roots(path: Path) -> None:
    """Vergisst zwischengespeicherte Wurzeln für ``path``, darunter und darüber (nach
    ``git init`` oder ``git clone`` – sonst gälte „kein Repository“ noch bis zu 30 Sekunden)."""
    path = path.resolve()
    for key in [k for k in _ROOT_CACHE if k == path or path in k.parents or k in path.parents]:
        del _ROOT_CACHE[key]


@dataclass(frozen=True)
class Change:
    """Eine nicht committete Änderung. ``status``: M geändert, D gelöscht, A neu (vorgemerkt),
    R umbenannt, ?? neu (nicht vorgemerkt) – auch kombiniert (AM, RM, AD …). ``orig`` ist bei
    Umbenennungen und Kopien der bisherige Pfad."""

    status: str
    file: str  # relativ zur Repository-Wurzel
    orig: str = ""


def changes_in(path: Path) -> list[Change]:
    """Nicht committete Änderungen unterhalb von ``path``, bei Umbenennungen mit dem bisherigen
    Pfad."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    # Nicht strippen: Die Statusspalte beginnt ggf. mit einem Leerzeichen (" M datei").
    out = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        str(path.resolve()),
        strip=False,
    )
    entries = out.split("\0")
    changes = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, file, orig = entry[:2], entry[3:], ""
        if ("R" in xy or "C" in xy) and i < len(entries):  # der bisherige Pfad folgt
            orig = entries[i]
            i += 1
        changes.append(Change(xy.strip(), file, orig))
    return changes


def pending_changes(path: Path) -> list[tuple[str, str]]:
    """Nicht committete Änderungen unterhalb von ``path`` als (Status, Pfad relativ zur Wurzel);
    bei Umbenennungen der neue Pfad (den bisherigen liefert :func:`changes_in`)."""
    return [(c.status, c.file) for c in changes_in(path)]


_STATUS_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}
_STATUS_TTL = 5.0


def cached_pending_changes(path: Path) -> list[tuple[str, str]]:
    """Wie :func:`pending_changes`, aber höchstens alle paar Sekunden neu abgefragt (für die
    Oberfläche, die bei jeder Eingabe neu zeichnet). Nach Speichern, Commit und Wechsel des
    Datenordners mit :func:`invalidate_status` ungültig machen."""
    key = path.resolve()
    cached = _STATUS_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _STATUS_TTL:
        return list(cached[1])
    changes = pending_changes(path)
    _STATUS_CACHE[key] = (time.monotonic(), changes)
    return list(changes)


_INVALIDATE_HOOKS: list[Callable[[], object]] = []


def on_invalidate(hook: Callable[[], object]) -> None:
    """Meldet einen weiteren Zwischenspeicher an, der mit :func:`invalidate_status` geleert wird."""
    _INVALIDATE_HOOKS.append(hook)


def invalidate_status() -> None:
    """Verwirft zwischengespeicherte Git-Stände (nach Speichern, Commit, Synchronisation)."""
    _STATUS_CACHE.clear()
    for key in [k for k, (_, root) in _ROOT_CACHE.items() if root is None]:
        del _ROOT_CACHE[key]  # „kein Repository“ ist nicht von Dauer
    for hook in _INVALIDATE_HOOKS:
        hook()


def refuse_conflict_markers(root: Path, files: Iterable[Path]) -> None:
    """Verweigert das Committen von Datendateien, in denen noch Konfliktmarkierungen eines
    unvollständigen Zusammenführens stehen: Sie würden geteilt und sperrten dann die Bearbeitung
    bei allen anderen. ``files`` sind absolute Pfade; die Meldung nennt sie relativ zu ``root``
    (Sprintdateien und team.yaml heißen in jedem Team gleich)."""
    from sprintforecast.storage import has_conflict_markers  # storage importiert dieses Modul

    marked: list[str] = []
    for file in files:
        if not DATA_FILES.search(file.name):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:  # gelöscht oder nicht lesbar: nichts zu prüfen
            continue
        if has_conflict_markers(text):
            try:
                name = file.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                name = file.as_posix()
            if name not in marked:
                marked.append(name)
    if marked:
        names = ", ".join(marked)
        raise GitError(
            t(
                "In diesen Dateien stehen noch Konfliktmarkierungen (<<<<<<<, =======, "
                ">>>>>>>), sie werden nicht übernommen: {files}",
                files=names,
            ),
            "conflict",
            t(
                "Betroffen: {files}. Die Markierungen stammen aus einem unvollständigen "
                "Zusammenführen: im Editor entfernen oder, wenn die Seite „Konflikte lösen“ "
                "erscheint, dort den letzten Stand wiederherstellen.",
                files=names,
            ),
        )


def refuse_staged_conflict_markers(root: Path) -> None:
    """Wie :func:`refuse_conflict_markers` für alles, was gerade vorgemerkt ist (vor einem
    Commit, der nicht über :func:`commit_directory` läuft: Zusammenführen abschließen,
    Wiederherstellen, Zurücknehmen)."""
    staged = split_z(_git(root, "diff", "--cached", "--name-only", "-z", strip=False))
    refuse_conflict_markers(root, (root / name for name in staged))


def commit_directory(path: Path, message: str, tags: list[str] | None = None) -> str:
    """Committet alle Änderungen unterhalb von ``path`` (nur dort) und setzt optional Tags."""
    root = repo_root(path)
    if root is None:
        raise GitError(t("{path} liegt in keinem Git-Repository", path=path))
    changes = pending_changes(path)
    if not changes:
        raise GitError(t("Keine Änderungen zum Committen"))
    if blocked := [f for _, f in changes if FORBIDDEN.search(f)]:
        raise GitError(
            t(
                "Tabellenkalkulationen werden nicht committet – bitte entfernen oder in "
                ".gitignore aufnehmen: {files}",
                files=", ".join(blocked),
            )
        )
    refuse_conflict_markers(root, (root / f for status, f in changes if "D" not in status))
    names = check_new_tags(root, tags)  # vor dem Commit: bei einem Konflikt bleibt alles offen
    target = str(path.resolve())
    try:
        _git(root, "add", "--all", "--", target)
        _git(root, "commit", "-m", message, "--", target)
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


_NOT_A_REPOSITORY = re.compile(r"not a git repository", re.I)


def commit(paths: list[Path], message: str, tag: str | None = None) -> str:
    """Committet ``paths`` und setzt optional einen Tag. Gibt den Commit-Hash zurück."""
    cwd = paths[0].resolve().parent
    try:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    except GitError as e:
        if e.kind == "error" and _NOT_A_REPOSITORY.search(str(e)):
            raise GitError(
                t("{path} liegt in keinem Git-Repository", path=cwd),
                "not_repo",
                hint_for("not_repo"),
            ) from e
        raise
    refuse_conflict_markers(root, paths)
    names = check_new_tags(root, [tag] if tag else None)
    try:
        _git(root, "add", "--", *(str(p.resolve()) for p in paths))
        _git(root, "commit", "-m", message, "--", *(str(p.resolve()) for p in paths))
        for name in names:
            _git(root, "tag", "-a", "-m", message, "--", name)
    finally:
        invalidate_status()
    return _git(root, "rev-parse", "--short", "HEAD")


GITIGNORE = """\
# Tabellenkalkulationen nie committen – sie können echte Team-Daten enthalten.
*.xlsx
*.xlsm
*.xls
# Übrig gebliebene Zwischendateien des Speicherns.
*.tmp
"""


def folder_problem(path: Path, error: Exception) -> GitError:
    """Ein Dateisystemfehler am Ordner ``path`` als :class:`GitError` der Art ``folder`` mit
    Klartext (Pfade stehen als Code, denn die Meldung erscheint als Markdown)."""
    shown = md_code(str(path))
    if isinstance(error, PermissionError):
        message = t(
            "Keine Zugriffsrechte für {path} – bitte einen anderen Ordner wählen oder die "
            "Rechte anpassen.",
            path=shown,
        )
    else:
        reason = getattr(error, "strerror", None) or str(error)
        message = t(
            "{path} lässt sich nicht anlegen ({reason}) – bitte den Pfad prüfen.",
            path=shown,
            reason=reason,
        )
    return GitError(message, "folder")


@contextlib.contextmanager
def _folder_access(path: Path) -> Iterator[None]:
    """Der Zielordner ``path`` eines Anlegens bzw. Klonens: Eine Datei an dieser Stelle und
    Dateisystemfehler (keine Rechte, Pfad unbrauchbar, auch die von Git gemeldeten) kommen als
    :class:`GitError` der Art ``folder`` mit Klartext statt als rohe Ausnahme."""
    try:
        if path.is_file():
            raise GitError(
                t(
                    "{path} ist eine Datei, kein Ordner – bitte einen Ordner angeben.",
                    path=md_code(str(path)),
                ),
                "folder",
            )
        yield
    except (OSError, ValueError) as e:  # ValueError: Pfad mit NUL-Zeichen
        raise folder_problem(path, e) from e
    except GitError as e:
        if e.kind == "error" and "Permission denied" in str(e):
            raise folder_problem(path, PermissionError()) from e
        raise


def init_data_repository(path: Path, teams_folder: bool = True) -> Path:
    """Legt ein Daten-Repository an (git init, .gitignore, optional Ordner ``teams``) und
    liefert den Ordner für die Teams. Eine Datei als Ziel und Dateisystemfehler kommen als
    :class:`GitError` (Art ``folder``)."""
    with _folder_access(path):
        path.mkdir(parents=True, exist_ok=True)
        if repo_root(path) is None:
            _git(path, "init", "-q")
            forget_roots(path)
        ignore = path / ".gitignore"
        if not ignore.exists():
            ignore.write_text(GITIGNORE, encoding="utf-8")
        if not teams_folder:
            return path
        teams = path / "teams"
        teams.mkdir(exist_ok=True)
        return teams


def clone_repository(url: str, path: Path, timeout: float = 300) -> None:
    """Klont ein bestehendes Daten-Repository nach ``path``. Die Adresse wird wie bei
    :func:`parse_remote_url` geprüft (Zugangsdaten in der Adresse, relative Pfade, ``git://`` und
    ``file://`` werden abgelehnt). Fehler (Adresse, Zielordner, Anmeldung, Server nicht
    erreichbar, Zeitüberschreitung) kommen als :class:`GitError` mit nächstem Schritt."""
    # Beim Klonen reicht auch http:// (viele Repositories im Firmennetz haben nichts anderes).
    address = parse_remote_url(url, allow_insecure=True)
    path = Path(os.path.abspath(path))  # ein relatives Ziel wäre sonst relativ zu path.parent
    try:
        with _folder_access(path):
            if path.exists() and any(path.iterdir()):
                raise GitError(
                    t("{path} ist nicht leer", path=md_code(str(path))),
                    "folder",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            _git(
                path.parent,
                "clone",
                "--",
                address.url,
                str(path),
                network=True,
                timeout=timeout,
                env_extra={"GIT_ALLOW_PROTOCOL": SAFE_PROTOCOLS},
            )
    except GitError as e:
        if e.kind == "auth":
            e.hint = auth_help(address.url)
        raise
    finally:
        with contextlib.suppress(
            OSError, ValueError
        ):  # ein unbrauchbarer Pfad wurde schon gemeldet
            forget_roots(path)
