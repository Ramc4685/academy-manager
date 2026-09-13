"""Read-only preflight for onboarding a new academy host (issue #611).

Launching an academy on a new host requires it to be registered in three
independent allowlists. Two of them live in consoles that expose no write API
for what we need, so they are forgotten silently and the failures surface one
at a time as a parent walks further into the funnel:

  1. Google OAuth client — authorized JavaScript origin + redirect URI.
     ``Error 400: redirect_uri_mismatch`` before the consent screen.
     Manual: Google exposes no API for classic OAuth 2.0 web clients.
  2. Firebase Auth authorized domains. Sign-in clears Google, then fails at
     Firebase. Checkable read-only via the Identity Toolkit admin API.
  3. Tenant origins (checkout/redirect allowlist). Parent registers, reaches
     "Review & pay", checkout dies with ``redirect url origin not allowed``.
     Structural since PR #628: rebuilt from the academy's slug + its
     ``academy_domains`` rows with ``status == "verified"``.

This script does not fix anything and never writes: it reports PASS / FAIL /
MANUAL per gate and prints the exact console steps for the manual ones. Keep
the step text in sync with ``docs/runbooks/tenant-host-onboarding.md`` (a unit
test asserts the runbook documents every gate title).

Usage::

    source backend/.venv/bin/activate
    python -m backend.scripts.tenant_host_preflight --host blno.courtmastr.com
    python -m backend.scripts.tenant_host_preflight --host blno.courtmastr.com --json

Exit code is 0 only when the two conclusively-checkable gates (host resolution
and tenant origins) pass. A Firebase gate that could not be read degrades to
MANUAL and never fails the run — ops must not learn to ignore a red preflight.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from backend.v2.shared.tenancy.resolver import (  # noqa: E402
    TenantResolutionError,
    TenantResolver,
)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_MANUAL = "MANUAL"

GATE_GOOGLE_OAUTH = "google_oauth_client"
GATE_FIREBASE_DOMAIN = "firebase_authorized_domain"
GATE_HOST_RESOLUTION = "host_resolution"
GATE_TENANT_ORIGINS = "tenant_origins"

#: Canonical gate headings. The runbook quotes these verbatim.
GATE_TITLES = {
    GATE_HOST_RESOLUTION: "Gate 0 - Host resolves to the tenant",
    GATE_GOOGLE_OAUTH: "Gate 1 - Google OAuth client origins and redirect URI",
    GATE_FIREBASE_DOMAIN: "Gate 2 - Firebase Auth authorized domains",
    GATE_TENANT_ORIGINS: "Gate 3 - Tenant redirect/CORS origins include the host",
}

#: Only these gates decide the exit code — the other two are fixed by hand in a
#: console, so failing the run on them would make a red preflight routine.
_BLOCKING_GATES = (GATE_HOST_RESOLUTION, GATE_TENANT_ORIGINS)

_IDENTITY_TOOLKIT_CONFIG_URL = (
    "https://identitytoolkit.googleapis.com/admin/v2/projects/{project_id}/config"
)


class FirebaseCheckUnavailable(Exception):
    """The Firebase authorized-domain list could not be read.

    Raised for a missing dependency, missing credentials, a denied permission,
    or a disabled API — anything that means "unknown", never "not authorized".
    """


class TenantOriginsPort(Protocol):
    """Read-only view of one academy's allowlistable origins."""

    async def for_academy(self, academy_id: str) -> tuple[str, ...]: ...


#: Returns the project's Firebase Auth authorized domains, or raises
#: ``FirebaseCheckUnavailable`` when the answer is unknown.
AuthorizedDomainsProvider = Callable[[], Awaitable[Sequence[str]]]


@dataclass(frozen=True)
class GateResult:
    gate: str
    title: str
    status: str
    detail: str
    next_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "next_steps": list(self.next_steps),
        }


@dataclass(frozen=True)
class PreflightReport:
    host: str
    academy_id: str | None
    gates: tuple[GateResult, ...]

    def gate(self, name: str) -> GateResult:
        for result in self.gates:
            if result.gate == name:
                return result
        raise KeyError(name)

    @property
    def google_oauth(self) -> GateResult:
        return self.gate(GATE_GOOGLE_OAUTH)

    @property
    def firebase(self) -> GateResult:
        return self.gate(GATE_FIREBASE_DOMAIN)

    @property
    def resolution(self) -> GateResult:
        return self.gate(GATE_HOST_RESOLUTION)

    @property
    def origins(self) -> GateResult:
        return self.gate(GATE_TENANT_ORIGINS)

    @property
    def ok(self) -> bool:
        return all(self.gate(name).status == STATUS_PASS for name in _BLOCKING_GATES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "academy_id": self.academy_id,
            "ok": self.ok,
            "gates": [gate.to_dict() for gate in self.gates],
        }


