"""S02: the family sees every unfinished or unconfirmed registration, and one
child can hold only one open registration per class."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    ListParentRegistrations,
    StartApplication,
    StartApplicationCommand,
    TransitionApplication,
)
from backend.v2.contexts.onboarding.domain.errors import ApplicationNotEditable
from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
)

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


class ManyAppRepo:
    """In-memory store with the Mongo adapter's filter and sort semantics."""

    def __init__(self, *apps: Application) -> None:
        self.apps = {a.application_id: a for a in apps}

    async def save(self, app):
        self.apps[app.application_id] = app

    async def get(self, application_id):
        return self.apps.get(application_id)

    async def latest_for_parent(self, parent_user_id):
        mine = [a for a in self.apps.values() if a.parent_user_id == parent_user_id]
        return max(mine, key=lambda a: a.created_at, default=None)

    async def list_open_for_parent(self, parent_user_id, statuses):
        rows = [
            a
            for a in self.apps.values()
            if a.parent_user_id == parent_user_id and a.status in statuses
        ]
        return sorted(rows, key=lambda a: a.created_at, reverse=True)

    async def reopen_for_edit(self, application_id, *, expected_status, updated_at):
        app = self.apps.get(application_id)
        if app is None or app.status != expected_status:
            return None
        self.apps[application_id] = app.model_copy(
            update={"status": "DRAFT", "updated_at": updated_at}
        )
        return self.apps[application_id]

    async def restamp_checkout(
        self,
        application_id,
        *,
        expected_status,
        expected_payment_id,
        stripe_checkout_session_id,
        payment_id,
        updated_at,
        new_status=None,
    ):
        app = self.apps.get(application_id)
        if app is None or app.status != expected_status or app.payment_id != expected_payment_id:
            return None
        self.apps[application_id] = app.model_copy(
            update={
                "status": new_status or app.status,
                "stripe_checkout_session_id": stripe_checkout_session_id,
                "payment_id": payment_id,
                "updated_at": updated_at,
            }
        )
        return self.apps[application_id]


def _app(
    app_id: str,
    status: str,
    *,
    child: str = "Lucia Rivera",
    session: str | None = "sess-free",
    parent: str = "parent-1",
    age: int = 0,
    student_id: str | None = None,
    **extra,
) -> Application:
    first, _, last = child.partition(" ")
    created = NOW - timedelta(hours=age)
    return Application(
        application_id=app_id,
        academy_id="acad",
        parent_user_id=parent,
        parent_email="new.parent@example.com",
        status=status,  # type: ignore[arg-type]
        child_profile=ChildProfile(first_name=first, last_name=last),
        selected_session_id=session,
        student_id=student_id,
        expires_at=created + timedelta(days=7),
        created_at=created,
        updated_at=created,
        **extra,
    )


async def _states(repo, parent="parent-1", payment_status=None):
    rows = await ListParentRegistrations(
        repo, clock=lambda: NOW, payment_status=payment_status
    ).execute(parent)
    return [(a.application_id, state) for a, state in rows]


@pytest.mark.asyncio
async def test_states_map_to_finish_waiting_waitlisted_and_declined():
    repo = ManyAppRepo(
        _app("a-draft", "DRAFT", child="Ana Rivera", age=1),
        _app("a-pay", "CHECKOUT_PENDING", child="Mateo Rivera", session="sess-paid", age=2),
        _app("a-exp", "CHECKOUT_EXPIRED", child="Rosa Rivera", age=3),
        _app("a-wait", "PENDING_APPROVAL", age=4),
        _app("a-approving", "APPROVING", child="Lena Rivera", age=5),
        _app("a-wl", "WAITLISTED", child="Tomas Rivera", age=6),
        _app("a-dec", "DECLINED", child="Pia Rivera", age=7, decided_at=NOW),
        _app("a-done", "APPROVED", child="Old Rivera", age=8),
        _app("a-gone", "ABANDONED", child="Gone Rivera", age=9),
    )
    assert await _states(repo) == [
        ("a-draft", "finish"),
        ("a-pay", "finish"),
        ("a-exp", "finish"),
        ("a-wait", "waiting"),
        ("a-approving", "waiting"),
        ("a-wl", "waitlisted"),
        ("a-dec", "declined"),
    ]


@pytest.mark.asyncio
async def test_list_hides_scratch_drafts_old_declines_and_other_parents():
    repo = ManyAppRepo(
        _app("blank", "DRAFT", child=""),
        _app("old-dec", "DECLINED", decided_at=NOW - timedelta(days=31)),
        _app("theirs", "PENDING_APPROVAL", parent="parent-2"),
    )
    assert await _states(repo) == []


@pytest.mark.asyncio
async def test_a_newer_attempt_hides_the_older_one_for_the_same_child_and_class():
    repo = ManyAppRepo(
        _app("old", "CHECKOUT_EXPIRED", age=5),
        _app("new", "PENDING_APPROVAL", age=1),
        _app("other-class", "PENDING_APPROVAL", session="sess-paid", age=2),
    )
    assert await _states(repo) == [("new", "waiting"), ("other-class", "waiting")]


