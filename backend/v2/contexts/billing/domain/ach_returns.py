"""Provider-neutral ACH/Nacha return-code helpers."""

from __future__ import annotations

import re

_R_CODE_RE = re.compile(r"\bR([0-9]{2})\b", re.IGNORECASE)

_PROVIDER_FAILURE_TO_NACHA: dict[str, str] = {
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


def nacha_return_code_for_provider_failure(value: object) -> str | None:
    normalized = normalize_nacha_return_code(value)
    if normalized is not None:
        return normalized
    compact = str(value or "").lower().strip()
    return _PROVIDER_FAILURE_TO_NACHA.get(compact)
