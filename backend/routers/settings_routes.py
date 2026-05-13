"""Academy settings + payout basis + reset password etc."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from bson import ObjectId
from auth import require_roles, log_audit
from db import get_db

router = APIRouter()


class AcademySettingsIn(BaseModel):
    name: Optional[str] = None
    zelle_handle: Optional[str] = None
    reminder_template: Optional[str] = None  # supports {parent_name},{kid_names},{amount}
    currency: Optional[str] = None
    default_capacity: Optional[int] = None
    beginner_price: Optional[float] = None
    intermediate_price: Optional[float] = None
    advanced_price: Optional[float] = None


class PayoutBasisIn(BaseModel):
    coach_id: str
    basis: str  # "collected" | "expected"


DEFAULTS = {
    "name": "BLno Badminton Academy",
    "zelle_handle": "248-885-9243",
    "reminder_template": (
        "Hi {parent_name}, friendly reminder — ${amount} pending for "
        "{kid_names}'s badminton training. Please send via Zelle to {zelle_handle}. "
        "Thanks! — BLno Academy"
    ),
    "currency": "USD",
    "default_capacity": 15,
    "beginner_price": 60,
    "intermediate_price": 70,
    "advanced_price": 80,
}


@router.get("/settings")
async def get_settings(admin=Depends(require_roles("admin"))):
    db = get_db()
    doc = await db.academy_settings.find_one({"_id": "singleton"})
    if not doc:
        await db.academy_settings.insert_one({"_id": "singleton", **DEFAULTS,
                                              "created_at": datetime.now(timezone.utc).isoformat()})
        return DEFAULTS
    doc.pop("_id", None)
    # Apply defaults for missing keys
    for k, v in DEFAULTS.items():
        doc.setdefault(k, v)
    return doc


@router.patch("/settings")
async def update_settings(body: AcademySettingsIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.academy_settings.update_one({"_id": "singleton"}, {"$set": update}, upsert=True)
    await log_audit(admin, "update", "settings", "singleton", str(list(update.keys())))
    return {"ok": True}


@router.post("/settings/payout-basis")
async def set_payout_basis(body: PayoutBasisIn, admin=Depends(require_roles("admin"))):
    if body.basis not in ("collected", "expected"):
        raise HTTPException(status_code=400, detail="basis must be 'collected' or 'expected'")
    db = get_db()
    # Update the active rule for this coach
    await db.payout_rules.update_many(
        {"coach_id": body.coach_id, "is_active": True},
        {"$set": {"basis": body.basis}},
    )
    await log_audit(admin, "set_basis", "payout_rule", body.coach_id, body.basis)
    return {"ok": True}