@pytest.mark.asyncio
async def test_a_newer_unfinished_draft_never_hides_a_submitted_registration():
    # K02: "Add a child" resumed Mateo's checkout and was retyped as Lucia.
    repo = ManyAppRepo(
        _app("lucia", "PENDING_APPROVAL", age=5),
        _app("retyped", "DRAFT", age=1),
        _app("mateo", "CHECKOUT_PENDING", child="Mateo Rivera", session="sess-paid", age=3),
    )
    assert await _states(repo) == [("mateo", "finish"), ("lucia", "waiting")]


@pytest.mark.asyncio
async def test_an_approved_child_drops_its_leftover_draft():
    repo = ManyAppRepo(
        _app("approved", "APPROVED", age=5),
        _app("leftover", "DRAFT", age=1),
    )
    assert await _states(repo) == []


@pytest.mark.asyncio
async def test_months_old_unfinished_registrations_are_not_shown():
    repo = ManyAppRepo(
        _app("old-draft", "DRAFT", age=24 * 90),
        _app("old-exp", "CHECKOUT_EXPIRED", child="Mateo Rivera", age=24 * 90),
        _app("past-ttl", "DRAFT", child="Rosa Rivera", age=24 * 8),
        _app("old-wait", "PENDING_APPROVAL", child="Ana Rivera", age=24 * 90),
    )
    assert await _states(repo) == [("old-wait", "waiting")]


@pytest.mark.asyncio
async def test_a_paid_or_just_started_checkout_offers_no_second_payment():
    async def payment_status(payment_id):
        return {"pay-ok": "succeeded", "pay-open": "pending"}.get(payment_id)

    repo = ManyAppRepo(
        _app("paid", "CHECKOUT_PENDING", child="Ana Rivera", age=2, payment_id="pay-ok"),
        _app("open", "CHECKOUT_PENDING", child="Rosa Rivera", age=3, payment_id="pay-open"),
    )
    fresh = _app("fresh", "CHECKOUT_PENDING", child="Mateo Rivera", payment_id="pay-open")
    repo.apps["fresh"] = fresh.model_copy(update={"updated_at": NOW - timedelta(minutes=2)})
    assert await _states(repo, payment_status=payment_status) == [
        ("fresh", "paying"),
        ("paid", "paying"),
        ("open", "finish"),
    ]


