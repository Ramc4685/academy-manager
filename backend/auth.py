import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request, Response, Depends
from fastapi.concurrency import run_in_threadpool
from bson import ObjectId
from db import get_db

try:
    import firebase_admin
    from firebase_admin import auth as firebase_admin_auth, credentials as firebase_admin_credentials
except ImportError:  # pragma: no cover
    firebase_admin = None
    firebase_admin_auth = None
    firebase_admin_credentials = None

_firebase_app = None


def _ensure_firebase_app():
    global _firebase_app
    if firebase_admin is None:
        raise HTTPException(
            status_code=500,
            detail="firebase-admin is required for Firebase auth",
        )
    if _firebase_app is not None:
        return _firebase_app
    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app
    cred_path = os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
    cred = None
    if cred_json:
        import json
        cred = firebase_admin_credentials.Certificate(json.loads(cred_json))
    elif cred_path:
        cred = firebase_admin_credentials.Certificate(cred_path)
    options = {"projectId": firebase_project_id()}
    if cred is not None:
        _firebase_app = firebase_admin.initialize_app(cred, options)
    else:
        # ApplicationDefault works on Fly/GCP with metadata; for verification-only
        # paths the project ID is sufficient with Application Default Credentials.
        try:
            cred = firebase_admin_credentials.ApplicationDefault()
            _firebase_app = firebase_admin.initialize_app(cred, options)
        except Exception:
            _firebase_app = firebase_admin.initialize_app(options=options)
    return _firebase_app

JWT_ALGORITHM = "HS256"
ACCESS_MIN = 60 * 12  # 12 hours
REFRESH_DAYS = 7


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def firebase_auth_enabled() -> bool:
    return _env_bool("FIREBASE_AUTH_ENABLED")


def firebase_project_id() -> str:
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        raise HTTPException(
            status_code=500,
            detail="Firebase auth is not configured",
        )
    return project_id


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


def _cookie_options() -> dict:
    secure_env = os.environ.get("COOKIE_SECURE")
    if secure_env is None:
        secure = os.environ.get("APP_ENV", "").lower() in {"production", "prod"}
    else:
        secure = secure_env.lower() in {"1", "true", "yes", "on"}
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "none" if secure else "lax",
        "path": "/",
    }


def set_auth_cookies(response: Response, access: str, refresh: str):
    opts = _cookie_options()
    response.set_cookie("access_token", access, max_age=ACCESS_MIN * 60, **opts)
    response.set_cookie("refresh_token", refresh, max_age=REFRESH_DAYS * 86400, **opts)


def clear_auth_cookies(response: Response):
    opts = _cookie_options()
    response.delete_cookie("access_token", path=opts["path"], secure=opts["secure"], samesite=opts["samesite"])
    response.delete_cookie("refresh_token", path=opts["path"], secure=opts["secure"], samesite=opts["samesite"])


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _serialize_auth_user(user: dict) -> dict:
    user["id"] = str(user["_id"])
    user.pop("_id", None)
    user.pop("password_hash", None)
    return user


def _verify_firebase_token(token: str) -> dict:
    _ensure_firebase_app()
    try:
        return firebase_admin_auth.verify_id_token(token, check_revoked=True)
    except firebase_admin_auth.RevokedIdTokenError:
        raise HTTPException(status_code=401, detail="Firebase token revoked")
    except firebase_admin_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Firebase token expired")
    except firebase_admin_auth.UserDisabledError:
        raise HTTPException(status_code=403, detail="Firebase user disabled")
    except (firebase_admin_auth.InvalidIdTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid Firebase token")


def _identity_provider(payload: dict) -> str:
    firebase_claim = payload.get("firebase") or {}
    return (firebase_claim.get("sign_in_provider") or "").lower()


async def get_firebase_identity(request: Request) -> dict:
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = await run_in_threadpool(_verify_firebase_token, token)
    auth_uid = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    email = (payload.get("email") or "").lower()
    if not auth_uid or not email:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")
    return {
        "auth_uid": auth_uid,
        "email": email,
        "name": payload.get("name") or payload.get("display_name") or "",
        "email_verified": bool(payload.get("email_verified")),
        "sign_in_provider": _identity_provider(payload),
    }


def _require_verified_identity(identity: dict) -> None:
    """Block any password-provider identity that hasn't verified email.

    Google / Apple / phone providers carry their own verification, so
    `email_verified` is always True for them. Only `password` users can
    arrive here unverified.
    """
    if identity.get("email_verified"):
        return
    if identity.get("sign_in_provider") == "password":
        raise HTTPException(
            status_code=403,
            detail="Email verification is required before this account can access the portal",
        )


async def _get_current_firebase_user(request: Request) -> dict:
    identity = await get_firebase_identity(request)
    _require_verified_identity(identity)
    auth_uid = identity["auth_uid"]
    email = identity["email"]

    db = get_db()
    user = await db.users.find_one(
        {"auth_provider": "firebase", "auth_uid": auth_uid},
    )
    if user is None and email:
        user = await db.users.find_one({"email": email})
        if user and user.get("auth_uid") and user.get("auth_uid") != auth_uid:
            raise HTTPException(
                status_code=401,
                detail="Firebase user mismatch",
            )
        if user and not user.get("auth_uid"):
            # Link the existing Mongo user to this Firebase identity.
            # Email verification is already enforced by _require_verified_identity above.
            now = datetime.now(timezone.utc).isoformat()
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "auth_provider": "firebase",
                        "auth_uid": auth_uid,
                        "email_verified": True,
                        "updated_at": now,
                    },
                },
            )
            user["auth_provider"] = "firebase"
            user["auth_uid"] = auth_uid
            user["email_verified"] = True
            user["updated_at"] = now

    if not user or user.get("status") in ("suspended", "deleted"):
        raise HTTPException(status_code=401, detail="User not found")
    return _serialize_auth_user(user)


async def delete_firebase_user(auth_uid: str) -> None:
    """Best-effort deletion of a Firebase user (used by backend-side rollbacks)."""
    if firebase_admin_auth is None or not auth_uid:
        return
    try:
        _ensure_firebase_app()
        await run_in_threadpool(firebase_admin_auth.delete_user, auth_uid)
    except Exception:
        # Rollback should never mask the original failure.
        pass


async def _get_current_local_user(request: Request) -> dict:
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
    return _serialize_auth_user(user)


async def get_current_user(request: Request) -> dict:
    if firebase_auth_enabled():
        return await _get_current_firebase_user(request)
    return await _get_current_local_user(request)


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
