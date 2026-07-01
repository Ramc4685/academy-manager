"""ACH/Nacha return-code helpers.

Stripe can surface ACH returns through different event shapes depending on
timing and API version. Keep extraction permissive, but only return a Nacha
code when there is an explicit R-code or a known bank-failure synonym.
"""

from __future__ import annotations

import re
from typing import Any

_R_CODE_RE = re.compile(r"\bR([0-9]{2})\b", re.IGNORECASE)

_STRIPE_CODE_TO_NACHA: dict[str, str] = {
    "insufficient_funds": "R01",
    "bank_account_insufficient_funds": "R01",
    "account_closed": "R02",
    "bank_account_closed": "R02",
    "no_account": "R03",
    "bank_account_not_found": "R03",
    "bank_account_unusable": "R03",
    "debit_not_authorized": "R10",
    "bank_account_restricted": "R29",
}


def ach_return_code_from_stripe_object(obj: dict[str, Any]) -> str | None:
    """Extract a normalized Nacha return code from a Stripe event object."""
    for value in _candidate_values(obj):
        normalized = _normalize_code(value)
        if normalized is not None:
            return normalized
    return None


def _candidate_values(obj: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        obj.get("failure_code"),
        obj.get("failure_reason"),
        obj.get("reason"),
    ]
    metadata = obj.get("metadata")
    if isinstance(metadata, dict):
        values.extend(
            [
                metadata.get("ach_return_code"),
                metadata.get("return_code"),
                metadata.get("failure_code"),
            ]
        )
    last_error = obj.get("last_payment_error")
    if isinstance(last_error, dict):
        values.extend(
            [
                last_error.get("decline_code"),
                last_error.get("code"),
                last_error.get("message"),
            ]
        )
    outcome = obj.get("outcome")
    if isinstance(outcome, dict):
        values.extend([outcome.get("reason"), outcome.get("seller_message")])
    refunds = obj.get("refunds")
    if isinstance(refunds, dict):
        data = refunds.get("data")
        if isinstance(data, list):
            for refund in data:
                if isinstance(refund, dict):
                    values.extend(
                        [
                            refund.get("failure_reason"),
                            refund.get("reason"),
                            refund.get("metadata", {}).get("ach_return_code")
                            if isinstance(refund.get("metadata"), dict)
                            else None,
                        ]
                    )
    return values


def _normalize_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    direct = _R_CODE_RE.search(text.replace("_", " ").replace("-", " "))
    if direct is not None:
        return f"R{direct.group(1)}".upper()
    compact = text.lower().strip()
    if compact in _STRIPE_CODE_TO_NACHA:
        return _STRIPE_CODE_TO_NACHA[compact]
    return None
