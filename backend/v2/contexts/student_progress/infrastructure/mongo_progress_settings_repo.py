"""The academy's progress settings, kept on its ``academies`` record (L5B).

One field, ``progress_settings``, written only by :meth:`set` with a targeted
``$set`` of that field, so a save on another settings panel (a whole-section
write elsewhere on the record) can never revert it, and this one never touches
theirs. No document means the defaults: milestones off, none configured.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from backend.v2.contexts.student_progress.domain.milestones import ProgressSettings
from backend.v2.shared.observability.ops_alerts import capture_message
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
        try:
            # Mongo hands datetimes back naive; ``since`` is compared with aware times.
            milestones = [
                {**m, "since": ensure_utc(m["since"])} for m in stored.get("milestones") or []
            ]
            return ProgressSettings.model_validate({**stored, "milestones": milestones})
        except (ValidationError, KeyError, TypeError, AttributeError):
            # A bad stored record must not 500 the journey, the email or Settings:
            # read as off (the safe default) and page someone.
            logging.getLogger(__name__).warning(
                "progress_settings_unreadable; using defaults", exc_info=True
            )
            capture_message(
                f"Progress settings for academy {current_academy_id()} are unreadable; "
                "milestones read as off until an owner or admin saves them again",
                level="error",
            )
            return ProgressSettings()

    async def set(self, settings: ProgressSettings) -> None:
        await self._academies.update_one(
            {"academy_id": current_academy_id()},
            {"$set": {FIELD: settings.model_dump(mode="python")}},
        )
