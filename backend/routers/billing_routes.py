import os
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from bson import ObjectId

from auth import get_current_user, log_audit
from db import get_db
from models import CustomerPortalIn, SubscriptionCheckoutIn

router = APIRouter()
log = logging.getLogger(__name__)


def _configure_stripe():
    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    try:
        import stripe
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Stripe dependency is not installed") from exc
    stripe.api_key = api_key
    return stripe


def _stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_API_KEY"))


def _stripe_dict(obj):
    if isinstance(obj, list):
        return [_stripe_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _stripe_dict(v) for k, v in obj.items()}
    if hasattr(obj, "to_dict_recursive"):
        return obj.to_dict_recursive()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "_to_dict_recursive"):
        return obj._to_dict_recursive()
    return obj


def _configured_frontend_origins() -> set[str]:
    origins = set()
    for raw in (os.environ.get("FRONTEND_URL", ""), os.environ.get("CORS_ORIGINS", "")):
        for origin in raw.split(","):
            normalized = _normalize_origin(origin.strip())
            if normalized and normalized != "*":
                origins.add(normalized)
    return origins


def _normalize_origin(origin: str) -> str | None:
    if not origin:
        return None
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _return_origin(origin_url: str) -> str:
    origin = _normalize_origin(origin_url)
    if not origin:
        raise HTTPException(status_code=400, detail="Invalid checkout return origin")
    allowed = _configured_frontend_origins()
    if not allowed:
        raise HTTPException(status_code=503, detail="Frontend origin is not configured")
    if origin not in allowed:
        raise HTTPException(status_code=400, detail="Checkout return origin is not allowed")
    return origin


class CheckoutIn(BaseModel):
    payment_id: str
    origin_url: str  # frontend window.location.origin


