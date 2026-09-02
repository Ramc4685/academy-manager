"""Contract tests for the verification-email send budget.

The claim is a single conditional upsert whose "denied" answer arrives as a
``DuplicateKeyError`` — behaviour that lives in Mongo's semantics, not in our
Python, so it is worth pinning against an actual (in-process) Mongo rather than
a hand-rolled fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_verification_email_cooldown import (
    COLLECTION,
    COOLDOWN,
    MAX_PER_DAY,
    MongoVerificationEmailCooldown,
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.mark.asyncio
async def test_first_send_to_an_address_is_allowed(db) -> None:  # type: ignore[no-untyped-def]
    cooldown = MongoVerificationEmailCooldown(db)
    assert await cooldown.claim_send("parent@example.com") is True


@pytest.mark.asyncio
async def test_an_immediate_second_send_to_the_same_address_is_refused(db) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("parent@example.com") is True
    assert await cooldown.claim_send("parent@example.com") is False


@pytest.mark.asyncio
async def test_the_cooldown_is_per_address_not_global(db) -> None:  # type: ignore[no-untyped-def]
    """One parent registering must not lock out the next one."""
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("first@example.com") is True
    assert await cooldown.claim_send("second@example.com") is True


@pytest.mark.asyncio
async def test_address_matching_ignores_case_and_surrounding_space(db) -> None:  # type: ignore[no-untyped-def]
    """Otherwise ``Victim@Example.com`` is a free extra send at the same inbox."""
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("parent@example.com") is True
    assert await cooldown.claim_send("  PARENT@Example.COM ") is False


@pytest.mark.asyncio
async def test_a_send_is_allowed_again_once_the_cooldown_elapses(db) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("parent@example.com") is True
    clock.advance(COOLDOWN + timedelta(seconds=1))
    assert await cooldown.claim_send("parent@example.com") is True


@pytest.mark.asyncio
async def test_the_daily_cap_holds_even_when_every_cooldown_has_elapsed(db) -> None:  # type: ignore[no-untyped-def]
    """The cooldown alone still permits ~288 messages a day at one victim.

    Waiting out each cooldown must therefore stop working once the rolling
    24h cap is spent.
    """
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    for _ in range(MAX_PER_DAY):
        assert await cooldown.claim_send("victim@example.com") is True
        clock.advance(COOLDOWN + timedelta(seconds=1))

    assert await cooldown.claim_send("victim@example.com") is False


@pytest.mark.asyncio
async def test_the_daily_cap_refills_once_the_oldest_send_ages_out(db) -> None:  # type: ignore[no-untyped-def]
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    for _ in range(MAX_PER_DAY):
        assert await cooldown.claim_send("parent@example.com") is True
        clock.advance(COOLDOWN + timedelta(seconds=1))
    assert await cooldown.claim_send("parent@example.com") is False

    clock.advance(timedelta(hours=25))
    assert await cooldown.claim_send("parent@example.com") is True


@pytest.mark.asyncio
async def test_the_row_carries_a_purge_at_for_the_ttl_index(db) -> None:  # type: ignore[no-untyped-def]
    """Migration 0163 reaps on ``purge_at``; a row without one would never expire."""
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)
    await cooldown.claim_send("parent@example.com")

    doc = await db[COLLECTION].find_one({})
    assert doc is not None
    # BSON has no timezone: datetimes come back naive-UTC from Mongo (and from
    # mongomock). The stored instant is still UTC, so re-attach it to compare.
    purge_at = doc["purge_at"].replace(tzinfo=UTC)
    # Must outlive the 24h window, or the daily cap would reset early.
    assert purge_at > clock.now + timedelta(hours=24)


@pytest.mark.asyncio
async def test_the_stored_row_does_not_contain_the_plaintext_address(db) -> None:  # type: ignore[no-untyped-def]
    """Anyone can create a row for an address they do not own; do not keep a
    readable log of every address typed at the endpoint."""
    cooldown = MongoVerificationEmailCooldown(db)
    await cooldown.claim_send("parent@example.com")

    doc = await db[COLLECTION].find_one({})
    assert doc is not None
    assert "parent@example.com" not in str(doc)


@pytest.mark.asyncio
async def test_sub_addressed_aliases_share_one_budget(db) -> None:  # type: ignore[no-untyped-def]
    """``victim+1@`` and ``victim+2@`` are one mailbox, so they are one budget.

    An attacker can mint a separate Firebase account per alias with the public
    web API key. Keyed on the raw string, the daily cap would be per-alias —
    unbounded at a single victim — which would defeat the only recipient-side
    control this endpoint has.
    """
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("victim@example.com") is True
    assert await cooldown.claim_send("victim+signup@example.com") is False
    assert await cooldown.claim_send("victim+anything.else@example.com") is False


@pytest.mark.asyncio
async def test_gmail_dots_and_googlemail_share_one_budget(db) -> None:  # type: ignore[no-untyped-def]
    """Gmail ignores dots in the local part and aliases googlemail.com."""
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("victim@gmail.com") is True
    assert await cooldown.claim_send("v.i.c.t.i.m@gmail.com") is False
    assert await cooldown.claim_send("victim@googlemail.com") is False


@pytest.mark.asyncio
async def test_dots_still_separate_mailboxes_outside_gmail(db) -> None:  # type: ignore[no-untyped-def]
    """Dots are significant almost everywhere, so they must not be stripped globally.

    Two genuinely different parents at the same corporate domain must not end up
    sharing — and locking each other out of — one send budget.
    """
    clock = _Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cooldown = MongoVerificationEmailCooldown(db, now=clock)

    assert await cooldown.claim_send("jane.doe@example.com") is True
    assert await cooldown.claim_send("janedoe@example.com") is True
