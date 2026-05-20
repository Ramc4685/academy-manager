"""Parent onboarding backend — Phase 5 Slices 2 & 3.

Provides:
  POST   /onboarding/start
  PATCH  /onboarding/{id}
  GET    /onboarding/{id}/status
  POST   /onboarding/{id}/checkout   <- Slice 3

Status constants:
  DRAFT                         -> Slice 2
  CHECKOUT_PENDING              -> Slice 3
  CHECKOUT_EXPIRED              -> Slice 3
  PAYMENT_PROCESSING            -> Slice 3
  PENDING_APPROVAL              -> Slice 3
  CAPACITY_FAILED_REFUNDING     -> Slice 3
  CAPACITY_FAILED_REFUND_FAILED -> Slice 3
  REFUNDED                      -> Slice 3
  FAILED                        -> Slice 3
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import get_current_user
from db import get_db
from routers.billing_routes import _configure_stripe
from services.billing_proration import persist_legacy_snapshot, prorated_first_month_quote
from services.enrollment_service import capacity_snapshot, get_enrollable_session

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

DRAFT = "draft"
CHECKOUT_PENDING = "checkout_pending"
CHECKOUT_EXPIRED = "checkout_expired"
PAYMENT_PROCESSING = "payment_processing"
PENDING_APPROVAL = "pending_approval"
CAPACITY_FAILED_REFUNDING = "capacity_failed_refunding"
CAPACITY_FAILED_REFUND_FAILED = "capacity_failed_refund_failed"
REFUNDED = "refunded"
FAILED = "failed"

# ---------------------------------------------------------------------------
# Waiver seed
# ---------------------------------------------------------------------------

WAIVER_VERSION = "2026.1"

WAIVER_TEXT = (
    "YOUTH SPORTS LIABILITY WAIVER AND RELEASE OF LIABILITY\n\n"
    "This Waiver and Release of Liability ('Agreement') is entered into by the "
    "undersigned parent or legal guardian ('Guardian') on behalf of the minor "
    "participant named in this enrollment ('Participant').\n\n"
    "1. ASSUMPTION OF RISK. Guardian acknowledges that participation in badminton "
    "training and related activities ('Activities') involves inherent risks, including "
    "but not limited to: physical injury, muscle strains, sprains, fractures, "
    "concussions, and in rare cases, serious injury or death. Guardian voluntarily "
    "assumes all such risks on behalf of the Participant, whether foreseen or "
    "unforeseen, known or unknown.\n\n"
    "2. RELEASE AND INDEMNIFICATION. In consideration of the Participant's enrollment, "
    "Guardian hereby releases, waives, discharges, and covenants not to sue the "
    "Academy, its officers, directors, coaches, employees, volunteers, agents, and "
    "assigns (collectively 'Released Parties') from any and all liability, claims, "
    "demands, actions, or causes of action arising out of or related to any loss, "
    "damage, or injury, including death, that may be sustained by the Participant "
    "during or as a consequence of participation in the Activities. Guardian agrees "
    "to indemnify, defend, and hold harmless the Released Parties from any claims "
    "brought by or on behalf of the Participant or Guardian.\n\n"
    "3. MEDICAL AUTHORIZATION. Guardian authorizes the Released Parties to obtain "
    "emergency medical treatment for the Participant if Guardian cannot be reached "
    "in a timely manner. Guardian acknowledges responsibility for all medical costs "
    "and authorizes release of medical information to treating providers as necessary. "
    "Guardian warrants that the Participant is physically fit to participate in the "
    "Activities and has disclosed all relevant medical conditions.\n\n"
    "4. PHOTO AND MEDIA RELEASE. Guardian grants the Academy a non-exclusive, "
    "royalty-free license to use photographs, video recordings, and other likeness "
    "of the Participant taken during Activities for promotional, educational, and "
    "documentation purposes, including on the Academy's website and social media "
    "channels, without further compensation or notice.\n\n"
    "5. GOVERNING LAW. This Agreement shall be governed by the laws of the "
    "jurisdiction in which the Academy is located. If any provision of this Agreement "
    "is found to be unenforceable, the remaining provisions shall remain in full "
    "force and effect. This Agreement constitutes the entire understanding between "
    "the parties regarding liability for the Activities and supersedes all prior "
    "oral or written agreements on the subject matter herein.\n\n"
    "By accepting this waiver electronically, Guardian represents that they have "
    "read and understood this Agreement, are at least 18 years of age, and are the "
    "legal guardian of the Participant named in this enrollment."
)

WAIVER_CONTENT_HASH = hashlib.sha256(WAIVER_TEXT.encode("utf-8")).hexdigest()


async def seed_waiver_version(db=None) -> None:
    """Idempotently insert the current waiver version into waiver_versions.

    Safe to call multiple times — uses update_one with upsert so no duplicate
    will be inserted even if called concurrently at startup.
    """
    if db is None:
        db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.waiver_versions.update_one(
        {"version": WAIVER_VERSION},
        {
            "$setOnInsert": {
                "version": WAIVER_VERSION,
                "text": WAIVER_TEXT,
                "content_hash": WAIVER_CONTENT_HASH,
                "effective_from": now,
                "created_at": now,
            }
        },
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str_id(doc: dict) -> dict:
    """Return a copy of *doc* with ``_id`` converted to string ``id``."""
    out = dict(doc)
    out["id"] = str(out.pop("_id"))
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


def _child_identity(profile: dict[str, Any]) -> tuple[str, str]:
    return (str(profile.get("name", "")), str(profile.get("dob", "")))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WaiverAcceptanceBody(BaseModel):
    version: str
    accepted: bool


class PatchBody(BaseModel):
    parent_profile: dict[str, Any] | None = None
    child_profile: dict[str, Any] | None = None
    selected_session_id: str | None = None
    waiver_acceptance: WaiverAcceptanceBody | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

_ALLOWED_PARENT_KEYS = {"phone", "address", "emergency_contact", "emergency_phone"}
_ALLOWED_CHILD_KEYS = {"name", "dob", "medical_notes", "consent_to_treat"}


@router.get("/waiver/current")
async def get_current_waiver(
    current_user: dict = Depends(get_current_user),
):
    """Return the most-recent active waiver version (effective_from <= now).

    Authenticated parents use this to fetch the canonical waiver text before
    accepting. The frontend must render this text and send the ``version`` field
    back in the PATCH waiver_acceptance payload.
    """
    db = get_db()
    now_iso = _now_iso()

    # Find the most-recent effective waiver (effective_from <= now), desc order.
    cursor = db.waiver_versions.find(
        {"effective_from": {"$lte": now_iso}}
    ).sort("effective_from", -1).limit(1)
    docs = await cursor.to_list(length=1)

    if not docs:
        raise HTTPException(status_code=404, detail="No active waiver version found")

    doc = docs[0]
    return {
        "version": doc["version"],
        "content": doc["text"],
        "content_hash": doc["content_hash"],
        "effective_from": doc["effective_from"],
    }


@router.post("/start")
async def start_onboarding(
    current_user: dict = Depends(get_current_user),
):
    """Create (or return existing) draft onboarding application for the caller."""
    db = get_db()
    parent_user_id = current_user["id"]

    existing = await db.onboarding_applications.find_one(
        {"parent_user_id": parent_user_id, "status": DRAFT}
    )
    if existing:
        return _str_id(existing)

    now = _now_iso()
    doc = {
        "parent_user_id": parent_user_id,
        "parent_email": current_user["email"],
        "status": DRAFT,
        "parent_profile": {},
        "child_profile": {},
        "selected_session_id": None,
        "waiver_acceptance": None,
        "stripe_checkout_session_id": None,
        "expires_at": _expires_at(),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.onboarding_applications.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _str_id(doc)


@router.patch("/{app_id}")
async def patch_onboarding(
    app_id: str,
    body: PatchBody,
    current_user: dict = Depends(get_current_user),
):
    """Partially update a draft onboarding application."""
    db = get_db()

    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Application not found")

    app_doc = await db.onboarding_applications.find_one({"_id": oid})
    if app_doc is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if app_doc["parent_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    if app_doc["status"] != DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Application is no longer in draft status and cannot be modified",
        )

    updates: dict[str, Any] = {}

    if body.parent_profile is not None:
        filtered = {
            k: v for k, v in body.parent_profile.items()
            if k in _ALLOWED_PARENT_KEYS
        }
        merged = {**app_doc.get("parent_profile", {}), **filtered}
        updates["parent_profile"] = merged

    if body.child_profile is not None:
        previous_child_profile = app_doc.get("child_profile", {})
        filtered = {
            k: v for k, v in body.child_profile.items()
            if k in _ALLOWED_CHILD_KEYS
        }
        merged = {**app_doc.get("child_profile", {}), **filtered}
        updates["child_profile"] = merged
        if (
            app_doc.get("waiver_acceptance")
            and body.waiver_acceptance is None
            and _child_identity(merged) != _child_identity(previous_child_profile)
        ):
            updates["waiver_acceptance"] = None

    if body.selected_session_id is not None:
        updates["selected_session_id"] = body.selected_session_id

    if body.waiver_acceptance is not None:
        wa = body.waiver_acceptance
        if not wa.accepted:
            raise HTTPException(
                status_code=400,
                detail="waiver_acceptance.accepted must be true",
            )
        waiver_version_doc = await db.waiver_versions.find_one({"version": wa.version})
        if waiver_version_doc is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown waiver version: {wa.version!r}",
            )

        # Derive a stable child_id from name+dob (child docs not yet created)
        child_profile = updates.get("child_profile", app_doc.get("child_profile", {}))
        child_id_raw = (
            str(child_profile.get("name", "")) + "|" + str(child_profile.get("dob", ""))
        )
        child_id = hashlib.sha256(child_id_raw.encode("utf-8")).hexdigest()[:24]

        now_iso = _now_iso()
        await db.waiver_acceptances.update_one(
            {
                "parent_user_id": current_user["id"],
                "child_id": child_id,
                "waiver_version": wa.version,
            },
            {
                "$setOnInsert": {
                    "parent_user_id": current_user["id"],
                    "child_id": child_id,
                    "waiver_version": wa.version,
                    "content_hash": waiver_version_doc["content_hash"],
                    "waiver_text_hash": waiver_version_doc["content_hash"],
                    "waiver_text": waiver_version_doc["text"],
                    "text_snapshot": waiver_version_doc["text"],
                    "accepted_at": now_iso,
                }
            },
            upsert=True,
        )
        updates["waiver_acceptance"] = {
            "version": wa.version,
            "accepted": True,
            "accepted_at": now_iso,
            "child_id": child_id,
            "waiver_text_hash": waiver_version_doc["content_hash"],
        }

    if updates:
        updates["updated_at"] = _now_iso()
        await db.onboarding_applications.update_one(
            {"_id": oid}, {"$set": updates}
        )

    refreshed = await db.onboarding_applications.find_one({"_id": oid})
    return _str_id(refreshed)


@router.get("/{app_id}/status")
async def get_onboarding_status(
    app_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return a minimal polling-friendly status payload."""
    db = get_db()

    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Application not found")

    app_doc = await db.onboarding_applications.find_one({"_id": oid})
    if app_doc is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if app_doc["parent_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    child_name = app_doc.get("child_profile", {}).get("name")
    return {
        "id": str(app_doc["_id"]),
        "status": app_doc["status"],
        "selected_session_id": app_doc.get("selected_session_id"),
        "child_name": child_name,
        "updated_at": app_doc.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Slice 3 helpers
# ---------------------------------------------------------------------------


def _frontend_url() -> str:
    """Return the configured frontend base URL, defaulting to production."""
    return os.environ.get("FRONTEND_URL", "https://academy.courtmastr.com").rstrip("/")


# ---------------------------------------------------------------------------
# POST /onboarding/{id}/checkout
# ---------------------------------------------------------------------------


@router.post("/{app_id}/checkout")
async def create_onboarding_checkout(
    app_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Create a Stripe Checkout Session (mode=payment) for a draft onboarding application.

    Validates ownership, draft status, required fields, and advisory capacity.
    Does NOT reserve a seat — the webhook is the authoritative source.

    Stripe session expires_at is left at Stripe's default (~30 minutes from now),
    which aligns with the intent of keeping a short checkout window. The Stripe
    default avoids a separate 30-min delta calculation and is documented here as
    the intentional choice.
    """
    db = get_db()

    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Application not found")

    app_doc = await db.onboarding_applications.find_one({"_id": oid})
    if app_doc is None:
        raise HTTPException(status_code=404, detail="Application not found")

    # Owner-only check
    if app_doc["parent_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Must be in DRAFT status
    if app_doc["status"] != DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"Checkout only allowed in draft status; current status is {app_doc['status']!r}",
        )

    # Validate required fields
    if not app_doc.get("waiver_acceptance"):
        raise HTTPException(status_code=400, detail="waiver_acceptance is required before checkout")

    child_profile = app_doc.get("child_profile") or {}
    if not child_profile.get("name") or not child_profile.get("dob"):
        raise HTTPException(
            status_code=400,
            detail="child_profile.name and child_profile.dob are required before checkout",
        )

    if not app_doc.get("selected_session_id"):
        raise HTTPException(status_code=400, detail="selected_session_id is required before checkout")

    # Validate Stripe configured
    stripe = _configure_stripe()

    session_id = app_doc["selected_session_id"]

    # Load session doc for price and capacity advisory check
    if not ObjectId.is_valid(session_id):
        raise HTTPException(status_code=400, detail="selected_session_id is not a valid id")
    try:
        session_doc = await get_enrollable_session(db, session_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=400, detail="Selected session not found")
        raise

    # Advisory pre-check capacity (not authoritative — webhook does the atomic reserve)
    snapshot = await capacity_snapshot(db, session_doc)
    if snapshot["is_full"]:
        return JSONResponse(
            status_code=409,
            content={"error": "session_full", "detail": "The selected session is currently full"},
        )

    now = datetime.now(timezone.utc)
    quote = prorated_first_month_quote(
        session=session_doc,
        enrollment={
            "_id": app_id,
            "session_id": session_id,
            "parent_user_id": app_doc["parent_user_id"],
            "created_at": now.isoformat(),
        },
        period=now.strftime("%Y-%m"),
        calculated_at=now,
        calculated_by=app_doc["parent_user_id"],
    )
    snapshot_id = None
    if quote is not None:
        amount = quote.final_amount_cents / 100
        snapshot_id = await persist_legacy_snapshot(
            db,
            quote=quote,
            enrollment={
                "_id": app_id,
                "session_id": session_id,
                "parent_user_id": app_doc["parent_user_id"],
            },
            session=session_doc,
            period=now.strftime("%Y-%m"),
        )
        if amount <= 0:
            # Proration legitimately yielded $0 (e.g., enrollment on last day of month
            # with all classes within the free-class cutoff). Stripe rejects $0 line items
            # so we cannot create a checkout session. Return a 422 explaining the situation
            # rather than the misleading 400 about monthly_price.
            # TODO: implement a no-charge direct-enrollment path to allow these enrollments.
            next_month = (now.replace(day=1) + __import__("datetime").timedelta(days=32)).replace(day=1)
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Prorated first-month charge is $0 (no billable class occurrences "
                    f"remain in {now.strftime('%B %Y')}). "
                    f"Please re-enroll on or after {next_month.strftime('%Y-%m-%d')}."
                ),
            )
    else:
        try:
            amount = float(session_doc.get("monthly_price") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Session monthly price must be greater than zero")

    frontend_url = _frontend_url()
    success_url = f"{frontend_url}/onboarding/{app_id}/status?checkout=success"
    cancel_url = f"{frontend_url}/onboarding/{app_id}/status?checkout=cancel"

    metadata = {
        "onboarding_id": app_id,
        "parent_user_id": app_doc["parent_user_id"],
        "session_id": session_id,
        "calculation_snapshot_id": snapshot_id or "",
        "kind": "onboarding",
    }

    stripe_session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Academy first-month fee — {session_doc.get('name', '')}".strip(" —")},
                "unit_amount": int(round(amount * 100)),
            },
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=current_user["email"],
        metadata=metadata,
    )

    # Persist and transition status
    now = _now_iso()
    await db.onboarding_applications.update_one(
        {"_id": oid},
        {"$set": {
            "stripe_checkout_session_id": stripe_session.id,
            "status": CHECKOUT_PENDING,
            "updated_at": now,
        }},
    )

    return {
        "checkout_url": stripe_session.url,
        "checkout_session_id": stripe_session.id,
        "status": CHECKOUT_PENDING,
    }
