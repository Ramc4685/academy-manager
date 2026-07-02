"""Tenant-scoped Mongo repository for autopay dunning state."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar

from pymongo import ASCENDING, ReturnDocument

from backend.v2.contexts.billing.domain.dunning import (
    DunningState,
    open_initial_dunning_state,
    record_dunning_attempt_result,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoDunningStateRepository(TenantScopedRepository):
    collection_name = "dunning_states"
    retryable_parked_reasons: ClassVar[set[str]] = {
        "payment_processing",
        "charge_technical_failure",
        "attempt_indeterminate",
        "autopay_not_active",
        "connected_account_not_ready",
    }

    @staticmethod
    def _state_from_doc(doc: dict[str, object]) -> DunningState:
        payload = {k: v for k, v in doc.items() if k != "_id"}
        attempts = payload.get("notification_attempts")
        if isinstance(attempts, list):
            payload["notification_attempts"] = tuple(int(a) for a in attempts)
        for field in (
            "first_attempt_at",
            "last_attempt_at",
            "next_attempt_at",
            "last_notification_at",
            "terminal_at",
            "resolved_at",
            "processing_started_at",
            "lease_expires_at",
            "suppressed_at",
            "autopay_disabled_at",
            "created_at",
            "updated_at",
        ):
            if isinstance(payload.get(field), datetime) and payload[field].tzinfo is None:
                payload[field] = payload[field].replace(tzinfo=UTC)
        return DunningState(**payload)

    @staticmethod
    def _invoice_from_doc(doc: dict[str, object]) -> LedgerInvoice:
        return LedgerInvoice(
            **{k: v for k, v in doc.items() if k not in ("_id", "idempotency_key")}
        )

    async def prepare_due_states(self, *, now: datetime, limit: int) -> int:
        academy_id = current_academy_id()
        created = 0
        cursor = (
            self._db["invoices"]
            .find(
                {
                    "academy_id": academy_id,
                    "status": {"$in": ["open", "partially_paid"]},
                    "balance_due_cents": {"$gt": 0},
                    "due_date": {"$lte": now},
                    "enrollment_id": {"$exists": True, "$ne": None},
                }
            )
            .sort([("due_date", ASCENDING), ("invoice_id", ASCENDING)])
        )
        async for invoice_doc in cursor:
            if created >= limit:
                break
            enrollment_id = str(invoice_doc.get("enrollment_id") or "")
            if not enrollment_id:
                continue
            enrollment = await self._db["student_billing_enrollments"].find_one(
                {
                    "academy_id": academy_id,
                    "enrollment_id": enrollment_id,
                    "autopay_enrollment_status": "active",
                },
                {"_id": 1},
            )
            if enrollment is None:
                continue
            invoice_id = str(invoice_doc["invoice_id"])
            due_at = _as_datetime(invoice_doc.get("due_date"), now=now)
            state = open_initial_dunning_state(
                academy_id=academy_id,
                invoice_id=invoice_id,
                parent_id=str(invoice_doc["parent_id"]),
                enrollment_id=enrollment_id,
                due_at=due_at,
                now=now,
            )
            result = await self.collection.update_one(
                {"academy_id": academy_id, "invoice_id": invoice_id},
                {"$setOnInsert": _mongo_doc(state)},
                upsert=True,
            )
            if getattr(result, "upserted_id", None) is not None:
                created += 1
        return created

    async def claim_next_due(
        self, *, now: datetime, worker_id: str
    ) -> tuple[LedgerInvoice, DunningState] | None:
        academy_id = current_academy_id()
        cursor = self.collection.find(
            {
                "academy_id": academy_id,
                "status": {"$in": ["active", "processing"]},
            }
        ).sort([("next_attempt_at", ASCENDING), ("updated_at", ASCENDING)])
        async for state_doc in cursor:
            state = self._state_from_doc(state_doc)
            parked_for_retry_recheck = (
                state.status == "active"
                and state.next_attempt_at is None
                and state.suppression_reason in self.retryable_parked_reasons
            )
            parked_for_payment_processing = (
                parked_for_retry_recheck and state.suppression_reason == "payment_processing"
            )
            if state.status == "active":
                if state.next_attempt_at is None and not parked_for_retry_recheck:
                    continue
                if state.next_attempt_at is not None and state.next_attempt_at > now:
                    continue
                attempt_no = state.attempt_count + 1
            elif state.status == "processing":
                if state.lease_expires_at is None or state.lease_expires_at > now:
                    continue
                attempt_no = state.processing_attempt_no or state.attempt_count + 1
            else:
                continue

            invoice_doc = await self._db["invoices"].find_one(
                {"academy_id": academy_id, "invoice_id": state.invoice_id}
            )
            if not _invoice_chargeable(invoice_doc):
                await self._store_state(state.suppress(reason="invoice_not_chargeable", now=now))
                continue
            enrollment = await self._db["student_billing_enrollments"].find_one(
                {
                    "academy_id": academy_id,
                    "enrollment_id": str(invoice_doc.get("enrollment_id") or ""),
                }
            )
            if enrollment is None or enrollment.get("autopay_enrollment_status") != "active":
                await self._store_state(state.suppress(reason="autopay_not_active", now=now))
                continue
            latest_status = await self._latest_payment_attempt_status(state.invoice_id)
            if latest_status == "succeeded":
                await self._store_state(state.resolve(now=now))
                continue
            if latest_status == "processing":
                parked = state.model_copy(update={"status": "processing"}).park(
                    reason="payment_processing",
                    now=now,
                )
                await self._store_state(parked)
                continue
            if parked_for_payment_processing and latest_status not in {"failed", "requires_action"}:
                continue

            lease_expires_at = now + timedelta(minutes=30)
            claimed = state.claim(
                attempt_no=attempt_no,
                worker_id=worker_id,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            filter_: dict[str, Any] = {
                "academy_id": academy_id,
                "invoice_id": state.invoice_id,
                "status": state.status,
            }
            if state.status == "active":
                filter_.update(
                    {
                        "attempt_count": state.attempt_count,
                        "next_attempt_at": state.next_attempt_at,
                    }
                )
            else:
                filter_.update(
                    {
                        "processing_attempt_no": state.processing_attempt_no,
                        "lease_expires_at": state.lease_expires_at,
                    }
                )
            result = await self.collection.update_one(
                filter_,
                {"$set": _mongo_doc(claimed)},
            )
            if getattr(result, "matched_count", 0) != 1:
                continue
            return self._invoice_from_doc(invoice_doc), claimed
        return None

    async def finish_attempt(
        self,
        *,
        state: DunningState,
        succeeded: bool,
        failure_code: str | None,
        now: datetime,
    ) -> DunningState:
        updated = record_dunning_attempt_result(
            state,
            succeeded=succeeded,
            failure_code=failure_code,
            now=now,
        )
        stored = await self._replace_processing_state(state, updated)
        if stored is None:
            raise ValueError("dunning state changed during finish; retry")
        return stored

    async def release_attempt(
        self,
        *,
        state: DunningState,
        next_attempt_at: datetime | None,
        now: datetime,
    ) -> DunningState:
        updated = state.release(next_attempt_at=next_attempt_at, now=now)
        stored = await self._replace_processing_state(state, updated)
        if stored is None:
            raise ValueError("dunning state changed during release; retry")
        return stored

    async def park_attempt(
        self,
        *,
        state: DunningState,
        reason: str,
        now: datetime,
    ) -> DunningState:
        updated = state.park(reason=reason, now=now)
        stored = await self._replace_processing_state(state, updated)
        if stored is None:
            raise ValueError("dunning state changed during park; retry")
        return stored

    async def mark_notification_sent(
        self, *, invoice_id: str, attempt_no: int, sent_at: datetime
    ) -> DunningState:
        academy_id = current_academy_id()
        await self.collection.update_one(
            {"academy_id": academy_id, "invoice_id": invoice_id},
            {
                "$addToSet": {"notification_attempts": attempt_no},
                "$set": {"last_notification_at": sent_at, "updated_at": sent_at},
            },
        )
        doc = await self.collection.find_one({"academy_id": academy_id, "invoice_id": invoice_id})
        if doc is None:
            raise ValueError("dunning state not found")
        return self._state_from_doc(doc)

    async def list_terminal_disable_pending(self, *, limit: int) -> list[DunningState]:
        cursor = (
            self.collection.find(
                {
                    "academy_id": current_academy_id(),
                    "status": "dunned",
                    "autopay_disable_status": {"$in": ["pending", "failed"]},
                }
            )
            .sort([("updated_at", ASCENDING), ("invoice_id", ASCENDING)])
            .limit(limit)
        )
        return [self._state_from_doc(doc) async for doc in cursor]

    async def mark_autopay_disable_result(
        self,
        *,
        invoice_id: str,
        succeeded: bool,
        error: str | None,
        now: datetime,
    ) -> DunningState:
        academy_id = current_academy_id()
        update: dict[str, Any] = {
            "autopay_disable_status": "succeeded" if succeeded else "failed",
            "autopay_disable_error": None if succeeded else error,
            "updated_at": now,
        }
        if succeeded:
            update["autopay_disabled_at"] = now
        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, "invoice_id": invoice_id},
            {"$set": update},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise ValueError("dunning state not found")
        return self._state_from_doc(doc)

    async def list_admin_rows(self) -> list[dict[str, Any]]:
        academy_id = current_academy_id()
        rows: list[dict[str, Any]] = []
        cursor = self.collection.find(
            {
                "academy_id": academy_id,
                "$or": [
                    {"status": "dunned"},
                    {"status": "active", "attempt_count": {"$gt": 0}},
                    {"status": "processing"},
                ],
            },
            sort=[("updated_at", -1)],
        )
        async for state_doc in cursor:
            invoice = await self._db["invoices"].find_one(
                {"academy_id": academy_id, "invoice_id": state_doc["invoice_id"]}
            )
            if invoice is None:
                continue
            rows.append(
                {
                    "invoice_id": str(state_doc["invoice_id"]),
                    "parent_id": str(state_doc.get("parent_id") or invoice.get("parent_id") or ""),
                    "parent_name": None,
                    "period": str(invoice.get("period") or ""),
                    "status": str(state_doc.get("status") or "active"),
                    "attempt_count": int(state_doc.get("attempt_count") or 0),
                    "next_attempt_at": state_doc.get("next_attempt_at"),
                    "last_attempt_at": state_doc.get("last_attempt_at"),
                    "last_failure_code": state_doc.get("last_failure_code"),
                    "terminal_at": state_doc.get("terminal_at"),
                    "autopay_disable_status": state_doc.get("autopay_disable_status"),
                    "autopay_disable_error": state_doc.get("autopay_disable_error"),
                    "autopay_disabled_at": state_doc.get("autopay_disabled_at"),
                    "balance_due_cents": int(invoice.get("balance_due_cents") or 0),
                    "currency": str(invoice.get("currency") or "usd"),
                }
            )
        return rows

    async def _store_state(self, state: DunningState) -> DunningState:
        await self.collection.update_one(
            {"academy_id": current_academy_id(), "invoice_id": state.invoice_id},
            {"$set": _mongo_doc(state)},
        )
        return state

    async def _latest_payment_attempt_status(self, invoice_id: str) -> str | None:
        doc = await self._db["payment_attempts"].find_one(
            {"academy_id": current_academy_id(), "invoice_id": invoice_id},
            sort=[("created_at", -1), ("attempt_id", -1)],
        )
        return str(doc.get("status")) if doc else None

    async def _replace_processing_state(
        self, current: DunningState, updated: DunningState
    ) -> DunningState | None:
        academy_id = current_academy_id()
        result = await self.collection.update_one(
            {
                "academy_id": academy_id,
                "invoice_id": current.invoice_id,
                "status": "processing",
                "processing_attempt_no": current.processing_attempt_no,
                "processing_worker_id": current.processing_worker_id,
            },
            {"$set": _mongo_doc(updated)},
        )
        if getattr(result, "matched_count", 0) != 1:
            return None
        doc = await self.collection.find_one(
            {"academy_id": academy_id, "invoice_id": current.invoice_id}
        )
        return self._state_from_doc(doc) if doc else None


def _as_datetime(value: object, *, now: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    return now


def _mongo_doc(model: DunningState) -> dict[str, Any]:
    doc = model.model_dump(mode="python")
    doc["notification_attempts"] = list(model.notification_attempts)
    return doc


def _invoice_chargeable(invoice_doc: dict[str, Any] | None) -> bool:
    if invoice_doc is None:
        return False
    return (
        invoice_doc.get("status") in {"open", "partially_paid"}
        and int(invoice_doc.get("balance_due_cents") or 0) > 0
    )
