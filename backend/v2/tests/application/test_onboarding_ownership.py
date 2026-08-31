"""Wave 2 ownership tests — a parent can only read/patch their own
onboarding application. Closes the security gap surfaced by review
comment on PR #18."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    APPLICATION_TTL_DAYS,
    GetApplicationStatus,
    PatchApplication,
    PatchApplicationCommand,
    TransitionApplication,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationForPaymentNotFound,
    ApplicationNotEditable,
    ApplicationNotFound,
)
from backend.v2.contexts.onboarding.domain.models import Application, ChildProfile


class FakeAppRepo:
    """In-memory ApplicationRepository with REAL compare-and-set semantics.

    `reopen_for_edit` / `restamp_checkout` must miss when the stored document
    no longer matches what the caller read — a fake that always writes would
    make every concurrency test below vacuous.
    """

    def __init__(self, app: Application | None) -> None:
        self._app = app
        self.saved: list[Application] = []

    async def save(self, app):
        self._app = app
        self.saved.append(app)

    async def get(self, application_id):
        return self._app if self._app and self._app.application_id == application_id else None

    async def latest_for_parent(self, _):
        return self._app

    async def get_by_payment_id(self, payment_id):
        # Mirrors the adapter: the LIVE attempt only.
        if self._app is None or payment_id != self._app.payment_id:
            return None
        return self._app

    async def get_by_superseded_payment_id(self, payment_id):
        # Mirrors the adapter: an attempt a re-stamp replaced. Kept separate so
        # only the advance path can resolve through it (#549).
        if self._app is None or payment_id not in self._app.superseded_payment_ids:
            return None
        return self._app

    async def reopen_for_edit(self, application_id, *, expected_status, updated_at):
        app = await self.get(application_id)
        if app is None or app.status != expected_status:
            return None
        self._app = app.model_copy(update={"status": "DRAFT", "updated_at": updated_at})
        return self._app

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
        app = await self.get(application_id)
        if app is None or app.status != expected_status or app.payment_id != expected_payment_id:
            return None
        updates: dict[str, object] = {"updated_at": updated_at}
        if new_status is not None:
            updates["status"] = new_status
        if stripe_checkout_session_id is not None:
            updates["stripe_checkout_session_id"] = stripe_checkout_session_id
        if payment_id is not None:
            updates["payment_id"] = payment_id
        if (
            expected_payment_id is not None
            and payment_id is not None
            and payment_id != expected_payment_id
            and expected_payment_id not in app.superseded_payment_ids
        ):
            updates["superseded_payment_ids"] = [
                *app.superseded_payment_ids,
                expected_payment_id,
            ]
        self._app = app.model_copy(update=updates)
        return self._app


class RecordingRetirement:
    """Records what the use case asked Billing to kill off."""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str | None]] = []

    async def retire_checkout_attempt(self, *, checkout_session_id, payment_id):
        self.calls.append((checkout_session_id, payment_id))


class FakeWaiverRepo:
    async def get_active(self):
        return None


class ExistingStudentRegistrations:
    async def find_registration_student(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> str | None:
        return "existing-student"

    async def has_ambiguous_registration_match(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> bool:
        return False

    async def has_active_enrollment(
        self,
        student_id: str,
        *,
        exclude_enrollment_id: str | None = None,
    ) -> bool:
        return student_id == "existing-student"


class ConfigurableStudentRegistrations:
    def __init__(
        self,
        *,
        student_id: str | None = None,
        active: bool = False,
        ambiguous: bool = False,
    ) -> None:
        self.student_id = student_id
        self.active = active
        self.ambiguous = ambiguous

    async def find_registration_student(self, **kwargs) -> str | None:
        return self.student_id

    async def has_ambiguous_registration_match(self, **kwargs) -> bool:
        return self.ambiguous

    async def has_active_enrollment(
        self, student_id: str, *, exclude_enrollment_id: str | None = None
    ) -> bool:
        return self.active and student_id == self.student_id


def _app(parent_user_id: str = "alice") -> Application:
    now = datetime.now(UTC)
    return Application(
        application_id="app-1",
        academy_id="acad",
        parent_user_id=parent_user_id,
        parent_email=f"{parent_user_id}@example.com",
        status="DRAFT",
        expires_at=now + timedelta(days=APPLICATION_TTL_DAYS),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_patch_application_rejects_other_parent() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    with pytest.raises(ApplicationNotFound):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="bob",  # different parent
            )
        )


@pytest.mark.asyncio
async def test_patch_application_allows_owner() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    result = await uc.execute(
        PatchApplicationCommand(
            application_id="app-1",
            caller_user_id="alice",
            parent_profile={"first_name": "Alice"},
        )
    )
    assert result.parent_profile.first_name == "Alice"


@pytest.mark.asyncio
async def test_patch_application_rejects_an_already_enrolled_child() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    uc._student_registrations = ExistingStudentRegistrations()  # type: ignore[attr-defined]

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="alice",
                child_profile={
                    "first_name": "Sam",
                    "last_name": "Student",
                    "date_of_birth": "2015-05-10",
                    "skill_level": "beginner",
                },
            )
        )

    assert repo._app is not None
    assert repo._app.child_profile.first_name == ""


@pytest.mark.asyncio
async def test_patch_child_profile_clears_stale_student_binding_when_identity_changes() -> None:
    repo = FakeAppRepo(_app().model_copy(update={"student_id": "old-student"}))
    registrations = ConfigurableStudentRegistrations(student_id=None)
    uc = PatchApplication(
        apps=repo,
        waivers=FakeWaiverRepo(),
        student_registrations=registrations,
    )

    result = await uc.execute(
        PatchApplicationCommand(
            application_id="app-1",
            caller_user_id="alice",
            child_profile={
                "first_name": "Different",
                "last_name": "Child",
                "date_of_birth": "2017-01-02",
                "skill_level": "beginner",
            },
        )
    )

    assert result.student_id is None


@pytest.mark.asyncio
async def test_patch_rejects_ambiguous_legacy_child_match() -> None:
    repo = FakeAppRepo(_app())
    uc = PatchApplication(
        apps=repo,
        waivers=FakeWaiverRepo(),
        student_registrations=ConfigurableStudentRegistrations(ambiguous=True),
    )

    with pytest.raises(ApplicationNotEditable, match="more than one possible child"):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="alice",
                child_profile={
                    "first_name": "Sam",
                    "last_name": "Student",
                    "date_of_birth": "",
                    "skill_level": "beginner",
                },
            )
        )


@pytest.mark.asyncio
async def test_checkout_transition_rechecks_active_enrollment() -> None:
    app = _app().model_copy(
        update={
            "student_id": "existing-student",
            "child_profile": ChildProfile(
                first_name="Sam",
                last_name="Student",
                date_of_birth="2015-05-10",
                skill_level="beginner",
            ),
        }
    )
    repo = FakeAppRepo(app)
    uc = TransitionApplication(
        apps=repo,
        student_registrations=ConfigurableStudentRegistrations(
            student_id="existing-student", active=True
        ),
    )

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await uc.execute("app-1", "CHECKOUT_PENDING")

    assert repo._app is not None
    assert repo._app.status == "DRAFT"


@pytest.mark.asyncio
async def test_get_status_with_caller_rejects_other_parent() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    with pytest.raises(ApplicationNotFound):
        await uc.execute("app-1", caller_user_id="bob")


@pytest.mark.asyncio
async def test_get_status_with_caller_allows_owner() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    result = await uc.execute("app-1", caller_user_id="alice")
    assert result.application_id == "app-1"


@pytest.mark.asyncio
async def test_get_status_without_caller_skips_check() -> None:
    """Webhook handlers and admin paths call without caller_user_id."""
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    result = await uc.execute("app-1")
    assert result.application_id == "app-1"


@pytest.mark.asyncio
async def test_start_application_prefills_parent_profile_from_prior_application() -> None:
    """A returning parent adding a second child must not retype their own
    details: the new draft carries parent_profile from the last application."""
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        StartApplication,
        StartApplicationCommand,
    )
    from backend.v2.contexts.onboarding.domain.models import ParentProfile

    prior = _app(parent_user_id="alice").model_copy(
        update={
            "status": "COMPLETED",
            "parent_profile": ParentProfile(first_name="Alice", last_name="Ng", phone="5551234"),
        }
    )
    repo = FakeAppRepo(prior)
    uc = StartApplication(apps=repo, academy_id=lambda: "acad")

    fresh = await uc.execute(
        StartApplicationCommand(parent_user_id="alice", parent_email="alice@example.com")
    )

    assert fresh.application_id != prior.application_id
    assert fresh.status == "DRAFT"
    assert fresh.parent_profile.first_name == "Alice"
    assert fresh.parent_profile.last_name == "Ng"
    assert fresh.parent_profile.phone == "5551234"
    # Child details must start blank for the new application.
    assert fresh.child_profile.first_name == ""


@pytest.mark.asyncio
async def test_restarting_checkout_repoints_application_at_the_live_payment() -> None:
    """A parent who cancels the first Stripe session and pays on a second one
    must not have their registration orphaned.

    The application is already CHECKOUT_PENDING when the re-start happens, so
    the status does not change — but the ids must: `checkout.session.completed`
    for the SECOND payment resolves back to the application through
    `get_by_payment_id`, and that lookup only works if the application carries
    the live payment_id. Keeping the first payment_id leaves the parent charged
    and the application stuck (P0)."""
    repo = FakeAppRepo(
        _app().model_copy(
            update={
                "status": "CHECKOUT_PENDING",
                "stripe_checkout_session_id": "cs_first",
                "payment_id": "pay-first",
            }
        )
    )
    uc = TransitionApplication(apps=repo)

    updated = await uc.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_second",
        payment_id="pay-second",
    )

    assert updated.status == "CHECKOUT_PENDING"
    assert updated.payment_id == "pay-second"
    assert updated.stripe_checkout_session_id == "cs_second"
    assert repo._app is not None
    assert repo._app.payment_id == "pay-second"
    assert repo._app.stripe_checkout_session_id == "cs_second"


@pytest.mark.asyncio
async def test_same_status_transition_without_ids_leaves_the_application_untouched() -> None:
    """The plain idempotent re-apply (no ids supplied) must stay a no-op — the
    $0 checkout path calls CHECKOUT_PENDING with no ids at all."""
    original = _app().model_copy(
        update={
            "status": "CHECKOUT_PENDING",
            "stripe_checkout_session_id": "cs_first",
            "payment_id": "pay-first",
        }
    )
    repo = FakeAppRepo(original)
    uc = TransitionApplication(apps=repo)

    updated = await uc.execute("app-1", "CHECKOUT_PENDING")

    assert updated is original
    assert repo._app is original


def _checkout_pending(**extra) -> Application:
    """An application parked on a live Stripe Checkout Session."""
    return _app().model_copy(
        update={
            "status": "CHECKOUT_PENDING",
            "stripe_checkout_session_id": "cs_first",
            "payment_id": "pay-first",
            **extra,
        }
    )


# ---------------------------------------------------------------------------
# Option A — returning from Stripe's cancel URL RESUMES the application.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_application_resumes_an_abandoned_checkout() -> None:
    """The wizard calls start on mount, and Stripe's cancel_url points at the
    wizard. Minting a second application here would leave the first one holding
    a still-payable Checkout Session — one enrollment, two ways to be charged."""
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        StartApplication,
        StartApplicationCommand,
    )

    repo = FakeAppRepo(_checkout_pending())
    retirement = RecordingRetirement()
    uc = StartApplication(
        apps=repo,
        academy_id=lambda: "acad",
        checkout_retirement=retirement,
    )

    resumed = await uc.execute(
        StartApplicationCommand(parent_user_id="alice", parent_email="alice@example.com")
    )

    assert resumed.application_id == "app-1"
    # PatchApplication only accepts DRAFT, so a resume that left the status
    # alone would hand the parent a wizard that 409s on every keystroke.
    assert resumed.status == "DRAFT"
    assert repo._app is not None
    assert repo._app.status == "DRAFT"
    # The superseded session must stop being payable.
    assert retirement.calls == [("cs_first", "pay-first")]


@pytest.mark.asyncio
async def test_resume_leaves_the_payment_pointer_so_a_late_webhook_can_find_it() -> None:
    """`get_by_payment_id` is the ONLY handle checkout.session.completed has
    back to the application. Clearing payment_id on resume would orphan a
    payment that succeeded in the instants before the resume won."""
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        StartApplication,
        StartApplicationCommand,
    )

    repo = FakeAppRepo(_checkout_pending())
    uc = StartApplication(apps=repo, academy_id=lambda: "acad")

    await uc.execute(
        StartApplicationCommand(parent_user_id="alice", parent_email="alice@example.com")
    )

    assert repo._app is not None
    assert repo._app.payment_id == "pay-first"


@pytest.mark.asyncio
async def test_resume_never_resurrects_an_application_that_was_already_paid() -> None:
    """The parent may have paid in the other tab while the wizard was mounting.

    The compare-and-set on CHECKOUT_PENDING misses, and the use case must fall
    through to a brand new application rather than dragging a paid one back to
    DRAFT."""
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        StartApplication,
        StartApplicationCommand,
    )

    paid = _checkout_pending().model_copy(update={"status": "PENDING_APPROVAL"})
    repo = FakeAppRepo(paid)
    # latest_for_parent hands back the stale CHECKOUT_PENDING read the caller
    # would have taken a moment before the webhook landed.
    stale = _checkout_pending()

    async def _stale_latest(_):
        return stale

    repo.latest_for_parent = _stale_latest  # type: ignore[method-assign]
    retirement = RecordingRetirement()
    uc = StartApplication(
        apps=repo,
        academy_id=lambda: "acad",
        checkout_retirement=retirement,
    )

    fresh = await uc.execute(
        StartApplicationCommand(parent_user_id="alice", parent_email="alice@example.com")
    )

    assert fresh.application_id != "app-1"
    assert fresh.status == "DRAFT"
    # Nothing was retired: that Stripe session was PAID, and expiring/parking
    # anything around it would erase a real charge.
    assert retirement.calls == []


@pytest.mark.asyncio
async def test_payment_webhook_still_reaches_pending_approval_after_a_resume() -> None:
    """The other side of the same race: the resume wins the CAS, and the
    payment for the superseded session succeeds anyway. The webhook resolves
    the application by payment_id and finds it sitting in DRAFT — that has to
    complete, or the parent is charged with no registration."""
    repo = FakeAppRepo(
        _app().model_copy(
            update={
                "status": "DRAFT",
                "stripe_checkout_session_id": "cs_first",
                "payment_id": "pay-first",
            }
        )
    )
    uc = TransitionApplication(apps=repo)

    updated = await uc.execute_for_payment("pay-first", "PENDING_APPROVAL")

    assert updated is not None
    assert updated.status == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_a_draft_that_never_checked_out_cannot_be_reached_by_a_payment() -> None:
    """DRAFT -> PENDING_APPROVAL is only safe because execute_for_payment
    resolves through payment_id, which a never-checked-out draft does not
    carry. Guard the assumption the transition table now leans on.

    The miss RAISES rather than returning None: the two things the old None
    stood for — "not an onboarding payment at all" and "an onboarding payment
    whose application we lost" — are wildly different, and collapsing them is
    what let a paid-but-orphaned registration pass unnoticed (#549)."""
    repo = FakeAppRepo(_app())
    uc = TransitionApplication(apps=repo)

    with pytest.raises(ApplicationForPaymentNotFound) as excinfo:
        await uc.execute_for_payment("pay-anything", "PENDING_APPROVAL")

    assert excinfo.value.details["payment_id"] == "pay-anything"


@pytest.mark.asyncio
async def test_a_restamp_archives_the_payment_id_it_overwrites() -> None:
    """The re-stamp is what creates the orphan window: the parent may have
    completed the FIRST session at Stripe moments before the second start won
    the CAS. `get_by_payment_id` is the only handle the webhook has, so the id
    being overwritten has to remain resolvable (#549)."""
    repo = FakeAppRepo(_checkout_pending())
    uc = TransitionApplication(apps=repo)

    await uc.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_second",
        payment_id="pay-second",
    )

    assert repo._app is not None
    assert repo._app.payment_id == "pay-second"
    assert repo._app.superseded_payment_ids == ["pay-first"]

    updated = await uc.execute_for_payment("pay-first", "PENDING_APPROVAL")

    assert updated.status == "PENDING_APPROVAL"


