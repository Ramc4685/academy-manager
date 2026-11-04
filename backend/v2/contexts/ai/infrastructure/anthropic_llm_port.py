"""Anthropic Messages API over plain httpx (no SDK; httpx is already pinned).

Constructed only by ``composition.ai.compose_ai`` when ``V2_AI_ENABLED`` and
``V2_ANTHROPIC_API_KEY`` are both set (structural test
``test_email_sender_construction``), the way the Resend sender is gated.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.v2.contexts.ai.domain.errors import AiProviderError
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, LlmResult

log = logging.getLogger(__name__)

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 60.0

#: List price in cents per million tokens, by model. Rounded up to a whole
#: cent per call so the audit never under-counts against the cap.
PRICE_CENTS_PER_MTOK: dict[str, tuple[int, int]] = {DEFAULT_MODEL: (300, 1500)}


def cost_cents(model: str, input_tokens: int, output_tokens: int) -> int:
    in_price, out_price = PRICE_CENTS_PER_MTOK[model]
    micro = input_tokens * in_price + output_tokens * out_price
    return (micro + 999_999) // 1_000_000


class AnthropicLlmPort:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport

    async def complete(
        self, *, prompt_version: str, system: str, user: str, max_tokens: int
    ) -> LlmResult:
        body = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                resp = await client.post(MESSAGES_URL, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise AiProviderError(f"anthropic request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise AiProviderError(f"anthropic answered {resp.status_code}", status=resp.status_code)
        data: dict[str, Any] = resp.json()
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        model = str(data.get("model") or self._model)
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        result = LlmResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents(self._model, input_tokens, output_tokens),
            model=model,
        )
        log.info(
            "ai_call model=%s prompt_version=%s in=%d out=%d cost_cents=%d stop=%s",
            model,
            prompt_version,
            input_tokens,
            output_tokens,
            result.cost_cents,
            data.get("stop_reason"),
        )
        return result
