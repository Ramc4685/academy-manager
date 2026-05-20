"""Auth + Invites + Users routes."""
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId

from models import (
    RegisterIn, LoginIn, InviteIn, AcceptInviteIn, ForgotPasswordIn,
    ResetPasswordIn, UpdateUserIn, ResetUserPasswordIn,
)
from auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user, require_roles,
    check_lockout, record_failed, clear_attempts, log_audit, _secret,
    JWT_ALGORITHM, firebase_auth_enabled, get_firebase_identity,
    delete_firebase_user,
)


def _reject_when_firebase_enabled():
    if firebase_auth_enabled():
        raise HTTPException(
            status_code=410,
            detail="Legacy password auth is disabled. Use Firebase sign-in.",
        )


def _require_verified_signup(identity: dict) -> None:
    if identity.get("email_verified"):
        return
    if identity.get("sign_in_provider") == "password":
        raise HTTPException(
            status_code=403,
            detail="Verify your email address before completing registration.",
        )
from db import get_db
from services.enrollment_service import (
    capacity_snapshot,
    create_enrollment_with_capacity,
    release_session_seat,
    reserve_session_seat,
)
from services.billing_proration import persist_legacy_snapshot, prorated_first_month_quote
from services.waitlist_service import join_waitlist
from services.waiver_service import record_waiver_acceptance, waiver_fields
import jwt as pyjwt

router = APIRouter()


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _invoice_number(prefix: str = "INV") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


async def _create_registration_payment(db, enrollment_id: str, enrollment: dict, session: dict) -> str:
    now = datetime.now(timezone.utc)
    period = _current_period()
    quote = prorated_first_month_quote(
        session=session,
        enrollment={
            **enrollment,
            "_id": enrollment_id,
            "created_at": enrollment.get("created_at") or now.isoformat(),
        },
        period=period,
        calculated_at=now,
        calculated_by="registration",
    )
    snapshot_id = None
    if quote is not None:
        amount = quote.final_amount_cents / 100
        snapshot_id = await persist_legacy_snapshot(
            db,
            quote=quote,
            enrollment={**enrollment, "_id": enrollment_id},
            session=session,
            period=period,
        )
    else:
        amount = float(session.get("monthly_price", 0) or 0)
    doc = {
        "parent_user_id": enrollment["parent_user_id"],
        "student_id": enrollment["student_id"],
        "enrollment_id": enrollment_id,
        "session_id": enrollment["session_id"],
        "period": _current_period(),
        "amount": amount,
        "discount": 0,
        "final_amount": amount,
        "calculation_snapshot_id": snapshot_id,
        "status": "pending",
        "payment_date": None,
        "payment_method": None,
        "marked_by": None,
        "notes": "Registration payment",
        "payment_type": "registration",
        "invoice_number": _invoice_number("REG"),
        "invoice_created_at": datetime.now(timezone.utc).isoformat(),
        "refunded_amount": 0,
        "refund_status": "none",
        "refunds": [],
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.payments.insert_one(doc)
    return str(result.inserted_id)


def _serialize_user(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "email": u["email"],
        "name": u.get("name", ""),
        "phone": u.get("phone", ""),
        "role": u["role"],
        "status": u.get("status", "active"),
    }


# ----------------- /api/auth -----------------
@router.post("/auth/register")
async def register(body: RegisterIn, request: Request, response: Response):
    db = get_db()
    email = body.email.lower()
    firebase_identity = None
    try:
        if firebase_auth_enabled():
            firebase_identity = await get_firebase_identity(request)
            if firebase_identity["email"] != email:
                raise HTTPException(status_code=400, detail="Firebase login email does not match registration email")
            _require_verified_signup(firebase_identity)
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        if firebase_identity:
            await delete_firebase_user(firebase_identity["auth_uid"])
        raise
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "email": email,
        "name": body.name,
        "phone": body.phone or "",
        "role": "parent",
        "status": "active",
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }
    if firebase_identity:
        doc.update({
            "auth_provider": "firebase",
            "auth_uid": firebase_identity["auth_uid"],
            "email_verified": True,
        })
    else:
        doc["password_hash"] = hash_password(body.password)
    result = await db.users.insert_one(doc)
    user_id = str(result.inserted_id)
    if not firebase_auth_enabled():
        access = create_access_token(user_id, email, "parent")
        refresh = create_refresh_token(user_id)
        set_auth_cookies(response, access, refresh)
    return {"id": user_id, "email": email, "name": body.name, "role": "parent", "status": "active"}


