"""ParentSelfServicePolicy — academy-scoped parent self-service configuration.

Pure domain model. No infra imports. Governs absence notices, makeup
requests, and self-cancel behavior for parent-facing self-service flows
(R1/R2/R4). Defaults are conservative: notice windows and fees are set to
sane defaults an academy can tune from the admin BFF.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ParentSelfServicePolicy(BaseModel):
    """Academy-scoped policy governing parent self-service actions."""

    academy_id: str
    absence_notice_min_hours: int = 2  # R1 notice window
    makeup_expiry_days: int = 30  # R2 expiry window
    makeup_requires_notice: bool = True
    cancellation_minimum_notice_days: int = 7  # R4
    cancellation_fee_cents: int = 0  # R4, flat
    cancellation_effective_timing: Literal["immediate", "end_of_period"] = "end_of_period"

    @staticmethod
    def default(academy_id: str) -> ParentSelfServicePolicy:
        return ParentSelfServicePolicy(academy_id=academy_id)
