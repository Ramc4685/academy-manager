"""A family's message to the academy emails the admins once per hour, without its text."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.composition.academy_inbox import compose_send_academy_message
from backend.v2.composition.digests import unwrap_send_port
from backend.v2.shared.comms import CommsService, MongoMessageRepository
from backend.v2.shared.tenancy import current_academy_id

SETTINGS = SimpleNamespace(email_delivery_enabled=False, resend_api_key=None, env="test")


async def _seed(db: Any, academy: str) -> None:
    people = [
        ("owner", "owner@example.com", "Olive Owner", ["admin", "owner"]),
        ("desk", "desk@example.com", "Dana Desk", ["admin"]),
        ("coach", "coach@example.com", "Cory Coach", ["coach"]),
        ("parent", "parent@example.com", "Pat Parent", ["parent"]),
    ]
    for uid, email, name, roles in people:
        await db["users"].insert_one(
            {
                "user_id": uid,
                "academy_id": academy,
                "email": email,
                "display_name": name,
                "is_active": True,
            }
        )
        await db["academy_memberships"].insert_one(
            {"academy_id": academy, "user_id": uid, "roles": roles, "status": "active"}
        )


@pytest.mark.asyncio
async def test_first_message_alerts_admins_without_the_text(db: Any, acad: str) -> None:
    await _seed(db, acad)
    comms = CommsService(messages=MongoMessageRepository(db), academy_id=current_academy_id)
    send = compose_send_academy_message(db, SETTINGS, comms.send_to_academy)

    await send(parent_id="parent", body="Sam has asthma; inhaler is in his bag")
    await send(parent_id="parent", body="Also, running late today")

    sent = unwrap_send_port(send.alert._sender).sent  # type: ignore[attr-defined]
    assert sorted(row["user_id"] for row in sent) == ["desk", "owner"]  # admins only, once each
    for row in sent:
        assert row["subject"] == "New message from Pat Parent"
        assert "asthma" not in row["body"] and "inhaler" not in row["body"]
