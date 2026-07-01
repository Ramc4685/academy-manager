"""Unit tests for the stale tuition subscription cleanup utility."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "dev"
SCRIPT_PATH = SCRIPT_DIR / "cleanup_stale_tuition_subscriptions.py"


def _load_module() -> ModuleType:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(
        "cleanup_stale_tuition_subscriptions_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_filter_only_selects_stale_setup_bookkeeping_rows() -> None:
    module = _load_module()
    rows = [
        {
            "subscription_id": "sub-stale",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-1",
            "stripe_checkout_session_id": "cs_setup_1",
            "status": "incomplete",
        },
        {
            "subscription_id": "sub-live",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-2",
            "stripe_subscription_id": "sub_live_1",
            "stripe_checkout_session_id": "cs_live_1",
            "status": "active",
        },
        {
            "subscription_id": "sub-pending-but-linked",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-3",
            "stripe_checkout_session_id": "cs_pending_1",
            "status": "incomplete",
        },
        {
            "subscription_id": "sub-non-empty-placeholder",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-5",
            "stripe_subscription_id": "pending:cs_5",
            "stripe_checkout_session_id": "cs_pending_5",
            "status": "incomplete",
        },
        {
            "subscription_id": "sub-manual",
            "academy_id": "acad",
            "parent_id": "parent-1",
            "enrollment_id": "enr-4",
            "status": "incomplete",
        },
    ]
    enrollments = {
        "enr-1": {"enrollment_id": "enr-1", "stripe_subscription_id": None},
        "enr-2": {"enrollment_id": "enr-2", "stripe_subscription_id": "sub_live_1"},
        "enr-3": {"enrollment_id": "enr-3", "stripe_subscription_id": "sub_pending"},
        "enr-4": {"enrollment_id": "enr-4", "stripe_subscription_id": None},
        "enr-5": {"enrollment_id": "enr-5", "stripe_subscription_id": None},
    }

    candidates = module.select_cleanup_candidates(rows, enrollments)

    assert [row["subscription_id"] for row in candidates] == ["sub-stale"]


def test_delete_filter_targets_exact_candidate_ids() -> None:
    module = _load_module()

    assert module.delete_filter(["sub-stale", "sub-other"]) == {
        "subscription_id": {"$in": ["sub-stale", "sub-other"]},
        "stripe_subscription_id": {"$exists": False},
        "status": "incomplete",
    }


def test_apply_requires_explicit_cleanup_confirmation() -> None:
    module = _load_module()
    args = module.parse_args(["--mongo-url", "mongodb://example.test", "--apply"])

    with pytest.raises(SystemExit, match="confirm-delete-stale-subscriptions"):
        module.run(args)
