"""Family billing "Autopay OFF": pause every active enrollment of one parent.

Spec ``2026-09-05-family-billing-design.md`` §5. Mirrors the Billing Setup
enable path (``composition/admin.py::enable_billing_setup_autopay``): the
target list is persisted under an idempotency key BEFORE any write so a retry
finishes the same plan, each enrollment goes through the ONE guarded status
write, and one audit entry records who/why. Invoices and dunning states are
untouched — the worker skips non-active enrollments on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.autopay_eligibility import AUTOPAY_ACTIVE_STATUS
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry

PAUSED_STATUS = "paused"


class NothingToPause(ValueError):
    """The parent has no enrollment with autopay ``active``."""


class FamilyAutopayEnrollments(Protocol):
    async def list_for_parent(self, parent_id: str) -> list[Any]: ...

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: Any) -> bool: ...


class AuditAppender(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class PauseFamilyAutopayResult:
    paused_count: int
    active_count_before: int
    warnings: list[str] = field(default_factory=list)


class PauseFamilyAutopay:
    def __init__(
        self,
        *,
        enrollments: FamilyAutopayEnrollments,
        audit: AuditAppender,
        idempotency: IdempotencyStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._audit = audit
        self._idempotency = idempotency
        self._clock = clock

    async def execute(
        self, *, academy_id: str, parent_id: str, actor_id: str, reason: str, request_id: str
    ) -> PauseFamilyAutopayResult:
        idem_key = f"family_autopay_pause:{academy_id}:{parent_id}:{request_id}"
        cached = await self._idempotency.get(idem_key)
        if cached is not None and "result" in cached:
            r = cached["result"]
            return PauseFamilyAutopayResult(
                int(r["paused_count"]), int(r["active_count_before"]), list(r.get("warnings", []))
            )

        if cached is None:
            rows = await self._enrollments.list_for_parent(parent_id)
            targets = sorted(
                r.enrollment_id
                for r in rows
                if r.autopay_enrollment_status == AUTOPAY_ACTIVE_STATUS
            )
            if not targets:
                raise NothingToPause("no_active_autopay: parent has no enrollment on autopay")
            plan = {"target_enrollment_ids": targets}
            try:
                await self._idempotency.put(idem_key, {"plan": plan})
            except DuplicateKeyError:
                cached = await self._idempotency.get(idem_key)
                if cached is None:
                    raise
                plan = cached["plan"]
        else:
            plan = cached["plan"]

        targets = list(plan["target_enrollment_ids"])
        paused: list[str] = []
        warnings: list[str] = []
        try:
            for enrollment_id in targets:
                ok = await self._enrollments.set_autopay_enrollment_status(
                    enrollment_id=enrollment_id, status=PAUSED_STATUS
                )
                if ok:
                    paused.append(enrollment_id)
                else:
                    warnings.append(f"{enrollment_id}: transition rejected")
        except Exception:
            # Money-movement rule: anything already flipped must be on the audit
            # trail before the error escapes, or an enrollment is silently off
            # autopay with no record of who did it. The deterministic audit_id
            # makes the retry's append a no-op.
            await self._append_audit(
                academy_id=academy_id,
                parent_id=parent_id,
                actor_id=actor_id,
                reason=reason,
                request_id=request_id,
                targets=targets,
                paused=paused,
            )
            raise

        await self._append_audit(
            academy_id=academy_id,
            parent_id=parent_id,
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
            targets=targets,
            paused=paused,
        )
        result = PauseFamilyAutopayResult(len(paused), len(targets), warnings)
        try:
            await self._idempotency.put(
                idem_key,
                {
                    "plan": plan,
                    "result": {
                        "paused_count": result.paused_count,
                        "active_count_before": result.active_count_before,
                        "warnings": warnings,
                    },
                },
            )
        except DuplicateKeyError:
            # Mongo store is insert-only; the plan key already exists. Replays
            # re-run the (idempotent) guarded writes and the deterministic audit id.
            pass
        return result

    async def _append_audit(
        self,
        *,
        academy_id: str,
        parent_id: str,
        actor_id: str,
        reason: str,
        request_id: str,
        targets: list[str],
        paused: list[str],
    ) -> None:
        """One entry per request (spec §5 step 3). The audit_id is derived from
        ``request_id``, so a replay — or the failure path calling this before
        re-raising — can never double-log."""
        await self._audit.append(
            BillingAuditEntry(
                audit_id=f"baud-family-autopay-pause-{academy_id}-{parent_id}-{request_id}",
                academy_id=academy_id,
                action="autopay_paused",
                actor_id=actor_id,
                at=self._clock(),
                parent_id=parent_id,
                reason=reason,
                before={"enrollment_ids": targets, "status": AUTOPAY_ACTIVE_STATUS},
                after={"enrollment_ids": paused, "status": PAUSED_STATUS},
            )
        )
