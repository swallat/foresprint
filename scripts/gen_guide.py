# SPDX-License-Identifier: EUPL-1.2
"""Writes the help texts of the Go core (``go/internal/guide/data/guide.json``) from guide.py.

    uv run python scripts/gen_guide.py            # rewrite the file
    uv run python scripts/gen_guide.py --check    # CI: fail if the file differs

The texts are English source texts; the program translates them with the text catalogs.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from foresprint import guide

OUT = Path(__file__).resolve().parent.parent / "go" / "internal" / "guide" / "data" / "guide.json"


def render() -> str:
    document = {
        "fields": [{"key": k, **dataclasses.asdict(v)} for k, v in guide.FIELDS.items()],
        "workflow": [dataclasses.asdict(s) for s in guide.WORKFLOW],
        "terms": [list(x) for x in guide.TERMS],
        "git_help": [list(x) for x in guide.GIT_HELP],
        "capacity_sources": [list(x) for x in guide.CAPACITY_SOURCES],
        "commands": [list(x) for x in guide.COMMANDS],
        "topics": [[k, v] for k, v in guide.TOPICS.items()],
    }
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file differs")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"out of date (run scripts/gen_guide.py): {OUT}")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
