"""Welcome-email rendering and send contract (#613 Phase 2)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from backend.v2.composition.enrollment_welcome_email import (
    EnrollmentWelcomeEmailAdapter,
    render_welcome_email,
)
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy.context import tenant_scope

_ETIQUETTE = (
    "This group is only for families enrolled in {name}. "
    "If you are no longer part of this session, please exit the group."
)


def _session(**overrides: object) -> Session:
    base: dict[str, object] = {
        "session_id": "sess-1",
        "academy_id": "acad",
        "coach_id": "coach-1",
        "title": "Beginner Badminton",
        "location": "Court 1",
        # 18:00 America/Chicago on 2026-06-03 == 23:00 UTC.
        "start_at": datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
        "end_at": datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
        "capacity": 12,
        "timezone": "America/Chicago",
    }
    base.update(overrides)
    return Session(**base)  # type: ignore[arg-type]


def _render(session: Session, **kwargs: object) -> tuple[str, str]:
    return render_welcome_email(
        session=session,
        academy_name="BLNO Badminton",
        student_name=str(kwargs.pop("student_name", "Ada Lovelace")),
        **kwargs,  # type: ignore[arg-type]
    )


# --- conditional sections ---------------------------------------------------


def test_bare_session_renders_no_pack_sections() -> None:
    """Phase 2 is inert until an admin fills the pack in: an academy that has
    configured nothing still gets a correct, short welcome."""
    _, body = _render(_session())
    for heading in ("Parking", "What to bring", "Absences and make-ups", "Group chat"):
        assert heading not in body
    assert "Ada Lovelace is enrolled in Beginner Badminton" in body
    assert "minutes before" not in body


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("venue_address", "12 Court Lane", "12 Court Lane"),
        ("parking_notes", "Free lot behind", "Free lot behind"),
        ("what_to_bring", "Racquet and water", "Racquet and water"),
        ("arrival_minutes_before", 15, "Please arrive 15 minutes before"),
        ("coach_contact_policy", "Message via the app", "Message via the app"),
        ("absence_policy", "Tell us 24 hours ahead", "Tell us 24 hours ahead"),
    ],
)
def test_each_pack_field_appears_only_when_populated(
    field: str, value: object, expected: str
) -> None:
    _, without = _render(_session())
    assert expected not in without
    _, with_field = _render(_session(**{field: value}))
    assert expected in with_field


def test_group_link_renders_a_button_and_the_verbatim_etiquette_line() -> None:
    """The etiquette sentence is the only thing in this email that limits a
    forwarded invite link's blast radius. It is required verbatim."""
    _, body = _render(_session(whatsapp_group_link="https://chat.whatsapp.com/AbCd1234"))
    assert 'href="https://chat.whatsapp.com/AbCd1234"' in body
    assert "Open WhatsApp group" in body
    assert _ETIQUETTE.format(name="Beginner Badminton") in body


def test_no_group_link_means_no_button_and_no_etiquette_line() -> None:
    _, body = _render(_session())
    assert "Open WhatsApp group" not in body
    assert "please exit the group" not in body


def test_hostile_session_name_is_escaped_in_every_place_it_appears() -> None:
    session = _session(
        title="<script>alert('x')</script> Class",
        whatsapp_group_link="https://chat.whatsapp.com/AbCd1234",
    )
    subject, body = _render(session, student_name="<b>Ada</b>")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "<b>Ada</b>" not in body
    # The etiquette line still carries the (escaped) session name.
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; Class" in body
    # The subject is plain text; escaping there would leak entities to the inbox.
    assert subject.startswith("Welcome to ")


# --- timezone ---------------------------------------------------------------


def test_recurring_session_time_renders_from_the_local_wall_clock() -> None:
    session = _session(days_of_week=["Wed"], start_time="18:00", end_time="18:45")
    _, body = _render(session)
    assert "Wednesday, 6:00 PM to 6:45 PM" in body


def test_one_off_session_time_renders_in_the_session_timezone_not_utc() -> None:
    """#541/#604 are a live bug class here. The stored instant is 23:00 UTC;
    the family must read 6:00 PM, the clock the class actually happens on."""
    _, chicago = _render(_session(timezone="America/Chicago"))
    _, utc = _render(_session(timezone="UTC"))
    assert "6:00 PM" in chicago
    assert "11:00 PM" not in chicago
    # The same instant in a different session zone renders differently — the
    # assertion that fails if anyone reintroduces a fixed/UTC rendering.
    assert "11:00 PM" in utc


# --- send contract ----------------------------------------------------------


class _RecordingSender:
    def __init__(self, *, ok: bool = True) -> None:
        self.calls: list[dict] = []
        self._ok = ok

    async def send(self, **kwargs) -> SendOutcome:
        self.calls.append(kwargs)
        return SendOutcome(
            ok=self._ok,
            provider_message_id="msg-1" if self._ok else None,
            failed_reason=None if self._ok else "boom",
        )


class _Sessions:
    def __init__(self, session: Session | None) -> None:
        self._session = session

    async def get(self, session_id: str) -> Session | None:
        return self._session


class _User:
    def __init__(self, email: str = "", display_name: str = "") -> None:
        self.email = email
        self.display_name = display_name


class _Users:
    def __init__(self, by_id: dict[str, _User]) -> None:
        self._by_id = by_id

    async def get_by_id(self, user_id: str) -> _User | None:
        return self._by_id.get(user_id)


class _Academies:
    def __init__(self, timezone: str | None = "America/Chicago") -> None:
        self._timezone = timezone

    async def find_by_id(self, academy_id: str) -> dict:
        doc: dict = {"academy_id": academy_id, "display_name": "BLNO Badminton"}
        if self._timezone:
            doc["timezone"] = self._timezone
        return doc


