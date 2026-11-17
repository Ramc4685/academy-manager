"""Strict parse of a model's JSON answer (Track B rule: a malformed answer is
``AiProviderError`` -> 502, after the call has been recorded)."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from backend.v2.contexts.ai.domain.errors import AiProviderError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
UNREADABLE = "the model's answer could not be read"
#: A link-looking token. Mail clients auto-link these even after html.escape,
#: so parent-facing text that can skip review must not contain one. A domain is
#: a word character, a dot and a lowercase TLD with no space, so an ellipsis
#: ("...and") or a missed space before a sentence ("footwork.Next") is not one.
LINK_LIKE = re.compile(r"://|(?i:www\.)|@|(?<=\w)(?<!\.)\.[a-z]{2,}")


def parse_json_answer[T: BaseModel](text: str, model: type[T]) -> T:
    match = _FENCE.match(text)
    body = match.group(1) if match else text
    try:
        return model.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError(UNREADABLE) from exc
