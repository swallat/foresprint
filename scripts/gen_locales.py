# SPDX-License-Identifier: EUPL-1.2
"""Writes the text catalogs of the Go core from the Python translation table.

    uv run python scripts/gen_locales.py            # rewrite go/internal/i18n/data/
    uv run python scripts/gen_locales.py --check    # CI: fail if the files differ

One file per language, ``<code>.json``: ``{"code", "name", "texts"}``. The source texts are
English (the key); ``texts`` maps them to the translation. English has no entries. A new
language is a new file; nothing else changes in the program.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from foresprint.i18n import LANGUAGES
from foresprint.locale_de import DE

OUT = Path(__file__).resolve().parent.parent / "go" / "internal" / "i18n" / "data"
TABLES: dict[str, dict[str, str]] = {"de": DE, "en": {}}


def render(code: str) -> str:
    document = {"code": code, "name": LANGUAGES[code], "texts": dict(sorted(TABLES[code].items()))}
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the files differ")
    args = parser.parse_args()
    stale = []
    for code in TABLES:
        path, text = OUT / f"{code}.json", render(code)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        print("out of date (run scripts/gen_locales.py):", *map(str, stale), sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
