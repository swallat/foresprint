# SPDX-License-Identifier: EUPL-1.2
"""Generates the embedded holiday data of the Go core from the Python ``holidays`` library.

Writes ``go/internal/holidays/data/holidays.zip``: every country and region of the library,
2001-2050, with the names in all languages listed in ``LANGUAGES``. The file is a zip archive so
that the program decompresses only the countries it needs (a start-up cost of microseconds
instead of the 100 ms for the whole data). It is reproducible (sorted keys, fixed time stamps),
so a changed file always means a changed ``holidays`` version or a changed generator.

    uv run python scripts/gen_holidays.py            # write the file
    uv run python scripts/gen_holidays.py --check    # fail if the committed file is outdated

Contents (``format`` 1), all dates as days since the epoch 2001-01-01:

    meta.json            {"format": 1, "generator": "...", "holidays_version": "0.106",
                          "epoch": "2001-01-01", "first_year": 2001, "last_year": 2050,
                          "languages": ["de", "en"],
                          "aliases": {"UK": "GB", "DEU": "DE", ...},   # alternative codes
                          "countries": {"DE": "Germany", ...}}
    countries/DE.json    {"weekend": [5, 6], "subdivisions": ["BB", ...],
                          "names": [["Neujahr", "New Year's Day"], ...],  # one column per language
                          "subdivision_aliases": {"Bayern": "BY", ...},
                          "calendars": {"": {"days": [..], "names": [..]},   # "" = nationwide
                                        "BY": {...}}}

``days`` is delta-coded (the first value counts from the epoch, every further value from the
previous one); ``names`` holds one index into the country's ``names`` per holiday. Another
language is one more entry in ``languages`` and one more column in every ``names``; readers
look the column up by language code, so older readers stay compatible.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import warnings
import zipfile
from datetime import date, timedelta
from pathlib import Path

import holidays
from holidays import registry

# Countries that cover fewer years than FIRST_YEAR-LAST_YEAR make the library warn; that is fine.
warnings.simplefilter("ignore", UserWarning)

FORMAT = 1
EPOCH = date(2001, 1, 1)
FIRST_YEAR, LAST_YEAR = 2001, 2050
# Language code in the file -> language argument of the library. Not every language exists for
# every country; the library then falls back to the local language, as the Python core did.
LANGUAGES = {"de": "de", "en": "en_US"}
TARGET = Path(__file__).resolve().parent.parent / "go/internal/holidays/data/holidays.zip"


def country_names() -> dict[str, str]:
    """English names ("Saudi Arabia") from the class names of the library, as calendar.py shows
    them."""
    return {
        entry[1]: re.sub(r"(?<!^)(?=[A-Z])", " ", entry[0]) for entry in registry.COUNTRIES.values()
    }


def calendar(country: str, region: str | None, language: str) -> dict[date, str]:
    return dict(
        holidays.country_holidays(
            country, subdiv=region, years=range(FIRST_YEAR, LAST_YEAR + 1), language=language
        )
    )


def encode_calendar(
    code: str, region: str | None, names: dict[tuple[str, ...], int]
) -> dict | None:
    """Days and name indexes of one calendar; ``names`` is the country's name table."""
    per_language = [calendar(code, region, lib) for lib in LANGUAGES.values()]
    days = sorted(per_language[0])
    for other in per_language[1:]:
        # IsHoliday reads one language only; every language must have the same days.
        assert sorted(other) == days, f"{code}/{region}: languages differ in dates"
    if not days:
        return None
    indexes = []
    for day in days:
        entry = tuple(cal.get(day, "") for cal in per_language)
        indexes.append(names.setdefault(entry, len(names)))
    offsets, previous = [], 0
    for day in days:
        n = (day - EPOCH).days
        offsets.append(n - previous)
        previous = n
    return {"days": offsets, "names": indexes}


