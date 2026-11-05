"""Owner daily brief (issue #776)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.family_billing import FAILURE_ATTEMPT_STATUSES
from backend.v2.contexts.crm.domain.family_notes import TRIAL_PASSED_SOURCE_PREFIX as DOMAIN_PREFIX
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEventType
from backend.v2.shared.observability.owner_daily_brief import (
    DEPARTURE_EVENT_TYPES,
    FAILED_ATTEMPT_STATUSES,
    THREE_THINGS_LABELS,
    TRIAL_PASSED_SOURCE_PREFIX,
    BriefFamily,
    FamilyFacts,
    collect_owner_daily_brief,
    render_owner_daily_brief,
)

NOW = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)
RECENT = NOW - timedelta(hours=2)
OLD = NOW - timedelta(days=5)
ACADEMY = "acad-1"
OTHER = "acad-2"


class _FakeCollection:
    def __init__(
        self,
        docs: list[dict[str, Any]],
        *,
        aggregate_rows: list[dict[str, Any]] | None = None,
        fail: bool = False,
    ) -> None:
        self.docs = docs
        self.aggregate_rows = aggregate_rows or []
        self.fail = fail
        self.queries: list[dict[str, Any]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        if self.fail:
            raise RuntimeError("collection unreadable")
        self.queries.append(query)
        return sum(1 for doc in self.docs if _matches(doc, query))

    def aggregate(self, pipeline: list[dict[str, Any]]) -> Any:
        """Canned group rows; each carries the tenant it was grouped from
        and is only returned when the pipeline's ``$match`` selects it."""
        rows, fail = self.aggregate_rows, self.fail
        match: dict[str, Any] = next(
            (stage["$match"] for stage in pipeline if "$match" in stage), {}
        )

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for row in rows:
                if row.get("academy_id") == match.get("academy_id"):
                    yield {k: v for k, v in row.items() if k != "academy_id"}

        return _iter()

    async def find_one(
        self, query: dict[str, Any], _projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return next((doc for doc in self.docs if _matches(doc, query)), None)

    def find(self, query: dict[str, Any], _projection: dict[str, Any] | None = None) -> Any:
        docs, fail = self.docs, self.fail

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for doc in docs:
                if _matches(doc, query):
                    yield doc

        return _iter()


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected and (key in doc) != expected["$exists"]:
                return False
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
            if "$gt" in expected and (actual is None or actual <= expected["$gt"]):
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection([]))


async def _facts(academy_id: str) -> FamilyFacts:
    """What composition hands the brief from the family index: ``ACADEMY``'s
    families only (``fb-1`` is an alias of ``p-1``), ``p-2`` has an at-risk child."""
    if academy_id != ACADEMY:
        return FamilyFacts(family_by_alias={}, name_by_family={}, at_risk=())
    return FamilyFacts(
        family_by_alias={"p-1": "p-1", "fb-1": "p-1", "p-2": "p-2"},
        name_by_family={"p-1": "Testparent One", "p-2": "Testparent Two"},
        at_risk=(BriefFamily(family_id="p-2", name="Testparent Two"),),
    )


async def _quiet_facts(academy_id: str) -> FamilyFacts:
    return FamilyFacts(family_by_alias={}, name_by_family={}, at_risk=())


async def _no_facts(academy_id: str) -> FamilyFacts:
    raise RuntimeError("index down")


