"""The committed OpenAPI snapshot must match what the backend serves.

The frontend generates its API types from this snapshot, so a stale snapshot
lets a renamed or removed field reach production without failing typecheck.
Refresh it with:

    UPDATE_OPENAPI_SNAPSHOT=1 pytest backend/v2/tests/structural/test_openapi_snapshot.py
    cd frontend && pnpm generate:api
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.v2 import main
from backend.v2.shared.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = REPO_ROOT / "frontend/lib/api/openapi.snapshot.json"


# Every route the frontend can call, whatever the deployment's feature flags.
_ALL_ROUTES = {
    "enable_platform_routes": True,
    "enable_owner_role": True,
    "enable_student_login": True,
}


def _render(monkeypatch: pytest.MonkeyPatch) -> str:
    settings = get_settings().model_copy(update=_ALL_ROUTES)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return json.dumps(main.create_app().openapi(), indent=2, sort_keys=True) + "\n"


def test_openapi_snapshot_matches_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _render(monkeypatch)
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.write_text(current, encoding="utf-8")
    committed = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
    assert committed == current, (
        "frontend/lib/api/openapi.snapshot.json is out of date with the backend API. "
        "Run: UPDATE_OPENAPI_SNAPSHOT=1 pytest backend/v2/tests/structural/test_openapi_snapshot.py "
        "&& (cd frontend && pnpm generate:api), then commit both files and fix any frontend type errors."
    )
