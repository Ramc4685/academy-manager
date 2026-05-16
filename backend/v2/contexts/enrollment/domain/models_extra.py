"""Additional Enrollment domain models used by Wave 2+ writes.

Wave 1A only needed read aggregates. WaitlistEntry is the FIFO unit for
waitlist promotion (data-ownership.md). SessionCapacity is a read view
used by capacity checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WaitlistStatus = Literal["waiting", "promoted", "skipped", "removed"]


class WaitlistEntry(BaseModel):
    model_config = {"frozen": True}

    waitlist_id: str
    academy_id: str
    session_id: str
    student_id: str
    parent_id: str
    joined_at: datetime
    status: WaitlistStatus = "waiting"
