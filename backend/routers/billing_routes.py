"""Stripe Checkout for parent self-pay of monthly fees."""
import os
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from bson import ObjectId

from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, CheckoutSessionRequest,
)

from auth import get_current_user, log_audit
from db import get_db

router = APIRouter()
log = logging.getLogger(__name__)


def _client(request: Request) -> StripeCheckout:
    api_key = os.environ["STRIPE_API_KEY"]
    host_url = str(request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    return StripeCheckout(api_key=api_key, webhook_url=webhook_url)


class CheckoutIn(BaseModel):
    payment_id: str
    origin_url: str  # frontend window.location.origin


@router.post("/billing/checkout-session")
async def create_checkout_session(body: CheckoutIn, request: Request, user=Depends(get_current_user)):
    """Create a Stripe Checkout session for a specific PENDING payment record."""
    db = get_db()
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

    origin = body.origin_url.rstrip("/")
    success_url = f"{origin}/parent/payments?stripe_session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/parent/payments"

    sc = _client(request)
    req = CheckoutSessionRequest(
        amount=amount,
        currency="usd",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "payment_id": body.payment_id,
            "parent_user_id": pay.get("parent_user_id", ""),
            "student_name": (f"{student['first_name']} {student['last_name']}" if student else ""),
            "period": pay.get("period", ""),
        },
    )
    sess = await sc.create_checkout_session(req)

    # Create payment_transactions record
    await db.payment_transactions.insert_one({
        "session_id": sess.session_id,
        "payment_id": body.payment_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "amount": amount,
        "currency": "usd",
        "payment_status": "initiated",
        "status": "initiated",
        "metadata": req.metadata,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    await log_audit(user, "checkout_create", "payment", body.payment_id, f"session={sess.session_id}")
    return {"url": sess.url, "session_id": sess.session_id}


async def _apply_paid(db, payment_id: str, method: str = "stripe"):
    """Idempotently mark a payment paid."""
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
    pay = None
    if tx.get("payment_id"):
        pay = await db.payments.find_one({"_id": ObjectId(tx["payment_id"])})
    # Best-effort Stripe lookup; failure is non-fatal — webhook is canonical
    try:
        _client(request)
        import stripe
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
    sc = _client(request)
    try:
        evt = await sc.handle_webhook(body, sig)
    except Exception as e:
        log.warning(f"Stripe webhook verify failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    if evt.payment_status == "paid":
        tx = await db.payment_transactions.find_one({"session_id": evt.session_id})
        if tx:
            await db.payment_transactions.update_one(
                {"session_id": evt.session_id},
                {"$set": {"payment_status": "paid", "status": "complete",
                          "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
            await _apply_paid(db, tx["payment_id"])
    return {"received": True}
