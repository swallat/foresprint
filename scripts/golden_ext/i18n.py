# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the text catalogs: every translatable text with each placeholder filled
in with the value ``<name>``, in German and English. The Go test (go/internal/i18n) compares the
digest of all of them and the readable sample."""

from __future__ import annotations

import hashlib
import re

from foresprint import i18n
from foresprint.locale_de import DE

_PLACEHOLDER = re.compile(r"\{(\w+)(!r)?\}")
SAMPLE = 40


def _render(code: str, text: str) -> str:
    values = {name: f"<{name}>" for name, _ in _PLACEHOLDER.findall(text)}
    i18n.set_language(code)
    try:
        return i18n.t(text, **values)
    finally:
        i18n.set_language("en")


def generate(ctx) -> None:
    keys = sorted(DE)
    rows = {code: [_render(code, key) for key in keys] for code in ("de", "en")}
    digests = {
        code: hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
        for code, texts in rows.items()
    }
    step = max(1, len(keys) // SAMPLE)
    sample = [
        {"text": keys[i], "de": rows["de"][i], "en": rows["en"][i]}
        for i in range(0, len(keys), step)
    ]
    document = {"count": len(keys), "digest": digests, "sample": sample}
    ctx.write("i18n/catalog.json", ctx.dump_json(document))
