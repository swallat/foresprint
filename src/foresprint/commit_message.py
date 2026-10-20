# SPDX-License-Identifier: EUPL-1.2
"""Suggests a commit message from the changed files and values.

The suggestion is built from :class:`foresprint.diff.FileChange` (the data of the change
view), so it names what really changed: the file, and for a single value the old and the new
value. The result is one line; the user can edit it before committing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

from foresprint.diff import ADDED, REMOVED, FileChange, ValueChange
from foresprint.i18n import t

MAX_LENGTH = 72  # conventional limit of a commit subject line
_MAX_VALUE = 20  # characters of one old or new value in the message
_MAX_NAMES = 3  # file names listed for a change of several files


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _value(v: Any) -> str:
    """A scalar as written in the file; lists and mappings only as a hint."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dict | list):
        return "{…}" if isinstance(v, dict) else "[…]"
    return _short(str(v), _MAX_VALUE)


def _value_change(file: str, v: ValueChange) -> str:
    label = _short(v.label, MAX_LENGTH)
    if v.kind == ADDED:
        return t("Add {label} in {file}: {new}", label=label, file=file, new=_value(v.new))
    if v.kind == REMOVED:
        return t("Remove {label} from {file}", label=label, file=file)
    return t(
        "Update {label} in {file}: {old} → {new}",
        label=label,
        file=file,
        old=_value(v.old),
        new=_value(v.new),
    )


def _single(fc: FileChange) -> str:
    file = fc.file
    if fc.orig and "C" in fc.status:
        return t("Copy {orig} to {file}", orig=fc.orig, file=file)
    if fc.orig:
        return t("Rename {orig} to {file}", orig=fc.orig, file=file)
    if "D" in fc.status:
        return t("Remove {file}", file=file)
    if "A" in fc.status or fc.status == "??":
        return t("Add {file}", file=file)
    if len(fc.values) == 1 and not fc.omitted:
        return _value_change(file, fc.values[0])
    if fc.values:
        return t("Update {file}: {n} values", file=file, n=len(fc.values) + fc.omitted)
    return t("Update {file}", file=file)


def _names(files: Sequence[FileChange]) -> list[str]:
    """The first file names, without the folder where that stays unambiguous."""
    count = Counter(PurePosixPath(fc.file).name for fc in files)
    shown = files[:_MAX_NAMES]
    return [
        name if count[name] == 1 else fc.file
        for name, fc in ((PurePosixPath(fc.file).name, fc) for fc in shown)
    ]


def suggest_message(files: Sequence[FileChange]) -> str | None:
    """A one-line commit message for these changes; ``None`` without any change."""
    if not files:
        return None
    if len(files) == 1:
        message = _single(files[0])
    else:
        shown = ", ".join(_names(files))
        more = len(files) - _MAX_NAMES
        message = (
            t(
                "Update {n} files: {names} and {more} more",
                n=len(files),
                names=shown,
                more=more,
            )
            if more > 0
            else t("Update {n} files: {names}", n=len(files), names=shown)
        )
    return _short(message, MAX_LENGTH)
