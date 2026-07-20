"""Ensures test Firebase emulator users exist. Safe to call on every boot.

Creates users via the Firebase Auth REST API and marks email verified via the
Admin SDK (same pattern as seed_local.py). Silently skips existing users.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EMULATOR = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "firebase-emulator:9099")
PROJECT = "academy-courtmastr"
API_KEY = "test"

ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "CHANGE_ME")
COACH_PASSWORD = os.environ.get("SEED_COACH_PASSWORD", "CHANGE_ME")
PARENT_PASSWORD = os.environ.get("SEED_PARENT_PASSWORD", "CHANGE_ME")

TEST_USERS = [
    ("admin@example.test", ADMIN_PASSWORD, "Admin"),
    ("coach1@example.test", COACH_PASSWORD, "Coach One"),
    ("coach2@example.test", COACH_PASSWORD, "Coach Two"),
    ("parent1@example.test", PARENT_PASSWORD, "Parent One"),
]

_firebase_admin_app = None


def _admin_app():
    global _firebase_admin_app
    if _firebase_admin_app is not None:
        return _firebase_admin_app
    import firebase_admin
    from firebase_admin import credentials as firebase_admin_credentials

    options = {"projectId": PROJECT}
    if not firebase_admin._apps:
        try:
            cred = firebase_admin_credentials.ApplicationDefault()
            _firebase_admin_app = firebase_admin.initialize_app(cred, options)
        except Exception:
            _firebase_admin_app = firebase_admin.initialize_app(options=options)
    else:
        _firebase_admin_app = firebase_admin.get_app()
    return _firebase_admin_app


def _mark_verified(uid: str) -> None:
    """Mark the user email verified via Admin SDK."""
    _admin_app()
    from firebase_admin import auth as firebase_admin_auth
    firebase_admin_auth.update_user(uid, email_verified=True)


def ensure_user(email: str, password: str, display_name: str) -> str:
    base = f"http://{EMULATOR}/identitytoolkit.googleapis.com/v1"
    data = json.dumps({"email": email, "password": password, "displayName": display_name}).encode()
    req = urllib.request.Request(
        f"{base}/accounts:signUp?key={API_KEY}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            uid = resp["localId"]
        _mark_verified(uid)
        return "created"
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        msg = body.get("error", {}).get("message", "")
        if "EMAIL_EXISTS" not in msg:
            raise RuntimeError(f"{e.code} {msg}")

    # User already exists — look up UID and ensure email is verified.
    _admin_app()
    from firebase_admin import auth as firebase_admin_auth
    user = firebase_admin_auth.get_user_by_email(email)
    if not user.email_verified:
        _mark_verified(user.uid)
        return "verified"
    return "exists"


def main() -> None:
    created = skipped = 0
    for email, password, display_name in TEST_USERS:
        try:
            result = ensure_user(email, password, display_name)
            if result == "created":
                print(f"  created  {email}")
                created += 1
            elif result == "verified":
                print(f"  verified {email}")
                created += 1
            else:
                skipped += 1
        except Exception as exc:
            print(f"  ERROR for {email}: {exc}", file=sys.stderr)

    if created == 0 and skipped > 0:
        print(f"  All {skipped} Firebase emulator users already present and verified.")
    else:
        print(f"  {created} created, {skipped} already existed.")


if __name__ == "__main__":
    main()
