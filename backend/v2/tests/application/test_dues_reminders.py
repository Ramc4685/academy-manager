"""Dues reminder selection behavior."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases import admin_payment_ops


class CapturingReminderSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_dues_reminders(
        self,
        *,
        parent_ids: list[str] | None,
        generate_invoice_artifacts: bool,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "parent_ids": parent_ids,
                "generate_invoice_artifacts": generate_invoice_artifacts,
            }
        )
        return {
            "sent": len(parent_ids or []),
            "blocked": False,
            "reason": None,
            "selected_parent_ids": parent_ids or [],
            "generated_invoice_artifacts": len(parent_ids or []),
        }


@pytest.mark.asyncio
async def test_selected_dues_reminders_pass_recipient_ids_and_request_invoice_artifacts() -> None:
    assert hasattr(admin_payment_ops, "SendDuesReminders")
    assert hasattr(admin_payment_ops, "SendDuesRemindersCommand")

    sender = CapturingReminderSender()
    use_case = admin_payment_ops.SendDuesReminders(sender=sender)

    result = await use_case.execute(
        admin_payment_ops.SendDuesRemindersCommand(parent_ids=["parent-1", "parent-3"])
    )

    assert sender.calls == [
        {
            "parent_ids": ["parent-1", "parent-3"],
            "generate_invoice_artifacts": True,
        }
    ]
    assert result["sent"] == 2
    assert result["selected_parent_ids"] == ["parent-1", "parent-3"]
    assert result["generated_invoice_artifacts"] == 2
