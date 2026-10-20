# SPDX-License-Identifier: EUPL-1.2
"""CSV export of Jira as ticket source: English and German headers, repeated columns, delimiter
and BOM, decimal comma, missing columns."""

from pathlib import Path

import pytest

from sprintforecast.model import TrackerFields
from sprintforecast.sources import RawTicket, SourceError
from sprintforecast.sources.csv import CsvSource, parse_number, sniff_delimiter
from sprintforecast.storage import DataError

DATA = Path(__file__).parent / "data"
FIELDS = TrackerFields(estimate="Story Points", remaining="Remaining", epic="Epic Link")


def test_english_export_with_repeated_columns():
    source = CsvSource(DATA / "jira_en.csv", FIELDS)
    assert source.kind == "csv" and source.name == "jira_en.csv"
    tickets = source.fetch()
    assert [tk.key for tk in tickets] == ["ABC-1", "ABC-2", "ABC-3", "ABC-4"]
    assert tickets[0] == RawTicket(
        key="ABC-1",
        title="Checkout: new payment provider",
        status="To Do",
        issue_type="Story",
        estimate=5,
        remaining=3.5,
        sprint_name="Sprint 22",  # the last of several Sprint columns
        rank="0|i0001:",
        epic="ABC-100",
        labels=["payment", "Refined"],
        components=["Checkout"],
        blocked_by=["ABC-2", "ABC-3"],  # inward "Blocks" links, the outward one is ignored
        resolved=False,
    )
    second = tickets[1]
    assert second.title == "Schema change, part 1"  # quoted comma
    assert second.remaining is None and second.sprint_name is None and second.labels == []
    assert second.blocked_by == [] and second.epic == "ABC-200"
    done = tickets[2]
    assert done.resolved and done.sprint_name == "Sprint 20" and done.remaining == 0
    assert tickets[3].estimate is None and tickets[3].title == "Line one line two"


def test_german_export_with_semicolon_bom_decimal_comma_and_parent_as_epic():
    fields = TrackerFields(estimate="Story Points", remaining="Remaining")  # epic: Parent column
    tickets = CsvSource(DATA / "jira_de.csv", fields).fetch()
    assert tickets[0] == RawTicket(
        key="DEF-1",
        title="Zahlung umstellen",
        status="In Arbeit",
        issue_type="Story",
        estimate=2.5,
        remaining=1.5,
        sprint_name="Sprint 22",
        rank="0|i0001:",
        epic="DEF-100",
        labels=["payment"],
        components=["Kasse"],
        blocked_by=["DEF-2"],
    )
    assert tickets[1].title == "Schema; Teil 1" and tickets[1].epic is None
    assert tickets[2].resolved and tickets[2].estimate == 1


