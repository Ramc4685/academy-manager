from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    ProcessDunningRetries,
)
from backend.v2.contexts.billing.domain.dunning import open_initial_dunning_state
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _invoice(invoice_id: str = "inv-1") -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enr-1",
        period="2026-07",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 7, 1),
        created_at=NOW,
        updated_at=NOW,
    )


class _FakeDunningRepo:
    def __init__(self, invoice: LedgerInvoice) -> None:
        self.invoice = invoice
        self.state = open_initial_dunning_state(
            academy_id=invoice.academy_id,
            invoice_id=invoice.invoice_id,
            parent_id=invoice.parent_id,
            enrollment_id=invoice.enrollment_id,
            due_at=NOW,
            now=NOW,
        )
        self.prepared: list[datetime] = []
        self.finished = []
        self.notified: list[int] = []
        self.released = []
        self.parked: list[str] = []
        self.disable_results = []
        self.disable_pending: list = []
        self._claimed = False

    async def prepare_due_states(self, *, now: datetime, limit: int) -> int:
        self.prepared.append(now)
        return 1

    async def claim_next_due(self, *, now: datetime, worker_id: str):
        if self._claimed or self.state.status != "active" or self.state.next_attempt_at > now:
            return None
        self._claimed = True
        attempt_no = self.state.attempt_count + 1
        self.state = self.state.claim(attempt_no=attempt_no, worker_id=worker_id, now=now)
        return self.invoice, self.state

    async def list_terminal_disable_pending(self, *, limit: int):
        rows = self.disable_pending[:limit]
        self.disable_pending = self.disable_pending[limit:]
        return rows

    async def finish_attempt(self, *, state, succeeded: bool, failure_code: str | None, now):
        from backend.v2.contexts.billing.domain.dunning import record_dunning_attempt_result

        self.state = record_dunning_attempt_result(
            state,
            succeeded=succeeded,
            failure_code=failure_code,
            now=now,
        )
        self.finished.append((succeeded, failure_code, self.state.status))
        return self.state

    async def release_attempt(self, *, state, next_attempt_at: datetime, now):
        self.state = state.release(next_attempt_at=next_attempt_at, now=now)
        self.released.append((state.processing_attempt_no, next_attempt_at))
        return self.state

    async def park_attempt(self, *, state, reason: str, now):
        self.state = state.park(reason=reason, now=now)
        self.released.append((state.processing_attempt_no, None))
        self.parked.append(reason)
        return self.state

    async def mark_notification_sent(self, *, invoice_id: str, attempt_no: int, sent_at):
        self.notified.append(attempt_no)
        self.state = self.state.mark_notification_sent(attempt_no=attempt_no, now=sent_at)
        return self.state

    async def mark_autopay_disable_result(
        self,
        *,
        invoice_id: str,
        succeeded: bool,
        error: str | None,
        now,
    ):
        self.disable_results.append((invoice_id, succeeded, error))
        update = {
            "autopay_disable_status": "succeeded" if succeeded else "failed",
            "autopay_disable_error": error,
            "updated_at": now,
        }
        if succeeded:
            update["autopay_disabled_at"] = now
        self.state = self.state.model_copy(update=update)
        return self.state


