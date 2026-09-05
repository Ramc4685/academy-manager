"""Tenant-scoped Mongo repository for autopay dunning state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, ReturnDocument

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    invoice_is_chargeable,
    ladder_eligibility,
)
from backend.v2.contexts.billing.domain.dunning import (
    DunningState,
    open_initial_dunning_state,
    record_dunning_attempt_result,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoDunningStateRepository(TenantScopedRepository):
    collection_name = "dunning_states"
    # Park reasons a later tick re-claims. A parked state has next_attempt_at=None, so
    # anything missing from this set is parked forever and that invoice is never
    # collected again — every reason ProcessDunningRetries can park with must appear
    # here. checkout_session_open in particular is the release valve for the manual-pay
    # hold: the tick after the session settles or lapses picks the invoice back up on
    # the same rung (issue #434).
    retryable_parked_reasons: ClassVar[set[str]] = {
        "payment_processing",
        "charge_technical_failure",
        "attempt_indeterminate",
        "autopay_not_active",
        "connected_account_not_ready",
        "checkout_session_open",
        "stripe_not_configured",
    }

    #: Local hour (academy timezone) before which no NEW ladder is prepared on
    #: its due date, so the first autopay attempt lands in the morning of the
    #: due date instead of 00:00 UTC — 7pm the evening before in Chicago (#651).
    first_attempt_local_hour: ClassVar[int] = 9

    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        super().__init__(db)
        self._academy_timezone = academy_timezone

    async def _local_now(self, *, academy_id: str, now: datetime) -> datetime:
        """``now`` on the academy's wall clock (UTC when no zone is configured)."""
        aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        if self._academy_timezone is None:
            return aware
        try:
            zone = await self._academy_timezone(academy_id)
            return aware.astimezone(ZoneInfo(zone)) if zone else aware
        except Exception:  # pragma: no cover - defensive: never block collection
            return aware

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

    # Invoices are streamed and cross-referenced (existing dunning states,
    # autopay enrollment) in pages of this size, so the steady-state hourly
    # tick pays O(open-invoices / page) queries instead of one enrollment
    # find_one per open invoice (issue #513).
    prepare_batch_size: ClassVar[int] = 200

    async def prepare_due_states(self, *, now: datetime, limit: int) -> int:
        academy_id = current_academy_id()
        created = 0
        local_now = await self._local_now(academy_id=academy_id, now=now)
        if local_now.hour < self.first_attempt_local_hour:
            # Too early on the academy's clock: leave today's due invoices
            # for a later tick. Existing ladders still retry on schedule.
            return 0
        # due_date is stored as a naive midnight; anything due on or before
        # the academy's local calendar day is ready.
        due_cutoff = datetime.combine(local_now.date(), time.max)
        cursor = (
            self._db["invoices"]
            .find(
                {
                    "academy_id": academy_id,
                    "status": {"$in": ["open", "partially_paid"]},
                    "balance_due_cents": {"$gt": 0},
                    "due_date": {"$lte": due_cutoff},
                    "enrollment_id": {"$exists": True, "$ne": None},
                },
                {
                    "invoice_id": 1,
                    "parent_id": 1,
                    "enrollment_id": 1,
                    "due_date": 1,
                    "status": 1,
                    "balance_due_cents": 1,
                },
            )
            .sort([("due_date", ASCENDING), ("invoice_id", ASCENDING)])
        )
        batch: list[dict[str, Any]] = []
        async for invoice_doc in cursor:
            batch.append(invoice_doc)
            if len(batch) >= self.prepare_batch_size:
                created += await self._prepare_batch(
                    batch, academy_id=academy_id, now=now, remaining=limit - created
                )
                batch = []
                if created >= limit:
                    return created
        if batch:
            created += await self._prepare_batch(
                batch, academy_id=academy_id, now=now, remaining=limit - created
            )
        return created

    async def _prepare_batch(
        self,
        batch: list[dict[str, Any]],
        *,
        academy_id: str,
        now: datetime,
        remaining: int,
    ) -> int:
        """Create dunning states for one page of due invoices.

        Invoices that already hold a dunning state are dropped with a single
        ``$in`` query (they never count toward the limit, preserving the
        overfetch-past-existing-rows semantics), and autopay eligibility for
        the rest is resolved with one batched enrollment query rather than a
        per-invoice ``find_one``.
        """
        if remaining <= 0:
            return 0
        invoice_ids = [str(doc["invoice_id"]) for doc in batch]
        existing = {
            str(doc["invoice_id"])
            async for doc in self.collection.find(
                {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
                {"invoice_id": 1},
            )
        }
        candidates = [
            doc
            for doc in batch
            if str(doc["invoice_id"]) not in existing and str(doc.get("enrollment_id") or "")
        ]
        if not candidates:
            return 0
        enrollment_ids = sorted({str(doc["enrollment_id"]) for doc in candidates})
        autopay_active = {
            str(doc["enrollment_id"])
            async for doc in self._db["student_billing_enrollments"].find(
                {
                    "academy_id": academy_id,
                    "enrollment_id": {"$in": enrollment_ids},
                    "autopay_enrollment_status": AUTOPAY_ACTIVE_STATUS,
                },
                {"enrollment_id": 1},
            )
        }
        created = 0
        for invoice_doc in candidates:
            if created >= remaining:
                break
            enrollment_id = str(invoice_doc["enrollment_id"])
            eligibility = ladder_eligibility(
                invoice_status=invoice_doc.get("status"),
                balance_due_cents=int(invoice_doc.get("balance_due_cents") or 0),
                enrollment_id=enrollment_id,
                autopay_enrollment_status=(
                    AUTOPAY_ACTIVE_STATUS if enrollment_id in autopay_active else None
                ),
            )
            if not eligibility.eligible:
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
        # Due-ness is filtered in the query so we never stream the whole active
        # backlog: an active state is a candidate when its next_attempt_at has
        # passed, or when it is parked (next_attempt_at=None) for a retryable
        # recheck reason; a processing state only when its lease has expired.
        # The Python guards below re-check the same conditions on the decoded
        # state as a race-safe belt-and-braces before the CAS claim.
        cursor = self.collection.find(
            {
                "academy_id": academy_id,
                "$or": [
                    {"status": "active", "next_attempt_at": {"$lte": now}},
                    {
                        "status": "active",
                        "next_attempt_at": None,
                        "suppression_reason": {"$in": sorted(self.retryable_parked_reasons)},
                    },
                    {"status": "processing", "lease_expires_at": {"$lte": now}},
                ],
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
            if (
                enrollment is None
                or enrollment.get("autopay_enrollment_status") != AUTOPAY_ACTIVE_STATUS
            ):
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
            # issue #651: a voided or paid invoice has nothing left to collect,
            # so its ladder must not surface as a live autopay failure on
            # billing-health even if the state row was never suppressed.
            if str(invoice.get("status") or "") in {"void", "paid"}:
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

    async def suppress_for_invoice(self, *, invoice_id: str, reason: str, now: datetime) -> bool:
        """Stop the ladder for one invoice (voided / no longer collectable).

        Returns True when an active/processing/parked state was suppressed;
        False when the invoice has no ladder or it is already terminal.

        issue #651: a ``dunned`` (exhausted) ladder may still move to
        ``suppressed`` when ``reason == "invoice_voided"`` — voiding removes
        the debt, so the row must stop reading as an outstanding failure.
        ``resolved`` and already-``suppressed`` states are always left alone.
        """
        doc = await self.collection.find_one(
            {"academy_id": current_academy_id(), "invoice_id": invoice_id}
        )
        if doc is None:
            return False
        state = self._state_from_doc(doc)
        if state.status in {"suppressed", "resolved"}:
            return False
        if state.status == "dunned" and reason != "invoice_voided":
            return False
        await self._store_state(state.suppress(reason=reason, now=now))
        return True

    async def _store_state(self, state: DunningState) -> DunningState:
        await self.collection.update_one(
            {"academy_id": current_academy_id(), "invoice_id": state.invoice_id},
            {"$set": _mongo_doc(state)},
        )
        return state

    async def _latest_payment_attempt_status(self, invoice_id: str) -> str | None:
        """Latest CHARGE outcome for this invoice, or None.

        Pay-link mint failures (issue #426) share this collection but are not
        charge outcomes: a mint failure landing after a genuine ``succeeded``
        row would stop the sweep resolving an invoice that just paid, and keep
        escalating it toward the terminal autopay-disabled rung. Exclude them.
        """
        doc = await self._db["payment_attempts"].find_one(
            exclude_non_charge_attempts(
                {"academy_id": current_academy_id(), "invoice_id": invoice_id}
            ),
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
    return invoice_is_chargeable(
        invoice_doc.get("status"), int(invoice_doc.get("balance_due_cents") or 0)
    )
