"""The one Billing Health verdict.

Spec: ``docs/superpowers/specs/2026-09-07-billing-health-trim-design.md`` §4.

The page used to compute "System healthy" from backlog counts alone
(``failedRows.length === 0 && activeDunningRows.length === 0 &&
quarantined.length === 0``), which ignored ``payments_possible`` entirely: an
academy with no connected Stripe account and the platform fallback off — where
no parent can pay anything — rendered a green pill directly above a red card
reading "Parents cannot pay right now". It also counted quarantined webhooks
from a list capped at 50.

So the verdict is computed here, once, from the same aggregate counts the tiles
show, and the page renders it without recomputing anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

#: A reconciliation run older than this (or no run at all) is stale: the
#: scheduler ticks every 10 minutes, so two days of silence is a dead worker,
#: not a quiet one.
RECONCILIATION_STALE_AFTER = timedelta(hours=48)

HealthState = Literal["blocked", "attention", "ok"]

#: Every reason code the verdict can emit. ``fallback_only`` is informational:
#: money routing to the platform account is a deliberate setting, not a fault,
#: so it never raises the state on its own.
REASON_CODES: frozenset[str] = frozenset(
    {
        "connect_not_ready",
        "fallback_only",
        "webhooks_quarantined",
        "reconciliation_failed",
        "reconciliation_stale",
        "autopay_disable_failed",
    }
)

INFORMATIONAL_REASON_CODES: frozenset[str] = frozenset({"fallback_only"})

BLOCKED_HEADLINE = "Parents cannot pay right now"
OK_HEADLINE = "Stripe is healthy"

#: The names a caller passes in ``unavailable_checks`` when a read failed.
#: They are constants rather than inline strings because the verdict has to
#: recognise a failed reconciliation read: without that, a read error looks
#: exactly like "no run has ever finished" and the owner is told the worker is
#: dead when only the query failed.
CHECK_WEBHOOKS = "the webhook backlog"
CHECK_RECONCILIATION = "the reconciliation history"
CHECK_AUTOPAY_DISABLE = "the autopay switch-off backlog"


@dataclass(frozen=True)
class HealthReason:
    code: str
    detail: str


@dataclass(frozen=True)
class HealthVerdict:
    state: HealthState
    headline: str
    reasons: tuple[HealthReason, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "headline": self.headline,
            "reasons": [{"code": r.code, "detail": r.detail} for r in self.reasons],
        }


@dataclass(frozen=True)
class LastReconciliationRun:
    """The single run fact the verdict needs: when it ended and whether it failed."""

    finished_at: datetime | None
    failed: int = 0
    quarantined: int = 0


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def evaluate_billing_health(
    *,
    payments_possible: bool,
    connected_account_ready: bool,
    quarantined_webhooks: int,
    last_run: LastReconciliationRun | None,
    autopay_disable_failures: int,
    now: datetime,
    unavailable_checks: Sequence[str] = (),
) -> HealthVerdict:
    """One verdict for the Billing Health header.

    ``blocked`` outranks ``attention``: an academy that cannot take money is
    never described as merely needing attention, however clean its backlog is.
    Reasons found while blocked are still listed — the owner should see the
    whole picture — but they do not change the state or the headline.

    ``unavailable_checks`` names the sections whose read failed (§7). They
    contribute no reason code, but they stop the verdict claiming health: a
    check that could not run is not a check that passed.
    """

    reasons: list[HealthReason] = []

    if not payments_possible:
        reasons.append(
            HealthReason(
                "connect_not_ready",
                "No Stripe account is ready to take charges and the platform "
                "fallback is off, so no parent payment can succeed.",
            )
        )
    elif not connected_account_ready:
        # Informational only: charges succeed, they just land on the platform
        # account instead of the academy's, which is what the setting asks for.
        reasons.append(
            HealthReason(
                "fallback_only",
                "Charges succeed through the platform fallback, so money lands "
                "on the platform account rather than the academy's.",
            )
        )

    attention: list[HealthReason] = []

    if quarantined_webhooks > 0:
        attention.append(
            HealthReason(
                "webhooks_quarantined",
                f"{quarantined_webhooks} quarantined webhook "
                f"{_plural(quarantined_webhooks, 'event', 'events')} "
                "have not been applied.",
            )
        )

    checks = [c for c in unavailable_checks if c]
    reconciliation_checked = CHECK_RECONCILIATION not in checks

    if not reconciliation_checked:
        # The read failed, so we know nothing about the worker. Saying "no run
        # has finished" here would be the same class of wrong verdict this
        # module exists to remove: it names a fault we did not observe.
        pass
    elif last_run is None or last_run.finished_at is None:
        attention.append(
            HealthReason(
                "reconciliation_stale",
                "No reconciliation run has finished yet.",
            )
        )
    else:
        if last_run.failed > 0:
            attention.append(
                HealthReason(
                    "reconciliation_failed",
                    f"The last reconciliation run failed on {last_run.failed} "
                    f"{_plural(last_run.failed, 'payment', 'payments')}.",
                )
            )
        if now - last_run.finished_at > RECONCILIATION_STALE_AFTER:
            attention.append(
                HealthReason(
                    "reconciliation_stale",
                    "The last reconciliation run finished more than 48 hours ago.",
                )
            )

    if autopay_disable_failures > 0:
        attention.append(
            HealthReason(
                "autopay_disable_failed",
                f"Autopay switch-off failed for {autopay_disable_failures} "
                f"{_plural(autopay_disable_failures, 'invoice', 'invoices')}; "
                "the card may still be attached in Stripe.",
            )
        )

    reasons.extend(attention)

    if not payments_possible:
        return HealthVerdict("blocked", BLOCKED_HEADLINE, tuple(reasons))

    if attention:
        count = len(attention)
        headline = (
            f"Payments work, {count} {_plural(count, 'thing', 'things')} "
            f"{_plural(count, 'needs', 'need')} attention"
        )
        return HealthVerdict("attention", headline, tuple(reasons))

    if checks:
        # Not "healthy": a check that could not run has not passed.
        headline = f"Payments work, but {', '.join(checks)} could not be checked"
        return HealthVerdict("attention", headline, tuple(reasons))

    return HealthVerdict("ok", OK_HEADLINE, tuple(reasons))