# ---------------------------------------------------------------------------
# Re-stamp — concurrent / retried POST /parent/checkout/start.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_retires_the_checkout_it_supersedes() -> None:
    repo = FakeAppRepo(_checkout_pending())
    retirement = RecordingRetirement()
    uc = TransitionApplication(apps=repo, checkout_retirement=retirement)

    await uc.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_second",
        payment_id="pay-second",
    )

    assert repo._app is not None
    assert repo._app.payment_id == "pay-second"
    # Exactly one payable session may exist for an application.
    assert retirement.calls == [("cs_first", "pay-first")]


class _StaleReadRepo:
    """Serves one stale read while writes go to the shared store.

    This is the interleaving a read-then-blind-write cannot survive: the loser
    decided what to write from a snapshot the winner has since replaced.
    """

    def __init__(self, inner: FakeAppRepo, stale: Application) -> None:
        self._inner = inner
        self._stale = stale

    async def get(self, _application_id):
        return self._stale

    async def save(self, app):
        await self._inner.save(app)

    async def restamp_checkout(self, *args, **kwargs):
        return await self._inner.restamp_checkout(*args, **kwargs)


@pytest.mark.asyncio
async def test_losing_concurrent_restart_leaves_the_winner_in_place() -> None:
    """Two tabs start checkout at once. The compare-and-set covers payment_id,
    so the second writer misses — and must NOT re-point the application at its
    own payment, which would leave the winner's live payment orphaned."""
    repo = FakeAppRepo(_checkout_pending())
    retirement = RecordingRetirement()
    winner = TransitionApplication(apps=repo, checkout_retirement=retirement)

    await winner.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_winner",
        payment_id="pay-winner",
    )
    retirement.calls.clear()

    # The loser still holds the read it took BEFORE the winner wrote, so its
    # expected_payment_id is the stale "pay-first".
    loser = TransitionApplication(
        apps=_StaleReadRepo(repo, _checkout_pending()),  # type: ignore[arg-type]
        checkout_retirement=retirement,
    )

    with pytest.raises(ApplicationNotEditable) as excinfo:
        await loser.execute(
            "app-1",
            "CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_loser",
            payment_id="pay-loser",
        )

    assert excinfo.value.details["from_status"] == "CHECKOUT_PENDING"
    # The application still points at the winner.
    assert repo._app is not None
    assert repo._app.payment_id == "pay-winner"
    assert repo._app.stripe_checkout_session_id == "cs_winner"
    # And the loser killed its OWN session rather than leaving a second payable
    # one behind.
    assert retirement.calls == [("cs_loser", "pay-loser")]


