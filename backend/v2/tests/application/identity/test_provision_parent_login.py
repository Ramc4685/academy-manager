from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.use_cases.provision_parent_login import (
    ProvisionParentLogin,
    ProvisionParentLoginCommand,
)


@pytest.mark.asyncio
async def test_provisions_roster_parent_with_stable_id_and_actor() -> None:
    parents = AsyncMock()
    parents.ensure_parent_login.return_value = "parent-1"
    use_case = ProvisionParentLogin(parents)

    result = await use_case.execute(
        ProvisionParentLoginCommand(
            parent_id="parent-1",
            email="parent@example.com",
            display_name="Pat Parent",
            actor_id="admin-1",
        ),
        academy_id="academy-1",
    )

    assert result == "parent-1"
    parents.ensure_parent_login.assert_awaited_once_with(
        parent_id="parent-1",
        email="parent@example.com",
        display_name="Pat Parent",
        academy_id="academy-1",
        actor_id="admin-1",
    )
