"""Mongo-backed reporting snapshot repositories (Wave 5A Stream M).

Three thin repos, one per snapshot aggregate. All use a per-collection
unique key for the natural identifier and upsert on it so re-running a
computation simply refreshes the snapshot rather than producing
duplicates.

Decimal fields (``hours``) are persisted as strings to avoid Mongo's
implicit float coercion — same convention as the payout repository.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.v2.contexts.finance.domain.reporting_snapshots import (
    AcademyRevenueSnapshot,
    CoachPayoutSnapshot,
    SessionAttendanceSnapshot,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAcademyRevenueSnapshotRepository(TenantScopedRepository):
    collection_name = "academy_revenue_snapshots"

    @staticmethod
    def _to_doc(s: AcademyRevenueSnapshot) -> dict[str, Any]:
        return {
            "period": s.period,
            "gross_minor": int(s.gross_minor),
            "refunded_minor": int(s.refunded_minor),
            "outstanding_minor": int(s.outstanding_minor),
            "currency": s.currency,
            "computed_at": s.computed_at,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> AcademyRevenueSnapshot:
        return AcademyRevenueSnapshot(
            academy_id=str(doc["academy_id"]),
            period=str(doc["period"]),
            gross_minor=int(doc["gross_minor"]),
            refunded_minor=int(doc["refunded_minor"]),
            outstanding_minor=int(doc["outstanding_minor"]),
            currency=str(doc["currency"]),
            computed_at=doc["computed_at"],
        )

    async def find(
        self, *, academy_id: str, period: str
    ) -> AcademyRevenueSnapshot | None:
        # academy_id arg is informational — tenancy is enforced by base
        # class. Keeping it in the signature to match the port.
        del academy_id
        doc = await self._find_one({"period": period})
        return self._from_doc(doc) if doc else None

    async def upsert(self, snapshot: AcademyRevenueSnapshot) -> AcademyRevenueSnapshot:
        await self._update_one(
            {"period": snapshot.period},
            {"$set": self._to_doc(snapshot)},
            upsert=True,
        )
        stored = await self.find(academy_id=snapshot.academy_id, period=snapshot.period)
        if stored is None:  # pragma: no cover - defensive
            raise RuntimeError("revenue snapshot upsert lost the document")
        return stored


class MongoSessionAttendanceSnapshotRepository(TenantScopedRepository):
    collection_name = "session_attendance_snapshots"

    @staticmethod
    def _to_doc(s: SessionAttendanceSnapshot) -> dict[str, Any]:
        return {
            "session_id": s.session_id,
            "period": s.period,
            "scheduled_count": int(s.scheduled_count),
            "completed_count": int(s.completed_count),
            "no_show_count": int(s.no_show_count),
            "computed_at": s.computed_at,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> SessionAttendanceSnapshot:
        return SessionAttendanceSnapshot(
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            period=str(doc["period"]),
            scheduled_count=int(doc["scheduled_count"]),
            completed_count=int(doc["completed_count"]),
            no_show_count=int(doc["no_show_count"]),
            computed_at=doc["computed_at"],
        )

    async def find(
        self, *, academy_id: str, session_id: str, period: str
    ) -> SessionAttendanceSnapshot | None:
        del academy_id
        doc = await self._find_one({"session_id": session_id, "period": period})
        return self._from_doc(doc) if doc else None

    async def upsert(
        self, snapshot: SessionAttendanceSnapshot
    ) -> SessionAttendanceSnapshot:
        await self._update_one(
            {"session_id": snapshot.session_id, "period": snapshot.period},
            {"$set": self._to_doc(snapshot)},
            upsert=True,
        )
        stored = await self.find(
            academy_id=snapshot.academy_id,
            session_id=snapshot.session_id,
            period=snapshot.period,
        )
        if stored is None:  # pragma: no cover - defensive
            raise RuntimeError("attendance snapshot upsert lost the document")
        return stored


class MongoCoachPayoutSnapshotRepository(TenantScopedRepository):
    collection_name = "coach_payout_snapshots"

    @staticmethod
    def _to_doc(s: CoachPayoutSnapshot) -> dict[str, Any]:
        return {
            "coach_id": s.coach_id,
            "period": s.period,
            "hours": str(s.hours),
            "payout_minor": int(s.payout_minor),
            "currency": s.currency,
            "computed_at": s.computed_at,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> CoachPayoutSnapshot:
        return CoachPayoutSnapshot(
            academy_id=str(doc["academy_id"]),
            coach_id=str(doc["coach_id"]),
            period=str(doc["period"]),
            hours=Decimal(str(doc["hours"])),
            payout_minor=int(doc["payout_minor"]),
            currency=str(doc["currency"]),
            computed_at=doc["computed_at"],
        )

    async def find(
        self, *, academy_id: str, coach_id: str, period: str
    ) -> CoachPayoutSnapshot | None:
        del academy_id
        doc = await self._find_one({"coach_id": coach_id, "period": period})
        return self._from_doc(doc) if doc else None

    async def upsert(self, snapshot: CoachPayoutSnapshot) -> CoachPayoutSnapshot:
        await self._update_one(
            {"coach_id": snapshot.coach_id, "period": snapshot.period},
            {"$set": self._to_doc(snapshot)},
            upsert=True,
        )
        stored = await self.find(
            academy_id=snapshot.academy_id,
            coach_id=snapshot.coach_id,
            period=snapshot.period,
        )
        if stored is None:  # pragma: no cover - defensive
            raise RuntimeError("coach payout snapshot upsert lost the document")
        return stored