def exit_code(report: PreflightReport) -> int:
    return 0 if report.ok else 1


# ---------------------------------------------------------------------------
# Manual console steps (keep identical to docs/runbooks/tenant-host-onboarding.md)
# ---------------------------------------------------------------------------


def google_oauth_steps(host: str) -> tuple[str, ...]:
    return (
        "Open Google Cloud Console > APIs & Services > Credentials > the web "
        "OAuth 2.0 client used by Firebase Auth "
        "(https://console.cloud.google.com/apis/credentials).",
        f"Add to Authorized JavaScript origins: https://{host}",
        f"Add to Authorized redirect URIs: https://{host}/__/auth/handler",
        "Save, then wait a few minutes for Google to propagate the change.",
        "There is no API for classic OAuth 2.0 web clients - this step is "
        "console-only and cannot be scripted.",
    )


def firebase_domain_steps(host: str) -> tuple[str, ...]:
    return (
        "Open Firebase Console > Authentication > Settings > Authorized domains.",
        f"Add domain: {host}",
        f"Verify with: python -m backend.scripts.tenant_host_preflight --host {host}",
    )


def tenant_origins_steps(host: str, academy_id: str | None) -> tuple[str, ...]:
    target = academy_id or "<academy_id>"
    return (
        f"Add `{host}` to the `academy_domains` collection with "
        f'`academy_id: "{target}"` and `status: "verified"` (tenant creation '
        "writes the primary domain there; a custom domain must be added after "
        "ownership is verified).",
        "Unverified domains are deliberately excluded from the redirect "
        "allowlist - do not relax that to make this gate pass.",
    )


