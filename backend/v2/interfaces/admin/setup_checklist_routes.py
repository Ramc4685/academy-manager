"""Admin BFF: ``GET /admin/setup-checklist`` — the academy setup checklist.

Roadmap L7. Every item is *derived* from settings the academy already keeps
(academy profile, branding, billing rules, Stripe Connect, session types,
classes, staff, waiver, public page). There is no checklist collection and
nothing to tick by hand: an item is done when the thing it names exists.

Each source is read on its own; one that fails or is not wired in this
deployment reports ``unknown`` instead of failing the whole card, the same
way the dashboard attention sources degrade.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    DEFAULT_WAIVER_BODY,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.setup-checklist"])
log = logging.getLogger(__name__)

ChecklistStatus = Literal["done", "todo", "unknown"]
ChecklistKey = Literal[
    "academy_profile",
    "branding",
    "billing_rules",
    "stripe_connect",
    "session_types",
    "classes",
    "staff",
    "waiver",
    "public_page",
]

#: Roles that make a user staff for the "invite your team" item. A parent
#: who also coaches counts; a parent-only account does not.
STAFF_ROLES = frozenset({"owner", "admin", "coach", "assistant_coach", "billing", "front_desk"})

#: ``users.status`` spellings that mean the account cannot sign in.
INACTIVE_STATUSES = frozenset({"disabled", "inactive", "suspended", "deleted"})

#: The owner alone is one staff account; the item wants at least one more.
MIN_STAFF_ACCOUNTS = 2


class SetupChecklistItemView(BaseModel):
    key: ChecklistKey
    label: str
    detail: str
    status: ChecklistStatus
    href: str
    #: The settings panel behind ``href`` is owner-only (billing rules,
    #: Stripe). An admin without the owner scope sees the status but is
    #: told the owner finishes the step.
    owner_only: bool = False


class SetupChecklistView(BaseModel):
    items: list[SetupChecklistItemView]
    done_count: int
    total: int
    complete: bool


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _filled(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


async def _read(label: str, reader: Callable[[], Awaitable[Any]] | None) -> tuple[bool, Any]:
    """``(True, value)`` when the source answered, ``(False, None)`` otherwise."""
    if reader is None:
        return False, None
    try:
        return True, await reader()
    except Exception:
        log.warning("admin setup checklist source unavailable: %s", label, exc_info=True)
        return False, None


def _status(ok: bool, done: bool) -> ChecklistStatus:
    if not ok:
        return "unknown"
    return "done" if done else "todo"


def _is_staff(user: Any) -> bool:
    """A signed-in-capable account holding a staff role in this academy.

    ``list_admin_users`` is the same tenant-scoped ``users`` read the Users
    page shows; ``roles`` is already resolved there (the v2 array wins, the
    legacy scalar is only a fallback, and ``role`` is ``roles[0]``), so it
    is authoritative here and ``role`` is used only when ``roles`` is empty.
    A disabled or suspended account is not a team member the owner can
    lean on, so it does not count.
    """
    status = _field(user, "status")
    if isinstance(status, str) and status.strip().lower() in INACTIVE_STATUSES:
        return False
    roles = set(_field(user, "roles", ()) or ())
    if not roles:
        roles = {_field(user, "role", "")}
    return bool(roles & STAFF_ROLES)


def _waiver_done(report: Any) -> bool:
    """An active waiver that is not still the bootstrap placeholder."""
    active = _field(report, "active_waiver")
    if active is None:
        return False
    body = _field(active, "body")
    return not (isinstance(body, str) and body.strip() == DEFAULT_WAIVER_BODY)


def build_setup_checklist(
    *,
    academy: tuple[bool, Any],
    fees: tuple[bool, Any],
    gateway: tuple[bool, Any],
    session_types: tuple[bool, Any],
    classes: tuple[bool, Any],
    users: tuple[bool, Any],
    waivers: tuple[bool, Any],
    public_page: tuple[bool, Any],
) -> SetupChecklistView:
    """Pure derivation: source reads in, checklist out. No I/O."""
    academy_ok, academy_row = academy
    fees_ok, fees_row = fees
    gateway_ok, gateway_row = gateway
    types_ok, type_rows = session_types
    classes_ok, class_rows = classes
    users_ok, user_rows = users
    waivers_ok, waiver_report = waivers
    page_ok, page_settings = public_page

    profile_done = _filled(_field(academy_row, "timezone")) and _filled(
        _field(academy_row, "contact_email")
    )
    branding_done = _filled(_field(academy_row, "logo_url")) or _filled(
        _field(academy_row, "brand_color")
    )
    # ``None`` means the owner never chose; a stored 0 ("no late fee") is a
    # real choice and counts.
    rules_done = (
        _field(fees_row, "late_fee_cents") is not None
        and _field(fees_row, "grace_days") is not None
    )
    staff_count = sum(1 for user in (user_rows or []) if _is_staff(user))

    items = [
        SetupChecklistItemView(
            key="academy_profile",
            label="Academy details",
            detail="Set the timezone and a contact email families can reach.",
            status=_status(academy_ok, profile_done),
            href="/admin/settings?panel=academy",
        ),
        SetupChecklistItemView(
            key="branding",
            label="Branding",
            detail="Add your logo or brand colour for emails and the public page.",
            status=_status(academy_ok, branding_done),
            href="/admin/settings?panel=branding",
        ),
        SetupChecklistItemView(
            key="billing_rules",
            label="Billing rules",
            detail="Choose a late fee and grace period (0 is a valid choice).",
            status=_status(fees_ok, rules_done),
            href="/admin/settings?panel=billing-rules",
            owner_only=True,
        ),
        SetupChecklistItemView(
            key="stripe_connect",
            label="Card payments",
            detail="Connect Stripe so families can pay online.",
            status=_status(gateway_ok, bool(_field(gateway_row, "stripe_connected", False))),
            href="/admin/settings?panel=gateway",
            owner_only=True,
        ),
        SetupChecklistItemView(
            key="session_types",
            label="Session types",
            detail="Add at least one session type (group class, private lesson).",
            status=_status(types_ok, bool(type_rows)),
            href="/admin/settings?panel=session-types",
        ),
        SetupChecklistItemView(
            key="classes",
            label="First classes",
            detail="Schedule a class in the next 30 days.",
            status=_status(classes_ok, bool(class_rows)),
            href="/admin/sessions",
        ),
        SetupChecklistItemView(
            key="staff",
            label="Invite your team",
            detail="Invite at least one coach or staff member besides yourself.",
            status=_status(users_ok, staff_count >= MIN_STAFF_ACCOUNTS),
            href="/admin/users",
        ),
        SetupChecklistItemView(
            key="waiver",
            label="Waiver",
            detail="Replace the starter waiver with your own; families sign it at registration.",
            status=_status(waivers_ok, _waiver_done(waiver_report)),
            href="/admin/waivers",
        ),
        SetupChecklistItemView(
            key="public_page",
            label="Public class page",
            detail="Publish the page where new families find classes and book a trial.",
            status=_status(page_ok, bool(_field(page_settings, "published", False))),
            href="/admin/settings?panel=public-page",
        ),
    ]
    done = sum(1 for item in items if item.status == "done")
    return SetupChecklistView(
        items=items,
        done_count=done,
        total=len(items),
        complete=done == len(items),
    )


@router.get("/setup-checklist", response_model=SetupChecklistView)
async def get_setup_checklist(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SetupChecklistView:
    academy_id = claims.academy_id
    list_types = use_cases.list_session_types
    list_sessions = use_cases.list_admin_sessions
    public_page = getattr(request.app.state, "admin_public_page", None)

    async def _users() -> Any:
        return await use_cases.list_admin_users.execute(
            None, academy_id=academy_id, exclude_role="parent"
        )

    async def _types() -> Any:
        return await list_types.execute(include_archived=False)  # type: ignore[union-attr]

    async def _classes() -> Any:
        return await list_sessions(None, window="upcoming", coach_id=None)  # type: ignore[operator]

    async def _page() -> Any:
        return await public_page.get_public_page_settings.execute(academy_id)  # type: ignore[union-attr]

    return build_setup_checklist(
        academy=await _read("academy", lambda: use_cases.get_academy_use_case.execute(academy_id)),
        fees=await _read("fees", lambda: use_cases.get_academy_fees_use_case.execute(academy_id)),
        gateway=await _read(
            "gateway", lambda: use_cases.get_academy_gateway_use_case.execute(academy_id)
        ),
        session_types=await _read("session_types", _types if list_types is not None else None),
        classes=await _read("classes", _classes if list_sessions is not None else None),
        users=await _read("users", _users),
        waivers=await _read("waivers", use_cases.list_admin_waivers.execute),
        public_page=await _read("public_page", _page if public_page is not None else None),
    )
