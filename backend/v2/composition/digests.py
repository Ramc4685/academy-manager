"""Compose SendCoachDailyDigest from the communications + coaching contexts.

The plan generator is reused verbatim from Phase 2 (no new plan logic). It is
wrapped in a duck-typed ``plan_provider`` that first resolves the academy's
default program — mirroring the coach BFF route's graceful resolution — so a
missing pathway degrades to an all-unplaced plan instead of raising.

Email safety: every digest sender comes from ``_build_email_sender`` — the real
Resend adapter is only wired when ``email_delivery_enabled`` and a
``resend_api_key`` are both set *and* the environment is staging/prod;
otherwise a stub records sends without contacting a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.pathway import (
    CurriculumComposition,
    compose_curriculum,
    compose_student_progress,
)
from backend.v2.contexts.billing.infrastructure.mongo_autopay_consent_repo import (
    MongoAutopayConsentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    DuesView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.use_cases.get_digest_delivery_log import (
    GetDigestDeliveryLog,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    SendCoachDigestTest,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_daily_digest import (
    SendParentDailyDigest,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_digest_send_repo import (
    MongoDigestSendRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_parent_digest_send_repo import (
    MongoParentDigestSendRepository,
)
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    ListCoachOccurrencesForDate,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.application.use_cases.magic_link import IssueMagicLink
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.identity.infrastructure.mongo_magic_link_repo import (
    MongoMagicLinkRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.get_pathway_placement import (
    GetStudentPathwayPlacement,
    StudentPathwayPlacementRequest,
)
from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    GetTeachingFocus,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url


@dataclass(frozen=True, slots=True)
class ResolvedDigestSchedule:
    """Effective coach-digest schedule for one academy.

    ``enabled``/``hour`` are the *effective* values the hourly scheduler acts on
    after merging the per-academy notification override with the env fallback.
    """

    enabled: bool
    hour: int


def resolve_digest_schedule(
    *,
    academy_enabled: bool | None,
    academy_hour: int | None,
    env_enabled: bool,
    env_hour: int,
) -> ResolvedDigestSchedule:
    """Merge a per-academy override with the deprecated env fallback.

    Pure (no I/O, no APScheduler) so the resolution rule is unit-testable in
    isolation. The per-academy value wins when present; otherwise we fall back
    to the env default, preserving the original behaviour for any deployment
    that has not yet saved per-academy values.

    Note: ``hour`` is interpreted in the *scheduler* timezone, not the academy's
    local timezone — interpreting it per-academy is explicit future work.
    """
    enabled = env_enabled if academy_enabled is None else academy_enabled
    hour = env_hour if academy_hour is None else academy_hour
    if not (0 <= hour <= 23):
        hour = env_hour
    return ResolvedDigestSchedule(enabled=bool(enabled), hour=int(hour))


def _id_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("program_id", ""))
    return str(getattr(program, "program_id", ""))


def _name_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name", "") or "")
    return str(getattr(program, "name", "") or "")


class _CoachDigestPlanProvider:
    """Wraps GenerateDailyTeachingPlan; resolves the default program first.

    Crosses into the coaching context only at the composition root — the
    digest use case itself stays context-agnostic (ADR-0005).
    """

    def __init__(
        self,
        *,
        generate: GenerateDailyTeachingPlan,
        curriculum: CurriculumComposition,
    ) -> None:
        self._generate = generate
        self._curriculum = curriculum

    async def execute(self, coach_id: str, on_date: date) -> Any | None:
        program_id, program_name = await self._resolve_program()
        return await self._generate.execute(
            coach_id=coach_id,
            on_date=on_date,
            program_id=program_id,
            program_name=program_name,
        )

    async def _resolve_program(self) -> tuple[str | None, str]:
        try:
            program = await self._curriculum.resolve_default_program.execute()
        except Exception:
            return None, ""
        program_id = _id_of(program)
        if not program_id:
            return None, ""
        name = ""
        try:
            full = await self._curriculum.get_program.execute(program_id)
            if full is not None:
                name = _name_of(full)
        except Exception:
            name = ""
        return program_id, name


@dataclass(frozen=True, slots=True)
class _DigestParts:
    """Shared collaborators for the daily + test coach-digest use cases."""

    digests: MongoDigestSendRepository
    resolver: MongoAudienceResolver
    sender: Any
    plan_provider: _CoachDigestPlanProvider


def _build_digest_parts(db: AsyncIOMotorDatabase[Any]) -> _DigestParts:
    settings = get_settings()

    occurrences_repo = MongoSessionOccurrenceRepository(db)
    sessions_repo = MongoSessionRepository(db)
    enrollments_repo = MongoEnrollmentRepository(db)
    students_repo = MongoStudentRepository(db)
    curriculum = compose_curriculum(db)
    student_progress = compose_student_progress(db)

    generate = GenerateDailyTeachingPlan(
        occurrences=ListCoachOccurrencesForDate(
            occurrences=occurrences_repo, sessions=sessions_repo
        ),
        get_roster=GetSessionRoster(enrollments=enrollments_repo, students=students_repo),
        teaching_focus=student_progress.get_teaching_focus,
        lesson_cards=MongoLessonCardRepository(db),
        video_refs=MongoCurriculumVideoRefRepository(db),
        criteria=MongoCriterionRepository(db),
    )
    plan_provider = _CoachDigestPlanProvider(generate=generate, curriculum=curriculum)

    return _DigestParts(
        digests=MongoDigestSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        # Shared env-gated factory (defined below): the coach daily digest and
        # the admin-triggered digest test must not be the paths that mail real
        # coaches from a dev stack that inherited delivery flags and a key.
        sender=_build_email_sender(settings),
        plan_provider=plan_provider,
    )


def compose_send_coach_daily_digest(db: AsyncIOMotorDatabase[Any]) -> SendCoachDailyDigest:
    parts = _build_digest_parts(db)
    return SendCoachDailyDigest(
        digests=parts.digests,
        resolver=parts.resolver,
        sender=parts.sender,
        plan_provider=parts.plan_provider,
    )


def compose_send_coach_digest_test(db: AsyncIOMotorDatabase[Any]) -> SendCoachDigestTest:
    parts = _build_digest_parts(db)
    return SendCoachDigestTest(
        digests=parts.digests,
        resolver=parts.resolver,
        sender=parts.sender,
        plan_provider=parts.plan_provider,
    )


def compose_get_digest_delivery_log(db: AsyncIOMotorDatabase[Any]) -> GetDigestDeliveryLog:
    return GetDigestDeliveryLog(digests=MongoDigestSendRepository(db))


# ---------------------------------------------------------------------------
# Parent daily digest (Slice 3): cross-context data provider
# ---------------------------------------------------------------------------


def _day_bounds_utc(on_date: date, tz_name: str) -> tuple[datetime, datetime]:
    """UTC bounds for the *scheduler-local* calendar day.

    ``on_date`` is the local date the digest is being built for (per the hourly
    scheduler in ``main.py``, which ticks in ``settings.scheduler_tz``). Session
    occurrences are stored as aware UTC, so an evening local session can fall on
    the *next* UTC calendar day — bounding by naive UTC midnight would drop it.
    """
    try:
        tz: Any = ZoneInfo(tz_name)
    except Exception:
        tz = UTC
    local_start = datetime.combine(on_date, time.min, tzinfo=tz)
    local_end = datetime.combine(on_date, time.max, tzinfo=tz)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class _ParentDigestProvider:
    """Assembles one family's daily digest view (ADR-0005 cross-context wiring).

    ``build_view`` reaches across enrollment (children + sessions), curriculum +
    student_progress (teaching focus + pathway placement), billing (dues +
    autopay) and identity (portal status) — all at the composition root so the
    ``SendParentDailyDigest`` use case imports nothing cross-context. Every
    sub-lookup degrades gracefully: a failure hides that block rather than
    aborting the send. ``None`` is returned only when the family genuinely has no
    session today, so the use case records ``skipped_empty`` and e-mails nobody.
    """

    def __init__(
        self,
        *,
        students: MongoStudentRepository,
        enrollments: MongoEnrollmentRepository,
        occurrences: MongoSessionOccurrenceRepository,
        sessions: MongoSessionRepository,
        levels: MongoLevelRepository,
        curriculum: CurriculumComposition,
        teaching_focus: GetTeachingFocus,
        pathway_placement: GetStudentPathwayPlacement,
        ledger: MongoBillingLedgerRepository,
        autopay_consents: MongoAutopayConsentRepository,
        academies: MongoAcademyRepository,
        issue_magic_link: IssueMagicLink | None = None,
    ) -> None:
        self._students = students
        self._enrollments = enrollments
        self._occurrences = occurrences
        self._sessions = sessions
        self._levels = levels
        self._curriculum = curriculum
        self._teaching_focus = teaching_focus
        self._pathway_placement = pathway_placement
        self._ledger = ledger
        self._autopay_consents = autopay_consents
        self._academies = academies
        self._issue_magic_link = issue_magic_link

    async def build_view(self, parent_id: str, on_date: date) -> ParentDigestView | None:
        children_students = await self._list_children(parent_id)
        if not children_students:
            return None

        settings = get_settings()
        try:
            academy_doc = await self._academies.find_by_id(current_academy_id())
            academy_slug = str(academy_doc.get("slug") or "") if academy_doc else ""
        except Exception:
            academy_slug = ""
        frontend = academy_frontend_url(
            frontend_url=settings.frontend_url, academy_slug=academy_slug
        )

        # on_portal decides Variant A vs B up front so per-child deep links are
        # only populated when there is a portal to land on.
        user_doc = await self._parent_user_doc(parent_id)
        on_portal = self._is_on_portal(user_doc)

        program_id, program_name = await self._resolve_program()

        children: list[ChildDigestView] = []
        for student in children_students:
            session = await self._session_today(student.student_id, on_date)
            if session is None:
                continue
            _session_id, session_time, session_label = session
            focus_skill, focus_status = await self._focus(
                student.student_id, student.full_name, program_id
            )
            placement = await self._placement(student.student_id, program_id)
            children.append(
                ChildDigestView(
                    child_name=student.full_name,
                    session_time=session_time,
                    session_label=session_label,
                    focus_skill=focus_skill,
                    focus_status=focus_status,
                    level_name=placement["level_name"],
                    skills_completed=placement["skills_completed"],
                    skills_total=placement["skills_total"],
                    skills_left=placement["skills_left"],
                    levels_to_go=placement["levels_to_go"],
                    # Deep-link the absence-request flow (the Requests page opens
                    # on its Absences tab), NOT the attendance history page, which
                    # ignores query params and cannot report an absence.
                    cant_make_it_url=(
                        f"{frontend}/parent/requests" if (on_portal and frontend) else None
                    ),
                )
            )

        if not children:
            return None

        dues = await self._dues(parent_id, frontend)
        autopay_enabled = await self._autopay_enabled(parent_id)
        reply_to = await self._reply_to(settings.sender_email)
        activate_url = await self._activate_url(
            frontend=frontend,
            user_doc=user_doc,
            on_portal=on_portal,
            dues=dues,
            parent_id=parent_id,
        )

        return ParentDigestView(
            parent_name=self._parent_name(user_doc),
            date_label=self._date_label(on_date),
            program_name=program_name,
            children=tuple(children),
            on_portal=on_portal,
            dues=dues,
            autopay_enabled=autopay_enabled,
            portal_url=(f"{frontend}/parent/dashboard" if frontend else ""),
            # Variant B activation CTA. These parents already exist — admin
            # provisioning creates the Firebase account (MongoUserRepo
            # `_create_firebase_user`); they simply never set a password. We mint
            # a one-time magic link (`/auth/magic?t=`) that signs them straight
            # in and lands them on next_path. If minting fails the value falls
            # back to the sign-in page (`_activate_url`), so the digest never
            # crashes on this. See `_activate_url` for the fallback contract.
            activate_url=activate_url,
            reply_to=reply_to,
        )

    async def _list_children(self, parent_id: str) -> list[Any]:
        try:
            return await self._students.list_for_parent(parent_id)
        except Exception:
            return []

    async def _resolve_program(self) -> tuple[str, str]:
        try:
            program = await self._curriculum.resolve_default_program.execute()
        except Exception:
            return "", ""
        program_id = _id_of(program)
        if not program_id:
            return "", ""
        name = ""
        try:
            full = await self._curriculum.get_program.execute(program_id)
            if full is not None:
                name = _name_of(full)
        except Exception:
            name = ""
        return program_id, name

    async def _session_today(self, student_id: str, on_date: date) -> tuple[str, str, str] | None:
        try:
            enrollments = await self._enrollments.active_for_student(student_id)
        except Exception:
            return None
        scheduler_tz = getattr(get_settings(), "scheduler_tz", None) or "UTC"
        start, end = _day_bounds_utc(on_date, scheduler_tz)
        best: tuple[datetime, str, Any] | None = None
        for enrollment in enrollments:
            try:
                occurrences = await self._occurrences.list_for_session_between(
                    session_id=enrollment.session_id, start_at=start, end_at=end
                )
            except Exception:
                occurrences = []
            for occurrence in occurrences:
                if str(getattr(occurrence, "status", "")) == "cancelled":
                    continue
                occ_start = _as_aware_utc(occurrence.start_at)
                if best is None or occ_start < best[0]:
                    best = (occ_start, enrollment.session_id, occurrence)
        if best is None:
            return None
        _, session_id, occurrence = best
        try:
            session = await self._sessions.get(session_id)
        except Exception:
            session = None
        session_time = self._format_time_range(
            occurrence.start_at, occurrence.end_at, getattr(session, "timezone", None)
        )
        return session_id, session_time, self._session_label(session)

    @staticmethod
    def _session_label(session: Any) -> str:
        if session is None:
            return "Session"
        title = str(getattr(session, "title", "") or "Session")
        location = str(getattr(session, "location", "") or "")
        return f"{title} @ {location}" if location else title

    @staticmethod
    def _format_time_range(start: datetime, end: datetime, tz_name: str | None) -> str:
        tz: Any = UTC
        if tz_name:
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = UTC
        local_start = _as_aware_utc(start).astimezone(tz)
        local_end = _as_aware_utc(end).astimezone(tz)

        def hm(dt: datetime) -> str:
            hour = dt.hour % 12 or 12
            return f"{hour}:{dt.minute:02d}"

        def meridiem(dt: datetime) -> str:
            return "AM" if dt.hour < 12 else "PM"

        if meridiem(local_start) == meridiem(local_end):
            return f"{hm(local_start)} - {hm(local_end)} {meridiem(local_end)}"
        return f"{hm(local_start)} {meridiem(local_start)} - {hm(local_end)} {meridiem(local_end)}"

    async def _focus(self, student_id: str, student_name: str, program_id: str) -> tuple[str, str]:
        if not program_id:
            return "", ""
        try:
            result = await self._teaching_focus.for_students(
                [(student_id, student_name)], program_id
            )
        except Exception:
            return "", ""
        for group in result.groups:
            for student in group.students:
                if student.student_id == student_id and student.next_skill is not None:
                    status = str(student.next_skill.status or "").lower().replace("_", " ")
                    return student.next_skill.name, status
        return "", ""

    async def _placement(self, student_id: str, program_id: str) -> dict[str, Any]:
        default: dict[str, Any] = {
            "level_name": "",
            "skills_completed": 0,
            "skills_total": 0,
            "skills_left": 0,
            "levels_to_go": 0,
        }
        if not program_id:
            return default
        try:
            placement = await self._pathway_placement.execute(
                StudentPathwayPlacementRequest(student_id=student_id, program_id=program_id)
            )
        except Exception:
            return default
        skills_total = int(placement.skills_total or 0)
        skills_completed = int(placement.skills_completed or 0)
        levels_to_go = 0
        sequence = placement.level_sequence
        if sequence is not None:
            try:
                levels = await self._levels.list_for_program(program_id)
                levels_to_go = sum(
                    1 for level in levels if int(getattr(level, "sequence", 0)) > int(sequence)
                )
            except Exception:
                levels_to_go = 0
        return {
            "level_name": placement.level_name or "",
            "skills_completed": skills_completed,
            "skills_total": skills_total,
            "skills_left": max(skills_total - skills_completed, 0),
            "levels_to_go": levels_to_go,
        }

    async def _dues(self, parent_id: str, frontend: str) -> DuesView | None:
        try:
            invoices = await self._ledger.list_invoices_for_parent(parent_id)
        except Exception:
            return None
        # Match the parent checkout path, which only treats "open"/"partially_paid"
        # as payable — surfacing a pay link for a "draft" invoice would 404.
        open_statuses = {"open", "partially_paid"}
        owed = [
            invoice
            for invoice in invoices
            if int(getattr(invoice, "balance_due_cents", 0) or 0) > 0
            and str(getattr(invoice, "status", "")) in open_statuses
        ]
        if not owed:
            return None
        total_cents = sum(int(invoice.balance_due_cents) for invoice in owed)
        due_dates = [invoice.due_date for invoice in owed if invoice.due_date is not None]
        earliest = min(due_dates) if due_dates else None
        return DuesView(
            amount=f"${total_cents / 100:,.2f}",
            due_date=self._format_due_date(earliest) if earliest is not None else "",
            pay_url=(f"{frontend}/parent/payments" if frontend else ""),
        )

    @staticmethod
    def _format_due_date(value: Any) -> str:
        due = value.date() if isinstance(value, datetime) else value
        try:
            return f"{due.strftime('%B')} {due.day}"
        except Exception:
            return ""

    async def _autopay_enabled(self, parent_id: str) -> bool:
        # The AutopayConsent collection is append-only with no revoked/active
        # field, so the presence of ANY consent means the family has set up a
        # saved payment method (autopay). On lookup failure we default to True to
        # avoid nagging a family that may already have autopay.
        try:
            consents = await self._autopay_consents.list_for_parent(parent_id=parent_id)
        except Exception:
            return True
        return len(consents) > 0

    async def _reply_to(self, fallback: str | None) -> str | None:
        try:
            academy_id = current_academy_id()
            doc = await self._academies.find_by_id(academy_id)
            if doc:
                for key in ("contact_email", "owner_email", "email"):
                    value = doc.get(key)
                    if value:
                        return str(value)
        except Exception:
            pass
        return fallback

    async def _parent_user_doc(self, parent_id: str) -> dict[str, Any] | None:
        # Delegated to the tenant-scoped student repo (infrastructure) so the raw
        # ``users`` read does not live in the composition layer.
        try:
            return await self._students.get_parent_user_doc(parent_id)
        except Exception:
            return None

    async def _activate_url(
        self,
        *,
        frontend: str,
        user_doc: dict[str, Any] | None,
        on_portal: bool,
        dues: DuesView | None,
        parent_id: str,
    ) -> str:
        """Variant B CTA target: a one-time magic link, or /login as fallback.

        Only never-activated parents (Variant B, ``on_portal`` False) get the
        activation CTA, so that is the only case worth minting a token for. The
        link lands on the payments page when a balance is owed, else the
        dashboard. Minting is best-effort: any failure (no issuer wired, Mongo
        or Firebase error) degrades to the prefilled sign-in URL — a digest must
        never crash on this.
        """
        fallback = self._login_url(frontend, user_doc)
        if on_portal or not frontend or self._issue_magic_link is None:
            return fallback
        try:
            academy_id = current_academy_id()
            next_path = "/parent/payments" if dues is not None else "/parent/dashboard"
            token = await self._issue_magic_link.execute(
                user_id=parent_id, academy_id=academy_id, next_path=next_path
            )
        except Exception:
            return fallback
        return f"{frontend}/auth/magic?t={quote(token, safe='')}"

    @staticmethod
    def _login_url(frontend: str, user_doc: dict[str, Any] | None) -> str:
        """Sign-in deep link for a provisioned-but-never-activated parent.

        Email is prefilled when known so the parent can go straight to
        "Forgot password" and receive a set-password link.
        """
        if not frontend:
            return ""
        email = str((user_doc or {}).get("email") or "").strip()
        if not email:
            return f"{frontend}/login"
        return f"{frontend}/login?email={quote(email, safe='')}"

    @staticmethod
    def _is_on_portal(user_doc: dict[str, Any] | None) -> bool:
        # "On the portal" = the parent has an active login. The users collection
        # has no explicit last-login field, so the most reliable available signal
        # is a verified email — Firebase sets email_verified when the parent
        # completes the set-password invite or signs in with Google — with a
        # last-login/last-seen timestamp as a secondary signal if present.
        # Admin-provisioned parents who never activated their account have
        # neither, so they fall to Variant B (the activation CTA).
        if not user_doc:
            return False
        for key in ("email_verified", "emailVerified", "is_email_verified"):
            if bool(user_doc.get(key)):
                return True
        for key in ("last_login_at", "last_seen_at", "last_active_at"):
            if user_doc.get(key):
                return True
        return False

    @staticmethod
    def _parent_name(user_doc: dict[str, Any] | None) -> str:
        if not user_doc:
            return "there"
        display = str(user_doc.get("display_name") or "").strip()
        if display:
            return display
        combined = " ".join(
            str(user_doc.get(key) or "") for key in ("first_name", "last_name")
        ).strip()
        if combined:
            return combined
        email = user_doc.get("email")
        return str(email) if email else "there"

    @staticmethod
    def _date_label(on_date: date) -> str:
        return f"{on_date.strftime('%A, %B')} {on_date.day}"


_REAL_EMAIL_ENVS = frozenset({"staging", "prod"})


def _build_email_sender(settings: Any) -> Any:
    """Resend/Stub gating for every digest send path.

    The single construction site for any adapter that *sends* (enforced by
    ``v2/tests/structural/test_email_sender_construction.py``): parent digest,
    ops digest, coach daily digest and the admin-triggered coach digest test all
    come through here, so the gate cannot be right in one copy and missing in
    another. ``compose_email_credential_probe`` below is the only other place
    that builds the adapter — deliberately ungated, because it validates the
    API key and never sends.

    Beyond ``email_delivery_enabled`` + ``resend_api_key``, the real adapter is
    only wired in an approved environment (staging/prod) — see
    ``ResendEmailSendPort``'s own contract and ``AGENTS.md``: "Do not send real
    email from local/test environments." A dev or test deployment that has
    inherited delivery flags and Resend credentials must still fall back to the
    stub.
    """
    from_address = settings.sender_email or (
        f"noreply@{settings.frontend_url.replace('https://', '').replace('http://', '').split('/')[0]}"
        if settings.frontend_url
        else "noreply@academy.app"
    )
    env = str(getattr(settings, "env", "") or "").lower()
    if settings.email_delivery_enabled and settings.resend_api_key and env in _REAL_EMAIL_ENVS:
        return ResendEmailSendPort(api_key=settings.resend_api_key, from_address=from_address)
    return StubEmailSendPort()


def compose_email_credential_probe() -> Any | None:
    """A port for the boot-time credential check, or ``None`` when there is no
    credential to check (issue #435).

    Deliberately *not* ``compose_ops_digest_sender()``: that one is env-gated to
    staging/prod, and a stub carries no key to validate. The question this
    answers is "is the configured Resend key alive", so it follows the
    credential, not the environment.

    The probe only ever issues a read (``Domains.list``); ``from_address`` is
    never used, so no send path is reachable from it.
    """
    settings = get_settings()
    if not (settings.email_delivery_enabled and settings.resend_api_key):
        return None
    return ResendEmailSendPort(
        api_key=settings.resend_api_key, from_address="credential-probe@invalid"
    )


def compose_ops_digest_sender() -> Any:
    """Email port for the daily owner ops digest (issue #428).

    Reuses the parent/coach digest gating verbatim so the ops digest cannot be
    the one path that sends real email from a dev or test deployment.
    """
    return _build_email_sender(get_settings())


def compose_send_parent_daily_digest(
    db: AsyncIOMotorDatabase[Any],
) -> SendParentDailyDigest:
    settings = get_settings()
    student_progress = compose_student_progress(db)
    provider = _ParentDigestProvider(
        students=MongoStudentRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        occurrences=MongoSessionOccurrenceRepository(db),
        sessions=MongoSessionRepository(db),
        levels=MongoLevelRepository(db),
        curriculum=compose_curriculum(db),
        teaching_focus=student_progress.get_teaching_focus,
        pathway_placement=student_progress.get_pathway_placement,
        ledger=MongoBillingLedgerRepository(db),
        autopay_consents=MongoAutopayConsentRepository(db),
        academies=MongoAcademyRepository(db),
        issue_magic_link=IssueMagicLink(MongoMagicLinkRepository(db)),
    )
    return SendParentDailyDigest(
        digests=MongoParentDigestSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=_build_email_sender(settings),
        provider=provider,
    )
