"""``CreateTrialPassedFollowUps`` (roadmap L3c) over in-memory fakes.

The follow-up fake mirrors the real store: ``add_once`` is keyed on
``(academy_id, source_key)`` and answers False for ANY existing row with that
key, open or done (the migration 0201 unique index). Store behaviour itself is
proved on a real ``mongod`` in ``test_crm_trial_follow_ups_real_mongo.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from backend.v2.contexts.crm.application.use_cases.trial_follow_ups import (
    FOLLOW_UP_AFTER,
    LOOKBACK,
    SYSTEM_ACTOR,
    CreateTrialPassedFollowUps,
    follow_up_title,
)
from backend.v2.contexts.crm.domain.family_notes import FamilyFollowUp

A = "acad-l3c-a"
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Trial:
    trial_id: str
    parent_user_id: str = "p-1"
    student_id: str | None = None
    child_name: str | None = "Sample Child"
    session_id: str = "s-1"
    requested_at: datetime = NOW - timedelta(days=20)
    class_started_at: datetime = NOW - timedelta(days=8)


class FakeTrials:
    def __init__(self, trials: list[Trial]) -> None:
        self.trials = trials
        self.windows: list[tuple[datetime, datetime]] = []

    async def came_not_converted(
        self, academy_id: str, *, started_after: datetime, started_before: datetime
    ) -> list[Trial]:
        self.windows.append((started_after, started_before))
        return [t for t in self.trials if started_after <= t.class_started_at <= started_before]


class FakeRegistrations:
    def __init__(self, registered: set[str] | None = None) -> None:
        self.registered = registered or set()

    async def registered_since(self, academy_id: str, **kw: object) -> bool:
        return kw["parent_user_id"] in self.registered


@dataclass(frozen=True)
class Family:
    family_id: str
    parent_name: str | None = None


class FakeFamilies:
    def __init__(self, known: dict[str, str]) -> None:
        self.known = known  # alias -> canonical

    async def find(self, academy_id: str, family_id: str) -> Family | None:
        canonical = self.known.get(family_id)
        return Family(canonical) if canonical else None

    async def names(self, academy_id: str) -> dict[str, str | None]:
        return {}


class FakeOwners:
    def __init__(self, owner: str | None) -> None:
        self.owner = owner

    async def owner_user_id(self, academy_id: str) -> str | None:
        return self.owner


class FakeFollowUps:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], FamilyFollowUp] = {}

    async def add_once(self, follow_up: FamilyFollowUp) -> bool:
        assert follow_up.source_key
        key = (follow_up.academy_id, follow_up.source_key)
        if key in self.rows:
            return False
        self.rows[key] = follow_up
        return True


async def _utc(_academy: str) -> str | None:
    return "America/Chicago"


def _use_case(
    trials: list[Trial],
    *,
    registered: set[str] | None = None,
    owner: str | None = "owner-1",
    store: FakeFollowUps | None = None,
    families: dict[str, str] | None = None,
) -> tuple[CreateTrialPassedFollowUps, FakeFollowUps, FakeTrials]:
    store = store or FakeFollowUps()
    source = FakeTrials(trials)
    ids = iter(f"fu-{n}" for n in range(100))
    return (
        CreateTrialPassedFollowUps(
            trials=source,
            registrations=FakeRegistrations(registered),
            families=FakeFamilies(families if families is not None else {"p-1": "fam-1"}),
            owners=FakeOwners(owner),
            follow_ups=store,
            timezone=_utc,
            clock=lambda: NOW,
            new_id=lambda: next(ids),
        ),
        store,
        source,
    )


async def test_creates_one_follow_up_for_the_family_assigned_to_the_owner() -> None:
    uc, store, source = _use_case([Trial("tr-1")])
    run = await uc.execute(academy_id=A)
    assert (run.candidates, run.created) == (1, 1)
    assert source.windows == [(NOW - LOOKBACK, NOW - FOLLOW_UP_AFTER)]
    [row] = store.rows.values()
    assert row.parent_id == "fam-1"  # canonical family id
    assert row.title == "Trial passed, no registration: Sample Child"
    assert row.assignee_user_id == "owner-1"
    assert row.source_key == "trial_passed:tr-1"
    assert row.created_by == SYSTEM_ACTOR
    assert row.status == "open"
    assert row.due_on == date(2026, 9, 24)  # the academy's local today


async def test_running_twice_creates_nothing_new() -> None:
    store = FakeFollowUps()
    uc, _, _ = _use_case([Trial("tr-1")], store=store)
    await uc.execute(academy_id=A)
    again = await uc.execute(academy_id=A)
    assert (again.created, again.already_created) == (0, 1)
    assert len(store.rows) == 1


async def test_registered_family_gets_no_follow_up() -> None:
    uc, store, _ = _use_case([Trial("tr-1")], registered={"p-1"})
    run = await uc.execute(academy_id=A)
    assert (run.created, run.registered) == (0, 1)
    assert store.rows == {}


async def test_class_under_seven_days_ago_waits() -> None:
    uc, store, _ = _use_case([Trial("tr-1", class_started_at=NOW - timedelta(days=6))])
    assert (await uc.execute(academy_id=A)).created == 0
    assert store.rows == {}


async def test_no_owner_leaves_it_unassigned() -> None:
    uc, store, _ = _use_case([Trial("tr-1")], owner=None)
    await uc.execute(academy_id=A)
    [row] = store.rows.values()
    assert row.assignee_user_id == ""


async def test_unknown_family_is_skipped() -> None:
    uc, store, _ = _use_case([Trial("tr-1", parent_user_id="p-gone")])
    run = await uc.execute(academy_id=A)
    assert (run.created, run.unknown_family) == (0, 1)
    assert store.rows == {}


def test_title_without_a_child_name_is_the_plain_title() -> None:
    assert follow_up_title(Trial("tr-1", child_name=None)) == "Trial passed, no registration"
    assert follow_up_title(Trial("tr-1", child_name="x" * 300)) == ("Trial passed, no registration")
