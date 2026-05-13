"""Payments + Expenses + Payout rules + Coach payouts."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from models import (
    PaymentIn, MarkPaidIn, DiscountIn, GenerateMonthlyIn,
    ExpenseIn, PayoutRuleIn, CalcPayoutIn,
)
from auth import get_current_user, require_roles, log_audit
from db import get_db

router = APIRouter()


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
        "approval_status": {"$ne": "pending"},
    }).to_list(5000)
    created = 0
    skipped = 0
    skipped_no_charge = 0
    skipped_paused = 0
    for e in enrollments:
        # Skip if this period is in the enrollment's paused list
        if body.period in (e.get("skip_periods", []) or []):
            skipped_paused += 1
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
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.payments.insert_one(doc)
        created += 1
    await log_audit(admin, "generate", "payment", body.period,
                    f"created {created} skipped {skipped} no_charge {skipped_no_charge} paused {skipped_paused}")
    return {"created": created, "skipped": skipped,
            "skipped_no_charge": skipped_no_charge, "skipped_paused": skipped_paused}


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
            # Sum of paid revenue for this period for these sessions
            agg = await db.payments.aggregate([
                {"$match": {
                    "session_id": {"$in": session_ids},
                    "period": period,
                    "status": "paid",
                    "is_deleted": {"$ne": True},
                }},
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
