"""Unit tests for the tenant host onboarding preflight (issue #611).

Every dependency is faked: the preflight must be runnable (and testable)
without Mongo, Firebase, or network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.scripts import tenant_host_preflight as preflight
from backend.v2.shared.tenancy.resolver import TenantResolver

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "tenant-host-onboarding.md"


class _FakeLookup:
    """In-memory ``AcademyLookupPort``."""

    def __init__(
        self,
        *,
        by_slug: dict[str, str] | None = None,
        by_domain: dict[str, str] | None = None,
    ) -> None:
        self._by_slug = by_slug or {}
        self._by_domain = by_domain or {}

    async def find_by_slug(self, slug: str) -> str | None:
        return self._by_slug.get(slug)

    async def find_by_domain(self, domain: str) -> str | None:
        return self._by_domain.get(domain)

    async def exists(self, academy_id: str) -> bool:
        return academy_id in set(self._by_slug.values()) | set(self._by_domain.values())


class _FakeOrigins:
    """In-memory ``TenantOriginsResolver`` stand-in."""

    def __init__(self, origins: dict[str, tuple[str, ...]] | None = None) -> None:
        self._origins = origins or {}

    async def for_academy(self, academy_id: str) -> tuple[str, ...]:
        return self._origins.get(academy_id, ())


def _resolver(lookup: _FakeLookup) -> TenantResolver:
    return TenantResolver(lookup=lookup)


async def _fail_firebase() -> list[str]:
    raise preflight.FirebaseCheckUnavailable("403 PERMISSION_DENIED")


@pytest.mark.asyncio
async def test_preflight_reports_fail_when_host_not_resolvable() -> None:
    report = await preflight.run_preflight(
        host="ghost.example.com",
        resolver=_resolver(_FakeLookup()),
        origins=_FakeOrigins(),
        authorized_domains=_fail_firebase,
    )

    assert report.resolution.status == preflight.STATUS_FAIL
    assert "ghost.example.com" in report.resolution.detail
    assert report.resolution.next_steps
    assert report.academy_id is None
    assert report.ok is False


@pytest.mark.asyncio
async def test_preflight_reports_pass_when_host_resolves_and_origin_included() -> None:
    report = await preflight.run_preflight(
        host="academy.example.com",
        resolver=_resolver(_FakeLookup(by_slug={"academy": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://academy.example.com",)}),
        authorized_domains=_fail_firebase,
    )

    assert report.resolution.status == preflight.STATUS_PASS
    assert report.origins.status == preflight.STATUS_PASS
    assert report.academy_id == "acad_1"
    assert report.ok is True


@pytest.mark.asyncio
async def test_preflight_flags_origin_gap_even_when_host_resolves() -> None:
    # Resolves through the laxer (unverified) custom-domain path, so the host
    # is NOT in the verified ``academy_domains`` set the origins builder uses.
    report = await preflight.run_preflight(
        host="new.example.com",
        resolver=_resolver(_FakeLookup(by_domain={"new.example.com": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://other.example.com",)}),
        authorized_domains=_fail_firebase,
    )

    assert report.resolution.status == preflight.STATUS_PASS
    assert report.origins.status == preflight.STATUS_FAIL
    joined = " ".join(report.origins.next_steps).lower()
    assert "academy_domains" in joined
    assert "verified" in joined
    assert "new.example.com" in joined
    assert report.ok is False


@pytest.mark.asyncio
async def test_preflight_firebase_check_degrades_to_manual_when_unavailable() -> None:
    report = await preflight.run_preflight(
        host="academy.example.com",
        resolver=_resolver(_FakeLookup(by_slug={"academy": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://academy.example.com",)}),
        authorized_domains=_fail_firebase,
    )

    assert report.firebase.status == preflight.STATUS_MANUAL
    assert any("Authorized domains" in step for step in report.firebase.next_steps)
    # A gate that could not be verified must never gate the exit code.
    assert report.ok is True
    assert preflight.exit_code(report) == 0


@pytest.mark.asyncio
async def test_preflight_firebase_pass_and_fail_are_reported() -> None:
    async def authorized() -> list[str]:
        return ["localhost", "academy.example.com"]

    passing = await preflight.run_preflight(
        host="academy.example.com",
        resolver=_resolver(_FakeLookup(by_slug={"academy": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://academy.example.com",)}),
        authorized_domains=authorized,
    )
    assert passing.firebase.status == preflight.STATUS_PASS

    failing = await preflight.run_preflight(
        host="missing.example.com",
        resolver=_resolver(_FakeLookup(by_domain={"missing.example.com": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://missing.example.com",)}),
        authorized_domains=authorized,
    )
    assert failing.firebase.status == preflight.STATUS_FAIL
    # Firebase is manual to fix, so it still does not gate the exit code.
    assert failing.ok is True


@pytest.mark.asyncio
async def test_google_oauth_gate_is_always_manual_with_console_steps() -> None:
    report = await preflight.run_preflight(
        host="academy.example.com",
        resolver=_resolver(_FakeLookup(by_slug={"academy": "acad_1"})),
        origins=_FakeOrigins({"acad_1": ("https://academy.example.com",)}),
        authorized_domains=_fail_firebase,
    )

    assert report.google_oauth.status == preflight.STATUS_MANUAL
    steps = " ".join(report.google_oauth.next_steps)
    assert "https://academy.example.com" in steps
    assert "/__/auth/handler" in steps

    text = preflight.render_text(report)
    assert "MANUAL" in text
    payload = report.to_dict()
    assert payload["host"] == "academy.example.com"
    assert {gate["gate"] for gate in payload["gates"]} == {
        preflight.GATE_GOOGLE_OAUTH,
        preflight.GATE_FIREBASE_DOMAIN,
        preflight.GATE_HOST_RESOLUTION,
        preflight.GATE_TENANT_ORIGINS,
    }


def test_runbook_documents_every_gate_title() -> None:
    assert RUNBOOK.exists(), f"missing runbook: {RUNBOOK}"
    text = RUNBOOK.read_text(encoding="utf-8")
    for title in preflight.GATE_TITLES.values():
        assert title in text, f"runbook is missing gate heading: {title}"