@pytest.mark.asyncio
async def test_restart_refuses_when_the_child_is_already_enrolled() -> None:
    """The real ->CHECKOUT_PENDING transition runs this guard. The re-stamp
    branch writes too, so the same guard has to hold there."""
    repo = FakeAppRepo(
        _checkout_pending(
            child_profile=ChildProfile(
                first_name="Aanya",
                last_name="Raghavan",
                date_of_birth="2015-04-02",
                emergency_contact_name="Vikram",
                emergency_contact_phone="+1 555 0111",
            )
        )
    )
    retirement = RecordingRetirement()
    uc = TransitionApplication(
        apps=repo,
        student_registrations=ExistingStudentRegistrations(),
        checkout_retirement=retirement,
    )

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await uc.execute(
            "app-1",
            "CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_second",
            payment_id="pay-second",
        )

    assert repo._app is not None
    assert repo._app.payment_id == "pay-first"
    assert retirement.calls == []


@pytest.mark.asyncio
async def test_losing_the_entry_race_from_draft_leaves_one_payable_session() -> None:
    """Two tabs start checkout on the same DRAFT application at once.

    The re-stamp CAS only fires once an application is ALREADY
    CHECKOUT_PENDING, so it never covered this — the first race happens on the
    way IN. That write used to be a blind `save`, so both tabs wrote: two live
    payable Stripe sessions, and only the last-written `payment_id`, which is
    the sole handle `PaymentSucceeded` has to find the application again.

    The loser must now miss the CAS, retire the session IT minted, and leave
    the winner's ids untouched.
    """
    repo = FakeAppRepo(_app())  # DRAFT, no payment stamped yet
    retirement = RecordingRetirement()
    winner = TransitionApplication(apps=repo, checkout_retirement=retirement)

    await winner.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_winner",
        payment_id="pay-winner",
    )
    retirement.calls.clear()

    # The loser still holds its pre-race read: status DRAFT, no payment.
    loser = TransitionApplication(
        apps=_StaleReadRepo(repo, _app()),  # type: ignore[arg-type]
        checkout_retirement=retirement,
    )

    with pytest.raises(ApplicationNotEditable):
        await loser.execute(
            "app-1",
            "CHECKOUT_PENDING",
            stripe_checkout_session_id="cs_loser",
            payment_id="pay-loser",
        )

    # The winner still owns the application...
    current = await repo.get("app-1")
    assert current.status == "CHECKOUT_PENDING"
    assert current.stripe_checkout_session_id == "cs_winner"
    assert current.payment_id == "pay-winner"
    # ...and the loser killed its OWN session, not the winner's.
    assert retirement.calls == [("cs_loser", "pay-loser")]