class _FakeCharge:
    def __init__(
        self,
        *,
        success: bool,
        decline_code: str | None = None,
        requires_action: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self.success = success
        self.decline_code = decline_code
        self.requires_action = requires_action
        self.raises = raises
        self.calls: list[tuple[str, str | None]] = []

    async def execute(self, invoice_id: str, retry_scope: str | None = None):
        self.calls.append((invoice_id, retry_scope))
        if self.raises is not None:
            raise self.raises
        return {
            "success": self.success,
            "invoice_id": invoice_id,
            "status": "open" if not self.success else "paid",
            "balance_due_cents": 10_000 if not self.success else 0,
            "decline_code": self.decline_code,
            "requires_action": self.requires_action,
        }


class _FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_dunning_notice(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FakeEnrollmentAutopay:
    def __init__(self, *, result: bool = True, raises: Exception | None = None) -> None:
        self.disabled: list[str] = []
        self.result = result
        self.raises = raises

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
        if self.raises is not None:
            raise self.raises
        if status == "disabled":
            self.disabled.append(enrollment_id)
        return self.result


@pytest.mark.asyncio
async def test_worker_records_failed_retry_and_sends_one_parent_notification() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    charge = _FakeCharge(success=False, decline_code="insufficient_funds")
    notifier = _FakeNotifier()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=charge,
        notifier=notifier,
        enrollment_autopay=_FakeEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.processed == 1
    assert result.failed == 1
    assert charge.calls == [("inv-1", "dunning-attempt:1")]
    assert dunning.finished == [(False, "insufficient_funds", "active")]
    assert len(notifier.calls) == 1
    assert notifier.calls[0]["attempt_no"] == 1
    assert dunning.notified == [1]


@pytest.mark.asyncio
async def test_terminal_dunning_disables_autopay_after_max_attempts_only() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    dunning.state = dunning.state.model_copy(
        update={
            "attempt_count": 3,
            "first_attempt_at": NOW - timedelta(days=7),
            "last_attempt_at": NOW - timedelta(days=2),
            "next_attempt_at": NOW,
        }
    )
    enrollment_autopay = _FakeEnrollmentAutopay()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
        notifier=_FakeNotifier(),
        enrollment_autopay=enrollment_autopay,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.dunned == 1
    assert dunning.state.status == "dunned"
    assert enrollment_autopay.disabled == ["enr-1"]
    assert dunning.disable_results == [("inv-1", True, None)]


@pytest.mark.asyncio
async def test_worker_processing_result_does_not_increment_or_notify() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False),
        notifier=notifier,
        enrollment_autopay=_FakeEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.parked == 1
    assert result.failed == 0
    assert dunning.finished == []
    assert dunning.notified == []
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_worker_post_charge_exception_does_not_increment_or_notify() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, raises=RuntimeError("allocation write failed")),
        notifier=notifier,
        enrollment_autopay=_FakeEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.technical_failures == 1
    assert dunning.finished == []
    assert dunning.notified == []
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_worker_connect_account_not_ready_parks_without_parent_dunning() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()
    enrollment_autopay = _FakeEnrollmentAutopay()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="connected_account_not_ready"),
        notifier=notifier,
        enrollment_autopay=enrollment_autopay,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.parked == 1
    assert result.technical_failures == 1
    assert result.failed == 0
    assert dunning.finished == []
    assert dunning.parked == ["connected_account_not_ready"]
    assert dunning.notified == []
    assert notifier.calls == []
    assert enrollment_autopay.disabled == []


@pytest.mark.asyncio
async def test_terminal_disable_failure_is_recorded_and_retried() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    dunning.state = dunning.state.model_copy(
        update={
            "status": "dunned",
            "attempt_count": 4,
            "next_attempt_at": None,
            "terminal_at": NOW,
            "autopay_disable_status": "failed",
            "autopay_disable_error": "repo unavailable",
        }
    )
    dunning.disable_pending = [dunning.state]
    enrollment_autopay = _FakeEnrollmentAutopay(result=False)

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
        notifier=_FakeNotifier(),
        enrollment_autopay=enrollment_autopay,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.autopay_disable_failed == 1
    assert enrollment_autopay.disabled == ["enr-1"]
    assert dunning.disable_results == [("inv-1", False, "transition rejected")]


# ---------------------------------------------------------------------------
# The failure notice goes through the outbox (issue #435)
# ---------------------------------------------------------------------------


