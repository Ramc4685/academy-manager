"""Mongo repository for enrollment billing deferrals."""

from __future__ import annotations

from datetime import date, datetime

from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferral,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoBillingDeferralRepository(TenantScopedRepository):
    collection_name = "enrollment_billing_deferrals"

    @staticmethod
    def _date_value(value: object) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str) and value:
            return date.fromisoformat(value[:10])
        return None

    @classmethod
    def _to_domain(cls, doc: dict[str, object]) -> BillingDeferral:
        return BillingDeferral(
            deferral_id=str(doc["deferral_id"]),
            enrollment_id=str(doc["enrollment_id"]),
            student_id=str(doc["student_id"]),
            deferral_type=doc["deferral_type"],  # type: ignore[arg-type]
            reason=str(doc.get("reason") or ""),
            source=str(doc["source"]),
            source_id=_optional_str(doc.get("source_id")),
            actor_id=_optional_str(doc.get("actor_id")),
            actor_type=str(doc.get("actor_type") or "system"),
            billing_period=str(doc["billing_period"]),
            resume_on=cls._date_value(doc.get("resume_on")),
            review_on=cls._date_value(doc.get("review_on")),
            expires_on=cls._date_value(doc.get("expires_on")),
            status=doc.get("status", "active"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc.get("updated_at"),  # type: ignore[arg-type]
            closed_at=doc.get("closed_at"),  # type: ignore[arg-type]
            closed_by=_optional_str(doc.get("closed_by")),
            closure_reason=_optional_str(doc.get("closure_reason")),
            metadata=_str_dict(doc.get("metadata")),
        )

    @staticmethod
    def _to_doc(deferral: BillingDeferral) -> dict[str, object]:
        doc = deferral.model_dump(mode="python")
        for field in ("resume_on", "review_on", "expires_on"):
            value = doc.get(field)
            if isinstance(value, date):
                doc[field] = value.isoformat()
        return doc

    async def add(self, deferral: BillingDeferral) -> None:
        doc = self._to_doc(deferral)
        await self._update_one(
            {
                "enrollment_id": deferral.enrollment_id,
                "source": deferral.source,
                "source_id": deferral.source_id,
                "billing_period": deferral.billing_period,
                "status": "active",
            },
            {"$setOnInsert": doc},
            upsert=True,
        )

    async def active_for_enrollment_period(
        self,
        *,
        enrollment_id: str,
        period: str,
        today: date,
    ) -> BillingDeferral | None:
        cursor = self._find_many(
            {"enrollment_id": enrollment_id, "status": "active"},
            sort=[("created_at", -1)],
            limit=20,
        )
        async for doc in cursor:
            deferral = self._to_domain(doc)
            if deferral.covers_period(period, today=today):
                return deferral
        return None

    async def close_active_for_enrollment(
        self,
        enrollment_id: str,
        *,
        closed_at: datetime,
        closed_by: str,
        reason: str,
    ) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id, "status": "active"},
            {
                "$set": {
                    "status": "closed",
                    "closed_at": closed_at,
                    "closed_by": closed_by,
                    "closure_reason": reason,
                    "updated_at": closed_at,
                }
            },
        )

    async def list_admin_warnings(
        self, *, today: date, limit: int = 100
    ) -> list[dict[str, object]]:
        academy_id = current_academy_id()
        warnings: list[dict[str, object]] = []

        async for doc in self._find_many(
            {
                "status": "active",
                "$or": [
                    {"review_on": {"$lte": today.isoformat()}},
                    {"expires_on": {"$lt": today.isoformat()}},
                ],
            },
            sort=[("review_on", 1), ("expires_on", 1), ("created_at", 1)],
            limit=limit,
        ):
            warnings.append(await self._warning_from_deferral(doc, reason_code="stale_pause"))

        remaining = max(limit - len(warnings), 0)
        if remaining:
            async for enrollment in self._db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "skip_periods": {"$exists": True, "$ne": []},
                },
                limit=remaining,
            ):
                warnings.append(
                    await self._warning_from_enrollment(
                        enrollment,
                        reason_code="legacy_skip_period",
                        severity="medium",
                    )
                )

        remaining = max(limit - len(warnings), 0)
        if remaining:
            async for action in self._db["scheduled_enrollment_actions"].find(
                {"academy_id": academy_id, "status": "blocked_capacity"},
                limit=remaining,
            ):
                enrollment = await self._db["enrollments"].find_one(
                    {
                        "academy_id": academy_id,
                        "enrollment_id": str(action.get("enrollment_id") or ""),
                    }
                )
                if enrollment is not None:
                    warnings.append(
                        await self._warning_from_enrollment(
                            enrollment,
                            reason_code="capacity_blocked_resume",
                            severity="high",
                        )
                    )

        remaining = max(limit - len(warnings), 0)
        if remaining:
            async for enrollment in self._db["enrollments"].find(
                {"academy_id": academy_id, "status": "paused"},
                limit=remaining,
            ):
                subscription = await self._db["subscriptions"].find_one(
                    {
                        "academy_id": academy_id,
                        "enrollment_id": str(enrollment.get("enrollment_id") or ""),
                        "status": {"$in": ["active", "trialing"]},
                    }
                )
                if subscription is not None:
                    warnings.append(
                        await self._warning_from_enrollment(
                            enrollment,
                            reason_code="active_stripe_subscription_mismatch",
                            severity="high",
                        )
                    )

        return warnings[:limit]

    async def _warning_from_deferral(
        self, doc: dict[str, object], *, reason_code: str
    ) -> dict[str, object]:
        enrollment = await self._db["enrollments"].find_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": str(doc.get("enrollment_id") or ""),
            }
        )
        return await self._warning_from_enrollment(
            enrollment or doc,
            reason_code=reason_code,
            severity="high",
        )

    async def _warning_from_enrollment(
        self,
        enrollment: dict[str, object],
        *,
        reason_code: str,
        severity: str,
    ) -> dict[str, object]:
        student_id = str(enrollment.get("student_id") or "")
        student = await self._db["students"].find_one(
            {"academy_id": current_academy_id(), "student_id": student_id}
        )
        return {
            "enrollment_id": str(enrollment.get("enrollment_id") or ""),
            "student_id": student_id,
            "student_name": str((student or {}).get("full_name") or ""),
            "reason_code": reason_code,
            "severity": severity,
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}