def _db(**overrides: _FakeCollection) -> Any:
    # ``Any``: the fake stands in for AsyncIOMotorDatabase at every call site.
    """One academy's signals, plus another academy's copy of every row that
    must never leak into ``ACADEMY``'s brief."""
    a, o = ACADEMY, OTHER
    collections: dict[str, _FakeCollection] = {
        "academies": _FakeCollection([{"academy_id": a, "display_name": "Alpha Academy"}]),
        "enrollments": _FakeCollection(
            [
                {"academy_id": a, "enrolled_at": RECENT},
                {"academy_id": a, "enrolled_at": OLD},
                {"academy_id": o, "enrolled_at": RECENT},
            ]
        ),
        "enrollment_events": _FakeCollection(
            [],
            aggregate_rows=[
                {"academy_id": a, "_id": "moved away", "count": 2},
                {"academy_id": a, "_id": None, "count": 1},
                {"academy_id": o, "_id": "cost", "count": 9},
            ],
        ),
        "onboarding_applications": _FakeCollection(
            [
                {"academy_id": a, "status": "PENDING_APPROVAL"},
                {"academy_id": a, "status": "APPROVED"},
                {"academy_id": o, "status": "PENDING_APPROVAL"},
            ]
        ),
        "payments": _FakeCollection(
            [
                {"academy_id": a, "status": "failed", "updated_at": RECENT, "parent_id": "fb-1"},
                {"academy_id": a, "status": "failed", "updated_at": OLD, "parent_id": "p-2"},
                {"academy_id": a, "status": "succeeded", "updated_at": RECENT, "parent_id": "p-2"},
                {"academy_id": o, "status": "failed", "updated_at": RECENT, "parent_id": "p-9"},
            ]
        ),
        # Where a declined autopay actually lands (ChargeInvoiceViaAutopay ->
        # record_payment_attempt); the "Failed cards" line reads this.
        "payment_attempts": _FakeCollection(
            [
                {"academy_id": a, "status": "failed", "created_at": RECENT, "parent_id": "fb-1"},
                {"academy_id": a, "status": "failed", "created_at": OLD, "parent_id": "p-2"},
                {"academy_id": a, "status": "succeeded", "created_at": RECENT, "parent_id": "p-2"},
                {"academy_id": o, "status": "failed", "created_at": RECENT, "parent_id": "p-9"},
            ]
        ),
        "family_follow_ups": _FakeCollection(
            [
                {
                    "academy_id": a,
                    "status": "open",
                    "parent_id": "p-2",
                    "source_key": "trial_passed:t1",
                },
                {
                    "academy_id": a,
                    "status": "done",
                    "parent_id": "p-1",
                    "source_key": "trial_passed:t2",
                },
                {"academy_id": a, "status": "open", "parent_id": "p-1", "source_key": None},
                {
                    "academy_id": o,
                    "status": "open",
                    "parent_id": "p-9",
                    "source_key": "trial_passed:t9",
                },
            ]
        ),
        "invoices": _FakeCollection(
            [
                {"academy_id": a, "status": "open", "balance_due_cents": 4500},
                {"academy_id": a, "status": "paid", "balance_due_cents": 0},
                {"academy_id": a, "status": "open", "balance_due_cents": 0},
                {"academy_id": o, "status": "open", "balance_due_cents": 4500},
            ]
        ),
        "students": _FakeCollection(
            [
                {"academy_id": a, "student_id": "s-1", "parent_id": "p-1"},
                {"academy_id": a, "student_id": "s-2", "parent_id": "p-2"},
                {"academy_id": o, "student_id": "s-9", "parent_id": "p-9"},
            ]
        ),
        "waiver_acceptances": _FakeCollection([{"academy_id": a, "student_id": "s-1"}]),
        "users": _FakeCollection(
            [
                {"academy_id": a, "user_id": "p-1", "email": "p1@example.test"},
                {"academy_id": a, "user_id": "p-2", "email": "p2@example.test"},
                {"academy_id": o, "user_id": "p-9", "email": "p9@example.test"},
            ]
        ),
        "family_contacts": _FakeCollection([]),
        "email_suppressions": _FakeCollection(
            [
                {"email": "p1@example.test", "active": True, "first_seen_at": RECENT},
                {"email": "p2@example.test", "active": True, "first_seen_at": OLD},
                {"email": "p2@example.test", "active": False, "first_seen_at": RECENT},
                {"email": "p9@example.test", "active": True, "first_seen_at": RECENT},
            ]
        ),
    }
    collections.update(overrides)
    return _FakeDb(collections)


@pytest.mark.asyncio
async def test_brief_collects_every_owner_signal() -> None:
    brief = await collect_owner_daily_brief(_db(), academy_id=ACADEMY, family_facts=_facts, now=NOW)

    assert brief.new_enrollments == 1
    assert brief.departures_total == 3
    assert brief.approvals_waiting == 1
    assert brief.payments_failed == 1
    # An `open` invoice with nothing left owing is settled, not outstanding.
    assert brief.invoices_open == 1
    assert brief.waivers_missing == 1
    assert brief.emails_undeliverable == 1
    assert brief.academy_name == "Alpha Academy"
    assert brief.errors == []


@pytest.mark.asyncio
async def test_brief_requires_an_academy() -> None:
    with pytest.raises(ValueError):
        await collect_owner_daily_brief(_db(), academy_id="", family_facts=_facts, now=NOW)