class _FakeOutbox:
    def __init__(self, raises: Exception | None = None) -> None:
        self.appended: list = []
        self.raises = raises

    async def append(self, event, *, session=None) -> None:
        if self.raises is not None:
            raise self.raises
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100) -> list:
        return []

    async def mark_processed(self, event_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_failure_notice_is_enqueued_not_sent_directly() -> None:
    """With an outbox wired, delivery (and its retries) belong to the
    dispatcher — the worker must not also send the mail itself, or a parent
    would get two notices for one failed attempt."""
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()
    outbox = _FakeOutbox()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
        notifier=notifier,
        enrollment_autopay=_FakeEnrollmentAutopay(),
        outbox=outbox,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.notifications_sent == 1
    assert notifier.calls == [], "the worker must not send directly when enqueuing"
    assert len(outbox.appended) == 1
    event = outbox.appended[0]
    assert event.name == "Billing.DunningNoticeRequested"
    assert event.academy_id == invoice.academy_id
    assert event.aggregate_id == invoice.invoice_id
    assert event.payload.attempt_no == 1
    assert event.payload.invoice_id == "inv-1"
    assert event.payload.terminal is False
    # Recorded on enqueue: this is what stops the next tick queuing a duplicate.
    assert dunning.notified == [1]


@pytest.mark.asyncio
async def test_reprocessing_the_same_attempt_does_not_enqueue_a_duplicate() -> None:
    """A worker that crashes after enqueuing but before finishing leaves the
    attempt to be processed again. ``notification_attempts`` is the guard that
    stops the parent getting a second copy of the same notice."""
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    outbox = _FakeOutbox()

    def _worker():
        return ProcessDunningRetries(
            dunning=dunning,
            charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
            notifier=_FakeNotifier(),
            enrollment_autopay=_FakeEnrollmentAutopay(),
            outbox=outbox,
            clock=lambda: NOW,
        )

    await _worker().execute(limit=5, worker_id="worker-1")
    assert len(outbox.appended) == 1

    # Rewind to *the same* attempt and let the worker claim it again.
    dunning._claimed = False
    dunning.state = dunning.state.model_copy(
        update={"status": "active", "attempt_count": 0, "next_attempt_at": NOW}
    )
    result = await _worker().execute(limit=5, worker_id="worker-1")

    assert len(outbox.appended) == 1, "the same attempt must not be notified twice"
    assert result.notifications_sent == 0
    assert dunning.notified == [1]


@pytest.mark.asyncio
async def test_a_failed_enqueue_is_counted_not_swallowed_as_sent() -> None:
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    outbox = _FakeOutbox(raises=RuntimeError("mongo down"))

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
        notifier=_FakeNotifier(),
        enrollment_autopay=_FakeEnrollmentAutopay(),
        outbox=outbox,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.notifications_sent == 0
    assert result.notifications_failed == 1
    # Not marked notified, so the next tick can try to enqueue it again.
    assert dunning.notified == []


@pytest.mark.asyncio
async def test_without_an_outbox_the_direct_send_is_unchanged() -> None:
    """Older wiring (and any deployment without the outbox) keeps working."""
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="insufficient_funds"),
        notifier=notifier,
        enrollment_autopay=_FakeEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.notifications_sent == 1
    assert len(notifier.calls) == 1


@pytest.mark.asyncio
async def test_open_checkout_session_parks_without_consuming_a_rung() -> None:
    """Issue #434: a parent paying manually must not also be charged by dunning.

    The charge use case refuses (checkout_session_open) because a Checkout Session is
    still open. That is our lock, not a decline: the ladder must not advance, the
    parent must not be emailed a dunning notice, and the attempt is re-tried on a
    later tick once the session settles or lapses.
    """
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    notifier = _FakeNotifier()
    enrollment_autopay = _FakeEnrollmentAutopay()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="checkout_session_open"),
        notifier=notifier,
        enrollment_autopay=enrollment_autopay,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.parked == 1
    assert result.failed == 0
    assert dunning.parked == ["checkout_session_open"]
    # Ladder untouched: no attempt recorded, no notice, autopay left alone.
    assert dunning.finished == []
    assert dunning.state.attempt_count == 0
    assert dunning.notified == []
    assert notifier.calls == []
    assert enrollment_autopay.disabled == []


