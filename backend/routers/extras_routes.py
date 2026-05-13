"""Dues followup, Coach payslip, Pending approvals."""
from urllib.parse import quote
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from auth import get_current_user, require_roles
from db import get_db

router = APIRouter()


def _zelle_text(parent_name: str, child_name: str, amount: float) -> str:
    return (
        f"Hi {parent_name}, friendly reminder — ${int(amount)} pending for "
        f"{child_name}'s badminton training. Please send via Zelle to 248-885-9243. "
        f"Thanks! — BLno Academy"
    )


@router.get("/dues-followup")
async def dues_followup(admin=Depends(require_roles("admin"))):
    """All parents with at least one pending payment, with totals and WhatsApp link."""
    db = get_db()
    cursor = db.payments.find(
        {"status": "pending", "is_deleted": {"$ne": True}}
    ).sort("period", 1)
    pending = await cursor.to_list(5000)
    by_parent: dict = {}
    student_ids = set()
    parent_ids = set()
    for p in pending:
        pid = p.get("parent_user_id")
        if not pid:
            continue
        by_parent.setdefault(pid, {"total": 0, "items": []})
        by_parent[pid]["total"] += float(p.get("final_amount", 0))
        by_parent[pid]["items"].append({
            "period": p.get("period"),
            "amount": float(p.get("final_amount", 0)),
            "student_id": p.get("student_id"),
        })
        student_ids.add(p.get("student_id"))
        parent_ids.add(pid)

    parents = {}
    if parent_ids:
        async for u in db.users.find({"_id": {"$in": [ObjectId(x) for x in parent_ids]}}):
            parents[str(u["_id"])] = u
    students = {}
    if student_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in student_ids if x]}}):
            students[str(s["_id"])] = s

    rows = []
    for pid, data in by_parent.items():
        parent = parents.get(pid)
        if not parent:
            continue
        # Child names + per-month dues
        child_set: dict = {}
        for item in data["items"]:
            stu = students.get(item["student_id"])
            if not stu:
                continue
            name = f"{stu['first_name']} {stu['last_name']}"
            child_set.setdefault(name, 0)
            child_set[name] += item["amount"]
        kid_names = " & ".join(child_set.keys())
        message = _zelle_text(parent.get("name") or parent["email"], kid_names, data["total"])
        raw_phone = (parent.get("phone") or "").replace("+", "").replace("-", "").replace(" ", "")
        if raw_phone and not raw_phone.startswith("1") and len(raw_phone) == 10:
            raw_phone = "1" + raw_phone
        wa_url = f"https://wa.me/{raw_phone}?text={quote(message)}" if raw_phone else ""
        rows.append({
            "parent_id": pid,
            "parent_name": parent.get("name"),
            "parent_email": parent["email"],
            "parent_phone": parent.get("phone", ""),
            "kids": list(child_set.keys()),
            "kid_dues": child_set,
            "total_due": round(data["total"], 2),
            "message": message,
            "whatsapp_url": wa_url,
        })
    rows.sort(key=lambda r: r["total_due"], reverse=True)
    return rows


