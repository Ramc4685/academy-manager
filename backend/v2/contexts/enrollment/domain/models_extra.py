"""Additional Enrollment domain models used by Wave 2+ writes.

Wave 1A only needed read aggregates. WaitlistEntry is the FIFO unit for
waitlist promotion (data-ownership.md). SessionCapacity is a read view
used by capacity checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

#: Issue #828 — a freed seat is now OFFERED for a confirmation window rather
#: than seated instantly. ``offered`` means the seat is held (reserved on the
#: session) and ``offer_expires_at`` is stamped; ``expired`` means the window
#: closed unconfirmed and the seat went to the next family. Mongo's validator
#: for this enum lives in migration 0133 and is widened by 0183.
WaitlistStatus = Literal["waiting", "offered", "promoted", "expired", "skipped", "removed"]


class WaitlistEntry(BaseModel):
    model_config = {"frozen": True}

    waitlist_id: str
    academy_id: str
    session_id: str
    student_id: str
    parent_id: str
    joined_at: datetime
    status: WaitlistStatus = "waiting"
    #: Set only while ``status == "offered"`` (#828): the instant the held seat
    #: is released back to the next family if nobody confirms.
    offer_expires_at: datetime | None = None
    #: X2 (owner decision 2026-09-25): ``False`` for an offer made while the
    #: class was full only of holds. No seat is taken — and no held family is
    #: dropped — until the family confirms; ``ConfirmWaitlistOffer`` then gets
    #: the seat through the ``SeatBroker``. Rows written before X2 held a seat.
    offer_holds_seat: bool = True