@pytest.mark.asyncio
async def test_missing_academy_name_falls_back_to_the_id() -> None:
    brief = await collect_owner_daily_brief(
        _db(academies=_FakeCollection([])), academy_id=ACADEMY, family_facts=_facts, now=NOW
    )

    assert brief.academy_name == ACADEMY
    subject, _ = render_owner_daily_brief(brief)
    assert subject.endswith(f"· {ACADEMY}")


@pytest.mark.asyncio
async def test_departures_carry_their_reason() -> None:
    brief = await collect_owner_daily_brief(_db(), academy_id=ACADEMY, family_facts=_facts, now=NOW)

    assert [(row.reason, row.count) for row in brief.departures] == [
        ("moved away", 2),
        ("no reason recorded", 1),
    ]
    _, body = render_owner_daily_brief(brief)
    assert "moved away" in body


@pytest.mark.asyncio
async def test_brief_degrades_when_one_collection_is_unreadable() -> None:
    brief = await collect_owner_daily_brief(
        _db(payments=_FakeCollection([], fail=True)),
        academy_id=ACADEMY,
        family_facts=_facts,
        now=NOW,
    )

    assert brief.payments_failed == 0
    assert any("money" in err for err in brief.errors)
    # The rest of the brief still arrives.
    assert brief.approvals_waiting == 1


