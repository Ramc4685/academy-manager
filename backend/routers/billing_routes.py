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
        sess = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
        stripe_status = sess.get("status")
        stripe_payment_status = sess.get("payment_status")
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": stripe_payment_status, "status": stripe_status,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        if stripe_payment_status == "paid" and tx.get("payment_status") != "paid":
            await _apply_paid(db, tx["payment_id"])
        return {
            "session_id": session_id,
            "status": stripe_status,
            "payment_status": stripe_payment_status,
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
    except Exception as e:
        log.warning(f"Stripe webhook verify failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    if evt.get("type") == "checkout.session.completed":
        session = evt["data"]["object"]
        tx = await db.payment_transactions.find_one({"session_id": session.get("id")})
        payment_id = tx.get("payment_id") if tx else (session.get("metadata") or {}).get("payment_id")
        if tx:
            await db.payment_transactions.update_one(
                {"session_id": session.get("id")},
                {"$set": {"payment_status": "paid", "status": "complete",
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
        if payment_id:
            await _apply_paid(db, payment_id)
    return {"received": True}
