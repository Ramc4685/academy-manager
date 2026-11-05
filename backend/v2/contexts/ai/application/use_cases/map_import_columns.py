"""Roster-import copilot (plan 2026-11-04 Phase 2, slice B2): propose the
COLUMN MAPPING from any spreadsheet export to the five family-import columns.

Only the mapping is the model's job. Bad-row flags and family grouping come
from the existing import dry run once the file is in the five-column shape,
so the model never needs the whole file: it sees the header row and at most
:data:`SAMPLE_ROWS` data rows. By default every sample cell is masked to its
shape (``Jane Doe`` -> ``Aaaa Aaa``, ``(309) 555-0123`` -> ``(999) 999-9999``);
real values go only when the academy turned ``ai.share_import_values`` on.

Nothing here reads or writes the database except the ``ai_calls`` row, and
nothing the model answers is saved: the frontend rewrites the CSV client
side and the existing preview and commit stay the approval gate.

The import's caps and column rules are duplicated here as constants because
``ai`` may not import ``crm`` (``test_layering``); ``test_ai_map_import_columns``
pins them equal to the CRM's.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.v2.contexts.ai.application.ports import ImportValueSharing, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiImportSampleRejected, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE: Final = "roster_import_map"
MAX_TOKENS: Final = 1500

#: Mirrors ``contexts/crm/domain/family_import.py``.
MAX_IMPORT_BYTES: Final = 1_000_000
MAX_IMPORT_ROWS: Final = 1_000
IMPORT_COLUMNS: Final = (
    "parent_name",
    "parent_email",
    "parent_phone",
    "student_name",
    "student_date_of_birth",
)
REQUIRED_COLUMNS: Final = ("parent_name", "student_name")
COLUMN_RULES: Final = {
    "parent_name": "required; 1-120 characters",
    "parent_email": "one of email or phone is required; a single address, at most 254 characters",
    "parent_phone": "one of email or phone is required; 7-15 digits in any punctuation",
    "student_name": "required; 1-120 characters",
    "student_date_of_birth": "optional; YYYY-MM-DD, not in the future",
}

SAMPLE_ROWS: Final = 5
MASK_CELL_LENGTH: Final = 24
MAX_HEADER_LENGTH: Final = 80

TargetColumn = Literal[
    "parent_name", "parent_email", "parent_phone", "student_name", "student_date_of_birth"
]

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class ColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetColumn
    #: One header, or two joined with a space in this order.
    source_headers: list[str] = Field(min_length=1, max_length=2)
    confidence: Literal["high", "medium", "low"]
    note: str = ""


class ColumnMappingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[ColumnMapping]
    unmapped_headers: list[str] = []
    notes: str = ""


@dataclass(frozen=True)
class ImportSample:
    """Exactly what the model is allowed to see, plus ``file_headers`` (never
    sent) to translate the answer back when a header was relabeled."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    masked: bool
    file_headers: tuple[str, ...]


@dataclass(frozen=True)
class MapImportColumnsResult:
    draft: ColumnMappingDraft
    sample_mode: Literal["masked", "values"]
    prompt_version: str


def mask_cell(value: str) -> str:
    """The cell's shape: letters -> a/A (case kept), digits -> 9, the rest as is."""
    out = []
    for ch in value[:MASK_CELL_LENGTH]:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        else:
            out.append(ch)
    return "".join(out)


def _header_labels(headers: tuple[str, ...]) -> tuple[str, ...]:
    """Masked mode: a header that looks like data (an email means the file has
    no header row, so every column is relabeled; otherwise 4+ digits or over 40
    characters) becomes its column label instead of leaking a cell."""
    if any("@" in h for h in headers):
        return tuple(f"(column {i + 1})" for i in range(len(headers)))
    return tuple(
        f"(column {i + 1})" if sum(c.isdigit() for c in h) >= 4 or len(h) > 40 else h
        for i, h in enumerate(headers)
    )


