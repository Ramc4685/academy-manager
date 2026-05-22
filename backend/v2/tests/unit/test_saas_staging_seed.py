"""Unit tests for the local SaaS staging seed helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


def _load_seed_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "seed_saas_staging.py"
    spec = importlib.util.spec_from_file_location("seed_saas_staging_for_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owner_password_file_keeps_existing_single_owner_credential(tmp_path: Path) -> None:
    module = _load_seed_module()
    creds_file = tmp_path / "saas-staging-credentials.json"
    creds_file.write_text(
        json.dumps(
            {
                "owner_email": "admin@acme-saas-staging.dev",
                "owner_password": "acme-secret",
            }
        )
    )
    module.LOCAL_CREDS_DIR = tmp_path
    module.LOCAL_CREDS_FILE = creds_file

    assert module._load_or_create_owner_password("admin@acme-saas-staging.dev") == "acme-secret"


def test_owner_password_file_generates_distinct_credentials_per_owner(
    tmp_path: Path,
) -> None:
    module = _load_seed_module()
    creds_file = tmp_path / "saas-staging-credentials.json"
    creds_file.write_text(
        json.dumps(
            {
                "owner_email": "admin@acme-saas-staging.dev",
                "owner_password": "acme-secret",
            }
        )
    )
    module.LOCAL_CREDS_DIR = tmp_path
    module.LOCAL_CREDS_FILE = creds_file
    module._generate_password = lambda: "blno-secret"

    password = module._load_or_create_owner_password("admin@blno-badminton.dev")

    assert password == "blno-secret"
    data = json.loads(creds_file.read_text())
    assert data["owners"]["admin@acme-saas-staging.dev"]["owner_password"] == "acme-secret"
    assert data["owners"]["admin@blno-badminton.dev"]["owner_password"] == "blno-secret"
