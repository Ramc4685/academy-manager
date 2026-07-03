"""Behavior tests for the shared local-only Mongo URL guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[4] / "scripts" / "dev"


def _load_script_module(stem: str) -> ModuleType:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(
        f"{stem}_for_guard_test", SCRIPT_DIR / f"{stem}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _guard() -> ModuleType:
    return _load_script_module("mongo_guard")


@pytest.mark.parametrize(
    "url",
    [
        "mongodb://127.0.0.1:27017",
        "mongodb://127.0.0.1:27017/academy_manager_saas_staging",
        "mongodb://localhost:27017",
        "mongodb://mongo:27017/academy_manager_saas_staging",
        "mongodb://[::1]:27017",
        "mongodb://user:pass@127.0.0.1:27017/db?authSource=admin",
        "mongodb://127.0.0.1:27017,localhost:27018",
    ],
)
def test_guard_accepts_local_urls(url: str) -> None:
    _guard().assert_local_mongo_url(url)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "mongodb://prod-cluster.example.com:27017",
        "mongodb://academy-manager-prod.internal:27017/academy_manager",
        "mongodb://10.0.0.5:27017",
        "mongodb://user:pass@prod-host:27017",
    ],
)
def test_guard_rejects_non_local_hosts(url: str) -> None:
    with pytest.raises(SystemExit, match="REFUSING"):
        _guard().assert_local_mongo_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "mongodb://127.0.0.1,prod-host.example.com:27017/db",
        "mongodb://prod-host.example.com,127.0.0.1:27017/db",
        "mongodb://localhost:27017,mongo:27017,prod-host:27017",
        "mongodb://user:pass@127.0.0.1:27017,prod-host:27017/db",
    ],
)
def test_guard_rejects_seed_lists_with_any_non_local_host(url: str) -> None:
    with pytest.raises(SystemExit, match="REFUSING"):
        _guard().assert_local_mongo_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "mongodb+srv://cluster0.abc123.mongodb.net/app",
        "mongodb+srv://localhost/app",
        "postgresql://127.0.0.1:5432/db",
    ],
)
def test_guard_rejects_non_plain_mongodb_schemes(url: str) -> None:
    with pytest.raises(SystemExit, match="REFUSING"):
        _guard().assert_local_mongo_url(url)


def test_guard_rejects_empty_or_malformed_hosts() -> None:
    guard = _guard()
    with pytest.raises(SystemExit, match="REFUSING"):
        guard.assert_local_mongo_url("mongodb://")
    with pytest.raises(SystemExit, match="REFUSING"):
        guard.assert_local_mongo_url("mongodb://127.0.0.1,,mongo/db")


@pytest.mark.parametrize(
    "stem",
    [
        "scale_blno_staging",
        "export_local_auth_inventory_env",
        "cleanup_stale_tuition_subscriptions",
    ],
)
def test_destructive_scripts_use_shared_guard(stem: str) -> None:
    module = _load_script_module(stem)
    assert module.assert_local_mongo_url.__module__ == "mongo_guard"


@pytest.mark.parametrize("stem", ["scale_blno_staging", "export_local_auth_inventory_env"])
def test_migrated_scripts_still_reject_remote_urls(stem: str) -> None:
    module = _load_script_module(stem)
    with pytest.raises(SystemExit, match="REFUSING"):
        module.assert_local_mongo_url("mongodb://127.0.0.1,prod-host.example.com/db")
