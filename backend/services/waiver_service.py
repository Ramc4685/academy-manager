"""Waiver versioning helpers."""
import hashlib
from datetime import datetime, timezone


WAIVER_VERSION = "2026-05"
WAIVER_TEXT = "Participant is fit to play badminton and guardian accepts BLno Academy liability terms."
WAIVER_TEXT_HASH = hashlib.sha256(WAIVER_TEXT.encode("utf-8")).hexdigest()


def waiver_fields(accepted_by_user_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "waiver_accepted": True,
        "waiver_date": now,
        "waiver_accepted_at": now,
        "waiver_version": WAIVER_VERSION,
        "waiver_text_hash": WAIVER_TEXT_HASH,
        "waiver_accepted_by": accepted_by_user_id,
    }


async def record_waiver_acceptance(db, *, student_id: str, parent_user_id: str, accepted_by_user_id: str | None = None):
    await db.waiver_acceptances.insert_one({
        "student_id": student_id,
        "parent_user_id": parent_user_id,
        "accepted_by_user_id": accepted_by_user_id or parent_user_id,
        "waiver_version": WAIVER_VERSION,
        "waiver_text_hash": WAIVER_TEXT_HASH,
        "waiver_text": WAIVER_TEXT,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    })