def read_sample(csv_text: str, *, share_values: bool) -> ImportSample:
    """The header row and the first :data:`SAMPLE_ROWS` non-blank data rows,
    masked unless ``share_values``. Header names go as written unless they look
    like data (see :func:`_header_labels`)."""
    if len(csv_text.encode("utf-8", errors="surrogatepass")) > MAX_IMPORT_BYTES:
        raise AiImportSampleRejected("The file is too large.", max_bytes=MAX_IMPORT_BYTES)
    if "\x00" in csv_text:
        raise AiImportSampleRejected("The file is not a text CSV file.")
    reader = csv.reader(io.StringIO(csv_text.removeprefix("﻿"), newline=""), strict=True)
    try:
        header_cells = next(reader, None)
        if header_cells is None or not any(cell.strip() for cell in header_cells):
            raise AiImportSampleRejected("The file is empty.")
        headers = tuple(
            (cell.strip() or f"(column {i + 1})")[:MAX_HEADER_LENGTH]
            for i, cell in enumerate(header_cells)
        )
        rows: list[tuple[str, ...]] = []
        count = 0
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            count += 1
            if count > MAX_IMPORT_ROWS:
                raise AiImportSampleRejected(
                    "The file has too many rows.", max_rows=MAX_IMPORT_ROWS
                )
            if len(rows) < SAMPLE_ROWS:
                padded = tuple(
                    cells[i].strip() if i < len(cells) else "" for i in range(len(headers))
                )
                rows.append(padded if share_values else tuple(mask_cell(c) for c in padded))
    except csv.Error as exc:
        raise AiImportSampleRejected("The file could not be read as CSV.", reason=str(exc)) from exc
    if not rows:
        raise AiImportSampleRejected("The file has a header but no rows.")
    return ImportSample(
        headers=headers if share_values else _header_labels(headers),
        rows=tuple(rows),
        masked=not share_values,
        file_headers=headers,
    )


def user_message(sample: ImportSample) -> str:
    """Built only from the sample and the target rules: never from a request
    dict or a stored document."""
    facts = {
        "headers": list(sample.headers),
        "sample_rows_are": "masked to shape (letters a/A, digits 9, cut to 24 characters)"
        if sample.masked
        else "real values",
        "sample_rows": [list(row) for row in sample.rows],
        "target_columns": [{"name": name, "rule": COLUMN_RULES[name]} for name in IMPORT_COLUMNS],
    }
    return json.dumps(facts, ensure_ascii=False, indent=1)


def parse_draft(text: str, *, headers: tuple[str, ...]) -> ColumnMappingDraft:
    """Strict: a fenced or bare JSON object in the exact shape, every target at
    most once, both required targets present, every source header from the
    file and used once. Anything else is a provider error (502)."""
    try:
        draft = ColumnMappingDraft.model_validate(json.loads(_FENCE.sub("", text)))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError("the model's answer could not be read") from exc
    targets = [m.target for m in draft.mappings]
    used = [h for m in draft.mappings for h in m.source_headers] + draft.unmapped_headers
    known = set(headers)
    if (
        len(set(targets)) != len(targets)
        or len(set(used)) != len(used)
        or any(required not in targets for required in REQUIRED_COLUMNS)
        or any(h not in known for m in draft.mappings for h in m.source_headers)
        or any(h not in known for h in draft.unmapped_headers)
    ):
        raise AiProviderError("the model's answer could not be read")
    return draft


class MapImportColumns:
    def __init__(
        self, *, llm: LlmPort, record_ai_call: RecordAiCall, sharing: ImportValueSharing
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._sharing = sharing

    async def execute(self, *, csv_text: str, approver: str) -> MapImportColumnsResult:
        await self._record.assert_under_cap()
        share = await self._sharing.share_values()
        sample = read_sample(csv_text, share_values=share)
        prompt = PROMPTS[FEATURE]
        result = await self._llm.complete(
            prompt_version=prompt.version,
            system=prompt.system_text,
            user=user_message(sample),
            max_tokens=MAX_TOKENS,
        )
        # Recorded before parsing so a malformed answer is still counted.
        await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=approver
        )
        draft = parse_draft(result.text, headers=sample.headers)
        # Relabeled headers back to the file's names so the frontend can match them.
        back = dict(zip(sample.headers, sample.file_headers, strict=True))
        for m in draft.mappings:
            m.source_headers = [back[h] for h in m.source_headers]
        draft.unmapped_headers = [back[h] for h in draft.unmapped_headers]
        return MapImportColumnsResult(
            draft=draft,
            sample_mode="masked" if sample.masked else "values",
            prompt_version=prompt.version,
        )
