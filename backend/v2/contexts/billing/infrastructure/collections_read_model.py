"""Mongo read model behind ``GET /admin/payments/collections``.

Spec: ``docs/superpowers/specs/2026-09-05-payments-buckets-design.md`` §3.

The read model only gathers facts — a fixed number of batched Mongo reads,
every one scoped by the request tenant (``current_academy_id()`` resolved at
build time, never at composition time) — and hands each family to the pure
classifier in :mod:`collections_buckets`. Bucket rules and autopay
eligibility live there and in :mod:`autopay_eligibility`; nothing here decides
which bucket a family belongs to.

Error handling (spec §6): a family whose facts cannot be assembled or
classified never breaks the build; it is logged and, when ``debug=True``,
returned in ``unclassified``. Card / connected-account lookups that fail
degrade to ``None`` ("unknown"), which the classifier never treats as eligible.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.contexts.billing.application.collections_buckets import (
    FamilyFacts,
    FamilyRow,
    InvoiceFacts,
    PauseFacts,
    StudentFacts,
    build_collections_view_from_rows,
    classify_family,
)
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

_LEFTOVER_STATUSES = ["open", "partially_paid"]
_ACTIVE_ENROLLMENT_STATUSES = ["active", "paused"]
_PAUSED_STATUS = "paused"
_UTC_NAME = "UTC"


def _period_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


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


def _student_name(doc: dict[str, Any]) -> str:
    full = _opt_str(doc.get("full_name"))
    if full:
        return full
    parts = [_opt_str(doc.get("first_name")), _opt_str(doc.get("last_name"))]
    joined = " ".join(p for p in parts if p)
    return joined or str(doc.get("student_id") or "Student")


def _session_title(doc: dict[str, Any] | None) -> str | None:
    if not doc:
        return None
    return _opt_str(doc.get("title")) or _opt_str(doc.get("name"))


def _invoice_parent_id(doc: dict[str, Any]) -> str | None:
    return _opt_str(doc.get("parent_id")) or _opt_str(doc.get("parent_user_id"))


class MongoCollectionsReadModel:
    """Batched facts → ``build_collections_view_from_rows`` for the admin Payments page."""

    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        connected_accounts: Any,
        billing_settings: Any,
        customers: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._academy_timezone = academy_timezone
        self._connected_accounts = connected_accounts
        self._billing_settings = billing_settings
        self._customers = customers
        self._clock = clock

    # ------------------------------------------------------------------ entry

    async def build(self, period: str | None = None, *, debug: bool = False) -> dict[str, Any]:
        academy_id = current_academy_id()
        now = _as_utc(self._clock())
        tz_name = await self._resolve_timezone(academy_id)
        today = now.astimezone(ZoneInfo(tz_name)).date()
        period = period or _period_of(today)

        invoices = await self._period_invoices(academy_id, period)
        invoice_ids = [inv["invoice_id"] for inv in invoices]
        enrollment_ids = sorted(
            {inv["enrollment_id"] for inv in invoices if inv.get("enrollment_id")}
        )

        dunning_by_invoice = await self._dunning_by_invoice(academy_id, invoice_ids)
        attempt_by_invoice = await self._latest_attempt_by_invoice(academy_id, invoice_ids)
        autopay_by_enrollment = await self._autopay_by_enrollment(academy_id, enrollment_ids)
        paused_by_student, deferral_by_enrollment = await self._paused(academy_id)

        invoice_parents = {pid for inv in invoices if (pid := _invoice_parent_id(inv))}
        students_by_parent, student_docs = await self._students(
            academy_id, invoice_parents, set(paused_by_student)
        )
        parent_ids = set(students_by_parent) | invoice_parents
        leftover_by_parent = await self._leftover_by_parent(academy_id, period, parent_ids)
        session_by_student = await self._session_by_student(academy_id, set(student_docs))
        users = await self._users(parent_ids)
        paid_by_invoice = await self._paid_by_invoice(academy_id, invoice_ids)
        cards = await self._cards()
        connected_ready = await self._connected_account_ready()

        invoices_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        orphans: list[dict[str, Any]] = []
        for inv in invoices:
            parent_id = _invoice_parent_id(inv)
            if parent_id is None:
                orphans.append(inv)
            else:
                invoices_by_parent[parent_id].append(inv)

        families: list[FamilyFacts] = []
        unclassified: list[dict[str, Any]] = []
        for parent_id in sorted(parent_ids):
            try:
                student_ids = students_by_parent.get(parent_id, [])
                students = tuple(
                    StudentFacts(
                        student_id=sid,
                        name=_student_name(student_docs[sid]),
                        session_title=_session_title(session_by_student.get(sid)),
                    )
                    for sid in student_ids
                )
                paused = tuple(
                    self._pause_facts(
                        enrollment,
                        student_docs[sid],
                        session_by_student.get(sid),
                        deferral_by_enrollment,
                    )
                    for sid in student_ids
                    for enrollment in paused_by_student.get(sid, [])
                )
                invoice_facts = tuple(
                    self._invoice_facts(
                        inv,
                        dunning=dunning_by_invoice.get(inv["invoice_id"]),
                        attempt=attempt_by_invoice.get(inv["invoice_id"]),
                        autopay_status=autopay_by_enrollment.get(inv.get("enrollment_id") or ""),
                        paid=paid_by_invoice.get(inv["invoice_id"]),
                    )
                    for inv in invoices_by_parent.get(parent_id, [])
                )
                user = users.get(parent_id) or {}
                # No customer row means no card; a failed lookup means unknown.
                has_card, last4 = (
                    cards.get(parent_id, (False, None)) if cards is not None else (None, None)
                )
                families.append(
                    FamilyFacts(
                        parent_id=parent_id,
                        parent_name=_opt_str(user.get("display_name"))
                        or _opt_str(user.get("name")),
                        parent_email=_opt_str(user.get("email")),
                        students=students,
                        invoices=invoice_facts,
                        leftover_balance_cents=leftover_by_parent.get(parent_id, 0),
                        paused=paused,
                        has_payment_method=has_card,
                        card_last4=last4,
                        connected_account_ready=connected_ready,
                    )
                )
            except Exception as exc:
                log.warning(
                    "collections read model: family %s skipped: %s", parent_id, exc, exc_info=True
                )
                unclassified.append({"parent_id": parent_id, "error": str(exc)})

        for inv in orphans:
            unclassified.append(
                {
                    "parent_id": None,
                    "error": f"invoice {inv['invoice_id']} has no parent_id",
                }
            )

        rows = self._classify(
            families, today=today, zone=ZoneInfo(tz_name), unclassified=unclassified
        )
        if unclassified:
            log.warning(
                "collections read model: %d unclassified families for %s/%s",
                len(unclassified),
                academy_id,
                period,
            )
        return build_collections_view_from_rows(
            rows,
            period=period,
            timezone=tz_name,
            generated_at=now,
            unclassified=unclassified if debug else None,
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _classify(
        families: Iterable[FamilyFacts],
        *,
        today: date,
        zone: tzinfo,
        unclassified: list[dict[str, Any]],
    ) -> list[FamilyRow]:
        """Classify once; a family whose classification raises is reported, not fatal."""
        kept: list[FamilyRow] = []
        for family in families:
            try:
                row = classify_family(family, today=today, zone=zone)
            except Exception as exc:
                log.warning(
                    "collections read model: family %s unclassifiable: %s",
                    family.parent_id,
                    exc,
                    exc_info=True,
                )
                unclassified.append({"parent_id": family.parent_id, "error": str(exc)})
                continue
            if row is not None:
                kept.append(row)
        return kept

    async def _resolve_timezone(self, academy_id: str) -> str:
        try:
            name = await self._academy_timezone(academy_id)
        except Exception:
            log.warning("collections read model: timezone lookup failed", exc_info=True)
            name = None
        if not name:
            return _UTC_NAME
        try:
            ZoneInfo(name)
        except Exception:
            log.warning("collections read model: unknown timezone %r, using UTC", name)
            return _UTC_NAME
        return name

    @staticmethod
    def _invoice_facts(
        inv: dict[str, Any],
        *,
        dunning: dict[str, Any] | None,
        attempt: dict[str, Any] | None,
        autopay_status: str | None,
        paid: dict[str, Any] | None,
    ) -> InvoiceFacts:
        due = _to_date(inv.get("due_date"))
        if due is None:
            raise ValueError(f"invoice {inv['invoice_id']} has no due_date")
        return InvoiceFacts(
            invoice_id=str(inv["invoice_id"]),
            invoice_number=_opt_str(inv.get("invoice_number")),
            period=str(inv.get("period") or ""),
            status=str(inv.get("status") or ""),
            total_cents=_int(inv.get("total_cents")),
            balance_due_cents=_int(inv.get("balance_due_cents")),
            due_date=due,
            delivery_status=str(inv.get("delivery_status") or "not_sent"),
            last_sent_at=_to_datetime(inv.get("last_sent_at")),
            enrollment_id=_opt_str(inv.get("enrollment_id")),
            student_id=_opt_str(inv.get("student_id")),
            autopay_enrollment_status=autopay_status,
            dunning_status=_opt_str((dunning or {}).get("status")),
            dunning_attempt_count=_int((dunning or {}).get("attempt_count")),
            dunning_next_attempt_at=_to_datetime((dunning or {}).get("next_attempt_at")),
            latest_attempt_status=_opt_str((attempt or {}).get("status")),
            latest_attempt_reason=_opt_str((attempt or {}).get("reason")),
            paid_cents=_int((paid or {}).get("paid_cents")),
            paid_method=_opt_str((paid or {}).get("paid_method")),
            paid_at=_to_datetime((paid or {}).get("paid_at")),
        )

    @staticmethod
    def _pause_facts(
        enrollment: dict[str, Any],
        student: dict[str, Any],
        session: dict[str, Any] | None,
        deferral_by_enrollment: dict[str, dict[str, Any]],
    ) -> PauseFacts:
        enrollment_id = str(enrollment["enrollment_id"])
        deferral = deferral_by_enrollment.get(enrollment_id) or {}
        return PauseFacts(
            enrollment_id=enrollment_id,
            student_name=_student_name(student),
            session_title=_session_title(session),
            resume_on=_to_date(deferral.get("resume_on")),
            review_on=_to_date(deferral.get("review_on")),
        )

    # ------------------------------------------------------------------ queries
    # Every query below carries ``academy_id`` (the request tenant) except the
    # ``users`` lookup, which is a global collection keyed by user id.

    async def _period_invoices(self, academy_id: str, period: str) -> list[dict[str, Any]]:
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "status": {"$ne": "void"},
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0,
                "invoice_id": 1,
                "invoice_number": 1,
                "parent_id": 1,
                "parent_user_id": 1,
                "student_id": 1,
                "enrollment_id": 1,
                "period": 1,
                "status": 1,
                "total_cents": 1,
                "balance_due_cents": 1,
                "due_date": 1,
                "delivery_status": 1,
                "last_sent_at": 1,
            },
        )
        docs = [doc async for doc in cursor]
        for doc in docs:
            doc["invoice_id"] = str(doc.get("invoice_id"))
            if doc.get("enrollment_id") is not None:
                doc["enrollment_id"] = str(doc["enrollment_id"])
        return docs

    async def _leftover_by_parent(
        self, academy_id: str, period: str, parent_ids: set[str]
    ) -> dict[str, int]:
        if not parent_ids:
            return {}
        ids = sorted(parent_ids)
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "$or": [{"parent_id": {"$in": ids}}, {"parent_user_id": {"$in": ids}}],
                "period": {"$lt": period},
                "status": {"$in": _LEFTOVER_STATUSES},
                "balance_due_cents": {"$gt": 0},
                "is_deleted": {"$ne": True},
            },
            {"_id": 0, "parent_id": 1, "parent_user_id": 1, "balance_due_cents": 1},
        )
        totals: dict[str, int] = defaultdict(int)
        async for doc in cursor:
            parent_id = _invoice_parent_id(doc)
            if parent_id:
                totals[parent_id] += _int(doc.get("balance_due_cents"))
        return dict(totals)

    async def _dunning_by_invoice(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not invoice_ids:
            return {}
        cursor = self._db["dunning_states"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "status": 1, "attempt_count": 1, "next_attempt_at": 1},
        )
        return {str(doc["invoice_id"]): doc async for doc in cursor}

    async def _latest_attempt_by_invoice(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not invoice_ids:
            return {}
        pipeline = [
            {
                "$match": exclude_non_charge_attempts(
                    {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}}
                )
            },
            {"$sort": {"created_at": -1, "attempt_id": -1}},
            {
                "$group": {
                    "_id": "$invoice_id",
                    "status": {"$first": "$status"},
                    "reason": {"$first": {"$ifNull": ["$failure_message", "$failure_code"]}},
                }
            },
        ]
        cursor = self._db["payment_attempts"].aggregate(pipeline)
        return {
            str(doc["_id"]): {"status": doc.get("status"), "reason": doc.get("reason")}
            async for doc in cursor
        }

    async def _autopay_by_enrollment(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, str | None]:
        if not enrollment_ids:
            return {}
        cursor = self._db["student_billing_enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "autopay_enrollment_status": 1},
        )
        return {
            str(doc["enrollment_id"]): _opt_str(doc.get("autopay_enrollment_status"))
            async for doc in cursor
        }

    async def _paused(
        self, academy_id: str
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
        """Paused enrollments per student, and the newest deferral per enrollment."""
        cursor = self._db["enrollments"].find(
            {"academy_id": academy_id, "status": _PAUSED_STATUS},
            {"_id": 0, "enrollment_id": 1, "student_id": 1, "session_id": 1},
        )
        by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
        paused_ids: list[str] = []
        async for doc in cursor:
            student_id = _opt_str(doc.get("student_id"))
            if not student_id or doc.get("enrollment_id") is None:
                continue
            doc["enrollment_id"] = str(doc["enrollment_id"])
            by_student[student_id].append(doc)
            paused_ids.append(doc["enrollment_id"])
        for rows in by_student.values():
            rows.sort(key=lambda d: d["enrollment_id"])

        deferrals: dict[str, dict[str, Any]] = {}
        if paused_ids:
            deferral_cursor = self._db["enrollment_billing_deferrals"].find(
                {"academy_id": academy_id, "enrollment_id": {"$in": paused_ids}},
                {"_id": 0, "enrollment_id": 1, "resume_on": 1, "review_on": 1, "created_at": 1},
                sort=[("created_at", -1)],
            )
            async for doc in deferral_cursor:
                deferrals.setdefault(str(doc["enrollment_id"]), doc)
        return dict(by_student), deferrals

    async def _students(
        self, academy_id: str, invoice_parents: set[str], paused_student_ids: set[str]
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
        """Students of the invoice parents plus the parents of paused students."""
        projection = {
            "_id": 0,
            "student_id": 1,
            "parent_id": 1,
            "full_name": 1,
            "first_name": 1,
            "last_name": 1,
        }
        clauses: list[dict[str, Any]] = []
        if invoice_parents:
            clauses.append({"parent_id": {"$in": sorted(invoice_parents)}})
        if paused_student_ids:
            clauses.append({"student_id": {"$in": sorted(paused_student_ids)}})
        if not clauses:
            return {}, {}
        # Two passes so every sibling of a paused student is listed too.
        first = self._db["students"].find({"academy_id": academy_id, "$or": clauses}, projection)
        seed_docs = [doc async for doc in first]
        parents = {p for doc in seed_docs if (p := _opt_str(doc.get("parent_id")))}
        missing_parents = parents - invoice_parents
        docs = list(seed_docs)
        if missing_parents:
            second = self._db["students"].find(
                {"academy_id": academy_id, "parent_id": {"$in": sorted(missing_parents)}},
                projection,
            )
            docs.extend([doc async for doc in second])

        by_parent: dict[str, list[str]] = defaultdict(list)
        student_docs: dict[str, dict[str, Any]] = {}
        for doc in docs:
            student_id = _opt_str(doc.get("student_id"))
            parent_id = _opt_str(doc.get("parent_id"))
            if not student_id or not parent_id or student_id in student_docs:
                continue
            student_docs[student_id] = doc
            by_parent[parent_id].append(student_id)
        for ids in by_parent.values():
            ids.sort(key=lambda sid: (_student_name(student_docs[sid]), sid))
        return dict(by_parent), student_docs

    async def _session_by_student(
        self, academy_id: str, student_ids: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not student_ids:
            return {}
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": sorted(student_ids)},
                "status": {"$in": _ACTIVE_ENROLLMENT_STATUSES},
            },
            {"_id": 0, "student_id": 1, "session_id": 1, "status": 1},
        )
        session_id_by_student: dict[str, str] = {}
        async for doc in cursor:
            student_id = _opt_str(doc.get("student_id"))
            session_id = _opt_str(doc.get("session_id"))
            if not student_id or not session_id:
                continue
            # Prefer the active enrollment's session over a paused one.
            if student_id not in session_id_by_student or doc.get("status") == "active":
                session_id_by_student[student_id] = session_id
        if not session_id_by_student:
            return {}
        sessions_cursor = self._db["sessions"].find(
            {
                "academy_id": academy_id,
                "session_id": {"$in": sorted(set(session_id_by_student.values()))},
            },
            {"_id": 0, "session_id": 1, "title": 1, "name": 1},
        )
        sessions = {str(doc["session_id"]): doc async for doc in sessions_cursor}
        return {
            student_id: sessions[session_id]
            for student_id, session_id in session_id_by_student.items()
            if session_id in sessions
        }

    async def _users(self, parent_ids: set[str]) -> dict[str, dict[str, Any]]:
        """``users`` is global (spans academies); keyed the way ``MongoUserRepository`` keys it."""
        if not parent_ids:
            return {}
        ids = sorted(parent_ids)
        raw_ids: list[Any] = list(ids) + [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        cursor = self._db["users"].find(
            {
                "$or": [
                    {"user_id": {"$in": ids}},
                    {"auth_uid": {"$in": ids}},
                    {"_id": {"$in": raw_ids}},
                ]
            },
            {"user_id": 1, "auth_uid": 1, "display_name": 1, "name": 1, "email": 1},
        )
        wanted = set(ids)
        users: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            for key in (doc.get("user_id"), doc.get("auth_uid"), doc.get("_id")):
                candidate = str(key) if key is not None else None
                if candidate in wanted:
                    users.setdefault(candidate, doc)
        return users

    async def _paid_by_invoice(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not invoice_ids:
            return {}
        alloc_cursor = self._db["payment_allocations"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "payment_id": 1, "amount_cents": 1},
        )
        allocations = [doc async for doc in alloc_cursor]
        if not allocations:
            return {}
        payment_ids = sorted({str(a["payment_id"]) for a in allocations if a.get("payment_id")})
        pay_cursor = self._db["ledger_payments"].find(
            {"academy_id": academy_id, "payment_id": {"$in": payment_ids}},
            {"_id": 0, "payment_id": 1, "payment_method": 1, "paid_at": 1, "created_at": 1},
        )
        payments = {str(doc["payment_id"]): doc async for doc in pay_cursor}

        result: dict[str, dict[str, Any]] = {}
        for alloc in allocations:
            invoice_id = str(alloc["invoice_id"])
            payment = payments.get(str(alloc.get("payment_id")), {})
            paid_at = _to_datetime(payment.get("paid_at")) or _to_datetime(
                payment.get("created_at")
            )
            entry = result.setdefault(
                invoice_id, {"paid_cents": 0, "paid_method": None, "paid_at": None}
            )
            entry["paid_cents"] += _int(alloc.get("amount_cents"))
            if entry["paid_at"] is None or (paid_at is not None and paid_at >= entry["paid_at"]):
                entry["paid_at"] = paid_at
                entry["paid_method"] = _opt_str(payment.get("payment_method"))
        return result

    async def _cards(self) -> dict[str, tuple[bool, str | None]] | None:
        """Per parent: (has chargeable card, last4). ``None`` when the lookup fails."""
        try:
            docs = await self._customers.list_academy_customers()
        except Exception:
            log.warning("collections read model: customer lookup failed", exc_info=True)
            return None
        cards: dict[str, tuple[bool, str | None]] = {}
        for doc in docs:
            parent_id = _opt_str(doc.get("parent_id"))
            if not parent_id:
                continue
            label, last4 = MongoParentBillingCustomerRepository.display_payment_method(doc)
            cards[parent_id] = ((label, last4) != (None, None), last4)
        return cards

    async def _connected_account_ready(self) -> bool | None:
        try:
            account = await self._connected_accounts.get_for_academy()
            settings = await self._billing_settings.get()
        except Exception:
            log.warning("collections read model: connected-account lookup failed", exc_info=True)
            return None
        ready = account is not None and account.is_ready_for_charges()
        return bool(ready or getattr(settings, "allow_platform_charge_fallback", False))
