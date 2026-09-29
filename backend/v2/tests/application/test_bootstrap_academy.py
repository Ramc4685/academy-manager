"""Application tests for clean SaaS academy bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

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
        self.waivers: dict[str, dict[str, Any]] = {}
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

    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]:
        self.waivers.setdefault(waiver["academy_id"], dict(waiver))
        return dict(self.waivers[waiver["academy_id"]])


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
    # Row 13: every academy bootstrapped today is badminton by default.
    assert academy["sport"] == "badminton"

    owner = store.users["owner@example.com"]
    assert owner["email"] == "owner@example.com"
    assert "academy_id" not in owner
    assert "roles" not in owner

    membership = store.memberships[(result.academy_id, owner["user_id"])]
    assert membership["roles"] == ["admin"]
    assert membership["status"] == "active"

    waiver = store.waivers[result.academy_id]
    assert waiver["version"] == "1"
    assert waiver["status"] == "active"
    assert waiver["assigned_to_registration"] is True
    assert waiver["body"]
    assert store.legacy_writes == []


def test_bootstrap_no_longer_writes_the_four_unread_collections() -> None:
    """Settings overhaul Lane D: nothing under `backend/v2` reads
    `academy_settings`, `billing_policies`, `academy_roles` or
    `academy_feature_flags`, so bootstrap must not write them either. The
    store protocol no longer even exposes the methods that used to.
    """
    store = FakeBootstrapStore()
    assert not hasattr(store, "ensure_academy_settings")
    assert not hasattr(store, "ensure_billing_policy")
    assert not hasattr(store, "ensure_default_roles")
    assert not hasattr(store, "ensure_feature_flags")


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
    source = Path("v2/contexts/identity/application/use_cases/bootstrap_academy.py").read_text(
        encoding="utf-8"
    )
    assert "default_academy_id" not in source


def test_bootstrap_requires_a_timezone() -> None:
    """No "UTC" default.

    A tenant created with a placeholder zone makes every downstream
    "resolve the timezone from the tenant" lookup faithfully return the wrong
    answer, which is indistinguishable from the bug it is meant to fix.
    """
    with pytest.raises(ValidationError):
        BootstrapAcademyCommand(
            display_name="North Shore Badminton",
            slug="north-shore",
            primary_domain="north.example.com",
            owner_email="owner@example.com",
            owner_display_name="Owner One",
        )  # type: ignore[call-arg]


def test_bootstrap_rejects_a_non_iana_timezone() -> None:
    with pytest.raises(ValidationError):
        _command(timezone="Central Time")


class FakeInvoicePrefixAssigner:
    """Mirrors AssignInvoicePrefix: idempotent per academy, unique across academies."""

    def __init__(self) -> None:
        self.prefixes: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    async def execute(self, *, academy_id: str, slug: str) -> str:
        self.calls.append((academy_id, slug))
        if academy_id in self.prefixes:
            return self.prefixes[academy_id]
        base = slug.split("-")[0].upper()[:6]
        prefix, n = base, 2
        while prefix in self.prefixes.values():
            prefix, n = f"{base[:5]}{n}", n + 1
        self.prefixes[academy_id] = prefix
        return prefix


@pytest.mark.asyncio
async def test_bootstrap_assigns_an_invoice_prefix_from_the_slug() -> None:
    store = FakeBootstrapStore()
    assigner = FakeInvoicePrefixAssigner()
    use_case = BootstrapAcademy(
        store=store,
        id_factory=lambda prefix: f"{prefix}001",
        invoice_prefix_assigner=assigner,
    )

    result = await use_case.execute(_command())

    assert assigner.calls == [(result.academy_id, "north-shore")]
    assert result.invoice_prefix == "NORTH"


@pytest.mark.asyncio
async def test_rebootstrap_keeps_the_invoice_prefix() -> None:
    store = FakeBootstrapStore()
    assigner = FakeInvoicePrefixAssigner()
    use_case = BootstrapAcademy(store=store, invoice_prefix_assigner=assigner)

    first = await use_case.execute(_command())
    second = await use_case.execute(_command())

    assert second.created is False
    assert second.invoice_prefix == first.invoice_prefix == "NORTH"


@pytest.mark.asyncio
async def test_bootstrap_without_an_assigner_reports_no_prefix() -> None:
    result = await _use_case(FakeBootstrapStore()).execute(_command())

    assert result.invoice_prefix is None


@pytest.mark.asyncio
async def test_bootstrap_accepts_an_explicit_sport() -> None:
    store = FakeBootstrapStore()

    result = await _use_case(store).execute(_command(sport="tennis"))

    assert store.academies[result.academy_id]["sport"] == "tennis"