@pytest.mark.asyncio
async def test_stripe_not_configured_parks_instead_of_disabling_autopay() -> None:
    """Issue #434: our misconfiguration must never spend a family's retry budget.

    The state is primed on the final rung, so a genuine card decline here would go
    terminal and disable autopay. stripe_not_configured is not a decline — the card
    was never charged — so it must park with the ladder and the family's autopay
    both left exactly as they were.
    """
    invoice = _invoice()
    dunning = _FakeDunningRepo(invoice)
    dunning.state = dunning.state.model_copy(
        update={
            "attempt_count": 3,
            "first_attempt_at": NOW - timedelta(days=7),
            "last_attempt_at": NOW - timedelta(days=2),
            "next_attempt_at": NOW,
        }
    )
    notifier = _FakeNotifier()
    enrollment_autopay = _FakeEnrollmentAutopay()

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=_FakeCharge(success=False, decline_code="stripe_not_configured"),
        notifier=notifier,
        enrollment_autopay=enrollment_autopay,
        clock=lambda: NOW,
    ).execute(limit=5, worker_id="worker-1")

    assert result.parked == 1
    assert result.dunned == 0
    assert result.failed == 0
    assert dunning.parked == ["stripe_not_configured"]
    # The family keeps their autopay and their last retry.
    assert enrollment_autopay.disabled == []
    assert dunning.disable_results == []
    assert dunning.state.status != "dunned"
    assert dunning.state.attempt_count == 3
    assert dunning.finished == []
    assert notifier.calls == []


def test_every_park_reason_is_re_claimable_by_the_repository() -> None:
    """A parked state has next_attempt_at=None and is only re-claimed if its reason is
    on the repository's allow-list. A reason missing from that list parks the invoice
    forever — it is never charged, never dunned, and never surfaces as failed. Keep the
    two in lockstep so a future park reason cannot silently strand collection."""
    from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
        _PARK_REASONS,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
        MongoDunningStateRepository,
    )

    stranded = _PARK_REASONS - MongoDunningStateRepository.retryable_parked_reasons
    assert not stranded, f"park reasons never re-claimed: {sorted(stranded)}"


class _RepeatClaimDunningRepo(_FakeDunningRepo):
    """Hands the same parked state back every time, like Mongo does.

    park() leaves next_attempt_at=None and claim_next_due sorts that column ascending,
    so a just-parked state is returned ahead of genuinely-due ones on the very next
    call within the same tick.
    """

    async def claim_next_due(self, *, now: datetime, worker_id: str):
        if self.state.status != "active":
            return None
        attempt_no = self.state.attempt_count + 1
        self.state = self.state.claim(attempt_no=attempt_no, worker_id=worker_id, now=now)
        return self.invoice, self.state


@pytest.mark.asyncio
async def test_a_parked_invoice_cannot_consume_the_whole_tick() -> None:
    """One parent mid-checkout must not starve every other due invoice.

    Without the repeat guard the worker claims, charges and re-parks the same held
    invoice `limit` times, so the invoices whose retry is actually due never get a turn.
    """
    invoice = _invoice()
    dunning = _RepeatClaimDunningRepo(invoice)
    charge = _FakeCharge(success=False, decline_code="checkout_session_open")

    result = await ProcessDunningRetries(
        dunning=dunning,
        charge_invoice=charge,
        notifier=_FakeNotifier(),
        enrollment_autopay=_FakeEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute(limit=50, worker_id="worker-1")

    # Charged (and counted) once, not once per loop iteration.
    assert charge.calls == [("inv-1", "dunning-attempt:1")]
    assert result.processed == 1
    assert result.parked == 1
    assert dunning.state.suppression_reason == "checkout_session_open"
    assert dunning.state.attempt_count == 0
