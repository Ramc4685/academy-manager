"""``_CoachGroupLinkProvider`` reads assignment, not upcoming dates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from backend.v2.composition.digests import _AcademyBrandLookup, _CoachGroupLinkProvider
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
)


@pytest.mark.asyncio
async def test_only_assigned_sessions_with_links_and_not_cancelled() -> None:
    sessions = SimpleNamespace(
        assigned_session_ids_for_coach=AsyncMock(return_value=["s1", "s2", "s3"]),
        get_many=AsyncMock(
            return_value=[
                SimpleNamespace(
                    session_id="s1",
                    title="Juniors",
                    location="Court A",
                    status="scheduled",
                    whatsapp_group_link="https://chat.whatsapp.com/A",
                ),
                SimpleNamespace(
                    session_id="s2",
                    title="Old",
                    location="",
                    status="cancelled",
                    whatsapp_group_link="https://chat.whatsapp.com/B",
                ),
                SimpleNamespace(
                    session_id="s3",
                    title="NoLink",
                    location="",
                    status="scheduled",
                    whatsapp_group_link=None,
                ),
            ]
        ),
    )
    links = await _CoachGroupLinkProvider(sessions=sessions).for_coach("coach-1")
    assert links == (
        WhatsAppGroupLink(label="Juniors @ Court A", url="https://chat.whatsapp.com/A"),
    )


@pytest.mark.asyncio
async def test_no_assignments_means_no_lookup() -> None:
    sessions = SimpleNamespace(
        assigned_session_ids_for_coach=AsyncMock(return_value=[]), get_many=AsyncMock()
    )
    assert await _CoachGroupLinkProvider(sessions=sessions).for_coach("c") == ()
    sessions.get_many.assert_not_called()


@pytest.mark.asyncio
async def test_brand_lookup_maps_academy_doc() -> None:
    academies = SimpleNamespace(
        find_by_id=AsyncMock(
            return_value={
                "display_name": "BLNO",
                "brand_color": "#112233",
                "logo_url": "",
                "contact_email": "hi@blno.test",
            }
        )
    )
    brand = await _AcademyBrandLookup(academies).brand_for("acad")
    assert brand is not None
    assert brand.academy_name == "BLNO"
    assert brand.accent() == "#112233"
    assert brand.logo_url is None
    assert brand.contact_email == "hi@blno.test"
    academies.find_by_id = AsyncMock(return_value=None)
    assert await _AcademyBrandLookup(academies).brand_for("acad") is None
