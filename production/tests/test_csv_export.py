"""CSV export safety tests (formula injection, numeric fidelity)."""

import csv
import io
from decimal import Decimal

import pytest

from production.services import csv_export


@pytest.mark.parametrize(
    "hostile",
    [
        "=1+1",
        "+SUM(A1:A2)",
        "-2+3",
        "@SUM(A1)",
        "\t=1+1",
        "\r=1+1",
        "  =cmd|' /C calc'!A0",
        "=HYPERLINK(\"http://example.invalid\",\"x\")",
    ],
)
def test_hostile_text_is_neutralised(hostile):
    cell = csv_export.sanitize_cell(hostile)
    assert cell.startswith("'")
    assert cell == "'" + hostile


@pytest.mark.parametrize("safe", ["SYN-ORD-001", "Machine stopped", "", "a=b", "1+1"])
def test_ordinary_text_is_unchanged(safe):
    assert csv_export.sanitize_cell(safe) == safe


def test_negative_decimal_stays_machine_readable():
    assert csv_export.sanitize_cell(Decimal("-15")) == "-15"
    assert csv_export.sanitize_cell(Decimal("85.500")) == "85.500"


def test_none_becomes_empty_cell():
    assert csv_export.sanitize_cell(None) == ""


def test_to_csv_round_trips_with_csv_reader():
    text = csv_export.to_csv(["code", "variance"], [["SYN-1", Decimal("-15")], ["=BAD", None]])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["code", "variance"]
    assert rows[1] == ["SYN-1", "-15"]
    assert rows[2] == ["'=BAD", ""]


def test_to_csv_empty_rows_still_has_header():
    text = csv_export.to_csv(["a", "b"], [])
    assert text.strip() == "a,b"