def build() -> dict[str, object]:
    """The files of the archive: path -> JSON-able content."""
    supported = holidays.list_supported_countries(include_aliases=False)
    country_name = country_names()
    files: dict[str, object] = {}
    for code in sorted(supported):
        names: dict[tuple[str, ...], int] = {}  # per country: a country file stands alone

        calendars = {}
        for region in [None, *supported[code]]:
            if (encoded := encode_calendar(code, region, names)) is not None:
                calendars[region or ""] = encoded
        # The library also accepts alias spellings ("Bayern") and deprecated codes of a region.
        # They get the calendar of the region they stand for; one that cannot be matched to an
        # existing calendar gets its own.
        cls = holidays.country_holidays(code).__class__
        spellings = {
            **dict(getattr(cls, "subdivisions_aliases", None) or {}),
            **{old: None for old in (getattr(cls, "_deprecated_subdivisions", None) or ())},
        }
        subdivision_aliases = {}
        for alias in sorted(spellings):
            if alias in calendars or alias in supported[code]:
                continue
            encoded = encode_calendar(code, alias, names)
            if encoded is None:
                continue
            match = next((r for r, c in calendars.items() if c == encoded), None)
            if match is not None:
                subdivision_aliases[alias] = match
            else:
                calendars[alias] = encoded
        files[f"countries/{code}.json"] = {
            "weekend": sorted(holidays.country_holidays(code).weekend),
            "subdivisions": list(supported[code]),
            "names": [list(entry) for entry in names],
            "subdivision_aliases": subdivision_aliases,
            "calendars": calendars,
        }
    aliases = {}
    for alias in holidays.list_supported_countries():
        if alias not in supported:
            aliases[alias] = holidays.country_holidays(alias).country
    files["meta.json"] = {
        "format": FORMAT,
        "generator": "scripts/gen_holidays.py",
        "holidays_version": holidays.__version__,
        "epoch": EPOCH.isoformat(),
        "first_year": FIRST_YEAR,
        "last_year": LAST_YEAR,
        "languages": list(LANGUAGES),
        "aliases": dict(sorted(aliases.items())),
        "countries": {code: country_name[code] for code in sorted(supported)},
    }
    return files


def encode(files: dict[str, object]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(2001, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            text = json.dumps(
                files[path], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            archive.writestr(info, text.encode("utf-8"), compresslevel=9)
    return buffer.getvalue()


def entries(archive: bytes) -> dict[str, set[tuple]]:
    """Per country: all (region, day, names) of an archive written by ``encode``."""
    result: dict[str, set[tuple]] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in zf.namelist():
            if not name.startswith("countries/"):
                continue
            content = json.loads(zf.read(name))
            rows = set()
            for region, cal in content["calendars"].items():
                day = 0
                for delta, index in zip(cal["days"], cal["names"], strict=True):
                    day += delta
                    rows.add((region, (EPOCH + timedelta(days=day)).isoformat(),
                              tuple(content["names"][index])))  # fmt: skip
            result[name.removeprefix("countries/").removesuffix(".json")] = rows
    return result


def meta(archive: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return json.loads(zf.read("meta.json"))


def summary(old: bytes, new: bytes) -> str:
    """Markdown list of what differs between two archives, for the pull request."""
    before, after = entries(old), entries(new)
    lines = []
    for country in sorted(before.keys() | after.keys()):
        a, b = before.get(country, set()), after.get(country, set())
        if a == b:
            continue
        lines.append(f"- {country}: {len(b - a)} added, {len(a - b)} removed (calendar entries)")
    return "\n".join(lines) if lines else "No difference in the holiday entries."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only compare, write nothing")
    parser.add_argument("--output", type=Path, default=TARGET)
    parser.add_argument(
        "--summary",
        type=Path,
        metavar="OLD",
        help="print a Markdown summary of the difference between OLD and the new data",
    )
    args = parser.parse_args()
    data = encode(build())
    if args.summary:
        print(summary(args.summary.read_bytes(), data))
        return 0
    if args.check:
        # Compare the content, not the bytes: deflate output differs between zlib builds.
        current = args.output.read_bytes() if args.output.is_file() else b""
        if not current or entries(current) != entries(data) or meta(current) != meta(data):
            print(f"{args.output} is outdated: run scripts/gen_holidays.py", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"{args.output}: {len(data) / 1024:.0f} KiB, holidays {holidays.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
