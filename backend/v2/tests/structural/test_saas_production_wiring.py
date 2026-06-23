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


def test_v2_main_uses_runtime_academy_for_single_academy_launch_composition() -> None:
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "runtime_academy_id = _runtime_academy_id(settings)" in source
    assert "_LegacyUserMembershipAdapter(users_repo, runtime_academy_id)" in source
    assert "default_academy_id=runtime_academy_id" in source
    assert "app.state.primary_academy_id = settings.primary_academy_id" in source


def test_v2_main_does_not_bypass_stripe_webhook_signatures_from_raw_env() -> None:
    source = (REPO_ROOT / "backend/v2/main.py").read_text(encoding="utf-8")

    assert "APP_ENV" not in source
    assert "skip_signature_verify=" not in source


def test_v2_main_uses_fake_stripe_gateway_for_non_prod_without_secrets(monkeypatch) -> None:
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
    from backend.v2.main import _build_stripe
    from backend.v2.shared.config.settings import Settings

    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("V2_STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("V2_STRIPE_WEBHOOK_SECRET", raising=False)

    settings = Settings(env="dev", _env_file=None)

    assert isinstance(_build_stripe(settings), FakeStripeGateway)


def test_fly_health_check_uses_v2_health_endpoint() -> None:
    fly_toml = (REPO_ROOT / "backend/fly.toml").read_text(encoding="utf-8")

    assert 'path = "/api/v2/healthz"' in fly_toml
    assert 'path = "/api/health"' not in fly_toml


def test_backend_runtime_entrypoints_start_v2_app_directly() -> None:
    dockerfile = (REPO_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    fly_toml = (REPO_ROOT / "backend/fly.toml").read_text(encoding="utf-8")

    assert "backend.v2.main:app" in dockerfile
    assert "backend.server:app" not in dockerfile
    assert "server:app" not in dockerfile
    assert "V2_ENABLED" not in fly_toml


def test_local_test_stack_uses_v2_app_and_health_endpoint() -> None:
    script = (REPO_ROOT / "scripts/local_test_stack.sh").read_text(encoding="utf-8")

    assert "backend.v2.main:app" in script
    assert "uvicorn server:app" not in script
    assert "V2_ENABLED" not in script
    assert "/api/v2/healthz" in script
    assert "/api/health" not in script


def test_saas_staging_runs_v2_migrations_on_boot() -> None:
    compose = (REPO_ROOT / "docker-compose.saas.yml").read_text(encoding="utf-8")

    assert 'V2_RUN_MIGRATIONS_ON_BOOT: "true"' in compose


def test_ci_installs_single_backend_requirements_file() -> None:
    workflow = (REPO_ROOT / ".github/workflows/production.yml").read_text(encoding="utf-8")

    assert "backend/requirements.txt" in workflow
    assert "requirements-v2.txt" not in workflow
    assert "Legacy backend tests" not in workflow


def test_v2_app_configures_cors_for_frontend_origin(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.v2.main import create_app
    from backend.v2.shared.config import get_settings

    monkeypatch.setenv("V2_CORS_ORIGINS", "https://academy.courtmastr.com")
    get_settings.cache_clear()

    client = TestClient(create_app())
    response = client.options(
        "/api/v2/me",
        headers={
            "Origin": "https://academy.courtmastr.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://academy.courtmastr.com"


def test_registered_business_routes_are_v2_only() -> None:
    from backend.v2.main import create_app

    app = create_app()
    framework_paths = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    route_paths = {
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", "").startswith("/")
    }
    business_paths = route_paths - framework_paths

    assert "/api/v2/healthz" in business_paths
    assert "/api/v2/parent/webhooks/stripe" in business_paths
    assert business_paths
    assert all(path.startswith("/api/v2/") or path == "/api/v2/me" for path in business_paths)
    assert "/api/health" not in route_paths
    assert "/api/webhook/stripe" not in route_paths