def host_resolution_steps(host: str) -> tuple[str, ...]:
    return (
        f"`{host}` resolves to no academy. Either the academy's `slug` does not "
        f"match the first label of `{host}` under the platform base domain, or "
        "the host is missing from `academy_domains`.",
        f"Register the host: add `{host}` to `academy_domains` with the "
        'academy_id and `status: "verified"`, or fix the academy `slug`.',
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


async def run_preflight(
    *,
    host: str,
    resolver: TenantResolver,
    origins: TenantOriginsPort,
    authorized_domains: AuthorizedDomainsProvider | None = None,
) -> PreflightReport:
    """Check every onboarding gate for ``host``. Never writes, never raises."""
    bare_host = _normalize_host(host)

    resolution, academy_id = await _check_resolution(bare_host, resolver)
    origins_gate = await _check_origins(bare_host, academy_id, origins)
    firebase_gate = await _check_firebase(bare_host, authorized_domains)
    oauth_gate = GateResult(
        gate=GATE_GOOGLE_OAUTH,
        title=GATE_TITLES[GATE_GOOGLE_OAUTH],
        status=STATUS_MANUAL,
        detail=(
            "Google exposes no read or write API for classic OAuth 2.0 web "
            "clients; confirm this one in the console."
        ),
        next_steps=google_oauth_steps(bare_host),
    )

    return PreflightReport(
        host=bare_host,
        academy_id=academy_id,
        gates=(resolution, oauth_gate, firebase_gate, origins_gate),
    )


async def _check_resolution(host: str, resolver: TenantResolver) -> tuple[GateResult, str | None]:
    try:
        result = await resolver.resolve(host=host, headers={})
    except TenantResolutionError as exc:
        return (
            GateResult(
                gate=GATE_HOST_RESOLUTION,
                title=GATE_TITLES[GATE_HOST_RESOLUTION],
                status=STATUS_FAIL,
                detail=f"{host} does not resolve to any academy ({exc.reason})",
                next_steps=host_resolution_steps(host),
            ),
            None,
        )
    except Exception as exc:  # defensive: a lookup failure is not a verdict
        return (
            GateResult(
                gate=GATE_HOST_RESOLUTION,
                title=GATE_TITLES[GATE_HOST_RESOLUTION],
                status=STATUS_FAIL,
                detail=f"{host} lookup failed: {exc}",
                next_steps=host_resolution_steps(host),
            ),
            None,
        )
    return (
        GateResult(
            gate=GATE_HOST_RESOLUTION,
            title=GATE_TITLES[GATE_HOST_RESOLUTION],
            status=STATUS_PASS,
            detail=(f"{host} resolves to academy_id={result.academy_id} via {result.source.value}"),
        ),
        result.academy_id,
    )


async def _check_origins(
    host: str, academy_id: str | None, origins: TenantOriginsPort
) -> GateResult:
    title = GATE_TITLES[GATE_TENANT_ORIGINS]
    if academy_id is None:
        return GateResult(
            gate=GATE_TENANT_ORIGINS,
            title=title,
            status=STATUS_FAIL,
            detail=f"skipped: {host} resolves to no academy",
            next_steps=tenant_origins_steps(host, None),
        )
    try:
        allowed = await origins.for_academy(academy_id)
    except Exception as exc:  # defensive
        return GateResult(
            gate=GATE_TENANT_ORIGINS,
            title=title,
            status=STATUS_FAIL,
            detail=f"origins lookup failed for {academy_id}: {exc}",
            next_steps=tenant_origins_steps(host, academy_id),
        )
    hosts = {urlsplit(origin).hostname for origin in allowed}
    if host in hosts:
        return GateResult(
            gate=GATE_TENANT_ORIGINS,
            title=title,
            status=STATUS_PASS,
            detail=f"{host} is covered by tenant origins: {', '.join(allowed)}",
        )
    listed = ", ".join(allowed) if allowed else "(none)"
    return GateResult(
        gate=GATE_TENANT_ORIGINS,
        title=title,
        status=STATUS_FAIL,
        detail=(
            f"{host} is NOT in the origins built for academy_id={academy_id}: "
            f"{listed}. Checkout on this host would fail with "
            "'redirect url origin not allowed'."
        ),
        next_steps=tenant_origins_steps(host, academy_id),
    )


async def _check_firebase(
    host: str, authorized_domains: AuthorizedDomainsProvider | None
) -> GateResult:
    title = GATE_TITLES[GATE_FIREBASE_DOMAIN]
    steps = firebase_domain_steps(host)
    if authorized_domains is None:
        return GateResult(
            gate=GATE_FIREBASE_DOMAIN,
            title=title,
            status=STATUS_MANUAL,
            detail="no Firebase project configured for this run; check by hand",
            next_steps=steps,
        )
    try:
        domains = await authorized_domains()
    except FirebaseCheckUnavailable as exc:
        return GateResult(
            gate=GATE_FIREBASE_DOMAIN,
            title=title,
            status=STATUS_MANUAL,
            detail=f"could not read authorized domains ({exc}); check by hand",
            next_steps=steps,
        )
    except Exception as exc:  # defensive: unknown must never read as "not authorized"
        return GateResult(
            gate=GATE_FIREBASE_DOMAIN,
            title=title,
            status=STATUS_MANUAL,
            detail=f"could not read authorized domains ({exc}); check by hand",
            next_steps=steps,
        )
    normalized = {_normalize_host(domain) for domain in domains}
    if host in normalized:
        return GateResult(
            gate=GATE_FIREBASE_DOMAIN,
            title=title,
            status=STATUS_PASS,
            detail=f"{host} is an authorized domain for Firebase Auth",
        )
    return GateResult(
        gate=GATE_FIREBASE_DOMAIN,
        title=title,
        status=STATUS_FAIL,
        detail=(
            f"{host} is not an authorized domain (Firebase Auth reports "
            f"{len(normalized)} domains). Sign-in on this host will fail after "
            "the Google consent screen."
        ),
        next_steps=steps,
    )


def _normalize_host(host: str) -> str:
    bare = (host or "").strip().lower().rstrip(".")
    if "//" in bare:
        bare = urlsplit(bare).netloc or bare
    if ":" in bare:
        bare = bare.rsplit(":", 1)[0]
    return bare


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_text(report: PreflightReport) -> str:
    lines = [
        f"Tenant host preflight: {report.host}",
        f"academy_id: {report.academy_id or '(unresolved)'}",
        "",
    ]
    for gate in report.gates:
        lines.append(f"[{gate.status}] {gate.title}")
        lines.append(f"        {gate.detail}")
        if gate.status != STATUS_PASS:
            for step in gate.next_steps:
                lines.append(f"        - {step}")
        lines.append("")
    verdict = "PASS" if report.ok else "FAIL"
    lines.append(
        f"Checkable gates: {verdict}. Gates marked MANUAL must be confirmed in "
        "the console - see docs/runbooks/tenant-host-onboarding.md."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live providers (Mongo + Identity Toolkit)
# ---------------------------------------------------------------------------


def make_identity_toolkit_provider(project_id: str) -> AuthorizedDomainsProvider:
    """Read ``authorizedDomains`` with the Admin SDK's own credentials.

    Read-only (GET). Any failure raises ``FirebaseCheckUnavailable`` so the gate
    degrades to MANUAL rather than reporting a false FAIL.
    """

    async def _provider() -> Sequence[str]:
        try:
            import google.auth
            import httpx
            from google.auth.transport.requests import Request
        except ImportError as exc:  # pragma: no cover - dependency shape
            raise FirebaseCheckUnavailable(f"missing dependency: {exc}") from exc

        try:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(Request())
            token = credentials.token
        except Exception as exc:
            raise FirebaseCheckUnavailable(f"no usable credentials: {exc}") from exc

        url = _IDENTITY_TOOLKIT_CONFIG_URL.format(project_id=project_id)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        # Without this the API answers with a misleading
                        # SERVICE_DISABLED 403 (issue #611).
                        "x-goog-user-project": project_id,
                    },
                )
        except Exception as exc:
            raise FirebaseCheckUnavailable(f"request failed: {exc}") from exc

        if response.status_code != 200:
            raise FirebaseCheckUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        domains = payload.get("authorizedDomains")
        if not isinstance(domains, list):
            raise FirebaseCheckUnavailable("response had no authorizedDomains list")
        return [str(domain) for domain in domains]

    return _provider


