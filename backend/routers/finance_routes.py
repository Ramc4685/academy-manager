"""Payments + Expenses + Payout rules + Coach payouts."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from models import (
    PaymentIn, MarkPaidIn, DiscountIn, GenerateMonthlyIn,
    ExpenseIn, PayoutRuleIn, CalcPayoutIn, RefundPaymentIn,
)
from auth import get_current_user, require_roles, log_audit
from db import get_db

router = APIRouter()


def _invoice_number(prefix: str = "INV") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


# ----------------- /api/payments -----------------
async def _enrich_payment(p: dict, db) -> dict:
    p["id"] = str(p.pop("_id"))
    student = await db.students.find_one({"_id": ObjectId(p["student_id"])}) if p.get("student_id") else None
    session = await db.sessions.find_one({"_id": ObjectId(p["session_id"])}) if p.get("session_id") else None
    p["student_name"] = f"{student['first_name']} {student['last_name']}" if student else ""
    p["session_name"] = session["name"] if session else ""
    return p


@router.get("/payments")
async def list_payments(status: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    if user["role"] == "parent":
        q["parent_user_id"] = user["id"]
    elif user["role"] not in ("admin",):
        raise HTTPException(status_code=403, detail="Forbidden")
    if status:
        q["status"] = status
    cursor = db.payments.find(q).sort("created_at", -1)
    items = await cursor.to_list(2000)
    return [await _enrich_payment(p, db) for p in items]


@router.post("/payments")
async def create_payment(body: PaymentIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    enrollment = await db.enrollments.find_one({"_id": _oid(body.enrollment_id)})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    final_amount = max(0, body.amount - body.discount)
    doc = {
        "parent_user_id": enrollment["parent_user_id"],
        "student_id": enrollment["student_id"],
        "enrollment_id": body.enrollment_id,
        "session_id": enrollment["session_id"],
        "period": body.period,
        "amount": body.amount,
        "discount": body.discount,
        "final_amount": final_amount,
        "status": "pending",
        "payment_date": None,
        "payment_method": None,
        "marked_by": None,
        "notes": body.notes or "",
        "invoice_number": _invoice_number(),
        "invoice_created_at": datetime.now(timezone.utc).isoformat(),
        "refunded_amount": 0,
        "refund_status": "none",
        "refunds": [],
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = await db.payments.insert_one(doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Payment exists for this enrollment+period: {e}")
    await log_audit(admin, "create", "payment", str(r.inserted_id), f"{body.period} ${final_amount}")
    doc.pop("_id", None)
    return {"id": str(r.inserted_id), **doc}


@router.post("/payments/generate-monthly")
async def generate_monthly(body: GenerateMonthlyIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    enrollments = await db.enrollments.find({
        "status": "active",
        "is_deleted": {"$ne": True},
        "approval_status": {"$nin": ["pending", "pending_payment"]},
    }).to_list(5000)
    created = 0
    skipped = 0
    skipped_no_charge = 0
    skipped_paused = 0
    skipped_autopay = 0
    for e in enrollments:
        # Skip if this period is in the enrollment's paused list
        if body.period in (e.get("skip_periods", []) or []):
            skipped_paused += 1
            continue
        if e.get("payment_mode") == "autopay" and e.get("subscription_status") in {"active", "trialing", "past_due"}:
            skipped_autopay += 1
            continue
        # Skip No Charge / Waived
        bt = e.get("billing_type", "Standard")
        if bt and bt.lower() != "standard":
            skipped_no_charge += 1
            continue
        existing = await db.payments.find_one({"enrollment_id": str(e["_id"]), "period": body.period})
        if existing:
            skipped += 1
            continue
        # Use session override for this period if present
        overrides = e.get("session_overrides", {}) or {}
        session_id = overrides.get(body.period, e["session_id"])
        session = await db.sessions.find_one({"_id": ObjectId(session_id)})
        if not session:
            continue
        price = float(session.get("monthly_price", 0))
        doc = {
            "parent_user_id": e["parent_user_id"],
            "student_id": e["student_id"],
            "enrollment_id": str(e["_id"]),
            "session_id": session_id,
            "period": body.period,
            "amount": price,
            "discount": 0,
            "final_amount": price,
            "status": "pending",
            "payment_date": None,
            "payment_method": None,
            "marked_by": None,
            "notes": "",
            "invoice_number": _invoice_number(),
            "invoice_created_at": datetime.now(timezone.utc).isoformat(),
            "refunded_amount": 0,
            "refund_status": "none",
            "refunds": [],
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.payments.insert_one(doc)
        created += 1
    await log_audit(admin, "generate", "payment", body.period,
                    f"created {created} skipped {skipped} no_charge {skipped_no_charge} paused {skipped_paused} autopay {skipped_autopay}")
    return {"created": created, "skipped": skipped,
            "skipped_no_charge": skipped_no_charge, "skipped_paused": skipped_paused,
            "skipped_autopay": skipped_autopay}


@router.patch("/payments/{pid}/mark-paid")
async def mark_paid(pid: str, body: MarkPaidIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    pay_date = body.payment_date or datetime.now(timezone.utc).isoformat()
    await db.payments.update_one(
        {"_id": _oid(pid)},
        {"$set": {
            "status": "paid",
            "payment_date": pay_date,
            "payment_method": body.payment_method,
            "marked_by": admin["id"],
            "notes": body.notes or "",
        }},
    )
    pay = await db.payments.find_one({"_id": _oid(pid)})
    if pay and pay.get("payment_type") == "registration" and pay.get("enrollment_id"):
        await db.enrollments.update_one(
            {"_id": ObjectId(pay["enrollment_id"]), "approval_status": "pending_payment"},
            {"$set": {
                "approval_status": "pending",
                "payment_confirmed_at": pay_date,
            }},
        )
    await log_audit(admin, "mark_paid", "payment", pid, body.payment_method)
    return {"ok": True}


@router.patch("/payments/{pid}/apply-discount")
async def apply_discount(pid: str, body: DiscountIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.payments.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    final = max(0, float(p["amount"]) - float(body.discount))
    await db.payments.update_one(
        {"_id": _oid(pid)},
        {"$set": {"discount": body.discount, "final_amount": final}},
    )
    await log_audit(admin, "discount", "payment", pid, f"discount={body.discount}")
    return {"ok": True}


@router.delete("/payments/{pid}")
async def delete_payment(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.payments.update_one({"_id": _oid(pid)}, {"$set": {"is_deleted": True}})
    await log_audit(admin, "delete", "payment", pid, "soft delete")
    return {"ok": True}


@router.post("/payments/{pid}/undo-paid")
async def undo_paid(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.payments.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    if p.get("status") != "paid":
        raise HTTPException(status_code=400, detail="Payment is not paid")
    await db.payments.update_one(
        {"_id": _oid(pid)},
        {"$set": {"status": "pending", "payment_date": None, "payment_method": None,
                  "notes": (p.get("notes", "") + " [reverted by admin]").strip()}},
    )
    await log_audit(admin, "undo_paid", "payment", pid, "")
    return {"ok": True}


@router.post("/payments/{pid}/refund")
async def refund_payment(pid: str, body: RefundPaymentIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.payments.find_one({"_id": _oid(pid), "is_deleted": {"$ne": True}})
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    if p.get("status") != "paid":
        raise HTTPException(status_code=400, detail="Only paid payments can be refunded")
    refunded = float(p.get("refunded_amount", 0) or 0)
    final_amount = float(p.get("final_amount", 0) or 0)
    amount = float(body.amount if body.amount is not None else final_amount - refunded)
    if amount <= 0 or refunded + amount > final_amount:
        raise HTTPException(status_code=400, detail="Invalid refund amount")

    provider_refund_id = None
    provider_status = "local_recorded"
    if p.get("payment_method") == "stripe":
        tx = await db.payment_transactions.find_one({"payment_id": pid, "payment_status": "paid"})
        payment_intent = tx.get("stripe_payment_intent") if tx else None
        if payment_intent and __import__("os").environ.get("STRIPE_API_KEY"):
            import stripe
            stripe.api_key = __import__("os").environ["STRIPE_API_KEY"]
            refund = stripe.Refund.create(payment_intent=payment_intent, amount=int(round(amount * 100)))
            if hasattr(refund, "to_dict_recursive"):
                refund = refund.to_dict_recursive()
            provider_refund_id = refund.get("id")
            provider_status = refund.get("status", "created")
        else:
            provider_status = "stripe_intent_unavailable"

    refund_doc = {
        "amount": amount,
        "reason": body.reason or "",
        "refunded_by": admin["id"],
        "refunded_at": datetime.now(timezone.utc).isoformat(),
        "provider_refund_id": provider_refund_id,
        "provider_status": provider_status,
    }
    new_refunded = round(refunded + amount, 2)
    status = "refunded" if new_refunded >= final_amount else "partially_refunded"
    await db.payments.update_one(
        {"_id": _oid(pid)},
        {"$set": {"refunded_amount": new_refunded, "refund_status": status, "status": status},
         "$push": {"refunds": refund_doc}},
    )
    await log_audit(admin, "refund", "payment", pid, f"${amount}")
    return {"ok": True, "refund": refund_doc, "refund_status": status, "refunded_amount": new_refunded}


@router.post("/coach-payouts/{pid}/undo-paid")
async def undo_payout_paid(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.coach_payouts.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payout not found")
    if p.get("status") != "paid":
        raise HTTPException(status_code=400, detail="Payout not in paid state")
    await db.coach_payouts.update_one(
        {"_id": _oid(pid)},
        {"$set": {"status": "approved", "paid_at": None, "paid_by": None}},
    )
    # Remove auto-created expense entry (matched by note)
    await db.expenses.update_many(
        {"category": "Coach Payout", "notes": {"$regex": pid}},
        {"$set": {"is_deleted": True}},
    )
    await log_audit(admin, "undo_paid", "coach_payout", pid, "")
    return {"ok": True}


@router.post("/coach-payouts/{pid}/undo-approve")
async def undo_payout_approve(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.coach_payouts.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payout not found")
    if p.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Not in approved state")
    await db.coach_payouts.update_one(
        {"_id": _oid(pid)},
        {"$set": {"status": "calculated", "approved_at": None, "approved_by": None}},
    )
    await log_audit(admin, "undo_approve", "coach_payout", pid, "")
    return {"ok": True}


# ----------------- /api/expenses -----------------
@router.get("/expenses")
async def list_expenses(admin=Depends(require_roles("admin"))):
    db = get_db()
    cursor = db.expenses.find({"is_deleted": {"$ne": True}}).sort("date", -1)
    items = await cursor.to_list(1000)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@router.post("/expenses")
async def create_expense(body: ExpenseIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    doc = body.model_dump()
    doc["is_deleted"] = False
    doc["created_by"] = admin["id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    r = await db.expenses.insert_one(doc)
    await log_audit(admin, "create", "expense", str(r.inserted_id), f"{body.category} ${body.amount}")
    doc.pop("_id", None)
    return {"id": str(r.inserted_id), **doc}


@router.patch("/expenses/{eid}")
async def update_expense(eid: str, body: ExpenseIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.expenses.update_one({"_id": _oid(eid)}, {"$set": body.model_dump()})
    await log_audit(admin, "update", "expense", eid, "")
    return {"ok": True}


@router.delete("/expenses/{eid}")
async def delete_expense(eid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.expenses.update_one({"_id": _oid(eid)}, {"$set": {"is_deleted": True}})
    await log_audit(admin, "delete", "expense", eid, "soft delete")
    return {"ok": True}


# ----------------- /api/payout-rules -----------------
@router.get("/payout-rules")
async def list_payout_rules(user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_active": True}
    if user["role"] == "coach":
        q["coach_id"] = user["id"]
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    cursor = db.payout_rules.find(q)
    items = await cursor.to_list(500)
    for it in items:
        it["id"] = str(it.pop("_id"))
    return items


@router.post("/payout-rules")
async def upsert_payout_rule(body: PayoutRuleIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    # Deactivate existing rules for coach
    await db.payout_rules.update_many(
        {"coach_id": body.coach_id, "is_active": True},
        {"$set": {"is_active": False}},
    )
    doc = body.model_dump()
    doc["is_active"] = True
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    r = await db.payout_rules.insert_one(doc)
    await log_audit(admin, "set", "payout_rule", body.coach_id, f"{body.rule_type}={body.value}")
    doc.pop("_id", None)
    return {"id": str(r.inserted_id), **doc}


# ----------------- /api/coach-payouts -----------------
@router.post("/coach-payouts/calculate")
async def calculate_payouts(body: CalcPayoutIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    period = body.period
    # Find all coaches with active rules
    rules = await db.payout_rules.find({"is_active": True}).to_list(500)
    created = 0
    for rule in rules:
        coach_id = rule["coach_id"]
        # Sessions assigned to coach
        sessions = await db.sessions.find(
            {"coach_id": coach_id, "is_deleted": {"$ne": True}}
        ).to_list(500)
        session_ids = [str(s["_id"]) for s in sessions]
        if not session_ids:
            continue
        amount = 0.0
        if rule["rule_type"] == "revenue_percentage":
            basis = rule.get("basis", "collected")
            match: dict = {
                "session_id": {"$in": session_ids},
                "period": period,
                "is_deleted": {"$ne": True},
            }
            if basis == "collected":
                match["status"] = "paid"
            else:
                match["status"] = {"$ne": "failed"}
            agg = await db.payments.aggregate([
                {"$match": match},
                {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
            ]).to_list(1)
            total = agg[0]["total"] if agg else 0
            amount = float(total) * float(rule["value"]) / 100.0
        elif rule["rule_type"] == "fixed_monthly":
            amount = float(rule["value"])
        elif rule["rule_type"] == "per_student":
            count = await db.enrollments.count_documents({"session_id": {"$in": session_ids}, "status": "active"})
            amount = float(rule["value"]) * count
        elif rule["rule_type"] == "fixed_per_class":
            # Count attendance days where coach taught
            count = await db.attendance.count_documents({"session_id": {"$in": session_ids}})
            # Distinct dates per session - rough estimate using distinct dates
            distinct_dates = await db.attendance.distinct("date", {"session_id": {"$in": session_ids}})
            amount = float(rule["value"]) * len(distinct_dates)
        existing = await db.coach_payouts.find_one({"coach_id": coach_id, "period": period})
        doc = {
            "coach_id": coach_id,
            "period": period,
            "session_ids": session_ids,
            "rule_type": rule["rule_type"],
            "rule_value": rule["value"],
            "calculated_amount": round(amount, 2),
            "status": "calculated",
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            if existing.get("status") == "paid":
                continue  # do not recalculate paid
            await db.coach_payouts.update_one({"_id": existing["_id"]}, {"$set": doc})
        else:
            await db.coach_payouts.insert_one(doc)
            created += 1
    await log_audit(admin, "calculate", "coach_payout", period, f"created {created}")
    return {"created": created, "period": period}


@router.get("/coach-payouts")
async def list_coach_payouts(period: str | None = None, user=Depends(get_current_user)):
    db = get_db()
    q: dict = {"is_deleted": {"$ne": True}}
    if period:
        q["period"] = period
    if user["role"] == "coach":
        q["coach_id"] = user["id"]
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    cursor = db.coach_payouts.find(q).sort("period", -1)
    items = await cursor.to_list(500)
    coach_ids = {it["coach_id"] for it in items}
    coaches = {}
    if coach_ids:
        async for c in db.users.find({"_id": {"$in": [ObjectId(c) for c in coach_ids]}}):
            coaches[str(c["_id"])] = c.get("name", c.get("email"))
    for it in items:
        it["id"] = str(it.pop("_id"))
        it["coach_name"] = coaches.get(it["coach_id"], "Unknown")
    return items


@router.post("/coach-payouts/{pid}/approve")
async def approve_payout(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.coach_payouts.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payout not found")
    if p["status"] != "calculated":
        raise HTTPException(status_code=400, detail=f"Cannot approve from status {p['status']}")
    await db.coach_payouts.update_one(
        {"_id": _oid(pid)},
        {"$set": {"status": "approved", "approved_by": admin["id"],
                  "approved_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(admin, "approve", "coach_payout", pid, "")
    return {"ok": True}


@router.post("/coach-payouts/{pid}/mark-paid")
async def pay_payout(pid: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    p = await db.coach_payouts.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Payout not found")
    if p["status"] != "approved":
        raise HTTPException(status_code=400, detail="Payout must be approved before marking paid")
    await db.coach_payouts.update_one(
        {"_id": _oid(pid)},
        {"$set": {"status": "paid", "paid_by": admin["id"],
                  "paid_at": datetime.now(timezone.utc).isoformat()}},
    )
    # Also create an expense entry for the payout
    await db.expenses.insert_one({
        "category": "Coach Payout",
        "description": f"Payout to {p['coach_id']} period {p['period']}",
        "amount": p["calculated_amount"],
        "date": datetime.now(timezone.utc).isoformat()[:10],
        "paid_to": p["coach_id"],
        "status": "paid",
        "notes": f"coach_payout_id={pid}",
        "is_deleted": False,
        "created_by": admin["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await log_audit(admin, "pay", "coach_payout", pid, "")
    return {"ok": True}
