"""Provider-neutral ACH/Nacha return-code helpers."""

from __future__ import annotations

import re
from typing import Literal

_R_CODE_RE = re.compile(r"\bR([0-9]{2})\b", re.IGNORECASE)


def normalize_nacha_return_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    direct = _R_CODE_RE.search(text.replace("_", " ").replace("-", " "))
    if direct is not None:
        return f"R{direct.group(1)}".upper()
    return None


AchDisposition = Literal["retry", "stop"]

#: Owner decision 2026-11-15: insufficient funds retries (at most twice); a
#: closed, invalid or unauthorized account never does. Every other bank failure
#: also stops: re-debiting an account we know is broken costs the parent fees.
_RETRY_CODES = frozenset({"insufficient_funds", "bank_account_insufficient_funds"})
_RETRY_R_CODES = frozenset({"R01", "R09"})
_STOP_CODES = frozenset(
    {
        "account_closed",
        "bank_account_closed",
        "no_account",
        "bank_account_not_found",
        "bank_account_invalid_details",
        "bank_account_unusable",
        "bank_account_frozen",
        "bank_account_restricted",
        "debit_not_authorized",
        "recipient_deceased",
        "tokenized_account_number_deactivated",
        "bank_cannot_process",
        "incorrect_account_details",
    }
)

#: ACH retry spacing, counted from when the failure is REPORTED (a return lands
#: about four business days after the debit, so counting from the first attempt
#: would re-debit at once). First debit + 2 retries.
ACH_RETRY_DELAY_DAYS = (3, 7)
ACH_MAX_ATTEMPTS = 1 + len(ACH_RETRY_DELAY_DAYS)


def ach_failure_disposition(code: object) -> AchDisposition | None:
    """How a bank-debit failure moves the ladder; None when ``code`` is not a bank
    failure (a card decline keeps the card ladder)."""
    text = str(code or "").strip().lower()
    if not text:
        return None
    if text in _RETRY_CODES:
        return "retry"
    if text in _STOP_CODES:
        return "stop"
    r_code = normalize_nacha_return_code(code)
    if r_code is None:
        return None
    return "retry" if r_code in _RETRY_R_CODES else "stop"
