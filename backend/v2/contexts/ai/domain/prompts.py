"""Prompt versions live in code, keyed by feature.

A feature's system prompt is a frozen value with a version string, so every
``ai_calls`` row can say exactly which prompt produced it. No feature uses a
prompt yet; the placeholder entry only proves the shape.
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
    }
)