class PublicRegisterIn(BaseModel):
    parent_name: str
    parent_email: EmailStr
    parent_phone: Optional[str] = ""
    password: str = Field(min_length=6)
    # child
    child_first_name: str
    child_last_name: str
    child_dob: str
    child_skill_level: str = "beginner"
    emergency_contact_name: str
    emergency_contact_phone: str
    medical_notes: Optional[str] = ""
    t_shirt_size: Optional[str] = ""
    previous_experience: Optional[str] = ""
    waiver_accepted: bool
    session_id: Optional[str] = None  # optional pick at registration


@router.post("/auth/register-full")
async def register_full(body: PublicRegisterIn, request: Request, response: Response):
    """Single-shot parent registration + child + optional enrollment.
    Replaces the Google Form workflow."""
    if not body.waiver_accepted:
        raise HTTPException(status_code=400, detail="Waiver must be accepted")
    db = get_db()
    email = body.parent_email.lower()
    firebase_identity = None
    try:
        if firebase_auth_enabled():
            firebase_identity = await get_firebase_identity(request)
            if firebase_identity["email"] != email:
                raise HTTPException(status_code=400, detail="Firebase login email does not match registration email")
            _require_verified_signup(firebase_identity)
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=400, detail="Email already registered. Please log in.")
    except HTTPException:
        if firebase_identity:
            await delete_firebase_user(firebase_identity["auth_uid"])
        raise
    seat_reserved = False
    waitlist_requested = False
    if body.session_id:
        try:
            await reserve_session_seat(db, body.session_id)
            seat_reserved = True
        except HTTPException as exc:
            if exc.status_code == 400 and exc.detail == "Session is full":
                waitlist_requested = True
            else:
                raise
    now = datetime.now(timezone.utc).isoformat()
    parent_id = None
    student_id = None
    enrollment_id = None
    waitlist_id = None
    payment_id = None
    try:
        # parent user
        parent_doc = {
            "email": email,
            "name": body.parent_name, "phone": body.parent_phone or "",
            "role": "parent", "status": "active", "must_change_password": False,
            "created_at": now, "updated_at": now,
        }
        if firebase_identity:
            parent_doc.update({
                "auth_provider": "firebase",
                "auth_uid": firebase_identity["auth_uid"],
                "email_verified": True,
            })
        else:
            parent_doc["password_hash"] = hash_password(body.password)
        pr = await db.users.insert_one(parent_doc)
        parent_id = str(pr.inserted_id)
        # student
        try:
            from datetime import datetime as dt
            d = dt.fromisoformat(body.child_dob)
            age = (dt.now() - d).days // 365
        except Exception:
            age = 0
        stu_doc = {
            "first_name": body.child_first_name, "last_name": body.child_last_name,
            "dob": body.child_dob, "age": age, "skill_level": body.child_skill_level,
            "emergency_contact_name": body.emergency_contact_name,
            "emergency_contact_phone": body.emergency_contact_phone,
            "medical_notes": body.medical_notes or "",
            "t_shirt_size": body.t_shirt_size or "",
            "previous_experience": body.previous_experience or "",
            "parent_user_id": parent_id, "status": "active",
            "is_deleted": False, "created_at": now,
            **waiver_fields(parent_id),
        }
        sr = await db.students.insert_one(stu_doc)
        student_id = str(sr.inserted_id)
        await record_waiver_acceptance(
            db,
            student_id=student_id,
            parent_user_id=parent_id,
            accepted_by_user_id=parent_id,
        )
        if body.session_id:
            if seat_reserved:
                enrollment_id, _ = await create_enrollment_with_capacity(
                    db,
                    session_id=body.session_id,
                    student={**stu_doc, "_id": sr.inserted_id},
                    actor_role="parent",
                    billing_type="Standard",
                    seat_reserved=True,
                    approval_status="pending_payment",
                )
                session = await db.sessions.find_one({"_id": ObjectId(body.session_id)})
                payment_id = await _create_registration_payment(
                    db,
                    enrollment_id,
                    {
                        "parent_user_id": parent_id,
                        "student_id": student_id,
                        "session_id": body.session_id,
                    },
                    session or {},
                )
            elif waitlist_requested:
                waitlist_id, _ = await join_waitlist(
                    db,
                    session_id=body.session_id,
                    student={**stu_doc, "_id": sr.inserted_id},
                    requested_by=parent_id,
                )
    except Exception:
        if payment_id:
            await db.payments.delete_one({"_id": ObjectId(payment_id)})
        if enrollment_id:
            await db.enrollments.delete_one({"_id": ObjectId(enrollment_id)})
        if student_id:
            await db.students.delete_one({"_id": ObjectId(student_id)})
        if parent_id:
            await db.users.delete_one({"_id": ObjectId(parent_id)})
        if seat_reserved and body.session_id:
            await release_session_seat(db, body.session_id)
        if firebase_identity:
            await delete_firebase_user(firebase_identity["auth_uid"])
        raise
    # Auto-login
    if not firebase_auth_enabled():
        access = create_access_token(parent_id, email, "parent")
        refresh = create_refresh_token(parent_id)
        set_auth_cookies(response, access, refresh)
    # Notify admins
    async for admin_user in db.users.find({"role": "admin", "status": "active"}):
        await db.notifications.insert_one({
            "user_id": str(admin_user["_id"]),
            "type": "registration",
            "title": "New parent registration",
            "message": f"{body.parent_name} registered {body.child_first_name} {body.child_last_name}"
                       + (" (enrolled in session)" if enrollment_id else " (joined waitlist)" if waitlist_id else ""),
            "related_entity": parent_id,
            "read": False,
            "created_at": now,
        })
    # Optional welcome email (fire-and-forget)
    try:
        from routers.email_routes import send_email, _wrap
        html = _wrap(
            f"<h2 style='margin:0 0 12px 0;'>Welcome, {body.parent_name}!</h2>"
            f"<p>{body.child_first_name} is registered with BLno Badminton Academy.</p>"
            + ("<p>Your child's enrollment is pending admin approval. We'll notify you soon.</p>" if enrollment_id else "")
            + ("<p>Your child is on the waitlist. We'll notify you when a spot opens.</p>" if waitlist_id else "")
        )
        import asyncio
        asyncio.create_task(send_email(email, "Welcome to BLno Badminton Academy", html))
    except Exception:
        pass
    return {
        "id": parent_id, "email": email, "name": body.parent_name,
        "role": "parent", "status": "active",
        "student_id": student_id, "enrollment_id": enrollment_id,
        "waitlist_id": waitlist_id, "waitlisted": bool(waitlist_id),
        "payment_id": payment_id,
    }


