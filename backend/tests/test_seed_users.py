"""Phase 2.1 — seed_users must not create a known-credential admin.

When FIREBASE_AUTH_ENABLED=true, the admin account is provisioned but
must NOT carry a password_hash (dead weight + backdoor if Firebase is
ever disabled).

When Firebase is disabled, admin still gets a password_hash, but only if
ADMIN_PASSWORD is set explicitly — never from the hardcoded default.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "academy_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-32-bytes-long-x")

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import db as db_module  # noqa: E402


@pytest.fixture
def mongo():
    client = AsyncMongoMockClient()
    fake_db = client["academy_test"]
    db_module._client = client
    db_module._db = fake_db
    yield fake_db
    db_module._client = None
    db_module._db = None


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "FIREBASE_AUTH_ENABLED",
        "ADMIN_PASSWORD",
        "ADMIN_EMAIL",
        "SEED_DEMO_ACCOUNTS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    yield


def test_firebase_mode_admin_has_no_password_hash(mongo, monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "ShouldBeIgnored123!")

    asyncio.run(db_module.seed_users())

    admin = asyncio.run(mongo.users.find_one({"email": "owner@example.com"}))
    assert admin is not None
    assert "password_hash" not in admin
    assert admin["role"] == "admin"
    assert admin["status"] == "active"


def test_legacy_mode_requires_explicit_admin_password(mongo, monkeypatch):
    # FIREBASE_AUTH_ENABLED not set; ADMIN_PASSWORD not set.
    # seed_users must refuse to plant a default password.
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        asyncio.run(db_module.seed_users())

    admin = asyncio.run(mongo.users.find_one({"email": "owner@example.com"}))
    assert admin is None


def test_legacy_mode_with_explicit_admin_password_seeds_user(mongo, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "Operator-set-password-1!")

    asyncio.run(db_module.seed_users())

    admin = asyncio.run(mongo.users.find_one({"email": "owner@example.com"}))
    assert admin is not None
    assert admin["role"] == "admin"
    assert "password_hash" in admin