# ---------------------------------------------------------------------------
# The archive is a ONE-WAY DOOR: it may advance an application, never retire it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("destructive", ["CHECKOUT_EXPIRED", "CAPACITY_FAILED_REFUNDING"])
async def test_a_stale_event_for_a_superseded_attempt_cannot_retire_the_live_one(
    destructive: str,
) -> None:
    """Archiving the superseded payment id must not widen the DESTRUCTIVE paths.

    Retirement expires the old Stripe session, which is what MAKES Stripe emit
    `checkout.session.expired` for it. The webhook's own
    `payment.status == "pending"` guard is supposed to absorb that, but the
    write arming it is neither atomic with the CAS nor exception-guarded — so
    the stale event does reach here.

    If the archive answered that event, the application would be parked in
    CHECKOUT_PENDING -> CHECKOUT_EXPIRED, which has NO outgoing transition and
    is not a status checkout can be restarted from, while the parent is paying
    the live attempt. Charged, unadvanced and unrecoverable — strictly worse
    than the orphan the archive repairs.
    """
    repo = FakeAppRepo(_checkout_pending())
    uc = TransitionApplication(apps=repo)

    await uc.execute(
        "app-1",
        "CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_second",
        payment_id="pay-second",
    )
    assert repo._app is not None
    assert repo._app.superseded_payment_ids == ["pay-first"]

    # The superseded attempt's own expiry / capacity event lands late.
    with pytest.raises(ApplicationForPaymentNotFound):
        await uc.execute_for_payment("pay-first", destructive)

    # The live attempt is untouched and can still be paid.
    assert repo._app.status == "CHECKOUT_PENDING"
    assert repo._app.payment_id == "pay-second"

    advanced = await uc.execute_for_payment("pay-second", "PENDING_APPROVAL")
    assert advanced.status == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_the_live_attempt_still_reaches_its_own_destructive_targets() -> None:
    """The narrowing above must not disarm the normal expiry path."""
    repo = FakeAppRepo(_checkout_pending())
    uc = TransitionApplication(apps=repo)

    expired = await uc.execute_for_payment("pay-first", "CHECKOUT_EXPIRED")

    assert expired.status == "CHECKOUT_EXPIRED"