def _period_from_timestamp(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m")


def _invoice_number(prefix: str = "INV") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _invoice_period(invoice: dict) -> str:
    lines = ((invoice.get("lines") or {}).get("data") or [])
    if lines:
        period = lines[0].get("period") or {}
        if period.get("start"):
            return _period_from_timestamp(period["start"])
    if invoice.get("period_start"):
        return _period_from_timestamp(invoice["period_start"])
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _get_or_create_customer(db, user: dict):
    existing = await db.users.find_one({"_id": ObjectId(user["id"])}, {"stripe_customer_id": 1, "email": 1, "name": 1})
    if existing and existing.get("stripe_customer_id"):
        return existing["stripe_customer_id"]
    stripe = _configure_stripe()
    customer = _stripe_dict(await asyncio.to_thread(
        stripe.Customer.create,
        email=user.get("email"),
        name=user.get("name") or user.get("email"),
        metadata={"user_id": user["id"], "role": user.get("role", "")},
    ))
    await db.users.update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"stripe_customer_id": customer["id"], "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return customer["id"]


async def _activate_subscription_enrollment(db, enrollment_id: str, session: dict):
    if not ObjectId.is_valid(enrollment_id):
        return False
    subscription_id = session.get("subscription")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    updates = {
        "payment_mode": "autopay",
        "subscription_status": "active",
        "stripe_customer_id": session.get("customer"),
        "autopay_started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if subscription_id:
        updates["stripe_subscription_id"] = subscription_id
    result = await db.enrollments.update_one({"_id": ObjectId(enrollment_id)}, {"$set": updates})
    enrollment = await db.enrollments.find_one({"_id": ObjectId(enrollment_id)})
    if enrollment and session.get("customer"):
        await db.users.update_one(
            {"_id": ObjectId(enrollment["parent_user_id"])},
            {"$set": {"stripe_customer_id": session["customer"], "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
    return result.matched_count == 1


@router.get("/billing/config")
async def billing_config(user=Depends(get_current_user)):
    return {"stripe_configured": _stripe_configured()}


@router.post("/billing/checkout-session")
async def create_checkout_session(body: CheckoutIn, request: Request, user=Depends(get_current_user)):
    """Create a Stripe Checkout session for a specific PENDING payment record."""
    db = get_db()
    if not ObjectId.is_valid(body.payment_id):
        raise HTTPException(status_code=400, detail="Invalid payment id")
    pay = await db.payments.find_one({"_id": ObjectId(body.payment_id)})
    if not pay:
        raise HTTPException(status_code=404, detail="Payment not found")
    if user["role"] == "parent" and pay.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not your payment")
    if pay.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    amount = float(pay.get("final_amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")
    student = await db.students.find_one({"_id": ObjectId(pay["student_id"])}) if pay.get("student_id") else None

    origin = _return_origin(body.origin_url)
    success_url = f"{origin}/parent/payments?stripe_session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/parent/payments"

    stripe = _configure_stripe()
    metadata = {
        "payment_id": body.payment_id,
        "parent_user_id": pay.get("parent_user_id", ""),
        "student_name": (f"{student['first_name']} {student['last_name']}" if student else ""),
        "period": pay.get("period", ""),
    }
    sess = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Academy fee {pay.get('period', '')}".strip()},
                "unit_amount": int(round(amount * 100)),
            },
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )

    # Create payment_transactions record
    await db.payment_transactions.insert_one({
        "session_id": sess["id"],
        "payment_id": body.payment_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "amount": amount,
        "currency": "usd",
        "payment_status": "initiated",
        "status": "initiated",
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    await log_audit(user, "checkout_create", "payment", body.payment_id, f"session={sess['id']}")
    return {"url": sess["url"], "session_id": sess["id"]}


@router.post("/billing/subscription-checkout")
async def create_subscription_checkout(body: SubscriptionCheckoutIn, request: Request, user=Depends(get_current_user)):
    """Create a Stripe Billing subscription for a single approved enrollment."""
    db = get_db()
    if user.get("role") not in {"admin", "parent"}:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not ObjectId.is_valid(body.enrollment_id):
        raise HTTPException(status_code=400, detail="Invalid enrollment id")
    enrollment = await db.enrollments.find_one({"_id": ObjectId(body.enrollment_id), "is_deleted": {"$ne": True}})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if user["role"] == "parent" and enrollment.get("parent_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not your enrollment")
    if enrollment.get("status") != "active":
        raise HTTPException(status_code=400, detail="Only active enrollments can use auto-pay")
    if enrollment.get("approval_status", "approved") != "approved":
        raise HTTPException(status_code=400, detail="Enrollment must be approved before auto-pay")
    if (enrollment.get("billing_type") or "Standard").lower() != "standard":
        raise HTTPException(status_code=400, detail="Auto-pay is only available for standard billing")
    if enrollment.get("stripe_subscription_id") and enrollment.get("subscription_status") in {"active", "trialing", "past_due"}:
        raise HTTPException(status_code=400, detail="Auto-pay is already set up for this enrollment")

    session_doc = await db.sessions.find_one({"_id": ObjectId(enrollment["session_id"]), "is_deleted": {"$ne": True}})
    student = await db.students.find_one({"_id": ObjectId(enrollment["student_id"])})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Session not found")
    amount = float(session_doc.get("monthly_price", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Session monthly price must be greater than zero")

    origin = _return_origin(body.origin_url)
    success_url = f"{origin}/parent/payments?stripe_subscription_session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/parent/payments"
    customer_user = user
    if user["role"] == "admin":
        parent = await db.users.find_one({"_id": ObjectId(enrollment["parent_user_id"])})
        if not parent:
            raise HTTPException(status_code=404, detail="Parent account not found")
        customer_user = {
            "id": str(parent["_id"]),
            "email": parent.get("email"),
            "name": parent.get("name"),
            "role": parent.get("role", "parent"),
        }
    customer_id = await _get_or_create_customer(db, customer_user)
    stripe = _configure_stripe()
    student_name = f"{student['first_name']} {student['last_name']}" if student else "Student"
    metadata = {
        "enrollment_id": body.enrollment_id,
        "parent_user_id": enrollment.get("parent_user_id", ""),
        "student_id": enrollment.get("student_id", ""),
        "session_id": enrollment.get("session_id", ""),
        "student_name": student_name,
        "session_name": session_doc.get("name", ""),
    }
    checkout = _stripe_dict(await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="subscription",
        customer=customer_id,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{session_doc.get('name', 'Academy')} monthly tuition"},
                "unit_amount": int(round(amount * 100)),
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=body.enrollment_id,
        metadata=metadata,
        subscription_data={"metadata": metadata},
    ))
    now = datetime.now(timezone.utc).isoformat()
    await db.payment_transactions.insert_one({
        "session_id": checkout["id"],
        "enrollment_id": body.enrollment_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "type": "subscription_checkout",
        "amount": amount,
        "currency": "usd",
        "payment_status": checkout.get("payment_status", "unpaid"),
        "status": checkout.get("status", "open"),
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
    })
    await db.enrollments.update_one(
        {"_id": ObjectId(body.enrollment_id)},
        {"$set": {
            "payment_mode": "autopay_pending",
            "stripe_customer_id": customer_id,
            "subscription_status": "pending_checkout",
            "updated_at": now,
        }},
    )
    await log_audit(user, "subscription_checkout_create", "enrollment", body.enrollment_id, f"session={checkout['id']}")
    return {"url": checkout["url"], "session_id": checkout["id"]}


@router.post("/billing/customer-portal")
async def create_customer_portal(body: CustomerPortalIn, request: Request, user=Depends(get_current_user)):
    if user.get("role") not in {"admin", "parent"}:
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    user_doc = await db.users.find_one({"_id": ObjectId(user["id"])}, {"stripe_customer_id": 1})
    customer_id = user_doc.get("stripe_customer_id") if user_doc else None
    if not customer_id:
        enrollment = await db.enrollments.find_one({"parent_user_id": user["id"], "stripe_customer_id": {"$exists": True}})
        customer_id = enrollment.get("stripe_customer_id") if enrollment else None
    if not customer_id:
        raise HTTPException(status_code=400, detail="Set up auto-pay before opening the billing portal")
    origin = _return_origin(body.origin_url)
    stripe = _configure_stripe()
    portal = _stripe_dict(await asyncio.to_thread(
        stripe.billing_portal.Session.create,
        customer=customer_id,
        return_url=f"{origin}/parent/payments",
    ))
    return {"url": portal["url"]}


async def _apply_paid(db, payment_id: str, method: str = "stripe"):
    """Idempotently mark a payment paid."""
    if not ObjectId.is_valid(payment_id):
        return False
    pay = await db.payments.find_one({"_id": ObjectId(payment_id)})
    if not pay:
        return False
    if pay.get("status") == "paid":
        return True
    await db.payments.update_one(
        {"_id": ObjectId(payment_id)},
        {"$set": {
            "status": "paid",
            "payment_date": datetime.now(timezone.utc).isoformat(),
            "payment_method": method,
            "notes": "Paid via Stripe",
        }},
    )
    if pay.get("payment_type") == "registration" and pay.get("enrollment_id"):
        await db.enrollments.update_one(
            {"_id": ObjectId(pay["enrollment_id"]), "approval_status": "pending_payment"},
            {"$set": {
                "approval_status": "pending",
                "payment_confirmed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    # Notification for the parent
    if pay.get("parent_user_id"):
        await db.notifications.insert_one({
            "user_id": pay["parent_user_id"],
            "type": "payment_received",
            "title": "Payment received",
            "message": f"${pay.get('final_amount', 0)} for {pay.get('period', '')} confirmed.",
            "related_entity": payment_id,
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return True


@router.get("/billing/checkout-status/{session_id}")
async def checkout_status(session_id: str, request: Request, user=Depends(get_current_user)):
    """Return local payment + transaction status. The Stripe webhook flips
    payment_transactions.payment_status='paid' which triggers _apply_paid().
    Frontend polls this endpoint after returning from Stripe Checkout."""
    db = get_db()
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx:
        raise HTTPException(status_code=404, detail="Checkout session not found")
    if user.get("role") == "parent" and tx.get("user_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your checkout session")
    if user.get("role") not in {"admin", "parent"}:
        raise HTTPException(status_code=403, detail="Forbidden")
    pay = None
    if tx.get("payment_id"):
        pay = await db.payments.find_one({"_id": ObjectId(tx["payment_id"])})
    # Best-effort Stripe lookup; failure is non-fatal — webhook is canonical
    try:
        stripe = _configure_stripe()
        sess = _stripe_dict(await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id))
        stripe_status = sess.get("status")
        stripe_payment_status = sess.get("payment_status")
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": stripe_payment_status, "status": stripe_status,
                      "stripe_payment_intent": sess.get("payment_intent"),
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        if tx.get("type") == "subscription_checkout" and sess.get("subscription"):
            enrollment_id = tx.get("enrollment_id") or (sess.get("metadata") or {}).get("enrollment_id")
            if enrollment_id:
                await _activate_subscription_enrollment(db, enrollment_id, sess)
        elif stripe_payment_status == "paid" and tx.get("payment_status") != "paid":
            await _apply_paid(db, tx["payment_id"])
        return {
            "session_id": session_id,
            "status": stripe_status,
            "payment_status": stripe_payment_status,
            "subscription_status": "active" if sess.get("subscription") and stripe_status == "complete" else None,
            "amount_total": sess.get("amount_total"),
        }
    except Exception as e:
        log.warning("Stripe lookup failed (using local state): %s", e)
        return {
            "session_id": session_id,
            "status": tx.get("status", "unknown"),
            "payment_status": (pay.get("status") if pay and pay.get("status") == "paid" else tx.get("payment_status", "unknown")),
            "amount_total": int(tx.get("amount", 0) * 100) if tx.get("amount") else None,
        }


async def _handle_onboarding_checkout_completed(db, stripe, session: dict) -> None:
    """Handle checkout.session.completed for onboarding events (metadata.kind=onboarding).

    Atomically reserves a capacity slot. On success creates a pending_approval
    enrollment, students row, payments row, and audit log. On capacity race:
    transitions to capacity_failed_refunding, creates a waitlist entry, attempts
    stripe.Refund.create. On refund failure: transitions to
    capacity_failed_refund_failed and writes an admin-attention audit log.

    TTL race (onboarding doc missing): logs structured warning and writes an
    admin-attention audit_logs row; never silently swallows real money.
    """
    from routers.onboarding_routes import (
        CHECKOUT_PENDING, PENDING_APPROVAL,
        CAPACITY_FAILED_REFUNDING, CAPACITY_FAILED_REFUND_FAILED, REFUNDED,
    )

    metadata = session.get("metadata") or {}
    onboarding_id = metadata.get("onboarding_id", "")
    parent_user_id = metadata.get("parent_user_id", "")
    session_id = metadata.get("session_id", "")
    payment_intent = session.get("payment_intent")
    now = datetime.now(timezone.utc).isoformat()

    # --- Look up onboarding doc ---
    ob_doc = None
    if ObjectId.is_valid(onboarding_id):
        ob_doc = await db.onboarding_applications.find_one({"_id": ObjectId(onboarding_id)})

    if ob_doc is None:
        # TTL race: doc deleted between checkout creation and webhook arrival.
        log.warning(
            "onboarding.webhook_missing_doc: onboarding_id=%s parent_user_id=%s "
            "payment_intent=%s — writing admin-attention audit log",
            onboarding_id, parent_user_id, payment_intent,
        )
        await db.audit_logs.insert_one({
            "user_id": parent_user_id,
            "user_email": "",
            "role": "system",
            "action": "onboarding.webhook_missing_doc",
            "entity_type": "onboarding_application",
            "entity_id": onboarding_id,
            "summary": (
                f"checkout.session.completed received for onboarding_id={onboarding_id!r} "
                f"but document was not found (possible TTL expiry). "
                f"payment_intent={payment_intent!r}. Admin attention required."
            ),
            "created_at": now,
        })
        return

    # --- Atomically reserve a capacity slot ---
    if not ObjectId.is_valid(session_id):
        log.warning("onboarding.webhook: invalid session_id=%r on onboarding %s", session_id, onboarding_id)
        return

    result = await db.sessions.update_one(
        {
            "_id": ObjectId(session_id),
            "is_deleted": {"$ne": True},
            "$expr": {
                "$lt": [
                    {"$ifNull": ["$reserved_seats", 0]},
                    {"$ifNull": ["$max_students", 0]},
                ],
            },
        },
        {"$inc": {"reserved_seats": 1}},
    )
    capacity_reserved = result.modified_count == 1

    if capacity_reserved:
        # --- Capacity available: enroll ---
        child_profile = ob_doc.get("child_profile") or {}
        child_name_parts = (child_profile.get("name") or "").split(None, 1)
        first_name = child_name_parts[0] if child_name_parts else "Student"
        last_name = child_name_parts[1] if len(child_name_parts) > 1 else ""
        student_doc = {
            "parent_user_id": parent_user_id,
            "first_name": first_name,
            "last_name": last_name,
            "dob": child_profile.get("dob", ""),
            "medical_notes": child_profile.get("medical_notes", ""),
            "skill_level": "beginner",
            "emergency_contact_name": "",
            "emergency_contact_phone": "",
            "waiver_accepted": True,
            "is_deleted": False,
            "created_at": now,
        }
        student_result = await db.students.insert_one(student_doc)
        student_id = str(student_result.inserted_id)

        enrollment_doc = {
            "session_id": session_id,
            "student_id": student_id,
            "parent_user_id": parent_user_id,
            "billing_type": "Standard",
            "approval_status": "pending",
            "status": "pending_approval",
            "payment_mode": "one_time_first_month",
            "enrolled_at": now,
            "is_deleted": False,
            "created_at": now,
        }
        enrollment_result = await db.enrollments.insert_one(enrollment_doc)
        enrollment_id = str(enrollment_result.inserted_id)

        # Load session for price
        session_doc = await db.sessions.find_one({"_id": ObjectId(session_id)})
        amount = float((session_doc or {}).get("monthly_price", 0))

        payment_doc = {
            "parent_user_id": parent_user_id,
            "student_id": student_id,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "period": datetime.now(timezone.utc).strftime("%Y-%m"),
            "amount": amount,
            "discount": 0,
            "final_amount": amount,
            "status": "paid",
            "payment_date": now,
            "payment_method": "stripe_onboarding",
            "marked_by": None,
            "notes": "First-month payment via Stripe onboarding checkout",
            "stripe_payment_intent": payment_intent,
            "payment_type": "one_time_first_month",
            "refunded_amount": 0,
            "refund_status": "none",
            "refunds": [],
            "is_deleted": False,
            "created_at": now,
        }
        await db.payments.insert_one(payment_doc)

        # Transition onboarding
        await db.onboarding_applications.update_one(
            {"_id": ob_doc["_id"]},
            {"$set": {"status": PENDING_APPROVAL, "updated_at": now}},
        )

        await db.audit_logs.insert_one({
            "user_id": parent_user_id,
            "user_email": ob_doc.get("parent_email", ""),
            "role": "system",
            "action": "onboarding.pending_approval_created",
            "entity_type": "onboarding_application",
            "entity_id": onboarding_id,
            "summary": (
                f"Onboarding enrollment created: enrollment_id={enrollment_id} "
                f"student_id={student_id} session_id={session_id} "
                f"payment_intent={payment_intent!r}"
            ),
            "created_at": now,
        })
    else:
        # --- Capacity race: seat taken before webhook ---
        await db.onboarding_applications.update_one(
            {"_id": ob_doc["_id"]},
            {"$set": {"status": CAPACITY_FAILED_REFUNDING, "updated_at": now}},
        )

        # Create a waitlist entry (status=waiting, no student doc yet)
        child_profile = ob_doc.get("child_profile") or {}
        waitlist_doc = {
            "session_id": session_id,
            "student_id": None,  # no student row at this point
            "parent_user_id": parent_user_id,
            "onboarding_id": onboarding_id,
            "status": "waiting",
            "requested_by": "onboarding_capacity_race",
            "requested_at": now,
            "offer_expires_at": None,
            "offered_at": None,
            "enrolled_at": None,
            "child_profile": child_profile,
            "is_deleted": False,
        }
        await db.waitlist.insert_one(waitlist_doc)

        # Attempt refund
        try:
            await asyncio.to_thread(stripe.Refund.create, payment_intent=payment_intent)
            await db.onboarding_applications.update_one(
                {"_id": ob_doc["_id"]},
                {"$set": {"status": REFUNDED, "updated_at": now}},
            )
            await db.audit_logs.insert_one({
                "user_id": parent_user_id,
                "user_email": ob_doc.get("parent_email", ""),
                "role": "system",
                "action": "onboarding.capacity_race_refunded",
                "entity_type": "onboarding_application",
                "entity_id": onboarding_id,
                "summary": (
                    f"Capacity race on session_id={session_id}: refund issued for "
                    f"payment_intent={payment_intent!r}. Onboarding placed on waitlist."
                ),
                "created_at": now,
            })
        except Exception as refund_exc:
            refund_error = str(refund_exc)
            log.error(
                "onboarding.refund_failed: onboarding_id=%s payment_intent=%s error=%s",
                onboarding_id, payment_intent, refund_error,
            )
            await db.onboarding_applications.update_one(
                {"_id": ob_doc["_id"]},
                {"$set": {
                    "status": CAPACITY_FAILED_REFUND_FAILED,
                    "refund_error": refund_error,
                    "updated_at": now,
                }},
            )
            await db.audit_logs.insert_one({
                "user_id": parent_user_id,
                "user_email": ob_doc.get("parent_email", ""),
                "role": "system",
                "action": "onboarding.refund_failed",
                "entity_type": "onboarding_application",
                "entity_id": onboarding_id,
                "summary": (
                    f"ADMIN ATTENTION: Capacity race refund failed for onboarding_id={onboarding_id!r} "
                    f"payment_intent={payment_intent!r} session_id={session_id!r}. "
                    f"Error: {refund_error}. Manual refund required."
                ),
                "created_at": now,
            })


async def _handle_charge_refunded(db, evt: dict) -> None:
    """Process a charge.refunded event: create a payment_refunds record and
    update the parent payments document."""
    charge = evt["data"]["object"]
    payment_intent_id = charge.get("payment_intent")
    if not payment_intent_id:
        log.info("charge.refunded event %s has no payment_intent; skipping", evt.get("id"))
        return

    pay = await db.payments.find_one({"stripe_payment_intent": payment_intent_id})
    if not pay:
        tx = await db.payment_transactions.find_one({"stripe_payment_intent": payment_intent_id})
        payment_id = tx.get("payment_id") if tx else None
        if payment_id and ObjectId.is_valid(payment_id):
            pay = await db.payments.find_one({"_id": ObjectId(payment_id)})
        if not pay:
            log.info(
                "charge.refunded event %s: no payments doc for payment_intent=%s; skipping",
                evt.get("id"),
                payment_intent_id,
            )
            return

    # Pull the first refund object from the charge for the refund id and reason.
    refund_list = (charge.get("refunds") or {}).get("data") or []
    stripe_refund_id = refund_list[0]["id"] if refund_list else evt["id"]
    reason = refund_list[0].get("reason") if refund_list else None

    # amount_refunded on the charge object is cumulative (in cents).
    amount_refunded_cents = int(charge.get("amount_refunded") or 0)
    amount_refunded = amount_refunded_cents / 100.0

    # Compute the incremental refund for this event (total minus already recorded).
    already_refunded = float(pay.get("refunded_amount") or 0)
    incremental = max(0.0, amount_refunded - already_refunded)

    now = datetime.now(timezone.utc).isoformat()
    payment_id_str = str(pay["_id"])

    # Insert the refund record (unique index on stripe_refund_id prevents duplicates).
    try:
        await db.payment_refunds.insert_one({
            "stripe_refund_id": stripe_refund_id,
            "payment_id": payment_id_str,
            "stripe_payment_intent": payment_intent_id,
            "amount": incremental,
            "reason": reason,
            "created_at": now,
        })
    except Exception as exc:
        # DuplicateKeyError means we already recorded this refund — safe to skip.
        log.warning("payment_refunds insert skipped for %s: %s", stripe_refund_id, exc)
        return

    # Update the parent payment.
    final_amount = float(pay.get("final_amount") or 0)
    new_refunded = round(already_refunded + incremental, 2)
    refund_status = "refunded" if new_refunded >= final_amount else "partially_refunded"
    refund_doc = {
        "amount": incremental,
        "reason": reason or "",
        "refunded_by": "stripe_webhook",
        "refunded_at": now,
        "provider_refund_id": stripe_refund_id,
        "provider_status": refund_list[0].get("status", "succeeded") if refund_list else "succeeded",
    }

    await db.payments.update_one(
        {"_id": pay["_id"]},
        {
            "$set": {
                "refunded_amount": new_refunded,
                "refund_status": refund_status,
                "status": refund_status,
                "stripe_payment_intent": payment_intent_id,
                "updated_at": now,
            },
            "$push": {"refunds": refund_doc},
        },
    )


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    db = get_db()
    body = await request.body()
    sig = request.headers.get("Stripe-Signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    stripe = _configure_stripe()
    try:
        evt = stripe.Webhook.construct_event(body, sig, webhook_secret)
        evt = _stripe_dict(evt)
    except Exception as e:
        log.warning(f"Stripe webhook verify failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = evt.get("id")
    event_type = evt.get("type")
    now = datetime.now(timezone.utc).isoformat()

    # --- Idempotency check ---
    existing_evt = await db.stripe_webhook_events.find_one({"event_id": event_id})
    if existing_evt and existing_evt.get("status") == "processed":
        return {"received": True, "deduped": True}

    # Insert a "processing" sentinel to claim this event.
    try:
        await db.stripe_webhook_events.insert_one({
            "event_id": event_id,
            "type": event_type,
            "status": "processing",
            "received_at": now,
            "processed_at": None,
        })
    except Exception:
        # Another process beat us to it; treat as deduped.
        return {"received": True, "deduped": True}

    # --- Route to handler ---
    error_msg = None
    try:
        if event_type == "checkout.session.completed":
            session = evt["data"]["object"]
            metadata = session.get("metadata") or {}

            if metadata.get("kind") == "onboarding":
                # Onboarding-specific path — must stay inside this sentinel try/except.
                await _handle_onboarding_checkout_completed(db, stripe, session)
            else:
                # Existing non-onboarding path — unchanged.
                tx = await db.payment_transactions.find_one({"session_id": session.get("id")})
                payment_id = tx.get("payment_id") if tx else metadata.get("payment_id")
                if tx:
                    await db.payment_transactions.update_one(
                        {"session_id": session.get("id")},
                        {"$set": {"payment_status": "paid", "status": "complete",
                                  "stripe_payment_intent": session.get("payment_intent"),
                                  "stripe_subscription_id": session.get("subscription"),
                                  "updated_at": datetime.now(timezone.utc).isoformat()}},
                    )
                enrollment_id = (tx or {}).get("enrollment_id") or metadata.get("enrollment_id")
                if session.get("mode") == "subscription" and enrollment_id:
                    await _activate_subscription_enrollment(db, enrollment_id, session)
                elif payment_id:
                    if session.get("payment_intent") and ObjectId.is_valid(payment_id):
                        await db.payments.update_one(
                            {"_id": ObjectId(payment_id)},
                            {"$set": {
                                "stripe_payment_intent": session.get("payment_intent"),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }},
                        )
                    await _apply_paid(db, payment_id)
        elif event_type == "checkout.session.expired":
            session = evt["data"]["object"]
            log.info("checkout.session.expired for session %s", session.get("id"))
            metadata = session.get("metadata") or {}
            if metadata.get("kind") == "onboarding":
                onboarding_id = metadata.get("onboarding_id", "")
                if ObjectId.is_valid(onboarding_id):
                    from routers.onboarding_routes import CHECKOUT_PENDING, CHECKOUT_EXPIRED
                    now_exp = datetime.now(timezone.utc).isoformat()
                    result = await db.onboarding_applications.update_one(
                        {"_id": ObjectId(onboarding_id), "status": CHECKOUT_PENDING},
                        {"$set": {"status": CHECKOUT_EXPIRED, "updated_at": now_exp}},
                    )
                    if result.modified_count == 1:
                        await db.audit_logs.insert_one({
                            "user_id": metadata.get("parent_user_id", ""),
                            "user_email": "",
                            "role": "system",
                            "action": "onboarding.checkout_expired",
                            "entity_type": "onboarding_application",
                            "entity_id": onboarding_id,
                            "summary": f"Checkout session expired for onboarding_id={onboarding_id!r}",
                            "created_at": now_exp,
                        })
        elif event_type == "invoice.paid":
            invoice = evt["data"]["object"]
            subscription_id = invoice.get("subscription")
            subscription_details = invoice.get("subscription_details") or {}
            metadata = subscription_details.get("metadata") or invoice.get("metadata") or {}
            enrollment = None
            if subscription_id:
                enrollment = await db.enrollments.find_one({"stripe_subscription_id": subscription_id})
            if not enrollment and metadata.get("enrollment_id") and ObjectId.is_valid(metadata["enrollment_id"]):
                enrollment = await db.enrollments.find_one({"_id": ObjectId(metadata["enrollment_id"])})
            if enrollment:
                period = _invoice_period(invoice)
                amount = float(invoice.get("amount_paid") or 0) / 100
                invoice_now = datetime.now(timezone.utc).isoformat()
                payment_doc = {
                    "parent_user_id": enrollment["parent_user_id"],
                    "student_id": enrollment["student_id"],
                    "enrollment_id": str(enrollment["_id"]),
                    "session_id": enrollment["session_id"],
                    "period": period,
                    "amount": amount,
                    "discount": 0,
                    "final_amount": amount,
                    "status": "paid",
                    "payment_date": invoice_now,
                    "payment_method": "stripe_subscription",
                    "marked_by": None,
                    "notes": "Paid via Stripe auto-pay",
                    "invoice_number": invoice.get("number") or _invoice_number(),
                    "invoice_created_at": invoice_now,
                    "stripe_invoice_id": invoice.get("id"),
                    "stripe_subscription_id": subscription_id,
                    "stripe_payment_intent": invoice.get("payment_intent"),
                    "payment_type": "subscription",
                    "refunded_amount": 0,
                    "refund_status": "none",
                    "refunds": [],
                    "is_deleted": False,
                    "created_at": invoice_now,
                }
                existing = await db.payments.find_one({"enrollment_id": str(enrollment["_id"]), "period": period})
                if existing:
                    await db.payments.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {
                            "status": "paid",
                            "payment_date": invoice_now,
                            "payment_method": "stripe_subscription",
                            "notes": "Paid via Stripe auto-pay",
                            "stripe_invoice_id": invoice.get("id"),
                            "stripe_subscription_id": subscription_id,
                            "stripe_payment_intent": invoice.get("payment_intent"),
                            "payment_type": "subscription",
                        }},
                    )
                else:
                    await db.payments.insert_one(payment_doc)
                await db.enrollments.update_one(
                    {"_id": enrollment["_id"]},
                    {"$set": {
                        "payment_mode": "autopay",
                        "subscription_status": "active",
                        "last_autopay_at": invoice_now,
                        "updated_at": invoice_now,
                    }},
                )
                await db.notifications.insert_one({
                    "user_id": enrollment["parent_user_id"],
                    "type": "payment_received",
                    "title": "Auto-pay received",
                    "message": f"${amount:.2f} for {period} confirmed.",
                    "related_entity": str(enrollment["_id"]),
                    "read": False,
                    "created_at": invoice_now,
                })
        elif event_type == "invoice.payment_failed":
            invoice = evt["data"]["object"]
            subscription_id = invoice.get("subscription")
            enrollment = await db.enrollments.find_one({"stripe_subscription_id": subscription_id}) if subscription_id else None
            if enrollment:
                await db.enrollments.update_one(
                    {"_id": enrollment["_id"]},
                    {"$set": {
                        "payment_mode": "autopay",
                        "subscription_status": "past_due",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
        elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
            subscription = evt["data"]["object"]
            subscription_id = subscription.get("id")
            if subscription_id:
                status = subscription.get("status", "unknown")
                payment_mode = "manual" if event_type == "customer.subscription.deleted" else "autopay"
                await db.enrollments.update_one(
                    {"stripe_subscription_id": subscription_id},
                    {"$set": {
                        "payment_mode": payment_mode,
                        "subscription_status": status,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
        elif event_type == "charge.refunded":
            await _handle_charge_refunded(db, evt)
        else:
            log.debug("Unhandled Stripe event type: %s", event_type)
    except Exception as exc:
        error_msg = str(exc)
        log.exception("Error handling Stripe event %s (%s): %s", event_id, event_type, exc)

    # --- Mark the event as processed or failed ---
    final_status = "failed" if error_msg else "processed"
    update_fields: dict = {"status": final_status, "processed_at": datetime.now(timezone.utc).isoformat()}
    if error_msg:
        update_fields["error"] = error_msg
    await db.stripe_webhook_events.update_one(
        {"event_id": event_id},
        {"$set": update_fields},
    )

    if error_msg:
        raise HTTPException(status_code=500, detail="Webhook handler error")

    return {"received": True}
