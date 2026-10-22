# SPDX-License-Identifier: EUPL-1.2
# ruff: noqa: E501
"""Golden references of the pure parts of ``foresprint.git``: address handling, Markdown quoting,
the recognition of Git's error messages and their texts.

Everything that reads the Git configuration or depends on the operating system is generated with
an empty Git configuration, from a folder that is no repository, and on Linux; the Go test skips
the comparison of those texts elsewhere.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from foresprint import git as gitmod
from foresprint.git import GitError
from foresprint.yamlmerge import MISSING  # noqa: F401  (keeps the import order stable)

ADDRESSES = [
    "https://github.com/team/data.git",
    "https://user:secret@github.com/team/data.git",
    "https://token@github.com/team/data.git",
    "https://host/path?token=abc#frag",
    "ssh://git@host.example:2222/team/data.git",
    "ssh://user:pw@host/team/data.git",
    "git@gitlab.example.com:team/data.git",
    "user:password@host:team/data.git",
    "HTTPS://Host/Team/Data.git",
    "/srv/git/data.git",
    "relative/path",
    "C:\\Users\\x\\data",
    "https://a@b@c/d",
    "http://insecure.example/x.git",
    "git://host/x.git",
    "file:///srv/git/x.git",
    "ext::sh -c touch% /tmp/x",
    "-oProxyCommand=evil",
    "",
    "   ",
    "https://host",
    "https://host/",
    "https://host:99999/x.git",
    "https://host:abc/x.git",
    "https://host:/x.git",
    "https://[::1]:8443/x.git",
    "https://bad host/x.git",
    "https://host/a b.git",
    "https://u:12/ss@host/x",
    "ssh://host/x.git",
    "ssh://-bad@host/x.git",
    "git@host:-bad",
    "x" * 2100,
    "https://host/\u202ex.git",
    "https://host/x.git\n",
    "  https://github.com/team/data.git  ",
    "https://äöü.example/x.git",
    "git@host:team/data.git extra",
    "host.example:team/data.git",
    "https://www.example.com/a/b.git?x=1",
    "ssh://git@host/x.git#frag",
]

TEXTS = [
    "",
    "plain text",
    "see https://user:pw@host/x.git?token=1 for details",
    "two https://a:b@h/x and ssh://git:pw@h2/y.git end",
    "xhttp://u:p@h/x and (https://u:p@h/y) and 1http://u:p@h/z",
    "a.b-c+d://u:p@host/x",
    "-https://u:p@h/x",
    "fatal: unable to access 'https://oauth2:glpat-abc@gitlab.example/team/x.git/': Could not resolve host",
    "http://x http://y?z",
    "ssh://u:p@h:22/x then more",
    "no scheme: u:p@h:path",
]

MD_TEXTS = [
    "",
    "plain",
    "a `b` c",
    "``double`` and `single`",
    "`start",
    "end`",
    " lead",
    "trail ",
    "line\nbreak\r\nand\rcr",
    "tab\there",
    "bidi \u202e reversed \u2066 isolate",
    "zero\u200dwidth joiner and \u200c non-joiner",
    "www.example.com/x and http://example.com *bold* _it_ [l](u) ![i](u) # h > q",
    "ctrl\x00\x01\x1f\x7f end",
    "\u2028para\u2029sep",
    "back\\slash and ~tilde~ and |pipe|",
]

MD_LINES = [
    "",
    "one",
    "one\ntwo",
    "one  \n\n  \ntwo   \n",
    "remote: line `with` ticks   \nremote: second\r\nlast",
    "a\u2028b",
]

MESSAGES = [
    "",
    "fatal: unable to auto-detect email address",
    "Author identity unknown\n\n*** Please tell me who you are.",
    "fatal: detected dubious ownership in repository at '/x'\nTo add an exception for this directory, call:\n\n\tgit config --global --add safe.directory /x",
    "error: unable to unlink old 'x.yaml': Device or resource busy",
    "error: unable to create file x.yaml: Permission denied",
    "fatal: could not create work tree dir 'x': Permission denied",
    "ssh: connect to host h port 22: Permission denied",
    "remote: Permission denied",
    "fatal: Unable to create '/x/.git/index.lock': File exists.",
    "fatal: Authentication failed for 'https://host/x.git/'",
    "fatal: could not read Username for 'https://host': terminal prompts disabled",
    "git@host: Permission denied (publickey).",
    "Host key verification failed.",
    "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@",
    "remote: HTTP Basic: Access denied",
    "fatal: unable to access 'https://h/x.git/': The requested URL returned error: 403",
    "fatal: repository 'https://h/x.git/' not found",
    "ERROR: Repository not found.\nfatal: Could not read from remote repository.",
    "fatal: unable to access 'https://h/x.git/': SSL certificate problem: self-signed certificate",
    "fatal: unable to access 'https://h/x.git/': Could not resolve host: h",
    "ssh: connect to host h port 22: Connection timed out\nfatal: Could not read from remote repository.",
    "fatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights",
    "remote: error: GH006: Protected branch update failed\nTo h\n ! [remote rejected] main -> main (protected branch hook declined)",
    "To h\n ! [rejected]        main -> main (fetch first)\nerror: failed to push some refs",
    "error: Pulling is not possible because you have unmerged files.",
    "fatal: You have not concluded your merge (MERGE_HEAD exists).",
    "CONFLICT (content): Merge conflict in team.yaml\nAutomatic merge failed; fix conflicts",
    "error: Your local changes to the following files would be overwritten by merge:\n\tx.yaml",
    "fatal: You are not currently on a branch.",
    "There is no tracking information for the current branch.",
    "fatal: No configured push destination.",
    "fatal: 'origin' does not appear to be a git repository",
    "something nobody expects",
    "fatal: refusing to merge unrelated histories",
]

# (message, url, drive_check) variants for the recognition with an address
URL_VARIANTS = [
    ("fatal: Authentication failed", "https://h/x.git"),
    ("fatal: Authentication failed", "ssh://git@h/x.git"),
    ("fatal: Authentication failed", "git@h:x.git"),
    ("Host key verification failed.", "git@h:x.git"),
    ("fatal: Authentication failed", ""),
]

KINDS = [
    "git_missing",
    "identity",
    "locked",
    "not_writable",
    "unsafe_directory",
    "auth",
    "offline",
    "denied",
    "rejected",
    "merge_in_progress",
    "conflict",
    "invalid",
    "dirty",
    "detached",
    "no_upstream",
    "no_remote",
    "not_repo",
    "not_found",
    "unrelated_histories",
    "tag_exists",
    "bad_url",
    "secret_in_url",
    "insecure_url",
    "new_branch",
    "remote_special",
    "certificate",
    "folder",
    "nothing_to_share",
    "sync_busy",
    "aborted",
    "error",
    "nonsense",
]

PROBE_MESSAGES = [
    ("fatal: unable to access 'https://h/x.git/': Could not resolve host: h", False),
    ("fatal: unable to access 'https://h/x.git/': error", False),
    ("fatal: unable to access 'https://h/x.git/': SSL certificate problem: x", False),
    ("fatal: Authentication failed", False),
    ("fatal: repository 'https://h/x.git/' not found", False),
    ("fatal: Could not read from remote repository.", False),
    ("fatal: something else entirely", False),
    ("ssh: connect to host h port 22: Connection refused", False),
    ("", True),
    ("fatal: Authentication failed", True),
    ("fatal: detected dubious ownership in repository", False),
    ("error: unable to create file x: Permission denied", False),
]

TAG_NAMES = [
    "v1",
    "sprint-2026.20",
    "-bad",
    "HEAD",
    "@",
    " lead",
    "trail ",
    "",
    "  ",
    "a b",
    "ok/name",
]


def error_json(e: GitError) -> dict[str, Any]:
    return {
        "message": str(e),
        "kind": e.kind,
        "hint": e.hint,
        "hint_md": e.hint_md,
        "raw": e.raw,
        "render_md": e.render(gitmod.md_code_lines),
        "full": e.full(),
    }


def guarded(fn):
    try:
        return {"ok": fn()}
    except GitError as e:
        return {"error": error_json(e)}


def generate(ctx) -> None:
    saved_env, saved_cwd = dict(os.environ), os.getcwd()
    try:
        _generate(ctx)
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)


def _generate(ctx) -> None:
    home = tempfile.mkdtemp(prefix="golden-git-home-")
    empty = tempfile.mkdtemp(prefix="golden-git-cwd-")
    os.environ.update(
        HOME=home,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    os.chdir(empty)
    cwd = Path(empty)
    gitmod.reset_git_cache()

    text = {
        "public_url": [
            {"in": a, "out": gitmod.public_url(a), "creds": gitmod.has_credentials(a)}
            for a in ADDRESSES + TEXTS
        ],
        "scrub": [{"in": s, "out": gitmod.scrub(s)} for s in TEXTS + ADDRESSES],
        "blank": [{"in": s, "out": gitmod.blank_controls(s)} for s in MD_TEXTS],
        "md_plain": [{"in": s, "out": gitmod.md_plain(s)} for s in MD_TEXTS],
        "md_code": [{"in": s, "out": gitmod.md_code(s)} for s in MD_TEXTS],
        "md_code_lines": [{"in": s, "out": gitmod.md_code_lines(s)} for s in MD_LINES + MD_TEXTS],
        "conflict_markers": [{"in": s, "out": _has_markers(s)} for s in MARKER_TEXTS],
    }
    ctx.write("git/text.json", ctx.dump_json(text))

    parsed = []
    for raw in ADDRESSES:
        for insecure in (False, True):

            def run(raw=raw, insecure=insecure):
                a = gitmod.parse_remote_url(raw, allow_insecure=insecure)
                return {"url": a.url, "kind": a.kind}

            parsed.append({"in": raw, "insecure": insecure, **guarded(run)})
    ctx.write("git/parse_url.json", ctx.dump_json(parsed))

    classified = []
    for message in MESSAGES:
        for url in ("", "https://h/x.git"):
            e = gitmod.classify(message, url=url, cwd=cwd)
            classified.append({"in": message, "url": url, **error_json(e)})
    for message, url in URL_VARIANTS:
        e = gitmod.classify(message, url=url, cwd=cwd)
        classified.append({"in": message, "url": url, **error_json(e)})
    for flag in ("missing", "timeout"):
        e = gitmod.classify("", **{flag: True}, cwd=cwd)
        item = {"in": "", "flag": flag, **error_json(e)}
        if flag == "missing":
            item["hint"] = item["hint_md"] = item["full"] = ""  # lists paths of this computer
        classified.append(item)
    ctx.write("git/classify.json", ctx.dump_json(classified))

    kinds = [{"kind": k, "title": gitmod.title_for(k), "hint": gitmod.hint_for(k)} for k in KINDS]
    ctx.write("git/kinds.json", ctx.dump_json(kinds))

    probes = []
    for message, timed_out in PROBE_MESSAGES:
        for url in ("https://h/x.git", "ssh://git@h/x.git"):
            e = gitmod._probe_error(message, gitmod.RemoteAddress(url, "https"), timed_out, cwd)
            probes.append({"in": message, "timed_out": timed_out, "url": url, **error_json(e)})
    ctx.write("git/probe_error.json", ctx.dump_json(probes))

    errors = []
    heads = ("main", "dev", "a", "b", "c", "d", "e")
    for branch, hs, unborn in (("main", ("dev",), False), ("main", heads, True), ("x", (), False)):
        e = gitmod.new_branch_error(branch, hs, unborn)
        errors.append({"what": "new_branch", **error_json(e)})
    e = gitmod.UnrelatedHistoriesError("https://u:p@h/x.git?x=1", "main")
    errors.append({"what": "unrelated", **error_json(e)})
    errors.append({"what": "secret", **error_json(gitmod.secret_in_url_error())})
    errors.append({"what": "special", **error_json(gitmod.remote_special_error())})
    errors.append({"what": "nothing", **error_json(gitmod.nothing_to_share_error())})
    errors.append({"what": "unwritable", "text": gitmod.unwritable_file_hint()})
    ctx.write("git/errors.json", ctx.dump_json(errors))

    names = []
    for name in TAG_NAMES:
        try:
            names.append({"in": name, "ok": gitmod.check_name(name) == name})
        except GitError as e:
            names.append({"in": name, "ok": False, "message": str(e)})
    records = [
        {"in": line, "count": n, "out": gitmod.split_record(line, n)}
        for line, n in (
            ("a\x1fb\x1fc", 3),
            ("a\x1fb", 3),
            ("", 2),
            ("a", 4),
            ("a\x1fb\x1fc\x1fd", 3),
        )
    ]
    zs = [{"in": s, "out": gitmod.split_z(s)} for s in ("", "a\0b\0", "\0\0a", "x")]
    ctx.write(
        "git/misc.json", ctx.dump_json({"tag_names": names, "records": records, "split_z": zs})
    )

    helpers = []
    for case in CREDENTIAL_CASES:
        cfg = Path(tempfile.mkdtemp(prefix="golden-git-cfg-")) / "config"
        cfg.write_text(case["config"], encoding="utf-8")
        os.environ["GIT_CONFIG_GLOBAL"] = str(cfg)
        try:
            helpers.append(
                {
                    "name": case["name"],
                    "config": case["config"],
                    "helpers": gitmod.credential_helpers(cwd),
                    "advice": gitmod.credential_advice(cwd),
                }
            )
        finally:
            os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    ctx.write("git/credential.json", ctx.dump_json(helpers))


def _has_markers(text: str) -> bool:
    from foresprint.storage import has_conflict_markers

    return has_conflict_markers(text)


MARKER_TEXTS = [
    "a: 1\n",
    "a: 1\n<<<<<<< HEAD\nb: 2\n=======\nb: 3\n>>>>>>> origin/main\n",
    "<<<<<<<\n=======\n>>>>>>>\n",
    "<<<<<<< HEAD\r\nb: 2\r\n=======\r\nb: 3\r\n>>>>>>> x\r\n",
    "<<<<<<< HEAD\nb\n>>>>>>> x\n",
    "text <<<<<<< HEAD\n=======\n>>>>>>> x\n",
    "<<<<<<<< HEAD\n=======\n>>>>>>> x\n",
]

CREDENTIAL_CASES = [
    {"name": "none", "config": ""},
    {"name": "manager", "config": "[credential]\n\thelper = manager\n"},
    {"name": "store", "config": "[credential]\n\thelper = store\n"},
    {"name": "store-with-options", "config": "[credential]\n\thelper = store --file=/x/y\n"},
    {
        "name": "store-path",
        "config": "[credential]\n\thelper = /usr/lib/git-core/git-credential-store\n",
    },
    {"name": "custom-script", "config": "[credential]\n\thelper = !f() { echo x; }; f\n"},
    {"name": "unknown", "config": "[credential]\n\thelper = frobnicate\n"},
    {"name": "cleared", "config": "[credential]\n\thelper = store\n\thelper =\n"},
    {
        "name": "cleared-then-set",
        "config": "[credential]\n\thelper = store\n\thelper =\n\thelper = osxkeychain\n",
    },
    {
        "name": "url-scoped-empty",
        "config": '[credential]\n\thelper = libsecret\n[credential "https://h"]\n\thelper =\n',
    },
    {
        "name": "two",
        "config": "[credential]\n\thelper = cache --timeout=60\n\thelper = manager-core\n",
    },
    {
        "name": "exe-path",
        "config": "[credential]\n\thelper = C:/Program Files/Git/mingw64/bin/git-credential-manager.exe\n",
    },
    {"name": "oauth", "config": "[credential]\n\thelper = oauth\n"},
]
