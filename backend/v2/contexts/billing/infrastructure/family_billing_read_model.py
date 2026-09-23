# backend/v2/contexts/billing/infrastructure/family_billing_read_model.py
"""Mongo read model behind ``GET /admin/families/{parent_id}/billing``.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3.1.

A fixed number of batched reads for ONE parent, every one scoped by the request
tenant (``current_academy_id()`` resolved at build time, never at composition
time), handed to the pure builder in :mod:`family_billing`. Nothing here
decides an action or an autopay state.

Error handling (spec §7): the parent, students and invoices are primary — if
they fail the build raises. Attempts, dunning, audit, events, discounts and
the customer row are secondary — a failure logs, leaves that source empty and
adds a ``warnings`` entry so the page still renders.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.autopay_eligibility import (
    CHARGEABLE_INVOICE_STATUSES,
)
from backend.v2.contexts.billing.application.family_billing import (
    AllocationFacts,
    AttemptFacts,
    AuditFacts,
    CreditFacts,
    CustomerFacts,
    DunningFacts,
    EmailDeliveryFacts,
    EnrollmentFacts,
    EventFacts,
    FamilyBillingUnavailable,
    FamilyFacts,
    InvoiceFacts,
    ParentFacts,
    StudentFacts,
    build_family_billing_view,
)
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

INVOICE_CAP = 200
#: Fields a student or invoice may store its parent reference under.
_STUDENT_PARENT_FIELDS = ("parent_id", "parent_user_id")
_INVOICE_PARENT_FIELDS = ("parent_id", "parent_user_id")
_UTC_NAME = "UTC"
_WEEKDAY_SHORT = {
    "monday": "Mon",
    "mon": "Mon",
    "tuesday": "Tue",
    "tue": "Tue",
    "wednesday": "Wed",
    "wed": "Wed",
    "thursday": "Thu",
    "thu": "Thu",
    "friday": "Fri",
    "fri": "Fri",
    "saturday": "Sat",
    "sat": "Sat",
    "sunday": "Sun",
    "sun": "Sun",
}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str) and value:
        try:
            return _as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _opt_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _student_name(doc: dict[str, Any]) -> str:
    full = _opt_str(doc.get("full_name"))
    if full:
        return full
    joined = " ".join(
        p for p in (_opt_str(doc.get("first_name")), _opt_str(doc.get("last_name"))) if p
    )
    return joined or str(doc.get("student_id") or "Student")


def _schedule(session: dict[str, Any] | None) -> str | None:
    if not session:
        return None
    days = session.get("days_of_week") or []
    if isinstance(days, str):
        days = [days]
    labels = [_WEEKDAY_SHORT.get(str(d).lower(), str(d)[:3].title()) for d in days]
    start = _opt_str(session.get("start_time"))
    parts = [", ".join(labels)] if labels else []
    if start:
        parts.append(start)
    return " ".join(parts) or None


class MongoFamilyBillingReadModel:
    """Batched facts → ``build_family_billing_view`` for one parent."""

    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        connected_accounts: Any,
        billing_settings: Any,
        customers: Any,
        credits: Any,
        users: Any,
        audit: Any,
        suppressions: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._academy_timezone = academy_timezone
        self._connected_accounts = connected_accounts
        self._billing_settings = billing_settings
        self._customers = customers
        self._credits = credits
        self._users = users
        self._audit = audit
        #: #778: the suppression list (#556) knows the address is dead. Optional
        #: so the many test constructions of this read model keep working, and
        #: read through ``_secondary`` so a lookup failure is a warning, never
        #: a 503 on the whole family page.
        self._suppressions = suppressions
        self._clock = clock

    # ------------------------------------------------------------------ entry

    async def build(self, parent_id: str) -> dict[str, Any] | None:
        academy_id = current_academy_id()
        now = _as_utc(self._clock())
        tz_name = await self._resolve_timezone(academy_id)
        today = now.astimezone(ZoneInfo(tz_name)).date()
        warnings: list[str] = []

        try:
            resolved = await self._parent(academy_id, parent_id)
            if resolved is None:
                return None
            parent, aliases = resolved
            student_docs = await self._students(academy_id, aliases)
            invoice_docs = await self._invoices(academy_id, aliases)
        except Exception as exc:  # primary sources
            raise FamilyBillingUnavailable(str(exc)) from exc

        student_ids = [s["student_id"] for s in student_docs]
        enrollment_docs = await self._enrollments(academy_id, student_ids)
        enrollment_ids = [e["enrollment_id"] for e in enrollment_docs]
        session_by_id = await self._sessions(
            academy_id, {e["session_id"] for e in enrollment_docs if e.get("session_id")}
        )
        billing_by_enrollment = await self._billing_enrollments(academy_id, enrollment_ids)
        deferral_by_enrollment = await self._deferrals(academy_id, enrollment_ids)
        discounts = await self._secondary(
            "discounts_unavailable", warnings, self._discounts(academy_id, enrollment_ids), {}
        )

        invoice_ids = [inv["invoice_id"] for inv in invoice_docs]
        allocations_by_invoice, payment_ids = await self._allocations(academy_id, invoice_ids)
        credits_by_invoice = await self._secondary(
            "credits_unavailable", warnings, self._credit_applications(academy_id, invoice_ids), {}
        )
        attempts = await self._secondary(
            "attempts_unavailable", warnings, self._attempts(academy_id, invoice_ids), []
        )
        dunning = await self._secondary(
            "dunning_unavailable", warnings, self._dunning(academy_id, invoice_ids), []
        )
        audit = await self._secondary(
            "audit_unavailable",
            warnings,
            self._audit.list_for_family(
                parent_id=parent_id,
                invoice_ids=invoice_ids,
                payment_ids=payment_ids,
                enrollment_ids=enrollment_ids,
            ),
            [],
        )
        events = await self._secondary(
            "events_unavailable", warnings, self._events(academy_id, enrollment_ids), []
        )
        available_credit = await self._secondary(
            "credits_unavailable", warnings, self._available_credit(aliases), 0
        )
        customer = await self._customer(academy_id, parent_id, aliases, warnings)
        connected_ready = await self._connected_account_ready()

        name_by_student = {s["student_id"]: _student_name(s) for s in student_docs}
        name_by_enrollment = {
            e["enrollment_id"]: name_by_student.get(e["student_id"], "Student")
            for e in enrollment_docs
        }
        autopay_by_enrollment = {
            eid: _opt_str(doc.get("autopay_enrollment_status"))
            for eid, doc in billing_by_enrollment.items()
        }

        students = tuple(
            StudentFacts(
                student_id=s["student_id"],
                name=name_by_student[s["student_id"]],
                status=_opt_str(s.get("status")),
                enrollments=tuple(
                    self._enrollment_facts(
                        e,
                        session_by_id.get(e.get("session_id") or ""),
                        billing_by_enrollment.get(e["enrollment_id"]),
                        deferral_by_enrollment.get(e["enrollment_id"]),
                        discounts.get(e["enrollment_id"]),
                    )
                    for e in enrollment_docs
                    if e["student_id"] == s["student_id"]
                ),
            )
            for s in student_docs
        )
        invoices = tuple(
            self._invoice_facts(
                inv,
                student_name=name_by_student.get(str(inv.get("student_id") or "")),
                autopay_status=autopay_by_enrollment.get(str(inv.get("enrollment_id") or "")),
                allocations=allocations_by_invoice.get(inv["invoice_id"], ()),
                credits=credits_by_invoice.get(inv["invoice_id"], ()),
            )
            for inv in invoice_docs
        )
        email_delivery = await self._email_delivery(parent.email, warnings)
        facts = FamilyFacts(
            parent=parent,
            students=students,
            invoices=invoices,
            attempts=tuple(attempts),
            dunning=tuple(dunning),
            audit=tuple(
                AuditFacts(
                    audit_id=a.audit_id,
                    action=a.action,
                    actor_id=a.actor_id,
                    at=_as_utc(a.at),
                    invoice_id=a.invoice_id,
                    payment_id=a.payment_id,
                    reason=a.reason,
                    before=a.before,
                    after=a.after,
                )
                for a in audit
            ),
            events=tuple(
                EventFacts(
                    event_id=str(ev.get("event_id") or ev.get("_id")),
                    event_type=str(ev.get("event_type") or ""),
                    enrollment_id=str(ev.get("enrollment_id") or ""),
                    student_name=name_by_enrollment.get(str(ev.get("enrollment_id") or "")),
                    occurred_at=_to_datetime(ev.get("occurred_at")) or now,
                    actor_id=_opt_str(ev.get("actor_id")),
                    reason=_opt_str(ev.get("reason")),
                    effective_at=_to_datetime(ev.get("effective_at")),
                )
                for ev in events
            ),
            customer=customer,
            available_credit_cents=_int(available_credit),
            connected_account_ready=connected_ready,
            warnings=tuple(dict.fromkeys(warnings)),
            email_delivery=email_delivery,
        )
        if warnings:
            log.warning("family billing read model: %s for parent %s", warnings, parent_id)
        return build_family_billing_view(facts, timezone=tz_name, generated_at=now, today=today)

    # ------------------------------------------------------------------ shaping

    @staticmethod
    def _enrollment_facts(
        e: dict[str, Any],
        session: dict[str, Any] | None,
        billing: dict[str, Any] | None,
        deferral: dict[str, Any] | None,
        discount: dict[str, Any] | None,
    ) -> EnrollmentFacts:
        billing = billing or {}
        return EnrollmentFacts(
            enrollment_id=e["enrollment_id"],
            student_id=e["student_id"],
            session_id=_opt_str(e.get("session_id")),
            session_title=_opt_str((session or {}).get("title"))
            or _opt_str((session or {}).get("name")),
            schedule=_schedule(session),
            status=str(e.get("status") or ""),
            monthly_price_cents=_opt_int((session or {}).get("monthly_price_cents")),
            override_price_cents=_opt_int(billing.get("override_price_cents")),
            autopay_status=_opt_str(billing.get("autopay_enrollment_status")),
            recurring_discount=discount,
            resume_on=_to_date((deferral or {}).get("resume_on")),
        )

    @staticmethod
    def _invoice_facts(
        inv: dict[str, Any],
        *,
        student_name: str | None,
        autopay_status: str | None,
        allocations: Sequence[AllocationFacts],
        credits: Sequence[CreditFacts],
    ) -> InvoiceFacts:
        return InvoiceFacts(
            invoice_id=inv["invoice_id"],
            invoice_number=_opt_str(inv.get("invoice_number")),
            period=str(inv.get("period") or ""),
            student_id=_opt_str(inv.get("student_id")),
            student_name=student_name,
            enrollment_id=_opt_str(inv.get("enrollment_id")),
            status=str(inv.get("status") or ""),
            total_cents=_int(inv.get("total_cents")),
            balance_due_cents=_int(inv.get("balance_due_cents")),
            due_date=_to_date(inv.get("due_date")),
            created_at=_to_datetime(inv.get("created_at")),
            paid_at=_to_datetime(inv.get("paid_at")),
            voided_at=_to_datetime(inv.get("voided_at")),
            void_reason=_opt_str(inv.get("void_reason")),
            delivery_status=str(inv.get("delivery_status") or "not_sent"),
            delivery_kind=_opt_str(inv.get("delivery_kind")),
            last_sent_at=_to_datetime(inv.get("last_sent_at")),
            autopay_status=autopay_status,
            allocations=tuple(allocations),
            credits=tuple(credits),
            refunded_cents=max(_int(inv.get("refunded_cents")), 0),
        )

    # ------------------------------------------------------------------ queries
    # Every query carries ``academy_id`` except ``users`` (global, keyed by user id).

    async def _email_delivery(
        self, email: str | None, warnings: list[str]
    ) -> EmailDeliveryFacts | None:
        """Translate one suppression into billing's own flat shape (#778).

        The billing context never imports communications, so the provider's
        ``EmailSuppression`` is read here and only three plain fields cross.
        """
        if not email or self._suppressions is None:
            return None
        record = await self._secondary(
            "email_delivery_unavailable",
            warnings,
            self._suppressions.get_active(email),
            None,
        )
        if record is None:
            return None
        reason = getattr(record, "reason", None)
        return EmailDeliveryFacts(
            email=email,
            reason=getattr(reason, "value", None) or (str(reason) if reason else None),
            since=_to_datetime(getattr(record, "first_seen_at", None)),
        )

    async def _secondary(
        self, warning: str, warnings: list[str], coro: Awaitable[Any], fallback: Any
    ) -> Any:
        try:
            return await coro
        except Exception:
            log.warning("family billing read model: %s", warning, exc_info=True)
            warnings.append(warning)
            return fallback

    async def _resolve_timezone(self, academy_id: str) -> str:
        try:
            name = await self._academy_timezone(academy_id)
        except Exception:
            log.warning("family billing read model: timezone lookup failed", exc_info=True)
            name = None
        if not name:
            return _UTC_NAME
        try:
            ZoneInfo(name)
        except Exception:
            return _UTC_NAME
        return name

    async def _parent(
        self, academy_id: str, parent_id: str
    ) -> tuple[ParentFacts, tuple[str, ...]] | None:
        """The parent and every id their family's rows may be stored under.

        People CRM spec §1: a student's ``parent_id`` may hold the roster
        ``user_id``, the ``firebase_uid``, an ``auth_uid`` or the users
        ``_id``. The users repository resolves them with one equality lookup
        per field (never an ``$or`` across fields, #878/#894); every tenant
        read below then asks one equality question per alias and merges.
        """
        found = (await self._users.resolve_parent_aliases([parent_id])).get(parent_id)
        if found is None:
            return None
        # The requested id first, then the canonical one, then the rest in a
        # stable order: reads merge in this order, so results are deterministic.
        aliases = tuple(dict.fromkeys([parent_id, found.canonical_id, *sorted(found.aliases)]))
        # A parent belongs to this tenant when they have a student here or a
        # membership here; the students query below is tenant-scoped, so a
        # user with no student AND no membership in this academy is a 404.
        if not await self._belongs_to_tenant(academy_id, aliases):
            return None
        # ...and they must actually BE a parent (spec §3: "a user who is not a
        # parent" is a 404). Membership alone admits coaches, admins and owners,
        # whose PII and family actions this page must never expose. A user with
        # a student in this tenant counts even if the role is missing (legacy
        # rows), and a coach who is also a parent keeps access via the role.
        if not await self._is_parent(
            academy_id, aliases, home_academy_id=found.home_academy_id, roles=found.roles
        ):
            return None
        parent = ParentFacts(
            parent_id=parent_id,
            name=found.display_name,
            email=found.email,
            phone=found.phone,
        )
        return parent, aliases

    async def _is_parent(
        self,
        academy_id: str,
        aliases: Sequence[str],
        *,
        home_academy_id: str | None,
        roles: Sequence[str],
    ) -> bool:
        """Is this user a parent *of this academy*?

        The role must come from the membership in the request tenant, never from
        the global ``users.roles``: a multi-academy user who parents at academy A
        and coaches at academy B would otherwise pass B's gate on A's role, and
        B's admin would see their contact details and family actions.
        """
        for alias in aliases:
            if await self._db["academy_memberships"].find_one(
                {"academy_id": academy_id, "user_id": alias, "roles": "parent"}, {"_id": 1}
            ):
                return True
        # A student of THIS academy is proof regardless of how roles are recorded.
        if await self._has_student(academy_id, aliases):
            return True
        # Legacy fallback for rows predating per-academy membership roles. Gated
        # on the user's OWN academy stamp, so it stays tenant-scoped: a coach of
        # this academy whose home academy is another one cannot pass on a parent
        # role earned there.
        if home_academy_id != academy_id:
            return False
        return "parent" in roles

    async def _has_student(self, academy_id: str, aliases: Sequence[str]) -> bool:
        for alias in aliases:
            for field_name in _STUDENT_PARENT_FIELDS:
                if await self._db["students"].find_one(
                    {"academy_id": academy_id, field_name: alias}, {"_id": 1}
                ):
                    return True
        return False

    async def _belongs_to_tenant(self, academy_id: str, aliases: Sequence[str]) -> bool:
        if await self._has_student(academy_id, aliases):
            return True
        for alias in aliases:
            if await self._db["academy_memberships"].find_one(
                {"academy_id": academy_id, "user_id": alias}, {"_id": 1}
            ):
                return True
        for alias in aliases:
            if await self._db["users"].find_one(
                {"user_id": alias, "academy_id": academy_id}, {"_id": 1}
            ):
                return True
        return False

    async def _available_credit(self, aliases: Sequence[str]) -> int:
        """Credit is keyed by whichever parent reference wrote it; sum them all."""
        total = 0
        for alias in aliases:
            total += _int(await self._credits.balance_for_parent(alias))
        return total

    async def _students(self, academy_id: str, aliases: Sequence[str]) -> list[dict[str, Any]]:
        """The family's children, stored under any alias (one equality read each)."""
        by_id: dict[str, dict[str, Any]] = {}
        for alias in aliases:
            for field_name in _STUDENT_PARENT_FIELDS:
                cursor = self._db["students"].find(
                    {"academy_id": academy_id, field_name: alias, "is_deleted": {"$ne": True}},
                    {
                        "_id": 0,
                        "student_id": 1,
                        "full_name": 1,
                        "first_name": 1,
                        "last_name": 1,
                        "status": 1,
                    },
                )
                async for doc in cursor:
                    if doc.get("student_id"):
                        doc["student_id"] = str(doc["student_id"])
                        by_id.setdefault(doc["student_id"], doc)
        docs = list(by_id.values())
        docs.sort(key=lambda d: (_student_name(d), d["student_id"]))
        return docs

    async def _enrollments(self, academy_id: str, student_ids: list[str]) -> list[dict[str, Any]]:
        if not student_ids:
            return []
        cursor = self._db["enrollments"].find(
            {"academy_id": academy_id, "student_id": {"$in": student_ids}},
            {"_id": 0, "enrollment_id": 1, "student_id": 1, "session_id": 1, "status": 1},
        )
        docs = [doc async for doc in cursor if doc.get("enrollment_id") and doc.get("student_id")]
        for doc in docs:
            doc["enrollment_id"] = str(doc["enrollment_id"])
            doc["student_id"] = str(doc["student_id"])
        docs.sort(key=lambda d: (d.get("status") != "active", d["enrollment_id"]))
        return docs

    async def _sessions(self, academy_id: str, session_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not session_ids:
            return {}
        cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": sorted(session_ids)}},
            {
                "_id": 0,
                "session_id": 1,
                "title": 1,
                "name": 1,
                "days_of_week": 1,
                "start_time": 1,
                "monthly_price_cents": 1,
            },
        )
        return {str(doc["session_id"]): doc async for doc in cursor}

    async def _billing_enrollments(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["student_billing_enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {
                "_id": 0,
                "enrollment_id": 1,
                "autopay_enrollment_status": 1,
                "override_price_cents": 1,
                "last_attempt_outcome": 1,
                "last_failure_code": 1,
            },
        )
        return {str(doc["enrollment_id"]): doc async for doc in cursor}

    async def _deferrals(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["enrollment_billing_deferrals"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "resume_on": 1, "review_on": 1, "created_at": 1},
            sort=[("created_at", -1)],
        )
        out: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            out.setdefault(str(doc["enrollment_id"]), doc)
        return out

    async def _discounts(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not enrollment_ids:
            return {}
        cursor = self._db["enrollment_discounts"].find(
            {
                "academy_id": academy_id,
                "enrollment_id": {"$in": enrollment_ids},
                "status": "active",
            },
            {
                "_id": 0,
                "enrollment_id": 1,
                "discount_id": 1,
                "category": 1,
                "category_label": 1,
                "kind": 1,
                "amount_cents": 1,
                "percent": 1,
                "note": 1,
            },
        )
        return {str(doc["enrollment_id"]): doc async for doc in cursor}

    async def _invoices(self, academy_id: str, aliases: Sequence[str]) -> list[dict[str, Any]]:
        """The family's invoices under any alias and either parent field.

        People CRM spec §1: this used to be ONE query with
        ``$or: [{parent_id}, {parent_user_id}]`` on the exact id, the #878/#894
        shape MongoDB 8.0 scans, and it missed every invoice stored under
        another alias. Now one equality read per (alias, field), merged by
        ``invoice_id``.
        """
        by_id: dict[str, dict[str, Any]] = {}
        for alias in aliases:
            for field_name in _INVOICE_PARENT_FIELDS:
                async for doc in self._invoice_cursor(academy_id, field_name, alias):
                    if doc.get("invoice_id"):
                        doc["invoice_id"] = str(doc["invoice_id"])
                        by_id.setdefault(doc["invoice_id"], doc)
        return self._cap_invoices(list(by_id.values()))

    def _invoice_cursor(self, academy_id: str, field_name: str, alias: str) -> Any:
        return self._db["invoices"].find(
            {"academy_id": academy_id, field_name: alias, "is_deleted": {"$ne": True}},
            {
                "_id": 0,
                "invoice_id": 1,
                "invoice_number": 1,
                "student_id": 1,
                "enrollment_id": 1,
                "period": 1,
                "status": 1,
                "total_cents": 1,
                "balance_due_cents": 1,
                "refunded_cents": 1,
                "due_date": 1,
                "created_at": 1,
                "paid_at": 1,
                "voided_at": 1,
                "void_reason": 1,
                "delivery_status": 1,
                "delivery_kind": 1,
                "last_sent_at": 1,
            },
        )

    @staticmethod
    def _cap_invoices(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Period desc, then created desc; ties keep invoice_id ascending (reverse
        # sort is stable, so the ascending pre-sort survives).
        docs.sort(key=lambda d: d["invoice_id"])
        docs.sort(
            key=lambda d: (
                str(d.get("period") or ""),
                _to_datetime(d.get("created_at")) or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=True,
        )
        # The cap bounds the response, but it must never bound the MONEY: an
        # older open invoice dropped here would silently vanish from
        # ``balance_cents``, ``open_invoice_count`` and the collection actions
        # the view derives. Keep every open invoice; spend the cap on settled
        # history, newest first.
        open_docs = [d for d in docs if str(d.get("status") or "") in CHARGEABLE_INVOICE_STATUSES]
        if len(open_docs) >= INVOICE_CAP:
            return open_docs
        settled = [d for d in docs if str(d.get("status") or "") not in CHARGEABLE_INVOICE_STATUSES]
        keep = {id(d) for d in open_docs} | {id(d) for d in settled[: INVOICE_CAP - len(open_docs)]}
        return [d for d in docs if id(d) in keep]

    async def _allocations(
        self, academy_id: str, invoice_ids: list[str]
    ) -> tuple[dict[str, list[AllocationFacts]], list[str]]:
        if not invoice_ids:
            return {}, []
        alloc_cursor = self._db["payment_allocations"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "payment_id": 1, "amount_cents": 1},
        )
        allocations = [doc async for doc in alloc_cursor if doc.get("payment_id")]
        payment_ids = sorted({str(a["payment_id"]) for a in allocations})
        payments: dict[str, dict[str, Any]] = {}
        if payment_ids:
            pay_cursor = self._db["ledger_payments"].find(
                {"academy_id": academy_id, "payment_id": {"$in": payment_ids}},
                {
                    "_id": 0,
                    "payment_id": 1,
                    "payment_method": 1,
                    "paid_at": 1,
                    "created_at": 1,
                    "stripe_payment_intent_id": 1,
                    "refunded_cents": 1,
                },
            )
            payments = {str(doc["payment_id"]): doc async for doc in pay_cursor}
        refunded_by_payment = await self._payment_refunds(academy_id, payment_ids, payments)
        out: dict[str, list[AllocationFacts]] = {}
        for a in allocations:
            payment = payments.get(str(a["payment_id"]), {})
            out.setdefault(str(a["invoice_id"]), []).append(
                AllocationFacts(
                    payment_id=str(a["payment_id"]),
                    amount_cents=_int(a.get("amount_cents")),
                    method=_opt_str(payment.get("payment_method")),
                    paid_at=_to_datetime(payment.get("paid_at"))
                    or _to_datetime(payment.get("created_at")),
                    stripe_payment_intent_id=_opt_str(payment.get("stripe_payment_intent_id")),
                    payment_refunded_cents=refunded_by_payment.get(str(a["payment_id"]), 0),
                )
            )
        return out, payment_ids

    async def _payment_refunds(
        self,
        academy_id: str,
        payment_ids: list[str],
        ledger_payments: dict[str, dict[str, Any]],
    ) -> dict[str, int]:
        """Each payment's cumulative refund (#929), from BOTH payment stores.

        The admin refund route records the payment side on the legacy
        ``payments`` row (``IssueRefund``); a Stripe-dashboard refund of a
        ledger-only charge lands on ``ledger_payments`` (webhook). Both hold the
        same Stripe payment intent's running total, so the larger one wins —
        they are never added.
        """
        out = {pid: max(_int(doc.get("refunded_cents")), 0) for pid, doc in ledger_payments.items()}
        if not payment_ids:
            return out
        cursor = self._db["payments"].find(
            {"academy_id": academy_id, "payment_id": {"$in": payment_ids}},
            {"_id": 0, "payment_id": 1, "refunded_cents": 1, "refunded_amount": 1},
        )
        async for doc in cursor:
            pid = str(doc.get("payment_id") or "")
            if pid:
                legacy = max(MongoPaymentRepository._refunded_cents(doc), 0)
                out[pid] = max(out.get(pid, 0), legacy)
        return out

    async def _credit_applications(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, list[CreditFacts]]:
        if not invoice_ids:
            return {}
        cursor = self._db["credit_applications"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "credit_id": 1, "amount_cents": 1},
        )
        out: dict[str, list[CreditFacts]] = {}
        async for doc in cursor:
            out.setdefault(str(doc["invoice_id"]), []).append(
                CreditFacts(
                    credit_id=str(doc.get("credit_id") or ""),
                    amount_cents=_int(doc.get("amount_cents")),
                )
            )
        return out

    async def _attempts(self, academy_id: str, invoice_ids: list[str]) -> list[AttemptFacts]:
        if not invoice_ids:
            return []
        cursor = self._db["payment_attempts"].find(
            exclude_non_charge_attempts(
                {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}}
            ),
            {
                "_id": 0,
                "attempt_id": 1,
                "invoice_id": 1,
                "status": 1,
                "failure_message": 1,
                "failure_code": 1,
                "amount_cents": 1,
                "created_at": 1,
            },
            sort=[("created_at", 1)],
        )
        return [
            AttemptFacts(
                attempt_id=str(doc.get("attempt_id") or ""),
                invoice_id=str(doc["invoice_id"]),
                status=str(doc.get("status") or ""),
                failure_message=_opt_str(doc.get("failure_message"))
                or _opt_str(doc.get("failure_code")),
                amount_cents=_int(doc.get("amount_cents")),
                created_at=_to_datetime(doc.get("created_at")),
            )
            async for doc in cursor
        ]

    async def _dunning(self, academy_id: str, invoice_ids: list[str]) -> list[DunningFacts]:
        if not invoice_ids:
            return []
        cursor = self._db["dunning_states"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {
                "_id": 0,
                "invoice_id": 1,
                "status": 1,
                "attempt_count": 1,
                "autopay_disabled_at": 1,
                "last_notification_at": 1,
            },
        )
        return [
            DunningFacts(
                invoice_id=str(doc["invoice_id"]),
                status=_opt_str(doc.get("status")),
                attempt_count=_int(doc.get("attempt_count")),
                autopay_disabled_at=_to_datetime(doc.get("autopay_disabled_at")),
                last_notification_at=_to_datetime(doc.get("last_notification_at")),
            )
            async for doc in cursor
        ]

    async def _events(self, academy_id: str, enrollment_ids: list[str]) -> list[dict[str, Any]]:
        if not enrollment_ids:
            return []
        cursor = self._db["enrollment_events"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {
                "_id": 1,
                "event_id": 1,
                "event_type": 1,
                "enrollment_id": 1,
                "occurred_at": 1,
                "actor_id": 1,
                "reason": 1,
                "effective_at": 1,
            },
            sort=[("occurred_at", -1)],
            limit=INVOICE_CAP,
        )
        return [doc async for doc in cursor]

    async def _customer(
        self, academy_id: str, parent_id: str, aliases: Sequence[str], warnings: list[str]
    ) -> CustomerFacts:
        has_login = False
        try:
            has_login = parent_id in await self._users.list_existing_user_ids(
                [parent_id], academy_id=academy_id
            )
        except Exception:
            log.warning("family billing read model: login lookup failed", exc_info=True)
        try:
            doc = None
            for alias in aliases:
                doc = await self._db["parent_billing_customers"].find_one(
                    {"academy_id": academy_id, "parent_id": alias}
                )
                if doc is not None:
                    break
        except Exception:
            log.warning("family billing read model: customer lookup failed", exc_info=True)
            warnings.append("customer_unavailable")
            return CustomerFacts(
                has_card=None,
                card_last4=None,
                card_label=None,
                last_invited_at=None,
                has_login_account=has_login,
            )
        if doc is None:
            return CustomerFacts(
                has_card=False,
                card_last4=None,
                card_label=None,
                last_invited_at=None,
                has_login_account=has_login,
            )
        label, last4 = MongoParentBillingCustomerRepository.display_payment_method(doc)
        return CustomerFacts(
            has_card=(label, last4) != (None, None),
            card_last4=last4,
            card_label=label,
            last_invited_at=_to_datetime(doc.get("billing_setup_last_invited_at")),
            has_login_account=has_login,
        )

    async def _connected_account_ready(self) -> bool | None:
        try:
            account = await self._connected_accounts.get_for_academy()
            settings = await self._billing_settings.get()
        except Exception:
            log.warning("family billing read model: connected-account lookup failed", exc_info=True)
            return None
        ready = account is not None and account.is_ready_for_charges()
        return bool(ready or getattr(settings, "allow_platform_charge_fallback", False))
