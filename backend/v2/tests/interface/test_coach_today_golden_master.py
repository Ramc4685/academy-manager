"""Golden-master test for GET /api/v2/coach/today.

Updating the baseline requires explicit env var ``UPDATE_BASELINES=1`` and a
PR review. This keeps schema drift from sneaking in.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).parent / "baselines" / "coach_today_2026-05-16.json"


def _normalize(value: Any) -> Any:
    """Replace volatile timestamps with their ISO-format Z-suffix string."""
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, str) and len(value) > 18 and value.endswith("+00:00"):
        return value.replace("+00:00", "Z")
    return value


def _utc(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_coach_today_matches_baseline(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    actual = _normalize(r.json())

    if os.environ.get("UPDATE_BASELINES") == "1":
        BASELINE_PATH.write_text(json.dumps(actual, indent=2) + "\n")
        return

    expected = json.loads(BASELINE_PATH.read_text())
    assert actual == expected, (
        "Coach today response does not match baseline.\n"
        f"Expected: {json.dumps(expected, indent=2)}\n"
        f"Actual:   {json.dumps(actual, indent=2)}\n"
        "Re-run with UPDATE_BASELINES=1 if this change is intentional, "
        "and have the baseline diff reviewed in your PR."
    )
