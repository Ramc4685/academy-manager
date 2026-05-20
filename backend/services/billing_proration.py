"""Legacy bridge to the v2 billing proration policy."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId

try:
    from backend.v2.contexts.billing.domain.proration import (
        BillingCalculationSnapshot,
        BillingPeriod,
        ClassOccurrence,
        FirstMonthProrationPolicy,
    )
except ModuleNotFoundError:  # pragma: no cover - legacy backend cwd import path
    from v2.contexts.billing.domain.proration import (  # type: ignore[no-redef]
        BillingCalculationSnapshot,
        BillingPeriod,
        ClassOccurrence,
        FirstMonthProrationPolicy,
    )


def prorated_first_month_quote(
    *,
    session: dict,
    enrollment: dict,
    period: str,
    calculated_at: datetime,
    calculated_by: str,
) -> BillingCalculationSnapshot | None:
    billing_start = _coerce_datetime(
        enrollment.get("billing_start_at")
        or enrollment.get("enrolled_at")
        or enrollment.get("created_at")
    )
    if billing_start is None or billing_start.strftime("%Y-%m") != period:
        return None
    timezone_name = str(session.get("timezone") or "America/Chicago")
    billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
    normalized = dict(session)
    normalized.setdefault("session_id", str(session.get("session_id") or session.get("_id") or ""))
    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=_session_amount_cents(normalized),
        discount_cents=0,
        period=billing_period,
        occurrences=_session_occurrences(normalized, billing_period),
        billing_start_at=billing_start,
        calculated_at=calculated_at if calculated_at.tzinfo else calculated_at.replace(tzinfo=timezone.utc),
        calculated_by=calculated_by,
    )
    return quote


async def persist_legacy_snapshot(
    db,
    *,
    quote: BillingCalculationSnapshot,
    enrollment: dict,
    session: dict,
    period: str,
) -> str:
    snapshot_id = str(ObjectId())
    stored = quote.model_copy(update={"snapshot_id": snapshot_id, "status": "CONSUMED"})
    await db.billing_calculation_snapshots.insert_one(
        {
            **stored.model_dump(mode="python"),
            "enrollment_id": str(enrollment.get("_id") or enrollment.get("enrollment_id") or ""),
            "session_id": str(session.get("_id") or session.get("session_id") or ""),
            "student_id": str(enrollment.get("student_id") or ""),
            "parent_id": str(enrollment.get("parent_user_id") or enrollment.get("parent_id") or ""),
            "billing_period_label": period,
            "created_at": quote.calculated_at,
        }
    )
    return snapshot_id


def _session_amount_cents(doc: dict) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return int(round(float(doc["monthly_price"]) * 100))
    return 0


def _coerce_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _session_occurrences(doc: dict, period: BillingPeriod) -> list[ClassOccurrence]:
    timezone_name = str(doc.get("timezone") or period.timezone or "America/Chicago")
    tz = ZoneInfo(timezone_name)
    session_id = str(doc.get("session_id") or doc.get("_id") or "")
    if not (doc.get("start_date") and doc.get("end_date") and doc.get("days_of_week")):
        return []
    start_date = date.fromisoformat(str(doc["start_date"]))
    end_date = date.fromisoformat(str(doc["end_date"]))
    days = {str(day)[:3].title() for day in (doc.get("days_of_week") or [])}
    start_time = time.fromisoformat(str(doc.get("start_time") or "00:00"))
    end_time = time.fromisoformat(str(doc.get("end_time") or doc.get("start_time") or "00:00"))
    current = max(start_date, period.start_at.date())
    period_last_day = date.fromordinal(period.end_at.date().toordinal() - 1)
    final = min(end_date, period_last_day)
    rows: list[ClassOccurrence] = []
    while current <= final:
        if current.strftime("%a") in days:
            local_start = datetime.combine(current, start_time, tzinfo=tz)
            local_end = datetime.combine(current, end_time, tzinfo=tz)
            rows.append(
                ClassOccurrence(
                    occurrence_id=f"{session_id}:{current.isoformat()}:{start_time.strftime('%H:%M')}",
                    session_id=session_id,
                    start_at=local_start.astimezone(timezone.utc),
                    end_at=local_end.astimezone(timezone.utc),
                    status="scheduled",
                    is_billable=True,
                    timezone=timezone_name,
                )
            )
        current = date.fromordinal(current.toordinal() + 1)
    return rows
