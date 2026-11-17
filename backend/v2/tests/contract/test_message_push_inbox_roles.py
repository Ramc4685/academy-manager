"""A DM push opens the recipient's own inbox, with roles read the way sign-in reads them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.v2.composition.push import compose_message_push

pytestmark = pytest.mark.asyncio


async def test_single_academy_coach_gets_the_coach_inbox_from_the_users_record(real_db) -> None:
    # No academy_memberships row: single-academy auth reads roles from users.
    await real_db["users"].insert_one(
        {"user_id": "c1", "email": "c@example.com", "roles": ["coach"], "is_active": True}
    )
    push = compose_message_push(real_db, SimpleNamespace(saas_mode=False))
    assert await push.inbox_path("acad-1", "c1") == "/coach/messages"
    assert await push.inbox_path("acad-1", "missing") == "/parent/messages"
