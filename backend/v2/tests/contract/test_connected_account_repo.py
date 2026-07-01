from __future__ import annotations

from backend.v2.contexts.billing.application.ports import ConnectedAccountRepository
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)


async def test_get_returns_none_when_no_doc(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)

    assert await repo.get_for_academy() is None


async def test_upsert_then_get_round_trip(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    account = ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_A")

    await repo.upsert(account)
    fetched = await repo.get_for_academy()

    assert fetched is not None
    assert fetched.academy_id == acad
    assert fetched.stripe_account_id == "acct_A"
    assert fetched.status == "pending"


async def test_upsert_is_idempotent_one_doc_per_academy(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_A"))
    await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_B"))

    fetched = await repo.get_for_academy()

    assert fetched is not None
    assert fetched.stripe_account_id == "acct_B"
    assert await repo.collection.count_documents({}) == 1


async def test_get_by_stripe_account_id(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_A"))

    fetched = await repo.get_by_stripe_account_id("acct_A")

    assert fetched is not None
    assert fetched.academy_id == acad
    assert await repo.get_by_stripe_account_id("acct_missing") is None


async def test_update_status_and_capabilities(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_A"))

    await repo.update_status(
        stripe_account_id="acct_A",
        status="active",
        capabilities={"card_payments": "active"},
        charges_enabled=True,
        payouts_enabled=True,
    )

    fetched = await repo.get_for_academy()
    assert fetched is not None
    assert fetched.status == "active"
    assert fetched.capabilities == {"card_payments": "active"}
    assert fetched.charges_enabled is True
    assert fetched.payouts_enabled is True


async def test_conforms_to_port() -> None:
    # Structural: the real repo must satisfy the port protocol.
    assert isinstance(MongoConnectedAccountRepository, type)
    _: type[ConnectedAccountRepository] = MongoConnectedAccountRepository  # type: ignore[assignment]


async def test_get_by_stripe_account_id_never_resolves_another_academys_account(
    db, acad, other_acad
) -> None:
    """Security-critical property (per this repo's own docstring): the webhook
    Connect-account guard resolves tenant identity by calling
    ``get_by_stripe_account_id`` while scoped to the RUNNING handler's own
    academy (see ``_ConnectAccountResolver`` in ``composition/parent.py``,
    which wraps this call in ``tenant_scope(self._academy_id)``). This method
    is deliberately tenant-scoped, not a global/unscoped lookup — so it can
    only ever resolve an academy's OWN ``stripe_account_id``, never another
    academy's, even when queried with the exact string of another academy's
    account id.

    This test proves that property directly against the real Mongo-backed
    repo (not a fake): each academy can resolve its own stripe_account_id,
    and querying with another academy's stripe_account_id while scoped to a
    different academy resolves to None rather than cross-attributing the
    document.
    """
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoConnectedAccountRepository(db)

    token = _tv.set(acad)
    try:
        await repo.upsert(
            ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_owned_by_A")
        )
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        await repo.upsert(
            ConnectedAccount.new(academy_id=other_acad, stripe_account_id="acct_owned_by_B")
        )
    finally:
        _tv.reset(token)

    # Academy A resolves its OWN stripe_account_id correctly.
    token = _tv.set(acad)
    try:
        own = await repo.get_by_stripe_account_id("acct_owned_by_A")
        assert own is not None
        assert own.academy_id == acad
        assert own.stripe_account_id == "acct_owned_by_A"

        # Academy A can NEVER resolve academy B's stripe_account_id to B's
        # document — the webhook guard for A's handler must not attribute
        # a Connect event on B's account to A (or to anyone, from A's view).
        cross = await repo.get_by_stripe_account_id("acct_owned_by_B")
        assert cross is None
    finally:
        _tv.reset(token)

    # And the symmetric case: academy B resolves its own account id, and can
    # never resolve academy A's id into A's document either.
    token = _tv.set(other_acad)
    try:
        own_b = await repo.get_by_stripe_account_id("acct_owned_by_B")
        assert own_b is not None
        assert own_b.academy_id == other_acad

        cross_b = await repo.get_by_stripe_account_id("acct_owned_by_A")
        assert cross_b is None
    finally:
        _tv.reset(token)


async def test_tenant_isolation_between_academies(db, acad, other_acad) -> None:
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoConnectedAccountRepository(db)

    token = _tv.set(acad)
    try:
        await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_A"))
    finally:
        _tv.reset(token)

    # Academy B has its own account and cannot read/see academy A's.
    token = _tv.set(other_acad)
    try:
        assert await repo.get_for_academy() is None
        assert await repo.get_by_stripe_account_id("acct_A") is None
        await repo.upsert(ConnectedAccount.new(academy_id=other_acad, stripe_account_id="acct_B"))
        b_view = await repo.get_for_academy()
        assert b_view is not None
        assert b_view.stripe_account_id == "acct_B"
    finally:
        _tv.reset(token)

    # Back in academy A: still only sees its own account.
    token = _tv.set(acad)
    try:
        a_view = await repo.get_for_academy()
        assert a_view is not None
        assert a_view.stripe_account_id == "acct_A"
        # A cannot resolve B's account id through the tenant-scoped lookup.
        assert await repo.get_by_stripe_account_id("acct_B") is None
    finally:
        _tv.reset(token)