@router.get("/auth/public-sessions")
async def public_sessions():
    """Active, enrollable sessions for the public registration form."""
    db = get_db()
    cursor = db.sessions.find({"status": "active", "is_deleted": {"$ne": True}})
    items = await cursor.to_list(50)
    out = []
    for s in items:
        capacity = await capacity_snapshot(db, s)
        out.append({
            "id": str(s["_id"]),
            "name": s["name"],
            "skill_level": s.get("skill_level"),
            "age_group": s.get("age_group"),
            "days_of_week": s.get("days_of_week"),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "monthly_price": s.get("monthly_price"),
            **capacity,
        })
    return out


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    _reject_when_firebase_enabled()
    db = get_db()
    email = body.email.lower()
    ident = f"{request.client.host if request.client else 'x'}:{email}"
    await check_lockout(ident)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await record_failed(ident)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") in ("suspended", "deleted"):
        raise HTTPException(status_code=403, detail="Account inactive")
    await clear_attempts(ident)
    uid = str(user["_id"])
    access = create_access_token(uid, email, user["role"])
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return _serialize_user(user)


@router.post("/auth/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    _reject_when_firebase_enabled()
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = pyjwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access = create_access_token(str(user["_id"]), user["email"], user["role"])
    new_refresh = create_refresh_token(str(user["_id"]))
    set_auth_cookies(response, access, new_refresh)
    return {"ok": True}


@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    _reject_when_firebase_enabled()
    db = get_db()
    user = await db.users.find_one({"email": body.email.lower()})
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": str(user["_id"]),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "used": False,
        })
        frontend = __import__("os").environ.get("FRONTEND_URL", "")
        reset_url = f"{frontend}/reset-password/{token}" if frontend else f"/reset-password/{token}"
        try:
            from routers.email_routes import send_email, _wrap
            await send_email(
                user["email"],
                "Reset your BLno Academy password",
                _wrap(
                    "<h2 style='margin:0 0 12px 0;'>Reset your password</h2>"
                    "<p>Use the secure link below to set a new password. This link expires in one hour.</p>"
                    f"<p><a href='{reset_url}' style='display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px;'>Reset password</a></p>"
                ),
            )
        except Exception:
            pass
    return {"ok": True}


