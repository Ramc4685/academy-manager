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

from backend.v2.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = REPO_ROOT / "frontend/lib/api/openapi.snapshot.json"


def _render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def test_openapi_snapshot_matches_backend() -> None:
    current = _render()
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.write_text(current, encoding="utf-8")
    committed = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
    assert committed == current, (
        "frontend/lib/api/openapi.snapshot.json is out of date with the backend API. "
        "Run: UPDATE_OPENAPI_SNAPSHOT=1 pytest backend/v2/tests/structural/test_openapi_snapshot.py "
        "&& (cd frontend && pnpm generate:api), then commit both files and fix any frontend type errors."
    )
