"""AI usage meter composition (plan 2026-11-04 Phase 2, slice A3).

Attached at ``app.state.ai_usage``. The entitlement check is the platform
billing ``HasFeature`` use case, adapted to the academy in scope here so the
``ai`` context never imports ``platform``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.ai import AcademyAiCapLookup
from backend.v2.contexts.ai.application.use_cases.get_ai_usage import (
    GetAiUsage,
    GetAiUsageForAcademy,
)
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class ScopedHasFeature:
    """``EntitlementSource`` over ``HasFeature`` for the academy in scope."""

    def __init__(self, has_feature: Any) -> None:
        self._has_feature = has_feature

    async def has_feature(self, feature: str) -> bool:
        return bool(await self._has_feature.execute(current_academy_id(), feature))


@dataclass(frozen=True)
class AiUsageComposition:
    get_ai_usage: GetAiUsage
    get_ai_usage_for_academy: GetAiUsageForAcademy


def compose_ai_usage(db: Any, has_feature: Any) -> AiUsageComposition:
    academies = db["academies"]

    async def academy_exists(academy_id: str) -> bool:
        # Same existence probe as compose_platform_application_fee: legacy
        # academy docs that do not parse as a platform Tenant still exist.
        count: int = await academies.count_documents({"academy_id": academy_id}, limit=1)
        return count > 0

    usage = GetAiUsage(
        calls=MongoAiCallRepository(db),
        cap_source=AcademyAiCapLookup(MongoAcademyRepository(db)),
        entitlements=ScopedHasFeature(has_feature),
    )
    return AiUsageComposition(
        get_ai_usage=usage,
        get_ai_usage_for_academy=GetAiUsageForAcademy(usage=usage, academy_exists=academy_exists),
    )
