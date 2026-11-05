"""Strict parse of a model's JSON answer (Track B rule: a malformed answer is
``AiProviderError`` -> 502, after the call has been recorded)."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from backend.v2.contexts.ai.domain.errors import AiProviderError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
UNREADABLE = "the model's answer could not be read"


def parse_json_answer[T: BaseModel](text: str, model: type[T]) -> T:
    match = _FENCE.match(text)
    body = match.group(1) if match else text
    try:
        return model.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError(UNREADABLE) from exc
