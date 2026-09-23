"""Seed + app builder shared by the public tenant page tests (Lane B2).

Fictional academies only. The seed deliberately plants private values
(contact details, ids, notes, links, an unpublished class, another
academy's class) that the anonymous page must never return; ``SECRETS``
lists them for the behavioural no-leak assertions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request

from backend.v2.composition.public_page_read import compose_public_page_read
from backend.v2.composition.public_trial_requests import (
    PublicTrialRequests,
    TrialRequestOwnerEmail,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    SubmitWebsiteInquiry,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.public_class_choice import (
    ResolvePublicClassChoice,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.interfaces.public.router import router as public_router
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.http import register_exception_handlers

ACADEMY = "acad-riverside"
OTHER = "acad-lakeside"
HOSTS = {
    "riverside-academy.courtmastr.test": ACADEMY,
    "lakeside-academy.courtmastr.test": OTHER,
}
RIVERSIDE_HOST = "riverside-academy.courtmastr.test"
NOW = datetime(2026, 9, 23, tzinfo=UTC)

SECRETS = {
    "contact_email": "owner.private@example.test",
    "contact_phone": "+1 555 0100",
    "coach_email": "coach.private@example.test",
    "coach_phone": "+1 555 0199",
    "student_id": "stu-secret-0001",
    "parent_id": "par-secret-0001",
    "parent_email": "family.private@example.test",
    "whatsapp": "https://chat.whatsapp.com/SECRETINVITE",
    "parking": "SECRET-PARKING-NOTE",
    "coach_policy": "SECRET-COACH-CONTACT-POLICY",
    "absence_policy": "SECRET-ABSENCE-POLICY",
    "private_title": "SECRET Private Invite-Only Squad",
    "private_session_id": "sess-secret-private",
    "published_session_id": "sess-jr-sat",
    "other_academy_title": "Lakeside Only Evening Class",
    "coach_id": "coach-secret-uid-1",
    "program_id": "prog-secret-juniors",
    "academy_id": ACADEMY,
    "internal_notes": "SECRET-INTERNAL-NOTE",
    "stripe": "acct_SECRETSTRIPE",
}


def _session(session_id: str, academy_id: str = ACADEMY, **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "academy_id": academy_id,
        "session_id": session_id,
        "coach_id": SECRETS["coach_id"],
        "title": f"Class {session_id.removeprefix('sess-')}",
        "location": "Main hall",
        "capacity": 10,
        "amount_cents": 9000,
        "status": "scheduled",
        "days_of_week": ["Sat"],
        "start_time": "09:00",
        "end_time": "10:00",
        "timezone": "America/New_York",
    }
    doc.update(fields)
    return doc


async def seed(db: Any, *, published: bool = True) -> None:
    future = datetime.now(UTC) + timedelta(days=10)
    past = datetime.now(UTC) - timedelta(days=10)
    await db["academies"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "slug": "riverside-academy",
                "display_name": "Riverside Shuttle Club",
                "timezone": "America/New_York",
                "currency": "USD",
                "brand_color": "#0f766e",
                "logo_url": "https://cdn.example.test/riverside.png",
                "address": "1 River Road, Riverside",
                "hours_text": "Sat 9am to 1pm",
                "contact_email": SECRETS["contact_email"],
                "contact_phone": SECRETS["contact_phone"],
                "stripe_account_id": SECRETS["stripe"],
                "internal_notes": SECRETS["internal_notes"],
                "public_page": {"published": published},
            },
            {
                "academy_id": OTHER,
                "slug": "lakeside-academy",
                "display_name": "Lakeside Racquets",
                "public_page": {"published": True},
            },
        ]
    )
    await db["programs"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "program_id": SECRETS["program_id"],
                "name": "Juniors",
                "level": "Beginner",
                "age_band": {"min_age": 6, "max_age": 9},
                "sort_order": 0,
                "archived": False,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": ACADEMY,
                "program_id": "prog-archived",
                "name": "Retired Squad",
                "sort_order": 1,
                "archived": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]
    )
    await db["sessions"].insert_many(
        [
            _session(
                SECRETS["published_session_id"],
                published=True,
                program_id=SECRETS["program_id"],
                coach_display="full_name",
                venue_address="1 River Road, Riverside",
                whatsapp_group_link=SECRETS["whatsapp"],
                parking_notes=SECRETS["parking"],
                coach_contact_policy=SECRETS["coach_policy"],
                absence_policy=SECRETS["absence_policy"],
                notes=SECRETS["internal_notes"],
            ),
            _session(
                "sess-jr-full",
                published=True,
                program_id=SECRETS["program_id"],
                capacity=2,
                days_of_week=["Sun"],
                coach_display="first_name",
            ),
            _session(SECRETS["private_session_id"], title=SECRETS["private_title"]),
            _session(
                "sess-explicit-private",
                published=False,
                title=SECRETS["private_title"] + " two",
            ),
            _session("sess-cancelled", published=True, status="cancelled"),
            _session(
                "sess-camp",
                published=True,
                title="October Camp",
                days_of_week=None,
                start_at=future,
                end_at=future + timedelta(hours=2),
                coach_display="hidden",
            ),
            _session(
                "sess-past",
                published=True,
                title="Finished Clinic",
                start_at=past,
                end_at=past + timedelta(hours=2),
            ),
            _session("sess-orphaned", published=True, program_id="prog-archived"),
            _session(
                "sess-other",
                academy_id=OTHER,
                published=True,
                title=SECRETS["other_academy_title"],
            ),
        ]
    )
    # ``days_of_week: None`` above only marks a one-off; drop the key itself.
    await db["sessions"].update_many(
        {"session_id": {"$in": ["sess-camp", "sess-past"]}},
        {"$unset": {"days_of_week": "", "start_time": "", "end_time": ""}},
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "enrollment_id": f"enr-{i}",
                "session_id": "sess-jr-full",
                "student_id": f"{SECRETS['student_id']}-{i}",
                "parent_id": SECRETS["parent_id"],
                "status": status,
            }
            for i, status in enumerate(["active", "held", "withdrawn"])
        ]
    )
    await db["users"].insert_one(
        {
            "user_id": SECRETS["coach_id"],
            "display_name": "Alex Morgan",
            "email": SECRETS["coach_email"],
            "phone": SECRETS["coach_phone"],
        }
    )
    await db["academy_memberships"].insert_one(
        {"academy_id": ACADEMY, "user_id": SECRETS["coach_id"], "roles": ["coach"]}
    )


class _ConfiguredTenancy(TenancyMiddleware):
    """The real middleware with its tenancy mode pinned for the test."""

    def __init__(
        self,
        app: Any,
        *,
        tenancy_mode: str,
        primary_academy_id: str | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(app, **kwargs)
        self._tenancy_mode = tenancy_mode  # type: ignore[assignment]
        self._primary_academy_id = primary_academy_id


async def host_resolver(request: Request) -> str | None:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return HOSTS.get(host)


def build_app(
    db: Any,
    *,
    resolve_tenant: Callable[[Request], Awaitable[str | None]] = host_resolver,
    check_tenant_servable: Callable[[str], Awaitable[tuple[bool, str | None]]] | None = None,
    tenancy_mode: str = "multi_academy",
    primary_academy_id: str | None = None,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(
        _ConfiguredTenancy,
        resolve_tenant=resolve_tenant,
        check_tenant_servable=check_tenant_servable,
        tenancy_mode=tenancy_mode,
        primary_academy_id=primary_academy_id,
    )
    app.include_router(public_router, prefix="/api/v2")
    app.state.public_page = compose_public_page_read(db)
    # Lane B4: the trial form, with the recording stub in place of Resend.
    app.state.sent_email = StubEmailSendPort()
    app.state.public_trial_requests = compose_trial_requests_for_test(db, app.state.sent_email)
    return app


def compose_trial_requests_for_test(db: Any, sender: Any) -> PublicTrialRequests:
    """``compose_public_trial_requests`` with an injected send port (no settings)."""
    academies = MongoAcademyRepository(db)
    return PublicTrialRequests(
        get_academy_profile=GetPublicAcademyProfile(academies),
        resolve_class_choice=ResolvePublicClassChoice(MongoSessionRepository(db)),
        submit_inquiry=SubmitWebsiteInquiry(CreateContact(MongoCrmContactRepository(db))),
        notifier=TrialRequestOwnerEmail(
            academies=academies,
            audiences=MongoAudienceResolver(db=db),
            sender=sender,
        ),
    )
