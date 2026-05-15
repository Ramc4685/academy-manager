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
    from routers.onboarding_routes import seed_waiver_version

    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.users.create_index(
        [("auth_provider", 1), ("auth_uid", 1)],
        unique=True,
        partialFilterExpression={
            "auth_provider": {"$type": "string"},
            "auth_uid": {"$type": "string"},
        },
    )
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
    await db.payments.create_index("stripe_payment_intent")
    await db.pause_requests.create_index([("enrollment_id", 1), ("period", 1), ("status", 1)])
    await db.pause_requests.create_index([("parent_user_id", 1), ("status", 1)])
    await db.coach_payouts.create_index([("coach_id", 1), ("period", 1)], unique=True)
    await db.stripe_webhook_events.create_index("event_id", unique=True)
    await db.payment_refunds.create_index("stripe_refund_id", unique=True)
    await db.payment_refunds.create_index("payment_id")
    await db.payment_refunds.create_index("created_at")

    # Onboarding applications
    await db.onboarding_applications.create_index("expires_at", expireAfterSeconds=0)
    await db.onboarding_applications.create_index("parent_user_id")
    await db.onboarding_applications.create_index("status")
    await db.onboarding_applications.create_index("stripe_checkout_session_id")

    # Waiver versions
    await db.waiver_versions.create_index("version", unique=True)
    await db.waiver_versions.create_index("effective_from")

    # Waiver acceptances
    await db.waiver_acceptances.create_index(
        [("parent_user_id", 1), ("child_id", 1), ("waiver_version", 1)],
        unique=True,
        partialFilterExpression={"child_id": {"$type": "string"}},
    )

    # Seed the current waiver version idempotently
    await seed_waiver_version(db)


def _firebase_mode() -> bool:
    return os.environ.get("FIREBASE_AUTH_ENABLED", "").lower() in ("1", "true", "yes")


async def seed_users():
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    demo_emails = ["coach@badminton.app", "parent@badminton.app"]

    if os.environ.get("SEED_DEMO_ACCOUNTS", "").lower() not in ("1", "true", "yes"):
        await db.users.update_many(
            {"email": {"$in": demo_emails}, "status": {"$ne": "deleted"}},
            {"$set": {"status": "deleted", "updated_at": now}},
        )

    firebase_mode = _firebase_mode()
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not firebase_mode and not admin_password:
        raise RuntimeError(
            "ADMIN_PASSWORD must be set explicitly when FIREBASE_AUTH_ENABLED is off."
        )

    accounts = [
        {
            "email": os.environ.get("ADMIN_EMAIL", "ramchand4685@gmail.com").lower(),
            "password": admin_password,
            "name": "Academy Admin",
            "role": "admin",
        }
    ]
    if os.environ.get("SEED_DEMO_ACCOUNTS", "").lower() in ("1", "true", "yes"):
        if firebase_mode:
            # Demo accounts in Firebase mode have no usable password locally —
            # they exist only as authorization rows that a Firebase signup will
            # link to. Operators wanting working demo logins must seed those
            # accounts in Firebase too.
            accounts.extend([
                {"email": "coach@badminton.app", "password": "", "name": "Coach Demo", "role": "coach"},
                {"email": "parent@badminton.app", "password": "", "name": "Parent Demo", "role": "parent"},
            ])
        else:
            accounts.extend([
                {"email": "coach@badminton.app", "password": "Coach@12345", "name": "Coach Demo", "role": "coach"},
                {"email": "parent@badminton.app", "password": "Parent@12345", "name": "Parent Demo", "role": "parent"},
            ])

    for acc in accounts:
        doc = {
            "email": acc["email"],
            "name": acc["name"],
            "phone": "",
            "role": acc["role"],
            "status": "active",
            "must_change_password": False,
            "updated_at": now,
        }
        existing = await db.users.find_one({"email": acc["email"]})
        if existing is None:
            doc["created_at"] = now
            if not firebase_mode and acc["password"]:
                doc["password_hash"] = _hash(acc["password"])
            await db.users.insert_one(doc)
        else:
            update = {
                "role": acc["role"],
                "status": "active",
                "updated_at": now,
            }
            if firebase_mode:
                # Strip any lingering legacy password hash so a known-credential
                # backdoor cannot exist on a Firebase-primary deployment.
                await db.users.update_one(
                    {"email": acc["email"]},
                    {"$set": update, "$unset": {"password_hash": ""}},
                )
            else:
                if acc["password"] and not _verify(acc["password"], existing.get("password_hash", "")):
                    update["password_hash"] = _hash(acc["password"])
                await db.users.update_one(
                    {"email": acc["email"]},
                    {"$set": update},
                )
