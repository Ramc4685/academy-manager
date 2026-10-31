"""The calling code an academy's bare national phone numbers belong to.

Phone numbers are stored as typed, so ``555-010-2030`` carries no country.
WhatsApp links need the full international number, and the People CRM folds
``5550102030`` and ``15550102030`` into one person, so both need to know which
country code a bare number implies.

It is derived at read time from ``academies.country`` (ISO code, the field
Stripe Connect already reads, #990): no stored setting and no migration. An
absent, blank or unmapped country gives ``"1"``, the North American code every
caller used before this existed, so an academy with no ``country`` (BLNO) is
unchanged. Only US academies can connect Stripe today, so ``US``/``CA`` are
the only codes mapped; add a country here when one is supported.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

log = logging.getLogger(__name__)

DEFAULT_CALLING_CODE: Final = "1"

_CALLING_CODES: Final[dict[str, str]] = {"US": "1", "CA": "1"}

AcademyCallingCodeReader = Callable[[str], Awaitable[str]]


def calling_code_for_country(country: object) -> str:
    """``"US"`` -> ``"1"``. Absent, blank or unmapped -> ``"1"``."""
    code = str(country).strip().upper() if country is not None else ""
    return _CALLING_CODES.get(code, DEFAULT_CALLING_CODE)


def academy_calling_code_lookup(db: Any) -> AcademyCallingCodeReader:
    """Reads one academy's ``country`` by id and maps it; never raises.

    A failed read degrades to the default: a missing WhatsApp link or a missed
    duplicate warning is worse than today's ``"1"``.
    """
    academies = db["academies"]

    async def calling_code(academy_id: str) -> str:
        try:
            doc = await academies.find_one({"academy_id": academy_id}, {"country": 1})
        except Exception:
            log.warning("academy country lookup failed for %r; using +1", academy_id, exc_info=True)
            return DEFAULT_CALLING_CODE
        return calling_code_for_country((doc or {}).get("country"))

    return calling_code