def test_bare_field_names_and_case_insensitive_headers(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("issue KEY,summary,Story Points,Remaining,Epic Link\nK-1,T,3,1,K-9\n")
    [ticket] = CsvSource(path, FIELDS).fetch()
    assert ticket == RawTicket(key="K-1", title="T", estimate=3, remaining=1, epic="K-9")


def test_configured_epic_column_absent_leaves_epic_empty(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Issue key,Summary,Story Points,Parent\nK-1,T,3,K-9\n")
    [ticket] = CsvSource(path, FIELDS).fetch()
    assert ticket.epic is None  # "Epic Link" is configured, so Parent is not used


def test_missing_estimate_column_names_the_expected_headers():
    with pytest.raises(SourceError) as e:
        CsvSource(DATA / "jira_missing.csv", FIELDS).fetch()
    message = str(e.value)
    assert "jira_missing.csv" in message
    for header in (
        "„Custom field (Story Points)“",
        "„Benutzerdefiniertes Feld (Story Points)“",
        "„Story Points“",
    ):
        assert header in message
    assert "Issue key" not in message  # present columns are not listed
    assert isinstance(e.value, DataError)


def test_missing_key_and_title_columns_are_reported_together(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Custom field (Story Points),Status\n3,To Do\n")
    with pytest.raises(SourceError) as e:
        CsvSource(path, FIELDS).fetch()
    lines = str(e.value).splitlines()
    assert len(lines) == 2
    assert "„Issue key“ / „Vorgangsschlüssel“" in lines[0]
    assert "„Summary“ / „Zusammenfassung“" in lines[1]


def test_estimate_field_not_configured(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Issue key,Summary\nK-1,T\n")
    with pytest.raises(SourceError, match=r"tracker\.fields\.estimate"):
        CsvSource(path, TrackerFields()).fetch()


def test_value_that_is_not_a_number(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Issue key,Summary,Story Points\nK-1,T,3\nK-2,T,viel\n")
    with pytest.raises(SourceError) as e:
        CsvSource(path, FIELDS).fetch()
    assert str(e.value).endswith(
        "Zeile 3: 'viel' in Spalte „Custom field (Story Points)“ ist keine Zahl"
    )


def test_row_without_key(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Issue key,Summary,Story Points\n,T,3\n")
    with pytest.raises(SourceError, match="Zeile 2: Schlüssel fehlt"):
        CsvSource(path, FIELDS).fetch()


def test_empty_missing_and_binary_files(tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(SourceError, match="leer"):
        CsvSource(empty, FIELDS).fetch()
    with pytest.raises(SourceError, match="nicht lesbar"):
        CsvSource(tmp_path / "nope.csv", FIELDS).fetch()
    binary = tmp_path / "latin.csv"
    binary.write_bytes("Issue key,Summary,Story Points\nK-1,Grüße,3\n".encode("latin-1"))
    with pytest.raises(SourceError, match="UTF-8"):
        CsvSource(binary, FIELDS).fetch()


def test_header_only_file_has_no_tickets(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text("Issue key,Summary,Story Points\n")
    assert CsvSource(path, FIELDS).fetch() == []


def test_number_parsing_and_delimiter_sniffing():
    assert parse_number("") is None and parse_number("  ") is None
    assert parse_number("3") == 3 and parse_number("2,5") == 2.5 and parse_number("2.5") == 2.5
    assert parse_number("1.234,5") == 1234.5 and parse_number("1,234.5") == 1234.5
    for bad in ("abc", "nan", "inf"):
        with pytest.raises(ValueError):
            parse_number(bad)
    assert sniff_delimiter("Issue key,Summary,Custom field (Rank)") == ","
    assert sniff_delimiter("Vorgangsschlüssel;Zusammenfassung;Benutzerdefiniertes Feld (Rang)") == (
        ";"
    )
    assert sniff_delimiter('"a, b";c;d') == ";"


# --- Review fixes ----------------------------------------------------------------------------

HEADER = "Summary,Issue key,Custom field (Story Points)\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "export.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_unterminated_quote_is_an_error_with_the_line(tmp_path: Path):
    path = write(tmp_path, HEADER + "ok,A-1,1\n" + '"never closed,A-2,2\nmore,A-3,3\n')
    with pytest.raises(SourceError, match="Zeile 3"):
        CsvSource(path, FIELDS).fetch()


def test_text_after_a_closing_quote_is_an_error(tmp_path: Path):
    path = write(tmp_path, HEADER + '"quoted" word,A-1,1\n')
    with pytest.raises(SourceError, match="Zeile 2"):
        CsvSource(path, FIELDS).fetch()


@pytest.mark.parametrize("value", ["-1", "-0.5", "-2,5"])
def test_negative_numbers_are_refused_with_the_line(tmp_path: Path, value: str):
    path = write(tmp_path, HEADER + 'ok,A-1,1\n"neg",A-2,"' + value + '"\n')
    with pytest.raises(SourceError, match=r"Zeile 3.*negativ"):
        CsvSource(path, FIELDS).fetch()


def test_negative_remaining_is_refused_too(tmp_path: Path):
    path = write(
        tmp_path,
        "Summary,Issue key,Custom field (Story Points),Custom field (Remaining)\nx,A-1,1,-3\n",
    )
    with pytest.raises(SourceError, match="negativ"):
        CsvSource(path, FIELDS).fetch()
    ok = write(
        tmp_path,
        "Summary,Issue key,Custom field (Story Points),Custom field (Remaining)\nx,A-1,0,0\n",
    )
    assert [(tk.estimate, tk.remaining) for tk in CsvSource(ok, FIELDS).fetch()] == [(0, 0)]


def test_negative_zero_is_stored_as_zero(tmp_path: Path):
    path = write(tmp_path, HEADER + "x,A-1,-0\n")
    value = CsvSource(path, FIELDS).fetch()[0].estimate
    assert value == 0 and str(value) == "0.0"


def test_rule_fields_are_read_from_their_columns(tmp_path: Path):
    path = tmp_path / "x.csv"
    path.write_text(
        "Issue key,Summary,Story Points,Custom field (Customer),Customer\n"
        "K-1,T,3,Acme,Beta\nK-2,T,1,,\n"
    )
    a, b = CsvSource(path, FIELDS, {"customer": "Customer"}).fetch()
    assert a.extra == {"customer": ["Acme", "Beta"]} and b.extra == {}
