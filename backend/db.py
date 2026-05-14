import os
import bcrypt
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _client


def get_db():
    global _db
    if _db is None:
        _db = get_client()[os.environ["DB_NAME"]]
    return _db


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


async def ensure_indexes():
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.invites.create_index("token", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    await db.users.create_index("stripe_customer_id")
    await db.enrollments.create_index([("session_id", 1), ("student_id", 1)], unique=True)
    await db.enrollments.create_index("stripe_subscription_id")
    await db.waitlist.create_index([("session_id", 1), ("status", 1), ("requested_at", 1)])
    await db.waitlist.create_index([("parent_user_id", 1), ("status", 1)])
    await db.waiver_acceptances.create_index([("student_id", 1), ("waiver_version", 1)])
    await db.attendance.create_index([("session_id", 1), ("student_id", 1), ("date", 1)], unique=True)
    await db.payments.create_index([("enrollment_id", 1), ("period", 1)], unique=True)
    await db.pause_requests.create_index([("enrollment_id", 1), ("period", 1), ("status", 1)])
    await db.pause_requests.create_index([("parent_user_id", 1), ("status", 1)])
    await db.coach_payouts.create_index([("coach_id", 1), ("period", 1)], unique=True)


async def seed_users():
    db = get_db()
    accounts = [
        {
            "email": os.environ.get("ADMIN_EMAIL", "admin@badminton.app").lower(),
            "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345"),
            "name": "Academy Admin",
            "role": "admin",
        },
        {
            "email": "coach@badminton.app",
            "password": "Coach@12345",
            "name": "Coach Demo",
            "role": "coach",
        },
        {
            "email": "parent@badminton.app",
            "password": "Parent@12345",
            "name": "Parent Demo",
            "role": "parent",
        },
    ]
    for acc in accounts:
        existing = await db.users.find_one({"email": acc["email"]})
        now = datetime.now(timezone.utc).isoformat()
        if existing is None:
            await db.users.insert_one({
                "email": acc["email"],
                "password_hash": _hash(acc["password"]),
                "name": acc["name"],
                "phone": "",
                "role": acc["role"],
                "status": "active",
                "must_change_password": False,
                "created_at": now,
                "updated_at": now,
            })
        elif not _verify(acc["password"], existing.get("password_hash", "")):
            await db.users.update_one(
                {"email": acc["email"]},
                {"$set": {"password_hash": _hash(acc["password"]), "updated_at": now}},
            )
