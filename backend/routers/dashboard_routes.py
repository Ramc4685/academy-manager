"""Dashboard + Reports (CSV) + Audit logs."""
import io
import csv
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from bson import ObjectId
from auth import get_current_user, require_roles
from db import get_db

router = APIRouter()


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ----------------- /api/dashboard -----------------
@router.get("/dashboard/admin")
async def admin_dashboard(period: str | None = None, admin=Depends(require_roles("admin"))):
    db = get_db()
    period = period or _current_period()

    # Income: sum of paid payments in period
    agg = await db.payments.aggregate([
        {"$match": {"period": period, "status": "paid", "is_deleted": {"$ne": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
    ]).to_list(1)
    monthly_income = float(agg[0]["total"]) if agg else 0.0

    # Expected revenue (paid + pending) for the period
    exp_rev_agg = await db.payments.aggregate([
        {"$match": {"period": period, "is_deleted": {"$ne": True}, "status": {"$ne": "failed"}}},
        {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
    ]).to_list(1)
    expected_revenue = float(exp_rev_agg[0]["total"]) if exp_rev_agg else 0.0

    # Waived / No Charge value: active enrollments with billing_type != Standard
    waived_value = 0.0
    nc_enrolls = await db.enrollments.find(
        {"status": "active", "is_deleted": {"$ne": True},
         "billing_type": {"$in": ["NoCharge", "Waived"]}}
    ).to_list(1000)
    if nc_enrolls:
        sess_ids = list({e["session_id"] for e in nc_enrolls})
        sessions_map = {}
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions_map[str(s["_id"])] = float(s.get("monthly_price", 0) or 0)
        waived_value = sum(sessions_map.get(e["session_id"], 0) for e in nc_enrolls)

    pending_agg = await db.payments.aggregate([
        {"$match": {"period": period, "status": "pending", "is_deleted": {"$ne": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$final_amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    pending_total = float(pending_agg[0]["total"]) if pending_agg else 0.0
    pending_count = int(pending_agg[0]["count"]) if pending_agg else 0

    # Expenses (this month, excluding payouts which are counted separately)
    month_start = f"{period}-01"
    exp_agg = await db.expenses.aggregate([
        {"$match": {"date": {"$gte": month_start}, "is_deleted": {"$ne": True}, "category": {"$ne": "Coach Payout"}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    expenses = float(exp_agg[0]["total"]) if exp_agg else 0.0

    # Coach payouts (paid this period)
    payout_agg = await db.coach_payouts.aggregate([
        {"$match": {"period": period, "is_deleted": {"$ne": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$calculated_amount"}}},
    ]).to_list(1)
    coach_payouts = float(payout_agg[0]["total"]) if payout_agg else 0.0

    net_profit = monthly_income - expenses - coach_payouts

    # Student/coach counts
    students = await db.students.count_documents({"is_deleted": {"$ne": True}, "status": "active"})
    coaches = await db.users.count_documents({"role": "coach", "status": "active"})
    active_sessions = await db.sessions.count_documents({"status": "active", "is_deleted": {"$ne": True}})

    # Attendance summary for the period (current month so far)
    att_agg = await db.attendance.aggregate([
        {"$match": {"date": {"$gte": month_start}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]).to_list(10)
    att = {a["_id"]: a["count"] for a in att_agg}
    att_total = sum(att.values()) or 1
    att_rate = round(100 * (att.get("present", 0) + att.get("late", 0)) / att_total, 1)

    # Profit trend (last 6 months)
    trend = []
    base = datetime.strptime(period + "-01", "%Y-%m-%d")
    for i in range(5, -1, -1):
        y = base.year
        m = base.month - i
        while m <= 0:
            m += 12
            y -= 1
        p = f"{y:04d}-{m:02d}"
        rev_agg = await db.payments.aggregate([
            {"$match": {"period": p, "status": "paid", "is_deleted": {"$ne": True}}},
            {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
        ]).to_list(1)
        rev = float(rev_agg[0]["total"]) if rev_agg else 0.0
        exp_month_start = f"{p}-01"
        next_month = (datetime.strptime(exp_month_start, "%Y-%m-%d") + timedelta(days=32)).strftime("%Y-%m-01")
        e_agg = await db.expenses.aggregate([
            {"$match": {"date": {"$gte": exp_month_start, "$lt": next_month}, "is_deleted": {"$ne": True}}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        e = float(e_agg[0]["total"]) if e_agg else 0.0
        trend.append({"period": p, "revenue": round(rev, 2), "expenses": round(e, 2), "profit": round(rev - e, 2)})

    # Upcoming classes (next 7 days based on days_of_week)
    today = datetime.now(timezone.utc)
    upcoming = []
    sess_cursor = db.sessions.find({"status": "active", "is_deleted": {"$ne": True}}).limit(50)
    sessions = await sess_cursor.to_list(50)
    day_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for s in sessions:
        s["id"] = str(s.pop("_id"))
        for d in range(0, 7):
            day_name = day_map[(today + timedelta(days=d)).weekday()]
            if day_name in s.get("days_of_week", []):
                upcoming.append({
                    "session_id": s["id"],
                    "name": s["name"],
                    "date": (today + timedelta(days=d)).strftime("%Y-%m-%d"),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                    "location": s.get("location"),
                })
    upcoming.sort(key=lambda x: (x["date"], x.get("start_time") or ""))

    # Session profitability
    session_rows = []
    for s in sessions:
        rev_agg = await db.payments.aggregate([
            {"$match": {"session_id": s["id"], "period": period, "status": "paid", "is_deleted": {"$ne": True}}},
            {"$group": {"_id": None, "total": {"$sum": "$final_amount"}}},
        ]).to_list(1)
        rev = float(rev_agg[0]["total"]) if rev_agg else 0.0
        enr = await db.enrollments.count_documents({"session_id": s["id"], "status": "active"})
        cap = int(s.get("max_students", 0) or 0)
        util = round(100 * enr / cap, 1) if cap > 0 else 0
        session_rows.append({"id": s["id"], "name": s["name"], "enrolled": enr,
                             "capacity": cap, "utilization": util, "revenue": round(rev, 2)})
    session_rows.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "period": period,
        "kpis": {
            "monthly_income": round(monthly_income, 2),
            "expected_revenue": round(expected_revenue, 2),
            "collected_revenue": round(monthly_income, 2),
            "waived_value": round(waived_value, 2),
            "expenses": round(expenses, 2),
            "coach_payouts": round(coach_payouts, 2),
            "net_profit": round(net_profit, 2),
            "pending_total": round(pending_total, 2),
            "pending_count": pending_count,
            "students": students,
            "coaches": coaches,
            "active_sessions": active_sessions,
            "attendance_rate": att_rate,
        },
        "trend": trend,
        "upcoming": upcoming[:10],
        "session_profitability": session_rows[:10],
    }


@router.get("/dashboard/coach")
async def coach_dashboard(coach=Depends(require_roles("coach"))):
    db = get_db()
    sessions = await db.sessions.find({"coach_id": coach["id"], "is_deleted": {"$ne": True}}).to_list(200)
    sess_ids = [str(s["_id"]) for s in sessions]
    students = await db.enrollments.count_documents({"session_id": {"$in": sess_ids}, "status": "active"})
    # next 7-day upcoming
    today = datetime.now(timezone.utc)
    day_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    upcoming = []
    for s in sessions:
        sid = str(s["_id"])
        for d in range(0, 7):
            day_name = day_map[(today + timedelta(days=d)).weekday()]
            if day_name in s.get("days_of_week", []):
                upcoming.append({
                    "session_id": sid,
                    "name": s["name"],
                    "date": (today + timedelta(days=d)).strftime("%Y-%m-%d"),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                    "location": s.get("location"),
                })
    upcoming.sort(key=lambda x: (x["date"], x.get("start_time") or ""))

    # current month payout
    period = _current_period()
    payout = await db.coach_payouts.find_one({"coach_id": coach["id"], "period": period})
    payout_amount = payout["calculated_amount"] if payout else 0
    payout_status = payout["status"] if payout else "not_calculated"

    return {
        "kpis": {
            "sessions_count": len(sessions),
            "students_count": students,
            "current_payout": payout_amount,
            "payout_status": payout_status,
        },
        "upcoming": upcoming[:10],
    }


@router.get("/dashboard/parent")
async def parent_dashboard(parent=Depends(require_roles("parent"))):
    db = get_db()
    children = await db.students.find({"parent_user_id": parent["id"], "is_deleted": {"$ne": True}}).to_list(20)
    child_ids = [str(c["_id"]) for c in children]
    enr_count = await db.enrollments.count_documents({"student_id": {"$in": child_ids}, "status": "active"})
    period = _current_period()
    pending = await db.payments.aggregate([
        {"$match": {"parent_user_id": parent["id"], "status": "pending", "is_deleted": {"$ne": True}}},
        {"$group": {"_id": None, "total": {"$sum": "$final_amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    pending_total = float(pending[0]["total"]) if pending else 0
    pending_count = int(pending[0]["count"]) if pending else 0

    # next 7-day classes
    today = datetime.now(timezone.utc)
    day_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    enrolls = await db.enrollments.find({"student_id": {"$in": child_ids}, "status": "active"}).to_list(200)
    sess_ids = list({e["session_id"] for e in enrolls})
    sessions_by_id = {}
    if sess_ids:
        async for s in db.sessions.find({"_id": {"$in": [ObjectId(x) for x in sess_ids]}}):
            sessions_by_id[str(s["_id"])] = s
    upcoming = []
    for e in enrolls:
        s = sessions_by_id.get(e["session_id"])
        if not s:
            continue
        for d in range(0, 7):
            day_name = day_map[(today + timedelta(days=d)).weekday()]
            if day_name in s.get("days_of_week", []):
                upcoming.append({
                    "session_name": s["name"],
                    "date": (today + timedelta(days=d)).strftime("%Y-%m-%d"),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                    "location": s.get("location"),
                })
    upcoming.sort(key=lambda x: (x["date"], x.get("start_time") or ""))

    return {
        "kpis": {
            "children": len(children),
            "active_enrollments": enr_count,
            "pending_total": round(pending_total, 2),
            "pending_count": pending_count,
        },
        "upcoming": upcoming[:10],
    }


# ----------------- /api/reports -----------------
def _csv_response(headers: list, rows: list, filename: str):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/reports/revenue.csv")
async def report_revenue(period: str | None = None, admin=Depends(require_roles("admin"))):
    db = get_db()
    q: dict = {"status": "paid", "is_deleted": {"$ne": True}}
    if period:
        q["period"] = period
    cursor = db.payments.find(q).sort("payment_date", -1)
    rows = []
    async for p in cursor:
        student = await db.students.find_one({"_id": ObjectId(p["student_id"])}) if p.get("student_id") else None
        session = await db.sessions.find_one({"_id": ObjectId(p["session_id"])}) if p.get("session_id") else None
        rows.append([
            p.get("period"),
            f"{student['first_name']} {student['last_name']}" if student else "",
            session["name"] if session else "",
            p.get("amount"), p.get("discount"), p.get("final_amount"),
            p.get("payment_method"), p.get("payment_date"),
        ])
    return _csv_response(
        ["Period", "Student", "Session", "Amount", "Discount", "Final", "Method", "Date"],
        rows, "revenue.csv",
    )


@router.get("/reports/pending-payments.csv")
async def report_pending(admin=Depends(require_roles("admin"))):
    db = get_db()
    cursor = db.payments.find({"status": "pending", "is_deleted": {"$ne": True}})
    rows = []
    async for p in cursor:
        student = await db.students.find_one({"_id": ObjectId(p["student_id"])}) if p.get("student_id") else None
        session = await db.sessions.find_one({"_id": ObjectId(p["session_id"])}) if p.get("session_id") else None
        parent = await db.users.find_one({"_id": ObjectId(p["parent_user_id"])}) if p.get("parent_user_id") else None
        rows.append([
            p.get("period"),
            f"{student['first_name']} {student['last_name']}" if student else "",
            session["name"] if session else "",
            parent.get("email") if parent else "",
            p.get("final_amount"),
        ])
    return _csv_response(
        ["Period", "Student", "Session", "Parent Email", "Amount Due"],
        rows, "pending-payments.csv",
    )


@router.get("/reports/attendance.csv")
async def report_attendance(admin=Depends(require_roles("admin"))):
    db = get_db()
    rows = []
    async for a in db.attendance.find().sort("date", -1).limit(5000):
        student = await db.students.find_one({"_id": ObjectId(a["student_id"])}) if a.get("student_id") else None
        session = await db.sessions.find_one({"_id": ObjectId(a["session_id"])}) if a.get("session_id") else None
        rows.append([
            a.get("date"),
            session["name"] if session else "",
            f"{student['first_name']} {student['last_name']}" if student else "",
            a.get("status"),
            a.get("notes", ""),
        ])
    return _csv_response(
        ["Date", "Session", "Student", "Status", "Notes"],
        rows, "attendance.csv",
    )


@router.get("/reports/coach-payouts.csv")
async def report_payouts(admin=Depends(require_roles("admin"))):
    db = get_db()
    rows = []
    async for p in db.coach_payouts.find({"is_deleted": {"$ne": True}}).sort("period", -1):
        coach = await db.users.find_one({"_id": ObjectId(p["coach_id"])}) if p.get("coach_id") else None
        rows.append([
            p.get("period"),
            coach.get("name", coach.get("email")) if coach else "",
            p.get("rule_type"),
            p.get("calculated_amount"),
            p.get("status"),
            p.get("approved_at", ""),
            p.get("paid_at", ""),
        ])
    return _csv_response(
        ["Period", "Coach", "Rule", "Amount", "Status", "Approved", "Paid"],
        rows, "coach-payouts.csv",
    )


@router.get("/reports/profit.csv")
async def report_profit(admin=Depends(require_roles("admin"))):
    db = get_db()
    # Aggregate revenue per period
    rev_agg = await db.payments.aggregate([
        {"$match": {"status": "paid", "is_deleted": {"$ne": True}}},
        {"$group": {"_id": "$period", "total": {"$sum": "$final_amount"}}},
    ]).to_list(1000)
    rev_map = {r["_id"]: r["total"] for r in rev_agg}
    exp_agg = await db.expenses.aggregate([
        {"$match": {"is_deleted": {"$ne": True}}},
        {"$group": {"_id": {"$substr": ["$date", 0, 7]}, "total": {"$sum": "$amount"}}},
    ]).to_list(1000)
    exp_map = {r["_id"]: r["total"] for r in exp_agg}
    periods = sorted(set(list(rev_map.keys()) + list(exp_map.keys())))
    rows = []
    for p in periods:
        rev = rev_map.get(p, 0)
        exp = exp_map.get(p, 0)
        rows.append([p, rev, exp, rev - exp])
    return _csv_response(["Period", "Revenue", "Expenses", "Profit"], rows, "profit.csv")


# ----------------- /api/audit-logs -----------------
@router.get("/audit-logs")
async def list_audit_logs(limit: int = 200, admin=Depends(require_roles("admin"))):
    db = get_db()
    cursor = db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(limit)
