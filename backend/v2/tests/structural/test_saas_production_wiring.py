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


def test_v2_main_wires_platform_audit_service() -> None:
    """Issue #79 regression. The audit routes raise 503 when
    ``app.state.platform_audit`` is None, so the lifespan MUST construct
    a real ``PlatformAuditService`` backed by Mongo at startup."""
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "PlatformAuditService" in source
    assert "MongoPlatformAuditRepository" in source
    assert "app.state.platform_audit" in source


def test_v2_main_wires_tenant_governance_service() -> None:
    """Issue #78 regression. The governance routes raise 503 when
    ``app.state.tenant_governance`` is None, so the lifespan MUST
    construct a real ``TenantGovernanceService`` backed by Mongo at
    startup."""
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "TenantGovernanceService" in source
    assert "MongoGovernanceStore" in source
    assert "app.state.tenant_governance" in source


def test_v2_main_wires_lifecycle_audit_recorder() -> None:
    """Issue #80 regression. The ``TenantLifecycleService`` MUST be
    constructed with an ``audit_recorder`` so each state transition
    leaves a ``platform_audit_events`` row."""
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "audit_recorder=" in source
    assert "TenantLifecycleService" in source


def test_v2_main_passes_saas_mode_into_register_public_parent() -> None:
    """Issue #81 regression. The parent registration use case MUST be
    constructed with ``saas_mode`` + ``memberships`` so the resolved
    tenant flows through instead of silently using
    ``default_academy_id``."""
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "RegisterPublicParent(" in source
    assert "saas_mode=settings.saas_mode" in source
    assert "memberships=membership_repo" in source


def test_fly_health_check_uses_v2_health_endpoint() -> None:
    fly_toml = (REPO_ROOT / "backend/fly.toml").read_text(encoding="utf-8")

    assert 'path = "/api/v2/healthz"' in fly_toml
    assert 'path = "/api/health"' not in fly_toml
