"""Payout period use cases racing each other on a real mongod (L7 part 2).

Each race lets both callers load the period before either writes (a barrier on
the first loads), so the interleaving is the bad one every time: exactly one
write lands, the other refuses with a conflict, the stored header and its line
set agree, and the audit trail records one transition. A screen that loaded an
older version (``expected_version``) is refused the same way. Generating a
period is all-or-nothing and audited once, and migration 0239 backfills the
version and makes one line per occurrence per line set a database rule.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
    MarkPayoutPaidCommand,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
)
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    OverridePayoutLine,
    RecomputePayoutPeriod,
    ReopenPayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodConflictError,
    PayoutPeriodStateError,
    PersistedPayoutLine,
    approve,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_audit_log import (
    MongoPayoutAuditLogRepository,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
)

pytestmark = pytest.mark.asyncio

JUNE_2 = datetime(2026, 6, 2, tzinfo=UTC)
MAY_1 = datetime(2026, 5, 1, tzinfo=UTC)
JUNE_1 = datetime(2026, 6, 1, tzinfo=UTC)


def _line(amount_minor: int, occurrence_id: str = "occ-1") -> PersistedPayoutLine:
    return PersistedPayoutLine(
        occurrence_id=occurrence_id,
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=amount_minor,
        currency="USD",
        rate_id="cr-1",
    )


def _period(**overrides: Any) -> PayoutPeriod:
    base: dict[str, Any] = dict(
        period_id="pp-1",
        academy_id="test-academy",
        coach_id="coach-A",
        period_start=MAY_1,
        period_end=JUNE_1,
        currency="USD",
        total_minor=2_500,
        lines=[_line(2_500)],
        generated_at=datetime(2026, 6, 1, 6, tzinfo=UTC),
        revenue_basis="invoiced",
    )
    base.update(overrides)
    return PayoutPeriod(**base)


class _Calc:
    def __init__(self, amount_minor: int) -> None:
        self.coach_id = "coach-A"
        self.academy_id = "test-academy"
        self.period_start = MAY_1
        self.period_end = JUNE_1
        self.currency = "USD"
        self.lines = [_line(amount_minor)]
        self.total_minor = amount_minor
        self.unpaid_occurrence_ids: list[str] = []
        self.unpaid_occurrences: list[Any] = []
        self.payout_warnings: list[Any] = []


class _Calculator:
    """Each call returns the next amount, so two recomputes write different sets."""

    def __init__(self, *amounts: int) -> None:
        self._amounts = list(amounts)

    async def calculate(self, **_: Any) -> _Calc:
        return _Calc(self._amounts.pop(0))


def _load_together(repo: MongoPayoutPeriodRepository, method: str = "find_by_id") -> None:
    """The first two loads wait for each other, so both callers hold the same version."""
    barrier = asyncio.Barrier(2)
    real = getattr(repo, method)
    waiting = {"left": 2}

    async def load_then_wait(*args: Any, **kwargs: Any) -> Any:
        found = await real(*args, **kwargs)
        if waiting["left"] > 0:
            waiting["left"] -= 1
            await barrier.wait()
        return found

    setattr(repo, method, load_then_wait)


async def _stored(real_db: Any) -> tuple[dict[str, Any], list[int]]:
    doc = await real_db["payout_periods"].find_one({"period_id": "pp-1"}, {"_id": 0})
    lines = await real_db["payout_period_lines"].find({"period_id": "pp-1"}).to_list(None)
    return doc, sorted(line["amount_minor"] for line in lines)


async def _actions(real_db: Any) -> list[str]:
    entries = await MongoPayoutAuditLogRepository(real_db).list_for_period("pp-1")
    return sorted(entry.action for entry in entries)


def _one_landed(results: list[Any]) -> Any:
    landed = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(landed) == 1, results
    assert len(refused) == 1 and isinstance(refused[0], PayoutPeriodConflictError), results
    return landed[0]


async def test_two_recomputes_racing_land_one_line_set_and_one_audit_entry(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    audit = MongoPayoutAuditLogRepository(real_db)
    await repo.save(_period())
    _load_together(repo)
    recompute = RecomputePayoutPeriod(
        calculator=_Calculator(3_000, 9_000), repository=repo, audit=audit
    )

    results = await asyncio.gather(
        recompute.execute(period_id="pp-1", actor_id="owner-a"),
        recompute.execute(period_id="pp-1", actor_id="owner-b"),
        return_exceptions=True,
    )

    winner = _one_landed(results)
    doc, lines = await _stored(real_db)
    assert lines == [winner.total_minor] and doc["total_minor"] == winner.total_minor
    assert doc["version"] == 1
    assert await _actions(real_db) == ["recomputed"]


async def test_recompute_racing_approve_never_approves_a_total_it_did_not_load(
    real_db, acad
) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    audit = MongoPayoutAuditLogRepository(real_db)
    await repo.save(_period())
    _load_together(repo)
    recompute = RecomputePayoutPeriod(calculator=_Calculator(4_000), repository=repo, audit=audit)
    approver = ApprovePayoutPeriod(repository=repo, audit=audit, clock=lambda: JUNE_2)

    results = await asyncio.gather(
        recompute.execute(period_id="pp-1", actor_id="owner-a"),
        approver.execute(period_id="pp-1", actor_id="owner-b"),
        return_exceptions=True,
    )

    winner = _one_landed(results)
    doc, lines = await _stored(real_db)
    if winner.status == "approved":
        # The approval is of the 2,500 both callers loaded; the recompute did nothing.
        assert (doc["status"], doc["total_minor"], lines) == ("approved", 2_500, [2_500])
        assert await _actions(real_db) == ["approved"]
    else:
        assert (doc["status"], doc["total_minor"], lines) == ("draft", 4_000, [4_000])
        assert await _actions(real_db) == ["recomputed"]


async def test_a_double_approve_lands_once_with_one_audit_entry(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    _load_together(repo)
    approver = ApprovePayoutPeriod(
        repository=repo, audit=MongoPayoutAuditLogRepository(real_db), clock=lambda: JUNE_2
    )

    results = await asyncio.gather(
        approver.execute(period_id="pp-1", actor_id="owner-a"),
        approver.execute(period_id="pp-1", actor_id="owner-b"),
        return_exceptions=True,
    )

    assert _one_landed(results).status == "approved"
    doc, _ = await _stored(real_db)
    assert (doc["status"], doc["version"]) == ("approved", 1)
    assert await _actions(real_db) == ["approved"]


def _writes(real_db: Any, repo: MongoPayoutPeriodRepository) -> dict[str, Any]:
    audit = MongoPayoutAuditLogRepository(real_db)
    return {
        "approve": lambda v: ApprovePayoutPeriod(
            repository=repo, audit=audit, clock=lambda: JUNE_2
        ).execute(period_id="pp-1", expected_version=v),
        "recompute": lambda v: RecomputePayoutPeriod(
            calculator=_Calculator(9_000), repository=repo, audit=audit
        ).execute(period_id="pp-1", actor_id="owner", expected_version=v),
        "override": lambda v: OverridePayoutLine(repository=repo, audit=audit).execute(
            period_id="pp-1",
            occurrence_id="occ-1",
            amount_minor=1,
            reason="typo",
            actor_id="owner",
            expected_version=v,
        ),
    }


@pytest.mark.parametrize("write", ["approve", "recompute", "override"])
async def test_a_write_from_a_screen_showing_an_older_version_conflicts(
    real_db, acad, write: str
) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    # Another tab changed the total after this screen loaded version 0.
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None
    await repo.replace_with_lines(
        loaded.model_copy(update={"lines": [_line(4_000)], "total_minor": 4_000})
    )
    before = await _stored(real_db)

    with pytest.raises(PayoutPeriodConflictError):
        await _writes(real_db, repo)[write](0)

    assert await _stored(real_db) == before
    assert await _actions(real_db) == []
    # The screen that reloaded (version 1) goes through.
    assert (await _writes(real_db, repo)[write](1)).version == 2


async def test_mark_paid_and_reopen_from_a_stale_screen_conflict(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    audit = MongoPayoutAuditLogRepository(real_db)
    await repo.save(_period())
    approved = await ApprovePayoutPeriod(
        repository=repo, audit=audit, clock=lambda: JUNE_2
    ).execute(period_id="pp-1")
    command = MarkPayoutPaidCommand(
        period_id="pp-1", method="check", paid_at=JUNE_2, amount_minor=2_500
    )

    with pytest.raises(PayoutPeriodConflictError):
        await MarkPayoutPaid(repository=repo, audit=audit).execute(command, expected_version=0)
    with pytest.raises(PayoutPeriodConflictError):
        await ReopenPayoutPeriod(repository=repo, audit=audit).execute(
            period_id="pp-1", actor_id="owner", reason="fix", expected_version=0
        )
    doc, _ = await _stored(real_db)
    assert (doc["status"], doc["version"]) == ("approved", approved.version)


async def test_lines_cannot_be_rewritten_on_an_approved_period(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None
    approved = await repo.replace(approve(loaded, at=JUNE_2))
    before = await _stored(real_db)

    with pytest.raises(PayoutPeriodStateError):
        await repo.replace_with_lines(
            approved.model_copy(update={"lines": [_line(1)], "total_minor": 1})
        )

    assert await _stored(real_db) == before


async def test_two_generates_of_one_window_store_one_period_and_audit_once(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    _load_together(repo, "find_overlapping")  # both pass every check, then both write
    ids = iter(["pp-1", "pp-2"])
    generate = GeneratePayoutPeriod(
        calculator=_Calculator(2_500, 2_500),
        repository=repo,
        audit=MongoPayoutAuditLogRepository(real_db),
        id_factory=lambda: next(ids),
    )

    results = await asyncio.gather(
        *(
            generate.execute(
                coach_id="coach-A", academy_id="test-academy", period_start=MAY_1, period_end=JUNE_1
            )
            for _ in range(2)
        )
    )

    # Either caller may win the insert; both get the one stored period.
    (winner,) = {r.period_id for r in results}
    assert await real_db["payout_periods"].count_documents({}) == 1
    assert await real_db["payout_period_lines"].count_documents({"period_id": winner}) == 1
    assert await real_db["payout_period_lines"].count_documents({}) == 1
    entries = await MongoPayoutAuditLogRepository(real_db).list_for_period(winner)
    assert [e.action for e in entries] == ["generated"]


async def test_a_generate_that_read_before_another_stored_the_window_returns_it(
    real_db, acad
) -> None:
    """Its window check missed the other generate; the overlap check must not 409 on it."""
    audit = MongoPayoutAuditLogRepository(real_db)
    first = await GeneratePayoutPeriod(
        calculator=_Calculator(2_500),
        repository=MongoPayoutPeriodRepository(real_db),
        audit=audit,
        id_factory=lambda: "pp-1",
    ).execute(coach_id="coach-A", academy_id="test-academy", period_start=MAY_1, period_end=JUNE_1)
    late = MongoPayoutPeriodRepository(real_db)

    async def read_before_the_insert(**_: Any) -> None:
        return None

    late.find_by_window = read_before_the_insert  # type: ignore[method-assign]
    again = await GeneratePayoutPeriod(
        calculator=_Calculator(2_500), repository=late, audit=audit, id_factory=lambda: "pp-2"
    ).execute(coach_id="coach-A", academy_id="test-academy", period_start=MAY_1, period_end=JUNE_1)

    assert again.period_id == first.period_id == "pp-1"
    assert await _actions(real_db) == ["generated"]


class _LinesWriteDies:
    """A database whose payout line inserts fail, as if the process died there."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    def __getitem__(self, name: str) -> Any:
        collection = self._db[name]
        if name != "payout_period_lines":
            return collection

        class _Dies:
            def __getattr__(self, attr: str) -> Any:
                return getattr(collection, attr)

            async def insert_many(self, *_: Any, **__: Any) -> None:
                raise ConnectionError("process died writing lines")

        return _Dies()


