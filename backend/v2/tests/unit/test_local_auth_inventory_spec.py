import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
LOCAL_AUTH_SPEC = REPO_ROOT / "frontend/e2e/specs/local-auth-inventory.spec.ts"
LOCAL_AUTH_CONFIG = REPO_ROOT / "frontend/playwright.local-auth.config.ts"
MANIFEST = REPO_ROOT / "docs/qa/2026-06-28-production-scale-local-inventory-manifest.json"
LOCAL_AUTH_ENV_EXPORT = REPO_ROOT / "scripts/dev/export_local_auth_inventory_env.py"


def test_local_auth_inventory_spec_uses_documented_manifest() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    assert "2026-06-28-production-scale-local-inventory-manifest.json" in spec
    assert "staticManifestRoutes" in spec
    assert "dynamicManifestRoutes" in spec
    assert "routesForRole" in spec
    assert "resolveDynamicRoute" in spec
    assert "const ADMIN_ROUTES" not in spec
    assert "const COACH_ROUTES" not in spec
    assert "const PARENT_ROUTES" not in spec


def test_local_auth_inventory_spec_generates_one_test_per_route() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    assert "public routes render meaningful content" not in spec
    assert "seeded admin route inventory renders without framework errors" not in spec
    assert "seeded coach route inventory renders without framework errors" not in spec
    assert "seeded parent route inventory renders without framework errors" not in spec
    assert "test(`public route ${href} renders meaningful content`" in spec
    assert 'test.describe("seeded admin route inventory"' in spec
    assert 'test.describe("seeded coach route inventory"' in spec
    assert 'test.describe("seeded parent route inventory"' in spec


def test_local_auth_config_defaults_to_documented_saas_staging_host() -> None:
    config = LOCAL_AUTH_CONFIG.read_text()

    assert 'process.env.LOCAL_AUTH_BASE_URL ?? "http://blno.localhost:3000"' in config


def test_local_auth_config_rejects_non_local_base_urls() -> None:
    config = LOCAL_AUTH_CONFIG.read_text()

    assert "assertLocalAuthBaseURL(" in config
    assert "URL(rawBaseURL)" in config
    assert 'url.protocol !== "http:"' in config
    assert '"localhost"' in config
    assert '"127.0.0.1"' in config
    assert '"blno.localhost"' in config


def test_local_auth_config_writes_audit_evidence_artifacts() -> None:
    config = LOCAL_AUTH_CONFIG.read_text()

    assert "LOCAL_AUTH_EVIDENCE_DIR" in config
    assert "/tmp/academy-manager-local/evidence/20260628-production-scale-audit" in config
    assert "outputDir:" in config
    assert '"json"' in config
    assert "playwright-report.json" in config
    assert "playwright-html" in config
    assert 'trace: "retain-on-failure"' in config
    assert 'screenshot: "only-on-failure"' in config
    assert 'video: "retain-on-failure"' in config


def test_local_auth_inventory_spec_declares_seeded_dynamic_route_env_vars() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    for env_name in (
        "LOCAL_AUTH_ADMIN_SESSION_ID",
        "LOCAL_AUTH_ADMIN_STUDENT_ID",
        "LOCAL_AUTH_ADMIN_USER_ID",
        "LOCAL_AUTH_ADMIN_PAYOUT_ID",
        "LOCAL_AUTH_ADMIN_APPLICATION_ID",
        "LOCAL_AUTH_ADMIN_WAIVER_ID",
        "LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID",
        "LOCAL_AUTH_ADMIN_PROGRAM_ID",
        "LOCAL_AUTH_COACH_OCCURRENCE_ID",
        "LOCAL_AUTH_COACH_SESSION_ID",
        "LOCAL_AUTH_COACH_SESSION_DATE",
        "LOCAL_AUTH_COACH_STUDENT_ID",
    ):
        assert env_name in spec


def test_dynamic_manifest_routes_have_exact_playwright_env_contract() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()
    manifest = json.loads(MANIFEST.read_text())
    # Mirrors UNSEEDED_ROLES in the spec: roles the local-auth sweep cannot
    # sign in as, so they need no dynamic-route env contract.
    unseeded_roles = {"proxy", "platform"}
    dynamic_routes = sorted(
        entry["route"]
        for entry in manifest["routes"]
        if "[" in entry["route"] and entry["role"] not in unseeded_roles
    )

    assert "const DYNAMIC_ROUTE_ENV_CONTRACT" in spec
    assert "route.startsWith" not in spec
    for route in dynamic_routes:
        assert f'"{route}":' in spec


def test_dynamic_route_env_contract_matches_exporter_names() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()
    exporter = LOCAL_AUTH_ENV_EXPORT.read_text()
    required_env_names = {
        "LOCAL_AUTH_ADMIN_SESSION_ID",
        "LOCAL_AUTH_ADMIN_STUDENT_ID",
        "LOCAL_AUTH_ADMIN_USER_ID",
        "LOCAL_AUTH_ADMIN_PAYOUT_ID",
        "LOCAL_AUTH_ADMIN_APPLICATION_ID",
        "LOCAL_AUTH_ADMIN_WAIVER_ID",
        "LOCAL_AUTH_ADMIN_WAIVER_SIGNATURE_ID",
        "LOCAL_AUTH_ADMIN_PROGRAM_ID",
        "LOCAL_AUTH_COACH_OCCURRENCE_ID",
        "LOCAL_AUTH_COACH_SESSION_ID",
        "LOCAL_AUTH_COACH_SESSION_DATE",
        "LOCAL_AUTH_COACH_STUDENT_ID",
    }

    for env_name in required_env_names:
        assert env_name in spec
        assert env_name in exporter


def test_local_auth_inventory_spec_adds_seeded_date_to_coach_session_routes() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    assert "withSeededCoachDate" in spec
    assert "LOCAL_AUTH_COACH_SESSION_DATE" in spec
    assert '"/coach/sessions/[id]"' in spec
    assert '"/coach/sessions/[id]/skills"' in spec
    assert "requiresCoachSessionDate: true" in spec
    assert "LOCAL_AUTH_COACH_OCCURRENCE_ID" in spec


def test_local_auth_inventory_spec_captures_network_failures_and_pass_screenshots() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    assert "collectRuntimeIssues" in spec
    assert 'page.on("requestfailed"' in spec
    assert 'page.on("response"' in spec
    assert "response.status() < 500" in spec
    assert "runtimeIssues.networkFailures" in spec
    assert "testInfo.attach" in spec
    assert "page.screenshot({ fullPage: true })" in spec


def test_local_auth_inventory_spec_waits_for_content_and_ignores_navigation_aborts() -> None:
    spec = LOCAL_AUTH_SPEC.read_text()

    assert "expect.poll" in spec
    assert "loading shell" in spec
    assert "net::ERR_ABORTED" in spec
    assert "return;" in spec
