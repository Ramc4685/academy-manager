"""Family and student CSV import: parsing, sanitising and validating (roadmap L8a).

Pure: no I/O. The use cases in ``application/use_cases/family_import.py``
take what this module parses, ask the duplicate finder about each family and
store the plan as an import batch.

The file
--------

UTF-8 CSV (a leading byte-order mark is fine), one row per child, at most
:data:`MAX_IMPORT_BYTES` bytes and :data:`MAX_IMPORT_ROWS` data rows. The
header is strict: every column must be one of :data:`IMPORT_COLUMNS`
(case and surrounding spaces ignored), each at most once, and the
:data:`REQUIRED_COLUMNS` must be present. Anything else refuses the whole
file (:class:`InvalidImportFile`), because a misspelled column would
otherwise be silently dropped.

=========================  ========  ======================================
Column                     Required  Rule
=========================  ========  ======================================
``parent_name``            yes       1-120 characters
``student_name``           yes       1-120 characters
``parent_email``           one of    a single address, at most 254 chars
``parent_phone``           these     7-15 digits in any punctuation
``student_date_of_birth``  no        ``YYYY-MM-DD``, not in the future
=========================  ========  ======================================

A row with no value at all is skipped (spreadsheets export trailing blank
rows). Every other problem is a per-row error, reported with the file's line
number, and the file is still previewed so staff can see every problem at
once.

Formula injection
-----------------

A cell starting with ``=``, ``+``, ``-`` or ``@`` runs as a formula when the
data is later opened in a spreadsheet. Names have those leading characters
removed (the row carries a warning saying so). An email that starts with
one is an error (no real address does). Phones are stored as digits only,
so they cannot carry a formula.

Families in the file
--------------------

Rows are grouped into families by the parent's normalised email; a row with
only a phone joins the family whose emailed rows share that phone, else
forms its own. :func:`group_rows` returns each usable row's family key. The
same child twice in one family is an error on the later row.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

from backend.v2.contexts.crm.domain.duplicates import probe_email, probe_phone_variants
from backend.v2.contexts.crm.domain.errors import InvalidImportFile
from backend.v2.contexts.crm.domain.family_index import phone_digits
from backend.v2.contexts.crm.domain.models import normalize_email, normalize_text
from backend.v2.shared.names import full_name_key

MAX_IMPORT_BYTES: Final = 1_000_000
MAX_IMPORT_ROWS: Final = 1_000
MAX_NAME_LENGTH: Final = 120
MAX_EMAIL_LENGTH: Final = 254
#: Longest raw cell accepted before anything is normalised.
MAX_CELL_LENGTH: Final = 1_000
MIN_PHONE_DIGITS: Final = 7
MAX_PHONE_DIGITS: Final = 15
EARLIEST_BIRTH_YEAR: Final = 1900

REQUIRED_COLUMNS: Final = ("parent_name", "student_name")
IMPORT_COLUMNS: Final = (
    "parent_name",
    "parent_email",
    "parent_phone",
    "student_name",
    "student_date_of_birth",
)

#: Leading characters a spreadsheet treats as the start of a formula.
FORMULA_PREFIXES: Final = ("=", "+", "-", "@")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LETTERS = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class RowIssue:
    field: str
    message: str


@dataclass(frozen=True)
class ImportRow:
    """One data row, normalised. ``errors`` empty means the row is usable."""

    #: The line in the file (the header is line 1).
    line: int
    parent_name: str
    student_name: str
    parent_email: str | None = None
    #: Digits only.
    parent_phone: str | None = None
    student_date_of_birth: str | None = None
    errors: tuple[RowIssue, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def student_key(self) -> str:
        return full_name_key(self.student_name)


@dataclass(frozen=True)
class ParsedImport:
    rows: tuple[ImportRow, ...]
    #: Every column the header named, in file order (after normalising).
    columns: tuple[str, ...] = ()


def strip_formula_prefix(value: str) -> tuple[str, bool]:
    """``value`` without leading formula characters, and whether any went."""
    text = value
    changed = False
    while text and text[0] in FORMULA_PREFIXES:
        text = text[1:].lstrip()
        changed = True
    return text, changed


def canonical_phone(digits: str | None) -> str | None:
    """One spelling per phone number (the national form for North America)."""
    variants = probe_phone_variants(digits)
    return variants[0] if variants else None


def _header(raw: Sequence[str]) -> tuple[str, ...]:
    lowered = tuple((normalize_text(cell) or "").lower() for cell in raw)
    unknown = [name for name in lowered if name not in IMPORT_COLUMNS]
    if unknown:
        raise InvalidImportFile(
            "The file has columns this import does not know.",
            unknown_columns=unknown,
            allowed_columns=list(IMPORT_COLUMNS),
        )
    repeated = sorted({name for name in lowered if lowered.count(name) > 1})
    if repeated:
        raise InvalidImportFile("A column appears more than once.", repeated_columns=repeated)
    missing = [name for name in REQUIRED_COLUMNS if name not in lowered]
    if missing:
        raise InvalidImportFile("Required columns are missing.", missing_columns=missing)
    return lowered


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        size = len(data.encode("utf-8", errors="surrogatepass"))
        text = data
    else:
        size = len(data)
        if size > MAX_IMPORT_BYTES:
            text = ""
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidImportFile("The file is not UTF-8 text.") from exc
    if size > MAX_IMPORT_BYTES:
        raise InvalidImportFile(
            "The file is too large.", max_bytes=MAX_IMPORT_BYTES, size_bytes=size
        )
    if "\x00" in text:
        raise InvalidImportFile("The file is not a text CSV file.")
    return text.removeprefix("﻿")


def parse_family_csv(data: bytes | str, *, today: date) -> ParsedImport:
    """Parse and validate the file. Raises :class:`InvalidImportFile` for a
    problem with the file as a whole; row problems are on each row."""
    text = _decode(data)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows: list[ImportRow] = []
    try:
        header_cells = next(reader, None)
        if header_cells is None or not any(cell.strip() for cell in header_cells):
            raise InvalidImportFile("The file is empty.")
        columns = _header(header_cells)
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_IMPORT_ROWS:
                raise InvalidImportFile("The file has too many rows.", max_rows=MAX_IMPORT_ROWS)
            rows.append(_row(reader.line_num, columns, cells, today=today))
    except csv.Error as exc:
        raise InvalidImportFile(
            "The file could not be read as CSV.", line=reader.line_num, reason=str(exc)
        ) from exc
    if not rows:
        raise InvalidImportFile("The file has a header but no rows.")
    return ParsedImport(rows=tuple(rows), columns=columns)


def _name(
    raw: str, field_name: str, label: str, errors: list[RowIssue], warnings: list[str]
) -> str:
    text, stripped = strip_formula_prefix(normalize_text(raw) or "")
    if stripped:
        warnings.append(f"{label}: leading = + - @ characters were removed.")
    if not text:
        errors.append(RowIssue(field_name, f"{label} is required."))
    elif len(text) > MAX_NAME_LENGTH:
        errors.append(RowIssue(field_name, f"{label} is longer than {MAX_NAME_LENGTH} characters."))
    return text


def _email(raw: str, errors: list[RowIssue]) -> str | None:
    text = normalize_email(raw)
    if text is None:
        return None
    if text.startswith(FORMULA_PREFIXES):
        errors.append(RowIssue("parent_email", "Email must not start with = + - or @."))
        return None
    if len(text) > MAX_EMAIL_LENGTH or probe_email(text) != text:
        errors.append(RowIssue("parent_email", "Email is not a valid address."))
        return None
    return text


def _phone(raw: str, errors: list[RowIssue]) -> str | None:
    text = normalize_text(raw)
    if text is None:
        return None
    digits = phone_digits(text)
    if _LETTERS.search(text) or not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        errors.append(
            RowIssue(
                "parent_phone",
                f"Phone must have {MIN_PHONE_DIGITS} to {MAX_PHONE_DIGITS} digits.",
            )
        )
        return None
    return digits


def _birth_date(raw: str, errors: list[RowIssue], *, today: date) -> str | None:
    text = normalize_text(raw)
    if text is None:
        return None
    parsed: date | None = None
    if _ISO_DATE.match(text):
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            parsed = None
    if parsed is None:
        errors.append(RowIssue("student_date_of_birth", "Date of birth must be YYYY-MM-DD."))
        return None
    if parsed > today or parsed.year < EARLIEST_BIRTH_YEAR:
        errors.append(RowIssue("student_date_of_birth", "Date of birth is not a plausible date."))
        return None
    return parsed.isoformat()


def _row(line: int, columns: Sequence[str], cells: Sequence[str], *, today: date) -> ImportRow:
    errors: list[RowIssue] = []
    warnings: list[str] = []
    if len(cells) > len(columns):
        errors.append(RowIssue("row", "The row has more values than the header has columns."))
    values = {name: (cells[i] if i < len(cells) else "") for i, name in enumerate(columns)}
    for name, value in list(values.items()):
        if len(value) > MAX_CELL_LENGTH:
            errors.append(RowIssue(name, f"Value is longer than {MAX_CELL_LENGTH} characters."))
            values[name] = ""
    parent_name = _name(values["parent_name"], "parent_name", "Parent name", errors, warnings)
    student_name = _name(values["student_name"], "student_name", "Student name", errors, warnings)
    email = _email(values.get("parent_email", ""), errors)
    phone = _phone(values.get("parent_phone", ""), errors)
    birth = _birth_date(values.get("student_date_of_birth", ""), errors, today=today)
    contact_error = any(issue.field in ("parent_email", "parent_phone") for issue in errors)
    if email is None and phone is None and not contact_error:
        errors.append(RowIssue("parent_email", "Give the parent's email or phone."))
    return ImportRow(
        line=line,
        parent_name=parent_name,
        student_name=student_name,
        parent_email=email,
        parent_phone=phone,
        student_date_of_birth=birth,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def group_rows(rows: Iterable[ImportRow]) -> tuple[list[ImportRow], dict[int, str]]:
    """Group usable rows into the file's families.

    Returns the rows (with any grouping error or warning added) and, for
    every usable row, its family key by line. A row carrying an error has no
    key.
    """
    ordered = list(rows)
    keys: dict[int, str] = {}
    by_phone: dict[str, str] = {}
    for row in ordered:
        if row.is_valid and row.parent_email:
            key = f"email:{row.parent_email}"
            keys[row.line] = key
            phone = canonical_phone(row.parent_phone)
            if phone:
                by_phone.setdefault(phone, key)
    for row in ordered:
        if row.is_valid and not row.parent_email:
            phone = canonical_phone(row.parent_phone)
            if phone:
                keys[row.line] = by_phone.get(phone, f"phone:{phone}")

    first_parent: dict[str, ImportRow] = {}
    seen_child: dict[tuple[str, str], int] = {}
    result: list[ImportRow] = []
    for row in ordered:
        found = keys.get(row.line)
        if found is None:
            result.append(row)
            continue
        key = found
        extra_errors: list[RowIssue] = []
        extra_warnings: list[str] = []
        first = first_parent.setdefault(key, row)
        if first is not row and full_name_key(first.parent_name) != full_name_key(row.parent_name):
            extra_warnings.append(
                f"Parent name differs from line {first.line}; "
                f"the family keeps {first.parent_name!r}."
            )
        child = (key, row.student_key)
        if child in seen_child:
            extra_errors.append(
                RowIssue("student_name", f"The same child is already on line {seen_child[child]}.")
            )
            del keys[row.line]
        else:
            seen_child[child] = row.line
        if extra_errors or extra_warnings:
            row = replace(
                row,
                errors=row.errors + tuple(extra_errors),
                warnings=row.warnings + tuple(extra_warnings),
            )
        result.append(row)
    return result, keys