@router.get("/coach-payouts/{coach_id}/payslip")
async def coach_payslip(coach_id: str, period: str, user=Depends(get_current_user)):
    """Detailed payslip for one coach × month: kids enrolled, prices, expected revenue, payout."""
    if user["role"] == "coach" and user["id"] != coach_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] not in ("admin", "coach"):
        raise HTTPException(status_code=403, detail="Forbidden")
    db = get_db()
    coach = await db.users.find_one({"_id": ObjectId(coach_id)})
    if not coach:
        raise HTTPException(status_code=404, detail="Coach not found")
    sessions = await db.sessions.find({"coach_id": coach_id, "is_deleted": {"$ne": True}}).to_list(500)
    session_map = {str(s["_id"]): s for s in sessions}
    enr_cursor = db.enrollments.find({
        "session_id": {"$in": list(session_map.keys())},
        "status": "active",
        "is_deleted": {"$ne": True},
        "approval_status": {"$ne": "pending"},
    })
    rows = []
    expected_revenue = 0.0
    for e in await enr_cursor.to_list(5000):
        s = session_map.get(e["session_id"])
        if not s:
            continue
        stu = await db.students.find_one({"_id": ObjectId(e["student_id"])})
        if not stu:
            continue
        billing = e.get("billing_type", "Standard")
        price = float(s.get("monthly_price", 0)) if billing == "Standard" else 0
        expected_revenue += price
        # Was a payment made this period?
        pay = await db.payments.find_one({"enrollment_id": str(e["_id"]), "period": period})
        rows.append({
            "child": f"{stu['first_name']} {stu['last_name']}",
            "session": s["name"],
            "skill": s.get("skill_level"),
            "billing_type": billing,
            "price": price,
            "payment_status": pay.get("status") if pay else "not_generated",
        })
    rule = await db.payout_rules.find_one({"coach_id": coach_id, "is_active": True})
    rule_type = rule["rule_type"] if rule else "revenue_percentage"
    rule_value = rule["value"] if rule else 30
    rule_basis = (rule.get("basis") if rule else "collected") or "collected"
    payout = 0.0
    collected = 0.0
    # Collected revenue this period for coach's sessions
    collected_agg = await db.payments.aggregate([
        {"$match": {
            "session_id": {"$in": list(session_map.keys())},
            "period": period,
            "status": "paid",
            "is_deleted": {"$ne": True},
        }},
        {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
    ]).to_list(1)
    collected = float(collected_agg[0]["total"]) if collected_agg else 0.0
    if rule_type == "revenue_percentage":
        basis_amount = collected if rule_basis == "collected" else expected_revenue
        payout = basis_amount * float(rule_value) / 100.0
    elif rule_type == "fixed_monthly":
        payout = float(rule_value)
    elif rule_type == "per_student":
        payout = float(rule_value) * len(rows)
    elif rule_type == "fixed_per_class":
        distinct_dates = await db.attendance.distinct(
            "date", {"session_id": {"$in": list(session_map.keys())}}
        )
        payout = float(rule_value) * len(distinct_dates)

    # Existing payout record for that period
    existing = await db.coach_payouts.find_one({"coach_id": coach_id, "period": period})
    return {
        "coach_id": coach_id,
        "coach_name": coach.get("name", coach.get("email")),
        "period": period,
        "kids_enrolled": len(rows),
        "expected_revenue": round(expected_revenue, 2),
        "collected_revenue": round(collected, 2),
        "rule_type": rule_type,
        "rule_value": rule_value,
        "rule_basis": rule_basis,
        "payout_amount": round(payout, 2),
        "payout_basis": rule_basis if rule_type == "revenue_percentage" else rule_type,
        "current_status": existing["status"] if existing else "not_calculated",
        "rows": rows,
    }


@router.get("/enrollments/pending-approval")
async def pending_approval(admin=Depends(require_roles("admin"))):
    db = get_db()
    cursor = db.enrollments.find({"approval_status": "pending", "is_deleted": {"$ne": True}})
    items = await cursor.to_list(500)
    stu_ids = {it["student_id"] for it in items}
    sess_ids = {it["session_id"] for it in items}
    students = {}
    sessions = {}
    if stu_ids:
        async for s in db.students.find({"_id": {"$in": [ObjectId(x) for x in stu_ids]}}):
            students[str(s["_id"])] = s
    if sess_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions[str(s["_id"])] = s
    for it in items:
        it["id"] = str(it.pop("_id"))
        stu = students.get(it["student_id"])
        sess = sessions.get(it["session_id"])
        it["student_name"] = f"{stu['first_name']} {stu['last_name']}" if stu else ""
        it["session_name"] = sess["name"] if sess else ""
    return items
