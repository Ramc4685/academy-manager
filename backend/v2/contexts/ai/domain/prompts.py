"""Prompt versions live in code, keyed by feature.

A feature's system prompt is a frozen value with a version string, so every
``ai_calls`` row can say exactly which prompt produced it. The placeholder
entry only proves the shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class PromptVersion:
    version: str
    system_text: str


PROMPTS: Final = MappingProxyType(
    {
        # Unused placeholder: no feature calls the model in Phase 1.
        "placeholder": PromptVersion(
            version="placeholder-v0",
            system_text="You are a placeholder. No feature uses this prompt.",
        ),
        # Phase 2 slice B2: the roster-import copilot proposes only the
        # column mapping; the existing dry run flags rows and groups families.
        "roster_import_map": PromptVersion(
            version="roster-import-map-v1",
            system_text=(
                "You map the columns of a spreadsheet export to the five columns of a "
                "family roster import. You are given the file's header names, a few "
                "sample rows (either real values or values masked to their shape, where "
                "every letter is a or A and every digit is 9) and the five target columns "
                "with their rules. Decide which header, or which pair of headers joined "
                "with a space (for example a first-name and a last-name column), fills "
                "each target. Use only the headers and samples given; invent nothing.\n"
                "Answer with JSON only, no prose and no code fence, exactly this shape:\n"
                '{"mappings": [{"target": "<one of the five target columns>", '
                '"source_headers": ["<header>"] or ["<header>", "<header>"], '
                '"confidence": "high" | "medium" | "low", "note": "<one short sentence>"}], '
                '"unmapped_headers": ["<every header you did not use>"], '
                '"notes": "<at most two short sentences for the person reviewing>"}\n'
                "Each target appears at most once. parent_name and student_name must be "
                "mapped. Leave a target out when no header fits it."
            ),
        ),
    }
)
