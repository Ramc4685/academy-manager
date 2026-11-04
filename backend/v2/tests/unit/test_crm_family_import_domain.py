"""CSV family import parsing (roadmap L8a): strict columns, caps, formula
sanitising, per-row validation and in-file family grouping. Pure; synthetic
names only."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.contexts.crm.domain.errors import InvalidImportFile
from backend.v2.contexts.crm.domain.family_import import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    group_rows,
    parse_family_csv,
    strip_formula_prefix,
)

TODAY = date(2026, 9, 24)
HEADER = "parent_name,parent_email,parent_phone,student_name,student_date_of_birth\n"


def _parse(body: str, header: str = HEADER):  # type: ignore[no-untyped-def]
    return parse_family_csv(header + body, today=TODAY)


def test_a_clean_row_is_normalised() -> None:
    parsed = _parse("  Pat   Testparent ,PAT@Example.TEST,(555) 010-2030,Kit Testkid,2016-05-04\n")
    (row,) = parsed.rows
    assert row.line == 2
    assert row.parent_name == "Pat Testparent"
    assert row.parent_email == "pat@example.test"
    assert row.parent_phone == "5550102030"
    assert row.student_name == "Kit Testkid"
    assert row.student_date_of_birth == "2016-05-04"
    assert row.is_valid and row.warnings == ()


def test_bom_and_header_case_and_spaces_are_accepted() -> None:
    parsed = parse_family_csv(
        "﻿ Parent_Name , STUDENT_NAME,parent_email\nPat,Kit,pat@example.test\n", today=TODAY
    )
    assert parsed.columns == ("parent_name", "student_name", "parent_email")
    assert parsed.rows[0].is_valid


@pytest.mark.parametrize(
    ("header", "detail"),
    [
        ("parent_name,student_name,notes\n", "unknown_columns"),
        ("parent_name,parent_name,student_name\n", "repeated_columns"),
        ("parent_email,student_name\n", "missing_columns"),
    ],
)
def test_the_header_is_strict(header: str, detail: str) -> None:
    with pytest.raises(InvalidImportFile) as caught:
        parse_family_csv(header + "a,b,c\n", today=TODAY)
    assert detail in caught.value.details


@pytest.mark.parametrize("body", ["", "\n\n", HEADER, HEADER + ",,,,\n"])
def test_an_empty_file_or_no_rows_is_refused(body: str) -> None:
    with pytest.raises(InvalidImportFile):
        parse_family_csv(body, today=TODAY)


def test_the_size_cap_is_in_bytes() -> None:
    filler = "é" * (MAX_IMPORT_BYTES // 2)  # two bytes each in UTF-8
    with pytest.raises(InvalidImportFile) as caught:
        _parse(f"Pat,pat@example.test,,{filler},\n")
    assert caught.value.details["max_bytes"] == MAX_IMPORT_BYTES


def test_the_row_cap() -> None:
    rows = "".join(f"Pat,p{i}@example.test,,Kid {i},\n" for i in range(MAX_IMPORT_ROWS + 1))
    with pytest.raises(InvalidImportFile) as caught:
        _parse(rows)
    assert caught.value.details["max_rows"] == MAX_IMPORT_ROWS
    assert len(_parse(rows.split("\n", 1)[1]).rows) == MAX_IMPORT_ROWS


def test_non_utf8_bytes_and_nul_are_refused() -> None:
    with pytest.raises(InvalidImportFile):
        parse_family_csv((HEADER + "Pat,,5550102030,K\xe9,\n").encode("latin-1"), today=TODAY)
    with pytest.raises(InvalidImportFile):
        _parse("Pat\x00,,5550102030,Kit,\n")


def test_malformed_csv_is_refused_with_its_line() -> None:
    with pytest.raises(InvalidImportFile) as caught:
        _parse('Pat,pat@example.test,,"Kit\n')
    assert "line" in caught.value.details


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("=HYPERLINK(1)", "HYPERLINK(1)"), ("+-@=Pat", "Pat"), ("- Pat", "Pat"), ("Pat", "Pat")],
)
def test_strip_formula_prefix(raw: str, clean: str) -> None:
    assert strip_formula_prefix(raw)[0] == clean


def test_formula_prefixes_are_removed_from_names_with_a_warning() -> None:
    (row,) = _parse("\"=cmd|' /C calc'!A0\",pat@example.test,,@Kit Testkid,\n").rows
    assert row.parent_name == "cmd|' /C calc'!A0"
    assert row.student_name == "Kit Testkid"
    assert row.is_valid
    assert len(row.warnings) == 2


def test_a_name_that_is_only_a_formula_prefix_is_an_error() -> None:
    (row,) = _parse("Pat,pat@example.test,,=,\n").rows
    assert [issue.field for issue in row.errors] == ["student_name"]


@pytest.mark.parametrize(
    ("cells", "field"),
    [
        (",pat@example.test,,Kit,", "parent_name"),
        ("Pat,pat@example.test,,,", "student_name"),
        ("Pat,=pat@example.test,,Kit,", "parent_email"),
        ("Pat,@example.test,,Kit,", "parent_email"),
        ("Pat,not-an-email,,Kit,", "parent_email"),
        ("Pat,a@b@example.test,,Kit,", "parent_email"),
        ("Pat,,12345,Kit,", "parent_phone"),
        ("Pat,,555-CALL-NOW,Kit,", "parent_phone"),
        ("Pat,,,Kit,", "parent_email"),
        ("Pat,pat@example.test,,Kit,05/04/2016", "student_date_of_birth"),
        ("Pat,pat@example.test,,Kit,2016-02-30", "student_date_of_birth"),
        ("Pat,pat@example.test,,Kit,2027-01-01", "student_date_of_birth"),
        ("Pat,pat@example.test,,Kit,1899-12-31", "student_date_of_birth"),
        ("Pat,pat@example.test,,Kit,2016-05-04,extra", "row"),
        (f"{'P' * 121},pat@example.test,,Kit,", "parent_name"),
        (f"Pat,pat@example.test,,{'K' * 1001},", "student_name"),
    ],
)
def test_row_errors_name_their_field(cells: str, field: str) -> None:
    (row,) = _parse(cells + "\n").rows
    assert not row.is_valid
    assert field in [issue.field for issue in row.errors]


def test_blank_rows_are_skipped_but_line_numbers_stay_true() -> None:
    parsed = _parse("\nPat,pat@example.test,,Kit,\n,,,,\nSam,sam@example.test,,Lee,\n")
    assert [row.line for row in parsed.rows] == [3, 5]


def test_missing_optional_columns_are_fine() -> None:
    parsed = parse_family_csv(
        "parent_name,student_name,parent_phone\nPat,Kit,555 010 2030\n", today=TODAY
    )
    assert parsed.rows[0].parent_phone == "5550102030"
    assert parsed.rows[0].parent_email is None


def test_grouping_by_email_then_phone() -> None:
    parsed = _parse(
        "Pat Testparent,pat@example.test,555-010-2030,Kit One,\n"
        "Pat Testparent,,+1 555 010 2030,Kit Two,\n"  # phone only: joins Pat by phone
        "Sam Testparent,,555-010-9999,Lee One,\n"
        "Sam Testparent,,5550109999,Lee Two,\n"
        "Pat T.,PAT@example.test,,Kit Three,\n"  # same email, different name
        "Bad Row,,,Nobody,\n"
    )
    rows, keys = group_rows(parsed.rows)
    assert keys == {
        2: "email:pat@example.test",
        3: "email:pat@example.test",
        4: "phone:5550109999",
        5: "phone:5550109999",
        6: "email:pat@example.test",
    }
    assert 7 not in keys
    assert rows[4].warnings and "line 2" in rows[4].warnings[0]


def test_the_same_child_twice_in_a_family_is_an_error_on_the_later_row() -> None:
    parsed = _parse(
        "Pat,pat@example.test,,Kit Testkid,\n"
        "Pat,pat@example.test,,  kit  TESTKID ,\n"
        "Sam,sam@example.test,,Kit Testkid,\n"  # another family: fine
    )
    rows, keys = group_rows(parsed.rows)
    assert rows[0].is_valid and rows[2].is_valid
    assert not rows[1].is_valid
    assert "line 2" in rows[1].errors[0].message
    assert set(keys) == {2, 4}
