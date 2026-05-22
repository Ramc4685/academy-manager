"""Structural checks for SaaS production wiring."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_v2_main_wires_real_membership_repo_for_saas_mode() -> None:
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "MongoMembershipRepository" in source
    assert "if settings.saas_mode" in source
    assert "_LegacyUserMembershipAdapter" in source


def test_v2_main_composes_bootstrap_academy_use_case() -> None:
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "BootstrapAcademy" in source
    assert "MongoTenantBootstrapStore" in source
    assert "app.state.bootstrap_academy" in source


def test_fly_health_check_uses_v2_health_endpoint() -> None:
    fly_toml = (REPO_ROOT / "backend/fly.toml").read_text(encoding="utf-8")

    assert 'path = "/api/v2/healthz"' in fly_toml
    assert 'path = "/api/health"' not in fly_toml
