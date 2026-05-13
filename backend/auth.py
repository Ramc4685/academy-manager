import os
import jwt
import uuid
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request, Response, Depends
from bson import ObjectId
from db import get_db

JWT_ALGORITHM = "HS256"
ACCESS_MIN = 60 * 12  # 12 hours
REFRESH_DAYS = 7


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MIN),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none",
                        max_age=ACCESS_MIN * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none",
                        max_age=REFRESH_DAYS * 86400, path="/")


def clear_auth_cookies(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get("status") == "deleted":
        raise HTTPException(status_code=401, detail="User not found")
    user["id"] = str(user["_id"])
    user.pop("_id", None)
    user.pop("password_hash", None)
    return user


def require_roles(*roles: str):
    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _checker


# Brute force helpers
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


async def check_lockout(identifier: str):
    db = get_db()
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if rec and rec.get("locked_until"):
        if datetime.fromisoformat(rec["locked_until"]) > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")


async def record_failed(identifier: str):
    db = get_db()
    rec = await db.login_attempts.find_one({"identifier": identifier}) or {"attempts": 0}
    attempts = rec.get("attempts", 0) + 1
    update = {"attempts": attempts, "updated_at": datetime.now(timezone.utc).isoformat()}
    if attempts >= LOCKOUT_THRESHOLD:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        update["attempts"] = 0
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)


async def clear_attempts(identifier: str):
    db = get_db()
    await db.login_attempts.delete_one({"identifier": identifier})


# Audit log helper
async def log_audit(user: dict, action: str, entity_type: str, entity_id: str, summary: str = ""):
    db = get_db()
    await db.audit_logs.insert_one({
        "user_id": user["id"],
        "user_email": user["email"],
        "role": user["role"],
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
