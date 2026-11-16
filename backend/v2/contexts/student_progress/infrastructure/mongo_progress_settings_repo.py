"""The academy's progress settings, kept on its ``academies`` record (L5B).

One field, ``progress_settings``, written only by :meth:`set` with a targeted
``$set`` of that field, so a save on another settings panel (a whole-section
write elsewhere on the record) can never revert it, and this one never touches
theirs. No document means the defaults: milestones off, none configured.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.student_progress.domain.milestones import ProgressSettings
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.mongo import ensure_utc

FIELD = "progress_settings"


class MongoProgressSettingsRepository:
    def __init__(self, db: Any) -> None:
        self._academies = db["academies"]

    async def get(self) -> ProgressSettings:
        doc = await self._academies.find_one(
            {"academy_id": current_academy_id()}, projection={FIELD: 1}
        )
        stored = (doc or {}).get(FIELD)
        if not stored:
            return ProgressSettings()
        # Mongo hands datetimes back naive; ``since`` is compared with aware progress times.
        milestones = [
            {**m, "since": ensure_utc(m["since"])} for m in stored.get("milestones") or []
        ]
        return ProgressSettings.model_validate({**stored, "milestones": milestones})

    async def set(self, settings: ProgressSettings) -> None:
        await self._academies.update_one(
            {"academy_id": current_academy_id()},
            {"$set": {FIELD: settings.model_dump(mode="python")}},
        )
