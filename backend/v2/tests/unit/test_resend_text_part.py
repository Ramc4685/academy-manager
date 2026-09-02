"""The Resend adapter sends a plain-text twin next to the HTML body."""

from __future__ import annotations

import pytest
import resend

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)


@pytest.mark.asyncio
async def test_send_includes_plain_text_twin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_send(params):
        captured.update(params)
        return {"id": "m1"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    port = ResendEmailSendPort(api_key="k", from_address="a@b.test")
    await port.send(
        recipient=ResolvedRecipient(user_id="u", email="p@x.test", display_name=None),
        subject="s",
        body='<p>Hello <a href="https://x.test/pay">Pay now</a></p>',
    )
    assert captured["html"].startswith("<p>Hello")
    assert captured["text"] == "Hello Pay now (https://x.test/pay)"