@pytest.mark.asyncio
async def test_a_quiet_day_does_not_claim_action_is_needed() -> None:
    quiet = _db(
        enrollment_events=_FakeCollection([], aggregate_rows=[]),
        onboarding_applications=_FakeCollection([]),
        payments=_FakeCollection([]),
        payment_attempts=_FakeCollection([]),
        students=_FakeCollection([]),
        waiver_acceptances=_FakeCollection([]),
        email_suppressions=_FakeCollection([]),
        family_follow_ups=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(
        quiet, academy_id=ACADEMY, family_facts=_quiet_facts, now=NOW
    )

    assert brief.has_attention_items is False
    subject, body = render_owner_daily_brief(brief)
    assert "nothing waiting" in subject
    assert "Nothing is waiting on a decision today." in body


@pytest.mark.asyncio
async def test_new_enrollments_alone_never_flip_the_subject_line() -> None:
    busy = _db(
        enrollment_events=_FakeCollection([], aggregate_rows=[]),
        onboarding_applications=_FakeCollection([]),
        payments=_FakeCollection([]),
        payment_attempts=_FakeCollection([]),
        students=_FakeCollection([]),
        waiver_acceptances=_FakeCollection([]),
        email_suppressions=_FakeCollection([]),
        family_follow_ups=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(
        busy, academy_id=ACADEMY, family_facts=_quiet_facts, now=NOW
    )

    assert brief.new_enrollments == 1
    assert brief.has_attention_items is False


def test_departure_events_match_the_domain() -> None:
    """``shared/`` may not import enrollment, so the list is duplicated.

    This pins the copy to the real literal: a new terminal transition added to
    the domain without updating the brief would silently stop being reported.
    """
    domain_types = set(EnrollmentLifecycleEventType.__args__)  # type: ignore[attr-defined]
    assert set(DEPARTURE_EVENT_TYPES) <= domain_types


def test_trial_passed_prefix_matches_the_domain() -> None:
    """``shared/`` may not import crm, so the prefix is duplicated."""
    assert TRIAL_PASSED_SOURCE_PREFIX == DOMAIN_PREFIX


def test_failed_attempt_statuses_match_billing() -> None:
    """``shared/`` may not import billing, so the failure statuses are duplicated."""
    assert set(FAILED_ATTEMPT_STATUSES) == set(FAILURE_ATTEMPT_STATUSES)


@pytest.mark.asyncio
async def test_failed_cards_read_payment_attempts_not_legacy_payments() -> None:
    """A declined autopay is a ``payment_attempts`` row, never a ``payments`` one."""
    db = _db(
        payments=_FakeCollection([]),
        payment_attempts=_FakeCollection(
            [
                {
                    "academy_id": ACADEMY,
                    "status": "failed",
                    "created_at": RECENT,
                    "parent_id": "p-1",
                },
                {"academy_id": ACADEMY, "status": "failed", "created_at": OLD, "parent_id": "p-2"},
                {
                    "academy_id": ACADEMY,
                    "status": "succeeded",
                    "created_at": RECENT,
                    "parent_id": "p-2",
                },
                {"academy_id": OTHER, "status": "failed", "created_at": RECENT, "parent_id": "p-9"},
            ]
        ),
    )
    brief = await collect_owner_daily_brief(db, academy_id=ACADEMY, family_facts=_facts, now=NOW)

    failed = brief.three_things[0]
    assert (failed.count, [f.name for f in failed.families]) == (1, ["Testparent One"])
    assert brief.payments_failed == 0  # the legacy counter still reads ``payments``
    assert brief.has_attention_items  # a failed card alone flips the subject line


@pytest.mark.asyncio
async def test_three_things_count_and_name_only_this_academy() -> None:
    brief = await collect_owner_daily_brief(_db(), academy_id=ACADEMY, family_facts=_facts, now=NOW)

    failed, trial, at_risk = brief.three_things
    assert [row.label for row in brief.three_things] == list(THREE_THINGS_LABELS)
    # The in-window failed payment is stored under an alias; it names the family.
    assert (failed.count, [f.name for f in failed.families]) == (1, ["Testparent One"])
    # Open job-created follow-ups only: not the done one, not the manual one.
    assert (trial.count, [f.name for f in trial.families]) == (1, ["Testparent Two"])
    assert (at_risk.count, [f.family_id for f in at_risk.families]) == (1, ["p-2"])
    assert brief.errors == []
    assert brief.has_attention_items


@pytest.mark.asyncio
async def test_three_things_render_first_in_order_with_links() -> None:
    brief = await collect_owner_daily_brief(
        _db(), academy_id=ACADEMY, family_facts=_facts, now=NOW, base_url="https://a.test/"
    )
    _, body = render_owner_daily_brief(brief)

    heading = body.index("Three things today")
    positions = [body.index(label) for label in THREE_THINGS_LABELS]
    assert heading < positions[0] < positions[1] < positions[2] < body.index("<table")
    assert "<a href='https://a.test/admin/families/p-1'>Testparent One</a>" in body
    assert "<a href='https://a.test/admin/families/p-2'>Testparent Two</a>" in body


@pytest.mark.asyncio
async def test_three_things_say_none_when_zero() -> None:
    quiet = _db(
        payments=_FakeCollection([]),
        payment_attempts=_FakeCollection([]),
        family_follow_ups=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(
        quiet, academy_id=ACADEMY, family_facts=_quiet_facts, now=NOW
    )
    _, body = render_owner_daily_brief(brief)

    assert [row.count for row in brief.three_things] == [0, 0, 0]
    assert body.count("</strong> — none</li>") == 3


@pytest.mark.asyncio
async def test_trial_passed_and_at_risk_alone_flip_the_subject_line() -> None:
    quiet = _db(
        enrollment_events=_FakeCollection([], aggregate_rows=[]),
        onboarding_applications=_FakeCollection([]),
        payments=_FakeCollection([]),
        payment_attempts=_FakeCollection([]),
        students=_FakeCollection([]),
        waiver_acceptances=_FakeCollection([]),
        email_suppressions=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(quiet, academy_id=ACADEMY, family_facts=_facts, now=NOW)

    assert brief.payments_failed == 0
    assert brief.has_attention_items is True


@pytest.mark.asyncio
async def test_unreadable_family_index_loses_only_the_at_risk_line() -> None:
    brief = await collect_owner_daily_brief(
        _db(), academy_id=ACADEMY, family_facts=_no_facts, now=NOW
    )
    _, body = render_owner_daily_brief(brief)

    failed, trial, at_risk = brief.three_things
    assert at_risk.count is None
    assert "<strong>At-risk families</strong> — could not be read" in body
    # Names degrade to the stored parent reference; counts survive.
    assert (failed.count, [f.name for f in failed.families]) == (1, ["fb-1"])
    assert trial.count == 1
    assert any(err.startswith("families:") for err in brief.errors)
    assert any(err.startswith("at_risk:") for err in brief.errors)


@pytest.mark.asyncio
async def test_unreadable_follow_ups_say_so_on_their_line() -> None:
    brief = await collect_owner_daily_brief(
        _db(family_follow_ups=_FakeCollection([], fail=True)),
        academy_id=ACADEMY,
        family_facts=_facts,
        now=NOW,
    )
    _, body = render_owner_daily_brief(brief)

    assert brief.three_things[1].count is None
    assert "<strong>Trial passed, not registered</strong> — could not be read" in body
    assert any(err.startswith("trial_passed:") for err in brief.errors)