class _MongoAcademyLookup:
    """Read-only ``AcademyLookupPort`` over the academies collections.

    Mirrors ``_AcademyLookupAdapter`` in ``backend/v2/main.py`` so the preflight
    answers the same question production asks.
    """

    def __init__(self, db: Any) -> None:
        self._academies = db["academies"]
        self._domains = db["academy_domains"]

    async def find_by_slug(self, slug: str) -> str | None:
        doc = await self._academies.find_one({"slug": slug})
        return doc.get("academy_id") if doc else None

    async def find_by_domain(self, domain: str) -> str | None:
        doc = await self._academies.find_one(
            {"$or": [{"custom_domain": domain}, {"primary_domain": domain}]}
        )
        if doc:
            return doc.get("academy_id")
        doc = await self._domains.find_one({"domain": domain, "status": "verified"})
        return doc.get("academy_id") if doc else None

    async def exists(self, academy_id: str) -> bool:
        return await self._academies.find_one({"academy_id": academy_id}) is not None


class _MongoOriginLookup:
    """Read-only ``AcademyOriginLookupPort`` (verified domains only)."""

    def __init__(self, db: Any) -> None:
        self._academies = db["academies"]
        self._domains = db["academy_domains"]

    async def routing_identity(self, academy_id: str) -> tuple[str | None, tuple[str, ...]]:
        doc = await self._academies.find_one({"academy_id": academy_id}, {"slug": 1, "_id": 0})
        slug = (doc or {}).get("slug")
        cursor = self._domains.find(
            {"academy_id": academy_id, "status": "verified"}, {"domain": 1, "_id": 0}
        )
        domains = [row["domain"] async for row in cursor if row.get("domain")]
        return slug, tuple(domains)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only preflight for a new academy host (issue #611).",
    )
    parser.add_argument("--host", required=True, help="Academy host, e.g. blno.courtmastr.com")
    parser.add_argument(
        "--mongo-url",
        default=os.environ.get("MONGO_URL"),
        help="Mongo connection string (default: $MONGO_URL)",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("MONGO_DB_NAME", "academy"),
        help="Mongo database name (default: $MONGO_DB_NAME or 'academy')",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("V2_FIREBASE_PROJECT_ID") or os.environ.get("FIREBASE_PROJECT_ID"),
        help="Firebase project id (default: $V2_FIREBASE_PROJECT_ID/$FIREBASE_PROJECT_ID)",
    )
    parser.add_argument(
        "--platform-base-domain",
        default=os.environ.get("PLATFORM_BASE_DOMAIN"),
        help="Platform base domain for subdomain resolution (default: $PLATFORM_BASE_DOMAIN)",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.environ.get("FRONTEND_URL"),
        help="Deployment frontend URL, used for origin scheme/port (default: $FRONTEND_URL)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a checklist")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    from backend.v2.shared.tenancy.origins import TenantOriginsResolver

    if not args.mongo_url:
        print("--mongo-url (or $MONGO_URL) is required", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        db = client[args.database]
        resolver = TenantResolver(
            lookup=_MongoAcademyLookup(db),
            platform_base_domain=args.platform_base_domain,
        )
        origins = TenantOriginsResolver(_MongoOriginLookup(db), frontend_url=args.frontend_url)
        provider = make_identity_toolkit_provider(args.project_id) if args.project_id else None
        report = await run_preflight(
            host=args.host,
            resolver=resolver,
            origins=origins,
            authorized_domains=provider,
        )
    finally:
        client.close()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_text(report))
    return exit_code(report)


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
