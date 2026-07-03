from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    DisconnectStripeUseCase,
)


@pytest.mark.asyncio
async def test_disconnect_clears_legacy_field_only_when_no_connected_accounts_port():
    repo = AsyncMock()
    repo.update_by_id.return_value = {"academy_id": "acad"}

    await DisconnectStripeUseCase(repo=repo).execute("acad")

    repo.update_by_id.assert_awaited_once_with("acad", {"stripe_account_id": None})


@pytest.mark.asyncio
async def test_disconnect_also_disables_accounts_v2_connected_account():
    repo = AsyncMock()
    repo.update_by_id.return_value = {"academy_id": "acad"}
    connected_accounts = AsyncMock()

    await DisconnectStripeUseCase(repo=repo, connected_accounts=connected_accounts).execute("acad")

    repo.update_by_id.assert_awaited_once_with("acad", {"stripe_account_id": None})
    connected_accounts.disable_for_academy.assert_awaited_once_with("acad")


@pytest.mark.asyncio
async def test_disconnect_raises_and_skips_connected_accounts_when_academy_missing():
    repo = AsyncMock()
    repo.update_by_id.return_value = None
    connected_accounts = AsyncMock()

    with pytest.raises(ValueError):
        await DisconnectStripeUseCase(repo=repo, connected_accounts=connected_accounts).execute(
            "missing-acad"
        )

    connected_accounts.disable_for_academy.assert_not_awaited()
