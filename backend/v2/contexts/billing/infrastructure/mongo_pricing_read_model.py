"""Mongo read model and link store for the Pricing page (Settings overhaul PR 11b).

Read only, apart from ``class_plan_links``, which this module owns. The
charged amount of a class is read with ``session_amount_cents``, the exact
helper the monthly invoice generator bills with, so the page shows what
families actually pay. Nothing here writes to ``sessions``, ``enrollments``
or ``student_billing_enrollments``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    ClassPlanLink,
    ClassPriceFacts,
    SavedOverrideFacts,
)
from backend.v2.contexts.billing.domain.session_type import SessionType
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    session_amount_cents,
)
from backend.v2.shared.tenancy import TenantScopedRepository

#: Enough for any academy's class list and override review; the page is not
#: paginated.
_ROW_CAP = 500

_CLOSED_SESSION_STATUSES = ["cancelled", "completed", "archived"]
_FEE_FIELDS = ("amount_cents", "monthly_price_cents", "monthly_price")


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _student_name(doc: dict[str, Any] | None) -> str | None:
    if not doc:
        return None
    full = _opt_str(doc.get("full_name")) or _opt_str(doc.get("name"))
    if full:
        return full
    parts = [p for p in (_opt_str(doc.get("first_name")), _opt_str(doc.get("last_name"))) if p]
    return " ".join(parts) or None


def _session_id(doc: dict[str, Any]) -> str:
    return str(doc.get("session_id") or doc.get("_id"))


def _session_title(doc: dict[str, Any]) -> str:
    return str(doc.get("title") or doc.get("name") or "Class")


class MongoPricingReadModel(TenantScopedRepository):
    collection_name = "sessions"

    def __init__(
        self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        super().__init__(db)
        self._now = clock

    async def _active_counts(self, session_ids: list[str] | None = None) -> dict[str, int]:
        match: dict[str, Any] = {"status": "active"}
        if session_ids is not None:
            match["session_id"] = {"$in": session_ids}
        cursor = self._db["enrollments"].aggregate(
            [
                {"$match": self._scoped(match)},
                {"$group": {"_id": "$session_id", "n": {"$sum": 1}}},
            ]
        )
        return {str(doc["_id"]): int(doc["n"]) async for doc in cursor if doc.get("_id")}

    @staticmethod
    def _facts(doc: dict[str, Any], students: int) -> ClassPriceFacts:
        return ClassPriceFacts(
            session_id=_session_id(doc),
            title=_session_title(doc),
            charged_cents=session_amount_cents(doc),
            fee_set=any(doc.get(field) is not None for field in _FEE_FIELDS),
            students=students,
        )

    async def list_classes(self) -> list[ClassPriceFacts]:
        """Classes still running: recurring, upcoming, or with active students."""
        counts = await self._active_counts()
        cursor = self._find_many(
            {
                "status": {"$nin": _CLOSED_SESSION_STATUSES},
                "$or": [
                    {"days_of_week.0": {"$exists": True}},
                    {"end_at": {"$gte": self._now()}},
                    {"session_id": {"$in": sorted(counts)}},
                ],
            },
            sort=[("title", 1), ("session_id", 1)],
            limit=_ROW_CAP,
        )
        return [self._facts(doc, counts.get(_session_id(doc), 0)) async for doc in cursor]

    async def get_class(self, session_id: str) -> ClassPriceFacts | None:
        doc = await self._find_one({"$or": [{"session_id": session_id}, {"_id": session_id}]})
        if doc is None:
            return None
        counts = await self._active_counts([_session_id(doc)])
        return self._facts(doc, counts.get(_session_id(doc), 0))

    async def _students(self, student_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not student_ids:
            return {}
        cursor = self._find_many_in_collection(
            "students",
            {"student_id": {"$in": sorted(student_ids)}},
            {"_id": 0, "student_id": 1, "full_name": 1, "name": 1, "first_name": 1, "last_name": 1},
        )
        return {str(doc["student_id"]): doc async for doc in cursor}

    async def _enrollment_sessions(self, enrollment_ids: set[str]) -> dict[str, str]:
        """Class enrollment id -> session id, tenant-scoped."""
        if not enrollment_ids:
            return {}
        cursor = self._find_many_in_collection(
            "enrollments",
            {"enrollment_id": {"$in": sorted(enrollment_ids)}},
            {"_id": 0, "enrollment_id": 1, "session_id": 1},
        )
        return {
            str(doc["enrollment_id"]): str(doc["session_id"])
            async for doc in cursor
            if doc.get("enrollment_id") and doc.get("session_id")
        }

    async def _sessions(self, session_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not session_ids:
            return {}
        cursor = self._find_many({"session_id": {"$in": sorted(session_ids)}})
        return {_session_id(doc): doc async for doc in cursor}

    async def list_saved_overrides(self, plans: Sequence[SessionType]) -> list[SavedOverrideFacts]:
        """Every stored per-student override, newest first within each source.

        ``student_billing_enrollments.override_price_cents`` (Student > Billing
        plans > Override price) and the amount on a class enrollment
        (Student > Sessions > Override fee). Neither is read by any charge
        path; this list is for the owner to review, never to apply.
        """
        plan_by_id = {p.session_type_id: p for p in plans}
        billing_docs = [
            doc
            async for doc in self._find_many_in_collection(
                "student_billing_enrollments",
                {"override_price_cents": {"$ne": None}},
                sort=[("updated_at", -1)],
                limit=_ROW_CAP,
            )
        ]
        enrollment_docs = [
            doc
            async for doc in self._find_many_in_collection(
                "enrollments",
                {"amount_cents": {"$ne": None}},
                sort=[("updated_at", -1)],
                limit=_ROW_CAP,
            )
        ]
        students = await self._students(
            {str(d["student_id"]) for d in [*billing_docs, *enrollment_docs] if d.get("student_id")}
        )
        # A billing-plan override row belongs to a class enrollment; the family
        # is billed that class's fee, never the plan price (#1007 review P2).
        plan_enrollment_session = await self._enrollment_sessions(
            {str(d["enrollment_id"]) for d in billing_docs if d.get("enrollment_id")}
        )
        sessions = await self._sessions(
            {str(d["session_id"]) for d in enrollment_docs if d.get("session_id")}
            | set(plan_enrollment_session.values())
        )

        rows: list[SavedOverrideFacts] = []
        for doc in billing_docs:
            plan = plan_by_id.get(str(doc.get("session_type_id") or ""))
            student_id = _opt_str(doc.get("student_id"))
            billed_session = sessions.get(
                plan_enrollment_session.get(str(doc.get("enrollment_id") or ""), "")
            )
            rows.append(
                SavedOverrideFacts(
                    source="billing_plan",
                    enrollment_id=str(doc.get("enrollment_id") or doc.get("_id")),
                    student_id=student_id,
                    student_name=_student_name(students.get(student_id or "")),
                    label=plan.name if plan else None,
                    override_cents=int(doc["override_price_cents"]),
                    charged_cents=(
                        session_amount_cents(billed_session) if billed_session else None
                    ),
                    status=_opt_str(doc.get("status")),
                )
            )
        for doc in enrollment_docs:
            session = sessions.get(str(doc.get("session_id") or ""))
            student_id = _opt_str(doc.get("student_id"))
            rows.append(
                SavedOverrideFacts(
                    source="class_enrollment",
                    enrollment_id=str(doc.get("enrollment_id") or doc.get("_id")),
                    student_id=student_id,
                    student_name=_student_name(students.get(student_id or "")),
                    label=_session_title(session) if session else None,
                    override_cents=int(doc["amount_cents"]),
                    charged_cents=session_amount_cents(session) if session else None,
                    status=_opt_str(doc.get("status")),
                )
            )
        return rows


class MongoClassPlanLinkRepository(TenantScopedRepository):
    """``class_plan_links``: one doc per decided class, owned by billing.

    ``plan_id`` null means the owner marked the class custom. No charge path
    reads this collection.
    """

    collection_name = "class_plan_links"

    async def list_links(self) -> list[ClassPlanLink]:
        cursor = self._find_many({})
        return [
            ClassPlanLink(session_id=str(doc["session_id"]), plan_id=_opt_str(doc.get("plan_id")))
            async for doc in cursor
            if doc.get("session_id")
        ]

    async def get_link(self, session_id: str) -> ClassPlanLink | None:
        doc = await self._find_one({"session_id": session_id})
        if doc is None:
            return None
        return ClassPlanLink(session_id=session_id, plan_id=_opt_str(doc.get("plan_id")))

    async def set_link(
        self, *, session_id: str, plan_id: str | None, actor_id: str, at: datetime
    ) -> None:
        await self._update_one(
            {"session_id": session_id},
            {
                "$set": {"plan_id": plan_id, "set_by": actor_id, "set_at": at, "source": "owner"},
                "$setOnInsert": {"created_at": at},
            },
            upsert=True,
        )

    async def set_link_if_unset(
        self, *, session_id: str, plan_id: str, actor_id: str, at: datetime
    ) -> bool:
        result = await self._update_one(
            {"session_id": session_id},
            {
                "$setOnInsert": {
                    "plan_id": plan_id,
                    "set_by": actor_id,
                    "set_at": at,
                    "source": "auto",
                    "created_at": at,
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None
