"""Read-only dry-run: which parents in an academy have a working login account,
and which need a non-Google login-invite email sent.

Every parent referenced by a student's roster is resolved through the *same*
membership-aware check the "Send login invite" button actually uses
(`composition/admin.py`'s `_MembershipAwareLoginInviteRecorder` ->
`MongoUserRepository.get_login_invite_user`): a `users` doc must exist, it
must carry a `firebase_uid`/`auth_uid`, and there must be an ACTIVE
`academy_memberships` row for it in this academy. That's a stricter check
than what the admin Users list/detail page uses (`get_admin_user`, which only
matches the legacy `users.academy_id` field) — which is exactly why some
parents render fine in the directory but 404 when you click "Send login
invite".

Never writes. Prints one JSON object: a summary count per `needs_action`
bucket, plus the full per-parent breakdown.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))


def _is_gmail(email: str) -> bool:
    return email.strip().lower().endswith("@gmail.com")


async def audit_parents(db: Any, *, academy_id: str) -> dict[str, Any]:
    parent_ids: set[str] = set()
    async for doc in db["students"].find(
        {"academy_id": academy_id}, {"parent_id": 1, "parent_user_id": 1}
    ):
        pid = doc.get("parent_id") or doc.get("parent_user_id")
        if pid:
            parent_ids.add(str(pid))

    rows: list[dict[str, Any]] = []
    for pid in sorted(parent_ids):
        or_filter: list[dict[str, Any]] = [
            {"user_id": pid},
            {"auth_uid": pid},
            {"firebase_uid": pid},
        ]
        user_doc = await db["users"].find_one({"$or": or_filter})
        if user_doc is None:
            rows.append(
                {
                    "parent_id": pid,
                    "has_user_doc": False,
                    "email": None,
                    "is_gmail": None,
                    "has_firebase_uid": False,
                    "has_active_membership": False,
                    "login_invite_sent_at": None,
                    "invite_button_works": False,
                    "needs_action": "create_account",
                }
            )
            continue

        email = str(user_doc.get("email") or "")
        firebase_uid = user_doc.get("firebase_uid") or user_doc.get("auth_uid")
        # Mirrors User._to_domain's user_id resolution in mongo_user_repo.py:
        # this is what load_auth_claims.py actually keys the login membership
        # check on -- NOT firebase_uid, which only gates the invite button.
        resolved_user_id = str(
            user_doc.get("user_id") or user_doc.get("auth_uid") or user_doc["_id"]
        )

        login_membership = await db["academy_memberships"].find_one(
            {
                "academy_id": academy_id,
                "user_id": resolved_user_id,
                "status": "active",
            }
        )
        can_login = login_membership is not None

        invite_membership = None
        if firebase_uid:
            invite_membership = await db["academy_memberships"].find_one(
                {
                    "academy_id": academy_id,
                    "user_id": str(firebase_uid),
                    "status": "active",
                }
            )
        invite_button_works = bool(firebase_uid) and invite_membership is not None
        is_gmail = _is_gmail(email) if email else None

        login_invite_sent_at = None
        for m in (login_membership, invite_membership):
            if m and m.get("login_invite_sent_at"):
                login_invite_sent_at = str(m["login_invite_sent_at"])
                break

        if not can_login:
            needs_action = "cannot_login_missing_membership"
        elif is_gmail:
            needs_action = "ok_google_signin"
        elif not invite_button_works:
            needs_action = "can_login_but_invite_button_broken"
        elif login_invite_sent_at:
            needs_action = "invite_already_sent"
        else:
            needs_action = "send_login_invite"

        rows.append(
            {
                "parent_id": pid,
                "resolved_user_id": resolved_user_id,
                "has_user_doc": True,
                "email": email,
                "is_gmail": is_gmail,
                "has_firebase_uid": bool(firebase_uid),
                "can_login": can_login,
                "invite_button_works": invite_button_works,
                "login_invite_sent_at": login_invite_sent_at,
                "needs_action": needs_action,
            }
        )

    summary: dict[str, int] = {}
    for row in rows:
        summary[row["needs_action"]] = summary.get(row["needs_action"], 0) + 1

    return {
        "academy_id": academy_id,
        "total_parents": len(rows),
        "summary": summary,
        "parents": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument(
        "--academy-id",
        default=(
            os.environ.get("PRIMARY_ACADEMY_ID")
            or os.environ.get("V2_PRIMARY_ACADEMY_ID")
            or "acad_blno_badminton"
        ),
    )
    args = parser.parse_args()

    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        db = client[args.db_name]
        result = await audit_parents(db, academy_id=args.academy_id)
    finally:
        client.close()

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