class _Audiences:
    """Stands in for the tenant-scoped resolver.

    ``resolve_selected_audience`` is the only method the adapter uses; an id
    that is not in ``_by_id`` models a user who belongs to another academy,
    which the real Mongo resolver filters out with its ``academy_id``
    predicate.
    """

    def __init__(self, by_id: dict[str, ResolvedRecipient]) -> None:
        self._by_id = by_id

    async def resolve_selected_audience(self, audience) -> list[ResolvedRecipient]:
        return [self._by_id[uid] for uid in audience.user_ids if uid in self._by_id]


def _audiences() -> _Audiences:
    return _Audiences(
        {
            "parent-1": ResolvedRecipient(
                user_id="parent-1", email="parent@example.com", display_name="Pat"
            )
        }
    )


def _adapter(
    sender: _RecordingSender,
    session: Session | None = None,
    *,
    audiences: _Audiences | None = None,
    academies: _Academies | None = None,
) -> tuple:
    session = session or _session()
    return (
        EnrollmentWelcomeEmailAdapter(
            sessions=_Sessions(session),
            users=_Users(
                {
                    "parent-1": _User(email="parent@example.com", display_name="Pat"),
                    "coach-1": _User(display_name="Coach Kishore"),
                }
            ),
            academies=academies or _Academies(),
            audiences=audiences or _audiences(),
            sender=sender,
        ),
        session,
    )


@pytest.mark.asyncio
async def test_send_uses_the_transactional_category() -> None:
    """TRANSACTIONAL means the #556 bounce/complaint gate still applies while
    a digest/campaign unsubscribe preference does not — and, per the
    unsubscribe footer contract, no CAN-SPAM footer is appended."""
    sender = _RecordingSender()
    adapter, _ = _adapter(sender)
    with tenant_scope("acad"):
        await adapter.send_welcome(
            session_id="sess-1", student_name="Ada", parent_user_id="parent-1"
        )
    assert len(sender.calls) == 1
    assert sender.calls[0]["category"] is EmailCategory.TRANSACTIONAL
    assert sender.calls[0]["recipient"].email == "parent@example.com"
    assert "Coach Kishore" in sender.calls[0]["body"]


@pytest.mark.asyncio
async def test_send_is_skipped_without_a_recipient_address() -> None:
    sender = _RecordingSender()
    adapter = EnrollmentWelcomeEmailAdapter(
        sessions=_Sessions(_session()),
        users=_Users({"parent-1": _User(email="")}),
        academies=_Academies(),
        audiences=_Audiences(
            {"parent-1": ResolvedRecipient(user_id="parent-1", email="", display_name="Pat")}
        ),
        sender=sender,
    )
    with tenant_scope("acad"):
        await adapter.send_welcome(
            session_id="sess-1", student_name="Ada", parent_user_id="parent-1"
        )
    assert sender.calls == []


@pytest.mark.asyncio
async def test_send_is_skipped_when_the_session_is_gone() -> None:
    sender = _RecordingSender()
    adapter = EnrollmentWelcomeEmailAdapter(
        sessions=_Sessions(None),
        users=_Users({"parent-1": _User(email="parent@example.com")}),
        academies=_Academies(),
        audiences=_audiences(),
        sender=sender,
    )
    with tenant_scope("acad"):
        await adapter.send_welcome(
            session_id="missing", student_name="Ada", parent_user_id="parent-1"
        )
    assert sender.calls == []


@pytest.mark.asyncio
async def test_a_parent_outside_the_tenant_is_never_mailed() -> None:
    """The roster-add path feeds `parent_id` straight from an admin request.

    Resolution goes through the tenant-scoped audience resolver, so an id that
    belongs to another academy resolves to nobody — and this message carries
    the venue address, the coach's name and the private group-chat invite.
    """
    sender = _RecordingSender()
    adapter, _ = _adapter(sender, audiences=_Audiences({}))
    with tenant_scope("acad"):
        await adapter.send_welcome(
            session_id="sess-1", student_name="Ada", parent_user_id="parent-from-other-academy"
        )
    assert sender.calls == []


@pytest.mark.asyncio
async def test_a_session_without_a_zone_falls_back_to_the_academy_zone() -> None:
    """Not the product default: an academy in New York must not be told its
    class starts at the Chicago hour."""
    sender = _RecordingSender()
    session = _session(timezone=None, days_of_week=[], start_time=None, end_time=None)
    adapter, _ = _adapter(sender, session, academies=_Academies(timezone="America/New_York"))
    with tenant_scope("acad"):
        await adapter.send_welcome(
            session_id="sess-1", student_name="Ada", parent_user_id="parent-1"
        )
    # 23:00 UTC is 7:00 PM in New York and 6:00 PM in Chicago.
    assert "7:00 PM" in sender.calls[0]["body"]


def test_body_has_no_unescaped_raw_interpolation_markers() -> None:
    """Cheap smoke test that the template is fully rendered."""
    _, body = _render(_session(whatsapp_group_link="https://chat.whatsapp.com/AbCd1234"))
    assert not re.search(r"\{[a-z_]+\}", body)


def test_group_chat_sits_right_after_where_and_no_reminder_footer() -> None:
    _, body = _render(
        _session(
            whatsapp_group_link="https://chat.whatsapp.com/AbCd1234",
            venue_address="123 Main",
            parking_notes="Lot B",
        )
    )
    assert body.index("Where") < body.index("Group chat") < body.index("Parking")
    assert "please disregard" not in body
