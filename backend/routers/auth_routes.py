"""Auth + Invites + Users routes."""
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from bson import ObjectId

from models import (
    RegisterIn, LoginIn, InviteIn, AcceptInviteIn, ForgotPasswordIn,
    ResetPasswordIn, UpdateUserIn,
)
from auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user, require_roles,
    check_lockout, record_failed, clear_attempts, log_audit, _secret,
    JWT_ALGORITHM,
)
from db import get_db
import jwt as pyjwt

router = APIRouter()


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
async def register(body: RegisterIn, response: Response):
    db = get_db()
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name,
        "phone": body.phone or "",
        "role": "parent",
        "status": "active",
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.users.insert_one(doc)
    user_id = str(result.inserted_id)
    access = create_access_token(user_id, email, "parent")
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)
    return {"id": user_id, "email": email, "name": body.name, "role": "parent", "status": "active"}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
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
        print(f"[PASSWORD RESET] {body.email}: token={token}")
    return {"ok": True}


@router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordIn):
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
async def accept_invite(token: str, body: AcceptInviteIn, response: Response):
    db = get_db()
    inv = await db.invites.find_one({"token": token, "status": "pending"})
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    if await db.users.find_one({"email": inv["email"]}):
        raise HTTPException(status_code=400, detail="User already exists")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "email": inv["email"],
        "password_hash": hash_password(body.password),
        "name": body.name or inv.get("name") or inv["email"].split("@")[0],
        "phone": body.phone or "",
        "role": inv["role"],
        "status": "active",
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.users.insert_one(doc)
    await db.invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "accepted"}})
    uid = str(result.inserted_id)
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
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update})
    await log_audit(admin, "update", "user", user_id, f"updated {list(update.keys())}")
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
