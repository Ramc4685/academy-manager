"""The Billing Health verdict (spec 2026-09-07 §4.2).

The bug this module exists to remove: the page computed "System healthy" from
backlog counts alone, so an academy that could not take a single payment got a
green pill above a red card. `blocked` must outrank everything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.billing.application.billing_health import (
    BLOCKED_HEADLINE,
    CHECK_RECONCILIATION,
    CHECK_WEBHOOKS,
    OK_HEADLINE,
    REASON_CODES,
    HealthVerdict,
    LastReconciliationRun,
    evaluate_billing_health,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
FRESH_RUN = LastReconciliationRun(finished_at=NOW - timedelta(minutes=10))


def _evaluate(**overrides) -> HealthVerdict:
    kwargs = {
        "payments_possible": True,
        "connected_account_ready": True,
        "quarantined_webhooks": 0,
        "last_run": FRESH_RUN,
        "autopay_disable_failures": 0,
        "now": NOW,
    }
    kwargs.update(overrides)
    return evaluate_billing_health(**kwargs)  # type: ignore[arg-type]


def _codes(verdict: HealthVerdict) -> set[str]:
    return {reason.code for reason in verdict.reasons}


def test_everything_clean_is_ok() -> None:
    verdict = _evaluate()
    assert verdict.state == "ok"
    assert verdict.headline == OK_HEADLINE
    assert verdict.reasons == ()


def test_payments_impossible_is_blocked_even_with_an_empty_backlog() -> None:
    """The contradiction this spec removes.

    Empty backlog, fresh reconciliation run, nothing quarantined — and no
    parent can pay a cent. The old page-side computation called this healthy.
    """
    verdict = _evaluate(payments_possible=False, connected_account_ready=False)
    assert verdict.state == "blocked"
    assert verdict.headline == BLOCKED_HEADLINE
    assert _codes(verdict) == {"connect_not_ready"}


def test_blocked_outranks_attention() -> None:
    verdict = _evaluate(
        payments_possible=False,
        connected_account_ready=False,
        quarantined_webhooks=3,
        autopay_disable_failures=2,
        last_run=LastReconciliationRun(finished_at=NOW - timedelta(days=5), failed=4),
    )
    assert verdict.state == "blocked"
    assert verdict.headline == BLOCKED_HEADLINE
    # The reasons are still reported; only the state and headline are the
    # blocked ones.
    assert "connect_not_ready" in _codes(verdict)
    assert "webhooks_quarantined" in _codes(verdict)
    assert "autopay_disable_failed" in _codes(verdict)


def test_fallback_only_alone_stays_ok() -> None:
    """Funds routing to the platform is a deliberate setting, not a fault."""
    verdict = _evaluate(payments_possible=True, connected_account_ready=False)
    assert verdict.state == "ok"
    assert verdict.headline == OK_HEADLINE
    assert _codes(verdict) == {"fallback_only"}


def test_quarantined_webhooks_need_attention() -> None:
    verdict = _evaluate(quarantined_webhooks=7)
    assert verdict.state == "attention"
    assert verdict.headline == "Payments work, 1 thing needs attention"
    assert _codes(verdict) == {"webhooks_quarantined"}
    assert "7" in verdict.reasons[0].detail


def test_failed_reconciliation_run_needs_attention() -> None:
    verdict = _evaluate(last_run=LastReconciliationRun(finished_at=NOW, failed=2))
    assert verdict.state == "attention"
    assert _codes(verdict) == {"reconciliation_failed"}


def test_stale_reconciliation_needs_attention() -> None:
    verdict = _evaluate(last_run=LastReconciliationRun(finished_at=NOW - timedelta(hours=49)))
    assert verdict.state == "attention"
    assert _codes(verdict) == {"reconciliation_stale"}


def test_no_run_at_all_is_stale_not_healthy() -> None:
    assert _evaluate(last_run=None).state == "attention"
    assert _codes(_evaluate(last_run=None)) == {"reconciliation_stale"}
    unfinished = LastReconciliationRun(finished_at=None)
    assert _codes(_evaluate(last_run=unfinished)) == {"reconciliation_stale"}


def test_a_run_inside_the_window_is_not_stale() -> None:
    verdict = _evaluate(last_run=LastReconciliationRun(finished_at=NOW - timedelta(hours=47)))
    assert verdict.state == "ok"


def test_autopay_switch_off_failure_needs_attention() -> None:
    verdict = _evaluate(autopay_disable_failures=1)
    assert verdict.state == "attention"
    assert _codes(verdict) == {"autopay_disable_failed"}
    assert "1 invoice" in verdict.reasons[0].detail


def test_several_reasons_are_counted_in_the_headline() -> None:
    verdict = _evaluate(quarantined_webhooks=1, autopay_disable_failures=1)
    assert verdict.headline == "Payments work, 2 things need attention"


def test_informational_fallback_is_not_counted_in_the_headline() -> None:
    verdict = _evaluate(connected_account_ready=False, quarantined_webhooks=1)
    assert verdict.headline == "Payments work, 1 thing needs attention"
    assert _codes(verdict) == {"fallback_only", "webhooks_quarantined"}


def test_an_unavailable_check_never_claims_health() -> None:
    verdict = _evaluate(unavailable_checks=[CHECK_WEBHOOKS])
    assert verdict.state == "attention"
    assert verdict.headline == "Payments work, but the webhook backlog could not be checked"
    # A check that could not run contributes no reason code (§7).
    assert verdict.reasons == ()


def test_a_failed_reconciliation_read_does_not_report_a_stale_worker() -> None:
    """A read error is not evidence of a fault.

    ``last_run`` is None both when no run has ever finished and when the query
    failed. Treating the second as the first told the owner the reconciliation
    worker was dead whenever Mongo hiccuped — the same class of wrong verdict
    this module exists to remove.
    """
    verdict = _evaluate(last_run=None, unavailable_checks=[CHECK_RECONCILIATION])

    assert _codes(verdict) == set()
    assert verdict.state == "attention"
    assert verdict.headline == (
        "Payments work, but the reconciliation history could not be checked"
    )


def test_a_genuinely_absent_run_is_still_reported_as_stale() -> None:
    """The guard above must not swallow the real "no run yet" signal."""
    verdict = _evaluate(last_run=None)

    assert "reconciliation_stale" in _codes(verdict)
    assert verdict.state == "attention"


def test_every_emitted_code_is_declared() -> None:
    verdict = evaluate_billing_health(
        payments_possible=False,
        connected_account_ready=False,
        quarantined_webhooks=1,
        last_run=LastReconciliationRun(finished_at=NOW - timedelta(days=3), failed=1),
        autopay_disable_failures=1,
        now=NOW,
    )
    assert _codes(verdict) <= REASON_CODES
    assert _codes(verdict) == {
        "connect_not_ready",
        "webhooks_quarantined",
        "reconciliation_failed",
        "reconciliation_stale",
        "autopay_disable_failed",
    }


def test_verdict_serialises_for_the_readiness_response() -> None:
    payload = _evaluate(quarantined_webhooks=1).as_dict()
    assert payload["state"] == "attention"
    assert payload["reasons"] == [
        {"code": "webhooks_quarantined", "detail": payload["reasons"][0]["detail"]}
    ]
