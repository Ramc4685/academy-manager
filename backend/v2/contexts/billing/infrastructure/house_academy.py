"""Which academy may charge on the PLATFORM Stripe account (the "house academy").

The platform Stripe account belongs to BLNO, which is both the platform owner
and its first tenant. BLNO's parents are charged directly on that account;
every other academy must charge through its own connected account, so a
tenant's refunds and disputes never land on the platform.

``billing_settings.allow_platform_charge_fallback`` used to be a per-academy
switch the academy OWNER could flip. It is now derived here, on read, from one
deploy-time setting (``HOUSE_ACADEMY_ID`` in fly.toml): true for the house
academy, false for everyone else. Changing it is a reviewed commit plus an
approved deploy, which is the audit trail.

When the setting is unset (local, staging, tests) the stored per-academy flag
is used unchanged, so existing seeds keep working.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_house_academy_id: str | None = None


def configure_house_academy(academy_id: str | None) -> None:
    """Set the house academy for this process. Called once at app start."""
    global _house_academy_id
    _house_academy_id = (academy_id or "").strip() or None
    if _house_academy_id:
        log.info("house_academy_configured academy_id=%s", _house_academy_id)
    else:
        log.warning(
            "house_academy_not_configured; billing_settings.allow_platform_charge_fallback "
            "is read as stored (legacy behaviour, local/staging only)"
        )


def house_academy_id() -> str | None:
    return _house_academy_id


def platform_charges_allowed(academy_id: str, stored_flag: bool) -> bool:
    """Whether ``academy_id`` may charge on the platform Stripe account."""
    if _house_academy_id is None:
        return bool(stored_flag)
    return academy_id == _house_academy_id