def _transition(repo):
    return TransitionApplication(repo, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_same_child_same_class_is_refused_in_plain_words():
    repo = ManyAppRepo(
        _app("first", "PENDING_APPROVAL", age=2),
        _app("again", "DRAFT", child="  lucia   RIVERA ", age=1),
    )
    with pytest.raises(ApplicationNotEditable, match="already registered for this class"):
        await _transition(repo).execute("again", "CHECKOUT_PENDING")
    assert repo.apps["again"].status == "DRAFT"


@pytest.mark.asyncio
async def test_an_unpaid_checkout_for_the_same_class_points_to_finish_registration():
    repo = ManyAppRepo(
        _app("first", "CHECKOUT_PENDING", age=2),
        _app("again", "DRAFT", age=1),
    )
    with pytest.raises(ApplicationNotEditable, match="unfinished registration"):
        await _transition(repo).execute("again", "CHECKOUT_PENDING")


@pytest.mark.asyncio
async def test_an_expired_unpaid_checkout_does_not_block_forever():
    repo = ManyAppRepo(
        _app("stale", "CHECKOUT_PENDING", age=24 * 8),
        _app("again", "DRAFT", age=1),
    )
    moved = await _transition(repo).execute("again", "CHECKOUT_PENDING")
    assert moved.status == "CHECKOUT_PENDING"


@pytest.mark.asyncio
async def test_same_student_record_is_refused_even_under_another_spelling():
    repo = ManyAppRepo(
        _app("first", "CHECKOUT_PENDING", student_id="stu-1", age=2),
        _app("again", "DRAFT", child="Lucy Rivera", student_id="stu-1", age=1),
    )
    with pytest.raises(ApplicationNotEditable):
        await _transition(repo).execute("again", "CHECKOUT_PENDING")


@pytest.mark.asyncio
async def test_second_class_for_the_same_child_is_allowed():
    repo = ManyAppRepo(
        _app("first", "PENDING_APPROVAL", age=2),
        _app("second", "DRAFT", session="sess-paid", age=1),
    )
    moved = await _transition(repo).execute("second", "CHECKOUT_PENDING")
    assert moved.status == "CHECKOUT_PENDING"


@pytest.mark.asyncio
async def test_twins_in_the_same_class_are_allowed():
    repo = ManyAppRepo(
        _app("lucia", "PENDING_APPROVAL", age=2),
        _app("sofia", "DRAFT", child="Sofia Rivera", age=1),
    )
    moved = await _transition(repo).execute("sofia", "CHECKOUT_PENDING")
    assert moved.status == "CHECKOUT_PENDING"


@pytest.mark.asyncio
async def test_an_expired_checkout_does_not_block_registering_again():
    repo = ManyAppRepo(
        _app("old", "CHECKOUT_EXPIRED", age=2),
        _app("again", "DRAFT", age=1),
    )
    moved = await _transition(repo).execute("again", "CHECKOUT_PENDING")
    assert moved.status == "CHECKOUT_PENDING"


def _start(repo):
    return StartApplication(apps=repo, academy_id=lambda: "acad", clock=lambda: NOW)


@pytest.mark.asyncio
async def test_finish_registration_resumes_the_card_not_the_latest_application():
    repo = ManyAppRepo(
        _app("mateo", "CHECKOUT_PENDING", child="Mateo Rivera", session="sess-paid", age=3),
        _app("lucia", "PENDING_APPROVAL", age=1),
    )
    resumed = await _start(repo).execute(
        StartApplicationCommand(
            parent_user_id="parent-1",
            parent_email="new.parent@example.com",
            application_id="mateo",
        )
    )
    assert resumed.application_id == "mateo"
    assert resumed.status == "DRAFT"


@pytest.mark.asyncio
async def test_finishing_an_expired_checkout_starts_again_with_the_same_child_and_class():
    repo = ManyAppRepo(_app("exp", "CHECKOUT_EXPIRED", child="Mateo Rivera", session="sess-paid"))
    fresh = await _start(repo).execute(
        StartApplicationCommand(
            parent_user_id="parent-1", parent_email="new.parent@example.com", application_id="exp"
        )
    )
    assert fresh.application_id != "exp"
    assert fresh.status == "DRAFT"
    assert fresh.child_profile.first_name == "Mateo"
    assert fresh.selected_session_id == "sess-paid"
    assert fresh.waiver_acceptance is None


@pytest.mark.asyncio
async def test_another_parents_application_id_is_ignored():
    repo = ManyAppRepo(_app("theirs", "CHECKOUT_EXPIRED", parent="parent-2"))
    fresh = await _start(repo).execute(
        StartApplicationCommand(
            parent_user_id="parent-1",
            parent_email="new.parent@example.com",
            application_id="theirs",
        )
    )
    assert fresh.application_id != "theirs"
    assert fresh.child_profile.first_name == ""


def _start(repo, account=None):
    async def account_profile(parent_user_id):
        return account

    return StartApplication(
        apps=repo,
        academy_id=lambda: "acad",
        clock=lambda: NOW,
        account_profile=account_profile if account is not None else None,
    )


@pytest.mark.asyncio
async def test_add_a_child_does_not_reopen_a_draft_checkout_refused_as_a_duplicate():
    """S02 persona follow-up: Lucia is already waiting for the free class; her
    second (refused) draft for the same class must not come back on Add a child."""
    repo = ManyAppRepo(
        _app("a-wait", "PENDING_APPROVAL", age=3),
        _app("a-dup", "DRAFT", age=1),
    )
    app = await _start(repo).execute(
        StartApplicationCommand(parent_user_id="parent-1", parent_email="new.parent@example.com")
    )
    assert app.application_id not in {"a-wait", "a-dup"}
    assert app.child_profile.first_name == ""
    assert repo.apps["a-dup"].status == "ABANDONED"


@pytest.mark.asyncio
async def test_a_draft_for_a_different_class_is_still_resumed():
    repo = ManyAppRepo(
        _app("a-wait", "PENDING_APPROVAL", age=3),
        _app("a-other", "DRAFT", session="sess-paid", age=1),
    )
    app = await _start(repo).execute(
        StartApplicationCommand(parent_user_id="parent-1", parent_email="new.parent@example.com")
    )
    assert app.application_id == "a-other"


@pytest.mark.asyncio
async def test_a_first_application_takes_the_parent_name_and_phone_from_the_account():
    """S21 persona follow-up: a seeded parent with no earlier application starts
    at the child step, not a blank parent step."""
    repo = ManyAppRepo()
    account = ParentProfile(first_name="Demo", last_name="Parent", phone="555-0103")
    app = await _start(repo, account).execute(
        StartApplicationCommand(parent_user_id="parent-1", parent_email="new.parent@example.com")
    )
    assert (app.parent_profile.first_name, app.parent_profile.last_name) == ("Demo", "Parent")
    assert app.parent_profile.phone == "555-0103"


@pytest.mark.asyncio
async def test_typed_parent_details_are_never_overwritten_by_the_account():
    previous = _app("a-old", "APPROVED", age=5).model_copy(
        update={"parent_profile": ParentProfile(first_name="Pat", last_name="Typed", phone="")}
    )
    repo = ManyAppRepo(previous)
    account = ParentProfile(first_name="Account", last_name="Name", phone="555-0103")
    app = await _start(repo, account).execute(
        StartApplicationCommand(parent_user_id="parent-1", parent_email="new.parent@example.com")
    )
    assert (app.parent_profile.first_name, app.parent_profile.last_name) == ("Pat", "Typed")
    assert app.parent_profile.phone == "555-0103"