@router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordIn):
    _reject_when_firebase_enabled()
    db = get_db()
    rec = await db.password_reset_tokens.find_one({"token": body.token, "used": False})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or used token")
    if rec["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expired")
    await db.users.update_one(
        {"_id": ObjectId(rec["user_id"])},
        {"$set": {"password_hash": hash_password(body.password)}},
    )
    await db.password_reset_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return {"ok": True}


# ----------------- /api/invites -----------------
@router.post("/invites")
async def create_invite(body: InviteIn, request: Request, admin=Depends(require_roles("admin"))):
    if body.role not in ("coach", "parent"):
        raise HTTPException(status_code=400, detail="Role must be coach or parent")
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="User with this email already exists")
    token = secrets.token_urlsafe(24)
    doc = {
        "email": email,
        "role": body.role,
        "name": body.name or "",
        "token": token,
        "invited_by": admin["id"],
        "status": "pending",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.invites.insert_one(doc)
    await log_audit(admin, "invite", "user", email, f"Invited {body.role} {email}")
    frontend = __import__("os").environ.get("FRONTEND_URL", "")
    return {
        "email": email,
        "role": body.role,
        "token": token,
        "accept_url": f"{frontend}/accept-invite/{token}",
        "status": "pending",
    }


@router.get("/invites")
async def list_invites(admin=Depends(require_roles("admin"))):
    db = get_db()
    cursor = db.invites.find({"status": "pending"}, {"_id": 0})
    return await cursor.to_list(500)


@router.delete("/invites/{token}")
async def cancel_invite(token: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    result = await db.invites.delete_one({"token": token})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"ok": True}


@router.get("/invites/info/{token}")
async def invite_info(token: str):
    db = get_db()
    inv = await db.invites.find_one({"token": token, "status": "pending"}, {"_id": 0, "token": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    return inv


@router.post("/invites/accept/{token}")
async def accept_invite(token: str, body: AcceptInviteIn, request: Request, response: Response):
    db = get_db()
    inv = await db.invites.find_one({"token": token, "status": "pending"})
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found or already used")

    firebase_identity = None
    if firebase_auth_enabled():
        firebase_identity = await get_firebase_identity(request)
        if firebase_identity["email"] != inv["email"].lower():
            raise HTTPException(
                status_code=403,
                detail="Sign in with the invited email address to accept this invite.",
            )
        _require_verified_signup(firebase_identity)
    else:
        if not body.password:
            raise HTTPException(status_code=400, detail="Password required")

    try:
        if await db.users.find_one({"email": inv["email"]}):
            raise HTTPException(status_code=400, detail="User already exists")
    except HTTPException:
        if firebase_identity:
            await delete_firebase_user(firebase_identity["auth_uid"])
        raise

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "email": inv["email"],
        "name": body.name or inv.get("name") or inv["email"].split("@")[0],
        "phone": body.phone or "",
        "role": inv["role"],
        "status": "active",
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }
    if firebase_identity:
        doc.update({
            "auth_provider": "firebase",
            "auth_uid": firebase_identity["auth_uid"],
            "email_verified": True,
        })
    else:
        doc["password_hash"] = hash_password(body.password)

    result = await db.users.insert_one(doc)
    await db.invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "accepted"}})
    uid = str(result.inserted_id)
    if not firebase_auth_enabled():
        access = create_access_token(uid, doc["email"], doc["role"])
        refresh = create_refresh_token(uid)
        set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": doc["email"], "name": doc["name"], "role": doc["role"], "status": "active"}


# ----------------- /api/users -----------------
@router.get("/users")
async def list_users(role: str | None = None, admin=Depends(require_roles("admin"))):
    db = get_db()
    q: dict = {"status": {"$ne": "deleted"}}
    if role:
        q["role"] = role
    cursor = db.users.find(q, {"password_hash": 0}).sort("created_at", -1)
    users = await cursor.to_list(1000)
    for u in users:
        u["id"] = str(u.pop("_id"))
    return users


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    u = await db.users.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u["id"] = str(u.pop("_id"))
    return u


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "email" in update:
        update["email"] = update["email"].lower()
        # ensure email isn't taken
        existing = await db.users.find_one({"email": update["email"], "_id": {"$ne": ObjectId(user_id)}})
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update})
    await log_audit(admin, "update", "user", user_id, f"updated {list(update.keys())}")
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, body: ResetUserPasswordIn, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": hash_password(body.password),
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(admin, "reset_password", "user", user_id, "")
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_roles("admin"))):
    db = get_db()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(admin, "delete", "user", user_id, "soft delete user")
    return {"ok": True}
