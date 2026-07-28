"""Static coverage checks for the production-scale local audit manifest."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "qa"
    / "2026-06-28-production-scale-local-inventory-manifest.json"
)
REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND_APP = Path(__file__).resolve().parents[4] / "frontend" / "app"


def test_inventory_manifest_covers_required_route_surface() -> None:
    data = json.loads(MANIFEST.read_text())
    routes = {entry["route"]: entry for entry in data["routes"]}

    required_routes = {
        "/",
        "/login",
        "/register",
        "/post-login",
        "/admin",
        "/admin/sessions",
        "/admin/sessions/[id]",
        "/admin/students",
        "/admin/students/[studentId]",
        "/admin/users",
        "/admin/payments",
        "/admin/billing-health",
        "/admin/payouts/[payoutId]",
        "/admin/pathway/[programId]",
        "/coach/today",
        "/coach/sessions/[id]",
        "/coach/sessions/[id]/skills",
        "/parent/onboarding",
        "/parent/payments",
        "/parent/checkout/return",
        "/calendar",
        "/messages",
    }

    assert len(routes) >= 49
    assert required_routes <= set(routes)


def test_inventory_manifest_matches_frontend_app_route_tree() -> None:
    data = json.loads(MANIFEST.read_text())
    manifest_routes = {entry["route"] for entry in data["routes"]}

    app_routes = {
        _route_from_app_file(path)
        for pattern in ("page.tsx", "route.ts")
        for path in FRONTEND_APP.rglob(pattern)
    }

    assert manifest_routes == app_routes


def test_each_inventory_route_has_controls_states_risks_and_acceptance() -> None:
    data = json.loads(MANIFEST.read_text())
    allowed_roles = {"admin", "authenticated", "coach", "parent", "proxy", "public", "student"}

    for entry in data["routes"]:
        assert entry["role"] in allowed_roles, entry["route"]
        assert entry["source"], entry["route"]
        assert entry["workflows"], entry["route"]
        assert set(entry["controls"]) == {"buttons", "inputs", "modals"}, entry["route"]
        for control_type in ("buttons", "inputs", "modals"):
            controls = entry["controls"][control_type]
            assert isinstance(controls, list), (entry["route"], control_type)
            assert all(isinstance(item, str) and item for item in controls), (
                entry["route"],
                control_type,
            )
        assert entry["states"], entry["route"]
        assert entry["risk_edges"], entry["route"]
        assert entry["acceptance"], entry["route"]
        assert len(entry["acceptance"]) >= len(entry["workflows"]), entry["route"]
        assert len(entry["acceptance"]) >= len(entry["risk_edges"]), entry["route"]
        assert all(isinstance(item, str) and item for item in entry["workflows"]), entry["route"]
        assert all(isinstance(item, str) and item for item in entry["states"]), entry["route"]
        assert all(isinstance(item, str) and item for item in entry["risk_edges"]), entry["route"]
        assert all(isinstance(item, str) and item for item in entry["acceptance"]), entry["route"]


def test_manifest_covers_global_shell_surfaces() -> None:
    data = json.loads(MANIFEST.read_text())
    surfaces = {entry["surface"]: entry for entry in data["global_surfaces"]}

    assert {
        "admin shell navigation and tenant controls",
        "coach shell navigation and offline affordances",
        "parent shell navigation and update affordances",
    } <= set(surfaces)

    for entry in surfaces.values():
        assert entry["roles"], entry["surface"]
        assert entry["sources"], entry["surface"]
        assert entry["workflows"], entry["surface"]
        assert set(entry["controls"]) == {"buttons", "inputs", "modals"}, entry["surface"]
        assert entry["states"], entry["surface"]
        assert entry["risk_edges"], entry["surface"]
        assert entry["acceptance"], entry["surface"]
        assert len(entry["acceptance"]) >= len(entry["risk_edges"]), entry["surface"]
        for source in entry["sources"]:
            assert (REPO_ROOT / source).exists(), (entry["surface"], source)


def test_inventory_manifest_sources_are_existing_frontend_files() -> None:
    data = json.loads(MANIFEST.read_text())

    for entry in data["routes"]:
        source = REPO_ROOT / entry["source"]
        assert source.exists(), entry["route"]
        assert source.name in {"page.tsx", "route.ts"}, entry["route"]


def test_manifest_records_expected_roles_and_high_risk_state_categories() -> None:
    data = json.loads(MANIFEST.read_text())
    roles = {entry["role"] for entry in data["routes"]}
    all_states = " ".join(state.lower() for entry in data["routes"] for state in entry["states"])
    all_risks = " ".join(edge.lower() for entry in data["routes"] for edge in entry["risk_edges"])

    assert {"admin", "coach", "parent", "public", "authenticated", "proxy"} <= roles
    for state_keyword in (
        "loading",
        "empty",
        "error",
        "validation",
        "not found",
        "access denied",
        "conflict",
    ):
        assert state_keyword in all_states
    for risk_keyword in (
        "tenant",
        "wrong-role",
        "double",
        "stripe",
        "webhook",
        "stale",
        "race",
    ):
        assert risk_keyword in all_risks


def test_manifest_records_global_acceptance_and_data_gates() -> None:
    data = json.loads(MANIFEST.read_text())

    assert data["dataset"]["synthetic_scale"]["parents"] >= 250
    assert data["dataset"]["synthetic_scale"]["students"] >= 500
    assert data["dataset"]["synthetic_scale"]["invoices"] >= 1500
    assert data["dataset"]["synthetic_scale"]["payout_periods"] >= 1
    assert data["dataset"]["synthetic_scale"]["onboarding_applications"] >= 1
    assert data["dataset"]["synthetic_scale"]["waiver_templates"] >= 1
    assert data["dataset"]["synthetic_scale"]["waiver_signatures"] >= 1
    assert "explicit approval" in " ".join(data["approval_gates"]).lower()
    assert any("ledger" in item.lower() for item in data["billing_invariants"])


def _route_from_app_file(path: Path) -> str:
    route_parts = []
    for part in path.relative_to(FRONTEND_APP).parts[:-1]:
        if part.startswith("(") and part.endswith(")"):
            continue
        route_parts.append(part)
    return "/" + "/".join(route_parts) if route_parts else "/"