async def test_a_generate_that_dies_writing_lines_leaves_no_half_period(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(_LinesWriteDies(real_db))

    with pytest.raises(ConnectionError):
        await repo.save(_period())

    # No header with a total and no lines; the next generate starts clean.
    assert await real_db["payout_periods"].count_documents({}) == 0
    stored = await MongoPayoutPeriodRepository(real_db).save(_period())
    assert [line.amount_minor for line in stored.lines] == [2_500]


M0239 = importlib.import_module("backend.v2.migrations.0239_payout_period_versions")


async def test_0239_backfills_versions_and_refuses_duplicate_lines_by_name(real_db) -> None:
    periods, lines = real_db["payout_periods"], real_db["payout_period_lines"]
    assert M0239.INDEX_NAME in await lines.index_information()
    await lines.drop_index(M0239.INDEX_NAME)

    await periods.insert_one({"academy_id": "a1", "period_id": "legacy", "coach_id": "c"})
    await periods.insert_one(
        {"academy_id": "a1", "period_id": "new", "coach_id": "d", "version": 4}
    )
    line = {"academy_id": "a1", "period_id": "legacy", "occurrence_id": "occ-1"}
    # A pre-L7 recompute race left the same occurrence twice in one line set.
    await lines.insert_many([dict(line), dict(line), {**line, "lines_version": "t2"}])
    try:
        with pytest.raises(RuntimeError, match="a1/legacy/None/occ-1 x2"):
            await M0239.up(real_db)
        assert M0239.INDEX_NAME not in await lines.index_information()
    finally:
        await lines.delete_one(line)
        await M0239.up(real_db)
        await M0239.up(real_db)  # idempotent

    versions = {d["period_id"]: d["version"] async for d in periods.find({})}
    assert versions == {"legacy": 0, "new": 4}
    with pytest.raises(DuplicateKeyError):
        await lines.insert_one(dict(line))
    # The same occurrence in another line set (or another academy) is allowed.
    await lines.insert_one({**line, "lines_version": "t3"})
    await lines.insert_one({**line, "academy_id": "a2"})
