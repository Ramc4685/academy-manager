"""Application tests for clean SaaS academy bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
    BootstrapDomainConflict,
    BootstrapSlugConflict,
)


class FakeBootstrapStore:
    def __init__(self) -> None:
        self.academies: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.memberships: dict[tuple[str, str], dict[str, Any]] = {}
        self.settings: dict[str, dict[str, Any]] = {}
        self.billing_policies: dict[str, dict[str, Any]] = {}
        self.waivers: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, list[dict[str, Any]]] = {}
        self.feature_flags: dict[str, dict[str, Any]] = {}
        self.legacy_writes: list[dict[str, Any]] = []

    async def find_academy_by_slug(self, slug: str) -> dict[str, Any] | None:
        for academy in self.academies.values():
            if academy["slug"] == slug:
                return dict(academy)
        return None

    async def find_academy_by_domain(self, domain: str) -> dict[str, Any] | None:
        for academy in self.academies.values():
            if academy["primary_domain"] == domain:
                return dict(academy)
        return None

    async def create_academy(self, academy: dict[str, Any]) -> dict[str, Any]:
        self.academies[academy["academy_id"]] = dict(academy)
        return dict(academy)

    async def ensure_owner_user(self, user: dict[str, Any]) -> dict[str, Any]:
        email = user["normalized_email"]
        self.users.setdefault(email, dict(user))
        return dict(self.users[email])

    async def ensure_owner_membership(self, membership: dict[str, Any]) -> dict[str, Any]:
        key = (membership["academy_id"], membership["user_id"])
        self.memberships.setdefault(key, dict(membership))
        return dict(self.memberships[key])

    async def ensure_academy_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.settings.setdefault(settings["academy_id"], dict(settings))
        return dict(self.settings[settings["academy_id"]])

    async def ensure_billing_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        self.billing_policies.setdefault(policy["academy_id"], dict(policy))
        return dict(self.billing_policies[policy["academy_id"]])

    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]:
        self.waivers.setdefault(waiver["academy_id"], dict(waiver))
        return dict(self.waivers[waiver["academy_id"]])

    async def ensure_default_roles(self, academy_id: str, roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.roles.setdefault(academy_id, [dict(role) for role in roles])
        return [dict(role) for role in self.roles[academy_id]]

    async def ensure_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        self.feature_flags.setdefault(flags["academy_id"], dict(flags))
        return dict(self.feature_flags[flags["academy_id"]])


def _command(**overrides: object) -> BootstrapAcademyCommand:
    values: dict[str, object] = {
        "display_name": "North Shore Badminton",
        "slug": "North-Shore",
        "primary_domain": "North.example.COM",
        "owner_email": " Owner@Example.COM ",
        "owner_display_name": "Owner One",
        "timezone": "America/Chicago",
    }
    values.update(overrides)
    return BootstrapAcademyCommand(**values)  # type: ignore[arg-type]


def _use_case(store: FakeBootstrapStore) -> BootstrapAcademy:
    counters: dict[str, int] = {}
    now = datetime(2026, 5, 21, tzinfo=UTC)

    def _id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]:03d}"

    return BootstrapAcademy(store=store, id_factory=_id, clock=lambda: now)


@pytest.mark.asyncio
async def test_bootstrap_creates_tenant_owner_membership_and_defaults() -> None:
    store = FakeBootstrapStore()

    result = await _use_case(store).execute(_command())

    assert result.created is True
    assert result.academy_id == "acad_001"
    assert result.slug == "north-shore"
    assert result.primary_domain == "north.example.com"

    academy = store.academies[result.academy_id]
    assert academy["display_name"] == "North Shore Badminton"
    assert academy["owner_email"] == "owner@example.com"

    owner = store.users["owner@example.com"]
    assert owner["email"] == "owner@example.com"
    assert "academy_id" not in owner
    assert "roles" not in owner

    membership = store.memberships[(result.academy_id, owner["user_id"])]
    assert membership["roles"] == ["admin"]
    assert membership["status"] == "active"

    assert store.settings[result.academy_id]["timezone"] == "America/Chicago"
    assert store.billing_policies[result.academy_id]["currency"] == "usd"
    assert store.waivers[result.academy_id]["version"] == "v1"
    assert [role["role"] for role in store.roles[result.academy_id]] == [
        "admin",
        "coach",
        "parent",
    ]
    assert store.feature_flags[result.academy_id]["saas_v2_enabled"] is True
    assert store.legacy_writes == []


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_for_same_slug_domain_and_owner_email() -> None:
    store = FakeBootstrapStore()
    use_case = _use_case(store)

    first = await use_case.execute(_command())
    second = await use_case.execute(_command())

    assert first.academy_id == second.academy_id
    assert first.owner_user_id == second.owner_user_id
    assert first.membership_id == second.membership_id
    assert first.created is True
    assert second.created is False
    assert len(store.academies) == 1
    assert len(store.users) == 1
    assert len(store.memberships) == 1


@pytest.mark.asyncio
async def test_duplicate_slug_with_different_domain_or_owner_is_a_clear_conflict() -> None:
    store = FakeBootstrapStore()
    use_case = _use_case(store)
    await use_case.execute(_command())

    with pytest.raises(BootstrapSlugConflict, match="north-shore"):
        await use_case.execute(
            _command(primary_domain="other.example.com", owner_email="other@example.com")
        )


@pytest.mark.asyncio
async def test_duplicate_domain_with_different_slug_is_a_clear_conflict() -> None:
    store = FakeBootstrapStore()
    use_case = _use_case(store)
    await use_case.execute(_command())

    with pytest.raises(BootstrapDomainConflict, match=r"north\.example\.com"):
        await use_case.execute(_command(slug="other-slug"))


def test_bootstrap_source_does_not_reference_default_academy_id() -> None:
    source = Path(
        "v2/contexts/identity/application/use_cases/bootstrap_academy.py"
    ).read_text(encoding="utf-8")
    assert "default_academy_id" not in source
