"""Connected-account country/currency come from the academy record.

Only US academies billing in USD are supported today (owner decision: lock
USD, no multi-currency). ``StartConnectOnboarding`` reads the academy's
``country`` / ``currency`` (absent -> US / USD), passes them to the gateway,
and refuses anything else BEFORE Stripe is asked to create an account.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.domain.connect_region import ConnectAccountRegion
from backend.v2.contexts.billing.domain.errors import UnsupportedConnectAccountRegion
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.billing.infrastructure.mongo_academy_billing_region import (
    MongoAcademyBillingRegionReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)

_ALLOWED_ORIGINS = ("https://app.test",)


class FakeAcademyRegions:
    """Mirrors the Mongo reader: an absent academy or field reads as US/USD."""

    def __init__(self, docs: dict[str, dict[str, Any]] | None = None) -> None:
        self._docs = docs or {}
        self.reads: list[str] = []

    async def get_region(self, academy_id: str) -> ConnectAccountRegion:
        self.reads.append(academy_id)
        doc = self._docs.get(academy_id) or {}
        return ConnectAccountRegion.from_stored(
            country=doc.get("country"), currency=doc.get("currency")
        )


def _use_case(
    stripe: FakeStripeGateway, repo: MongoConnectedAccountRepository, acad: str, regions: Any
) -> StartConnectOnboarding:
    return StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        academy_regions=regions,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=acad,
    )


async def _start(use_case: StartConnectOnboarding, acad: str) -> dict[str, str]:
    return await use_case.start(
        academy_id=acad,
        refresh_url="https://app.test/refresh",
        return_url="https://app.test/return",
    )


async def test_academy_without_country_or_currency_creates_us_usd_account(db, acad) -> None:
    stripe = FakeStripeGateway()
    regions = FakeAcademyRegions({acad: {"name": "No region fields"}})

    await _start(_use_case(stripe, MongoConnectedAccountRepository(db), acad, regions), acad)

    assert len(stripe.connected_accounts) == 1
    created = stripe.connected_accounts[0]
    assert created["country"] == "US"
    assert created["currency"] == "USD"
    assert regions.reads == [acad]


async def test_lowercase_stored_region_is_normalised(db, acad) -> None:
    stripe = FakeStripeGateway()
    regions = FakeAcademyRegions({acad: {"country": "us", "currency": "usd"}})

    await _start(_use_case(stripe, MongoConnectedAccountRepository(db), acad, regions), acad)

    assert stripe.connected_accounts[0]["country"] == "US"
    assert stripe.connected_accounts[0]["currency"] == "USD"


@pytest.mark.parametrize(
    "doc",
    [
        {"country": "CA"},
        {"currency": "CAD"},
        {"currency": "EUR"},
        {"country": "CA", "currency": "CAD"},
    ],
)
async def test_unsupported_region_is_refused_before_any_stripe_call(db, acad, doc) -> None:
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = _use_case(stripe, repo, acad, FakeAcademyRegions({acad: doc}))

    with pytest.raises(UnsupportedConnectAccountRegion) as exc_info:
        await _start(use_case, acad)

    expected_country = doc.get("country", "US")
    expected_currency = doc.get("currency", "USD")
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == (
        "Stripe accounts can only be created for academies in the US billing in USD "
        f"today (academy has country={expected_country}, currency={expected_currency})"
    )
    assert stripe.connected_accounts == []
    assert stripe.account_onboarding_links == []
    assert await repo.collection.count_documents({}) == 0


def test_region_defaults_and_normalises() -> None:
    us_usd = ConnectAccountRegion(country="US", currency="USD")
    assert ConnectAccountRegion.from_stored(country=None, currency=None) == us_usd
    assert ConnectAccountRegion.from_stored(country="  ", currency="") == us_usd
    assert ConnectAccountRegion.from_stored(country=" ca ", currency="cad") == (
        ConnectAccountRegion(country="CA", currency="CAD")
    )


async def test_mongo_reader_reads_the_real_academy_record(real_db) -> None:
    await real_db["academies"].insert_many(
        [
            # The academies validator requires academy_id + display_name.
            {"academy_id": "acad-plain", "display_name": "Plain"},
            {"academy_id": "acad-lower", "display_name": "Lower", "currency": "usd"},
            {
                "academy_id": "acad-ca",
                "display_name": "Maple",
                "country": "ca",
                "currency": "CAD",
            },
        ]
    )
    reader = MongoAcademyBillingRegionReader(real_db)
    us_usd = ConnectAccountRegion(country="US", currency="USD")

    assert await reader.get_region("acad-plain") == us_usd
    assert await reader.get_region("acad-lower") == us_usd
    assert await reader.get_region("acad-ca") == ConnectAccountRegion(country="CA", currency="CAD")
    assert await reader.get_region("acad-missing") == us_usd
