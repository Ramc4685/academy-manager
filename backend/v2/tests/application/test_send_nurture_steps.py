"""Lead nurture sequence (AI strategy Phase 3, C1): the daily job and the editor.

The stores are the real ones over ``mongomock`` with migrations 0192, 0203
and 0225 applied, so the send claim is the real ``claim_digest_send`` behind
the real ``(academy_id, subject_id, digest_date)`` unique index, contacts are
read through the real tenant-scoped repository, and the opt-out and contact
log lookups are the stores the send path and the Messages tab use. Only the
email itself is a fake (``FakeNotifier``). ``contract/test_nurture_sends_real_mongo.py``
proves the claim on a real ``mongod``.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import mongomock_motor
import pytest

from backend.v2.composition.nurture import (
    AcademyNurtureSettings,
    ContactLogConversations,
    MongoNurtureSendRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
)
from backend.v2.contexts.crm.application.use_cases.nurture_sequence import (
    ManageNurtureSequence,
    SendNurtureSteps,
)
from backend.v2.contexts.crm.domain.errors import InvalidNurtureSequence
from backend.v2.contexts.crm.domain.family_messages import FamilyContactLog
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact, PipelineOverride
from backend.v2.contexts.crm.domain.nurture import NurtureStep
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.shared.comms.claimed_send import NudgeSendsFailed
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

A = "acad-nurture-a"
B = "acad-nurture-b"
CHICAGO = ZoneInfo("America/Chicago")
#: The day every test contact arrives, 09:00 local.
ARRIVED = datetime(2026, 11, 2, 9, 0, tzinfo=CHICAGO)
#: Switched on the evening before.
ENABLED_AT = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)

STEPS = [
    NurtureStep(day=2, subject="Still thinking about {{class}}?", body="Hi from {{academy_name}}."),
    NurtureStep(day=7, subject="A week on", body="{{seat_band}} Book: {{booking_link}}"),
    NurtureStep(day=21, subject="Last note", body="We would love to see you."),
]

_MIGRATIONS = [
    importlib.import_module(f"backend.v2.migrations.{name}")
    for name in ("0192_crm_contacts", "0203_family_contact_log", "0225_nurture_sends")
]


def on_day(n: int) -> datetime:
    """10:25 local, ``n`` days after the contact arrived (the job's tick)."""
    return (ARRIVED + timedelta(days=n)).replace(hour=10, minute=25)


class FakeNotifier:
    """Records each send; ``results`` maps a contact id to what the email
    port would report (default ``sent``)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, int]] = []
        self.results: dict[str, str] = {}

    async def send_step(self, *, contact: CrmContact, step: NurtureStep) -> str:
        result = self.results.get(contact.contact_id, "sent")
        if result == "sent":
            self.sent.append((contact.contact_id, step.day))
        return result

    async def example_values(self, academy_id: str) -> dict[str, str]:
        return {
            "academy_name": f"Academy {academy_id}",
            "class": "Junior Beginners",
            "seat_band": "Only 3 seats are left.",
            "booking_link": "https://a.example.test/",
        }


class World:
    def __init__(self, db: Any) -> None:
        self.db = db
        self.notifier = FakeNotifier()
        self.settings = AcademyNurtureSettings(MongoAcademyRepository(db))
        self.job = SendNurtureSteps(
            settings=self.settings,
            contacts=MongoCrmContactRepository(db),
            opt_outs=MongoProspectOptOutRepository(db),
            conversations=ContactLogConversations(MongoFamilyContactLogRepository(db)),
            send_repo=MongoNurtureSendRepository(db),
            notifier=self.notifier,
        )
        self.manage = ManageNurtureSequence(self.settings, self.notifier, clock=lambda: ENABLED_AT)

    async def switch_on(self, academy_id: str = A) -> None:
        with tenant_scope(academy_id):
            await self.manage.save(academy_id, enabled=True, steps=STEPS, user_id="owner-1")

    async def add(
        self,
        contact_id: str,
        *,
        academy_id: str = A,
        email: str | None = None,
        marketing: bool = True,
        status: str = "lead",
        created_at: datetime = ARRIVED,
        override: PipelineOverride | None = None,
    ) -> CrmContact:
        contact = CrmContact(
            contact_id=contact_id,
            academy_id=academy_id,
            name="Sample Parent",
            email=email or f"{contact_id}@example.test",
            source="website",
            pipeline_status=status,  # type: ignore[arg-type]
            pipeline_override=override,
            consent=ContactConsent(contact_about_request=True, marketing=marketing),
            created_at=created_at.astimezone(UTC),
            updated_at=created_at.astimezone(UTC),
        )
        with tenant_scope(academy_id):
            stored, _ = await MongoCrmContactRepository(self.db).add_if_absent(contact)
        return stored

    async def run(self, local_now: datetime, academy_id: str = A) -> int:
        with tenant_scope(academy_id):
            return await self.job.execute(academy_id=academy_id, local_now=local_now)

    async def claims(self, academy_id: str = A) -> list[dict[str, Any]]:
        return await self.db["nurture_sends"].find({"academy_id": academy_id}).to_list(None)


@pytest.fixture
async def world() -> World:
    db = mongomock_motor.AsyncMongoMockClient()["nurture_test"]
    for module in _MIGRATIONS:
        await module.up(db)
    for academy_id in (A, B):
        await db["academies"].insert_one(
            {"academy_id": academy_id, "name": f"Academy {academy_id}"}
        )
    return World(db)


# -- audience ----------------------------------------------------------------


async def test_off_by_default_sends_nothing(world: World) -> None:
    await world.add("c1")
    assert await world.run(on_day(2)) == 0
    assert world.notifier.sent == [] and await world.claims() == []
    with tenant_scope(A):
        assert (await world.manage.get(A)).enabled is False


async def test_only_consented_open_leads_created_after_switch_on_get_a_step(
    world: World,
) -> None:
    await world.switch_on()
    await world.add("lead")
    await world.add("trial", status="trial")
    await world.add("no-consent", marketing=False)
    await world.add("enrolled", status="enrolled")
    await world.add("before-switch-on", created_at=ENABLED_AT - timedelta(hours=1))

    assert await world.run(on_day(2)) == 2
    assert sorted(world.notifier.sent) == [("lead", 2), ("trial", 2)]


async def test_the_switch_needs_a_written_step(world: World) -> None:
    with tenant_scope(A):
        await world.manage.save(A, enabled=True, steps=[], user_id="owner-1")
    await world.add("c1")
    assert await world.run(on_day(2)) == 0


async def test_another_academys_leads_are_not_in_this_academys_run(world: World) -> None:
    await world.switch_on(A)
    await world.add("b-lead", academy_id=B)
    assert await world.run(on_day(2), academy_id=A) == 0
    # B never switched it on, so its own run sends nothing either.
    assert await world.run(on_day(2), academy_id=B) == 0
    assert world.notifier.sent == []


async def test_one_inbox_gets_one_sequence(world: World) -> None:
    await world.switch_on()
    await world.add("first-child", email="sam@gmail.com")
    await world.add(
        "second-child", email="s.a.m+kid2@googlemail.com", created_at=ARRIVED + timedelta(hours=1)
    )
    assert await world.run(on_day(2)) == 1
    assert world.notifier.sent == [("first-child", 2)]


# -- schedule and day 0 --------------------------------------------------------


async def test_day_0_and_1_send_nothing_and_the_acknowledgement_is_untouched(
    world: World,
) -> None:
    await world.switch_on()
    await world.add("c1")
    with tenant_scope(A):
        assert await MongoCrmContactRepository(world.db).try_claim_acknowledgement("c1", at=ARRIVED)
    assert await world.run(on_day(0)) == 0
    assert await world.run(on_day(1)) == 0
    assert await world.claims() == []
    row = await world.db["crm_contacts"].find_one({"contact_id": "c1"})
    assert row["acknowledged_at"] is not None
    # And no step ever claims a day-0 key.
    for day in (2, 7, 21):
        await world.run(on_day(day))
    assert sorted(c["digest_date"] for c in await world.claims()) == [
        "nurture:day_2",
        "nurture:day_21",
        "nurture:day_7",
    ]


async def test_each_step_goes_once_on_its_day_and_a_rerun_sends_nothing(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    for day in range(0, 30):
        await world.run(on_day(day))
        await world.run(on_day(day))  # a second tick, or a second machine
    assert world.notifier.sent == [("c1", 2), ("c1", 7), ("c1", 21)]
    claims = await world.claims()
    assert len(claims) == 3
    assert {c["channel"] for c in claims} == {"email"}
    assert {c["status"] for c in claims} == {"sent"}


async def test_a_missed_tick_sends_the_step_late_but_never_a_backlog(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    # The job was down from day 1 to day 8: day 9 sends day 7 only, never day 2.
    assert await world.run(on_day(9)) == 1
    assert world.notifier.sent == [("c1", 7)]


async def test_a_step_past_its_grace_window_is_dropped(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    # Day 6: day 2 is four days late (grace is three) and day 7 is not due.
    assert await world.run(on_day(6)) == 0
    assert await world.claims() == []


# -- stop conditions -----------------------------------------------------------


async def test_a_pipeline_move_stops_the_sequence(world: World) -> None:
    await world.switch_on()
    await world.add(
        "moved",
        override=PipelineOverride(column="trial_booked", set_by="staff-1", set_at=ARRIVED),
    )
    assert await world.run(on_day(2)) == 0


async def test_enrolment_stops_the_sequence_after_it_started(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    assert await world.run(on_day(2)) == 1
    with tenant_scope(A):
        await MongoCrmContactRepository(world.db).mark_enrolled_by_email(
            "c1@example.test", parent_user_id="parent-1", updated_at=ARRIVED
        )
    assert await world.run(on_day(7)) == 0


async def test_a_reply_or_logged_contact_stops_the_sequence(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    with tenant_scope(A):
        await MongoFamilyContactLogRepository(world.db).add(
            FamilyContactLog(
                log_id="log-1",
                academy_id=A,
                parent_id="crm_contact:c1",
                channel="email",
                status="logged",
                note="Subject: Re: your trial",
                author_user_id="staff-1",
                created_at=ARRIVED,
                updated_at=ARRIVED,
            )
        )
    assert await world.run(on_day(2)) == 0
    assert await world.claims() == []


async def test_an_unsubscribe_stops_the_sequence(world: World) -> None:
    await world.switch_on()
    await world.add("c1", email="Sam+news@Example.test")
    assert await world.run(on_day(2)) == 1
    with tenant_scope(A):
        await MongoProspectOptOutRepository(world.db).opt_out(
            email="sam@example.test", recipient_id="crm_contact:c1"
        )
    assert await world.run(on_day(7)) == 0
    assert world.notifier.sent == [("c1", 2)]


async def test_a_claim_mark_from_another_academy_is_a_no_op(world: World) -> None:
    await world.switch_on()
    await world.add("c1")
    world.notifier.results = {"c1": "failed"}
    with pytest.raises(NudgeSendsFailed):
        await world.run(on_day(2))
    (claim,) = await world.claims()
    await MongoNurtureSendRepository(world.db).mark_sent(B, claim["send_id"])
    (after,) = await world.claims()
    assert after["status"] == "failed"


async def test_a_suppressed_send_is_final_and_a_failed_one_retries(world: World) -> None:
    await world.switch_on()
    await world.add("bounced")
    await world.add("flaky", email="flaky@example.test")
    world.notifier.results = {"bounced": "skipped", "flaky": "failed"}
    with pytest.raises(NudgeSendsFailed):
        await world.run(on_day(2))
    world.notifier.results = {}
    # The local-day runner re-runs a failed day: only the failed claim retries.
    assert await world.run(on_day(2)) == 1
    assert world.notifier.sent == [("flaky", 2)]
    statuses = {c["subject_id"]: (c["status"], c["retryable"]) for c in await world.claims()}
    assert statuses == {"bounced": ("failed", False), "flaky": ("sent", True)}


# -- the editor ----------------------------------------------------------------


async def test_save_keeps_the_start_on_a_resave_and_restarts_it_after_off(world: World) -> None:
    clock = [ENABLED_AT]
    manage = ManageNurtureSequence(world.settings, world.notifier, clock=lambda: clock[0])
    with tenant_scope(A):
        first = await manage.save(A, enabled=True, steps=STEPS, user_id="owner-1")
        clock[0] = ENABLED_AT + timedelta(days=3)
        again = await manage.save(A, enabled=True, steps=STEPS[:1], user_id="owner-1")
        assert again.enabled_at == first.enabled_at == ENABLED_AT
        off = await manage.save(A, enabled=False, steps=STEPS, user_id="owner-1")
        assert off.enabled_at is None
        clock[0] = ENABLED_AT + timedelta(days=5)
        on = await manage.save(A, enabled=True, steps=STEPS, user_id="owner-1")
        assert on.enabled_at == ENABLED_AT + timedelta(days=5)
        stored = await manage.get(A)
    assert stored.enabled and [s.day for s in stored.steps] == [2, 7, 21]
    doc = await world.db["academies"].find_one({"academy_id": A})
    assert doc["crm_nurture"]["updated_by"] == "owner-1"
    other = await world.db["academies"].find_one({"academy_id": B})
    assert "crm_nurture" not in other


@pytest.mark.parametrize(
    "step",
    [
        NurtureStep(day=3, subject="s", body="b"),
        NurtureStep(day=2, subject="Only a subject", body=""),
        NurtureStep(day=2, subject="Hi {{first_name}}", body="b"),
        NurtureStep(day=2, subject="s", body="x" * 4001),
    ],
)
async def test_save_refuses_a_bad_step(world: World, step: NurtureStep) -> None:
    with tenant_scope(A), pytest.raises(InvalidNurtureSequence):
        await world.manage.save(A, enabled=True, steps=[step], user_id="owner-1")


async def test_preview_fills_the_merge_fields(world: World) -> None:
    subject, text = await world.manage.preview(
        A,
        NurtureStep(
            day=7, subject="{{ class }} at {{academy_name}}", body="{{seat_band}}\n{{booking_link}}"
        ),
    )
    assert subject == f"Junior Beginners at Academy {A}"
    assert text == "Only 3 seats are left.\nhttps://a.example.test/"
