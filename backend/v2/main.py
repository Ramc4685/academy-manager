"""Composition root for the v2 FastAPI app.

Wires shared infrastructure (config, logging, tracing, mongo, outbox,
dispatcher) and mounts persona route packages. No business logic here — only
glue.

Run standalone::

    uvicorn backend.v2.main:app --reload --port 8001
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

from backend.v2.composition.admin import compose_admin
from backend.v2.composition.coach import compose_coach
from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
)
from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    LoadAuthClaims,
)
from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    User,
)
from backend.v2.contexts.identity.infrastructure.firebase_token_verifier import (
    FirebaseTokenVerifier,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_bootstrap_store import (
    MongoTenantBootstrapStore,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import (
    MongoUserRepository,
)
from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    TenantLifecycleService,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    PlatformAuditService,
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.audit.infrastructure.mongo_platform_audit_repo import (
    MongoPlatformAuditRepository,
)
from backend.v2.contexts.platform.billing.infrastructure.composition import (
    build_platform_billing_use_cases,
)
from backend.v2.contexts.platform.governance.application.use_cases import (
    TenantGovernanceService,
)
from backend.v2.contexts.platform.governance.infrastructure.mongo_governance_store import (
    MongoGovernanceStore,
)
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.interfaces.platform.router import router as platform_router
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.config import Settings, get_settings
from backend.v2.shared.events import EventDispatcher, MongoOutbox
from backend.v2.shared.http import InMemoryRateLimitMiddleware, register_exception_handlers
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.observability import configure_logging, configure_tracing
from backend.v2.shared.tenancy.resolver import (
    TenantResolutionError,
    TenantResolver,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    log.info("Starting v2 app in env=%s", settings.env)

    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.mongo_db]
    app.state.mongo = client
    app.state.db = db

    if settings.run_migrations_on_boot:
        applied = await run_pending_migrations(db)
        log.info("Applied %d migrations: %s", len(applied), applied)

    outbox = MongoOutbox(db)
    app.state.outbox = outbox
    dispatcher = EventDispatcher(db)
    await dispatcher.start()
    app.state.dispatcher = dispatcher

    idempotency_store = MongoIdempotencyStore(db)
    app.state.idempotency_store = idempotency_store

    # Identity wiring — needed by TenancyMiddleware for token verification
    # and membership validation (ADR-0007).
    users_repo = MongoUserRepository(db, default_academy_id=settings.default_academy_id)
    verifier = FirebaseTokenVerifier()

    # In SaaS mode, both academy_memberships and platform_roles come from the
    # real MongoMembershipRepository (which owns both collections). The
    # PlatformRoleRepository port wants list_active_for_user(); the repo
    # exposes list_active_platform_roles(), so we go through the same
    # _MongoPlatformRoleAdapter that the non-SaaS branch uses.
    #
    # In non-SaaS mode, memberships still fall back to the in-process legacy
    # adapter (which synthesises a single-tenant membership from
    # users.academy_id / users.roles); platform_roles use the real Mongo
    # collection because they are tenant-independent.
    if settings.saas_mode:
        membership_repo = MongoMembershipRepository(db)
        platform_role_repo = _MongoPlatformRoleAdapter(membership_repo)
    else:
        membership_repo = _LegacyUserMembershipAdapter(users_repo, settings.default_academy_id)
        platform_role_repo = _MongoPlatformRoleAdapter(MongoMembershipRepository(db))

    load_claims = LoadAuthClaims(
        verifier=verifier,
        users=users_repo,
        memberships=membership_repo,
        platform_roles=platform_role_repo,
    )
    app.state.load_auth_claims = load_claims
    app.state.register_public_parent = RegisterPublicParent(
        verifier=verifier,
        users=users_repo,
        memberships=membership_repo if settings.saas_mode else None,
        outbox=outbox,
        default_academy_id=settings.default_academy_id,
        saas_mode=settings.saas_mode,
    )
    app.state.bootstrap_academy = BootstrapAcademy(
        store=MongoTenantBootstrapStore(db),
    )

    # Tenant resolver — wired only in SaaS mode. In non-SaaS mode the
    # middleware falls back to ``settings.default_academy_id`` so existing
    # single-tenant flows keep working.
    app.state.tenant_resolver = (
        TenantResolver(
            lookup=_AcademyLookupAdapter(MongoAcademyRepository(db)),
            allowed_internal_header=settings.allowed_internal_tenant_header,
        )
        if settings.saas_mode
        else None
    )
    app.state.saas_mode = settings.saas_mode
    app.state.default_academy_id = settings.default_academy_id
    # Platform audit + governance services (issues #78, #79).
    # Constructed before TenantLifecycleService so the lifecycle service can
    # receive a recorder callable that emits one platform_audit_events row
    # per state transition (issue #80).
    app.state.platform_audit = PlatformAuditService(
        audit_events=MongoPlatformAuditRepository(db),
    )
    app.state.tenant_governance = TenantGovernanceService(
        store=MongoGovernanceStore(db),
    )

    async def _record_lifecycle_audit(command: RecordPlatformAuditEventCommand) -> None:
        # Wrapper so TenantLifecycleService doesn't depend on the audit
        # context directly. Logged-not-raised on failure: an audit gap
        # must not break a state transition.
        try:
            await app.state.platform_audit.record_event(command)
        except Exception as exc:
            log.warning("platform_audit_emit_failed: %s", exc)

    app.state.tenant_lifecycle = TenantLifecycleService(
        tenants=MongoTenantLifecycleRepository(db),
        audit_recorder=_record_lifecycle_audit,
    )
    app.state.platform_billing = build_platform_billing_use_cases(db)

    # Coach BFF wiring — exposed as app.state.coach for routes via deps.py.
    app.state.coach = compose_coach(db, outbox, idempotency_store)

    # Parent BFF wiring (Wave 2). Cross-context event handlers are registered
    # by compose_parent via install_handlers().
    stripe_gw = _build_stripe(settings)
    app.state.parent = compose_parent(db, outbox, idempotency_store, stripe_gw)

    # Admin BFF wiring (Wave 3).
    app.state.admin = compose_admin(db, outbox, idempotency_store, stripe_gw)

    app.state.bootstrap_academy = BootstrapAcademy(
        store=MongoTenantBootstrapStore(db),
    )

    try:
        yield
    finally:
        await dispatcher.stop()
        client.close()


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="Academy Manager v2",
        version="2.0.0",
        lifespan=_lifespan,
    )
    configure_tracing(app)
    register_exception_handlers(app)

    # The middleware needs access to the LoadAuthClaims use case wired in the
    # lifespan. We expose it via app.state and the middleware reads it
    # lazily on the first request.
    app.add_middleware(_LazyTenancyMiddleware)
    app.add_middleware(InMemoryRateLimitMiddleware)
    _add_cors_middleware(app, get_settings())

    @app.get("/api/v2/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Persona route packages.
    app.include_router(me_router, prefix="/api/v2")
    app.include_router(registration_router, prefix="/api/v2")
    app.include_router(platform_router, prefix="/api/v2")
    app.include_router(coach_router, prefix="/api/v2")
    app.include_router(parent_router, prefix="/api/v2")
    app.include_router(admin_router, prefix="/api/v2")

    return app


def _build_stripe(settings: Settings) -> StripeGateway:
    if settings.env == "prod" and settings.stripe_use_fake_gateway:
        raise RuntimeError("V2_STRIPE_USE_FAKE_GATEWAY must be false in production")
    if (
        settings.stripe_use_fake_gateway
        or not settings.stripe_api_key
        or not settings.stripe_webhook_secret
    ):
        return FakeStripeGateway()
    from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

    return RealStripeGateway(
        api_key=settings.stripe_api_key,
        webhook_secret=settings.stripe_webhook_secret,
    )


def _add_cors_middleware(app: FastAPI, settings: Settings) -> None:
    origins = settings.cors_allowed_origins()
    if not origins:
        return
    if "*" in origins:
        raise RuntimeError("Wildcard CORS origins are not allowed")
    allow_headers = ["Authorization", "Content-Type", "Idempotency-Key", "Stripe-Signature"]
    if settings.allowed_internal_tenant_header:
        allow_headers.append(settings.allowed_internal_tenant_header)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=allow_headers,
    )


class _LazyTenancyMiddleware(TenancyMiddleware):
    """Resolves load_auth_claims + tenant resolver from app.state lazily.

    Necessary because middleware is constructed during ``create_app`` (before
    the lifespan sets ``app.state.load_auth_claims`` and friends). On the
    first request we capture references off ``request.app.state`` and bind
    the resolver callable in either SaaS mode (TenantResolver) or
    single-tenant mode (default_academy_id).
    """

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if self._load_claims is None:
            use_case = getattr(request.app.state, "load_auth_claims", None)
            if use_case is not None:
                # Re-bind to the use case's `.execute` method so the
                # middleware can call it as load_claims(token,
                # resolved_academy_id=...).
                self._load_claims = use_case.execute  # type: ignore[assignment]
        if self._resolve_tenant is None:
            self._resolve_tenant = _build_request_tenant_resolver(request.app)
        if self._check_tenant_servable is None:
            self._check_tenant_servable = _build_tenant_servability_checker(request.app)
        return await super().dispatch(request, call_next)


def _build_request_tenant_resolver(app: FastAPI):
    """Build the per-request tenant resolution callable for the middleware.

    In SaaS mode (``saas_mode=True``) we delegate to ``TenantResolver``
    which inspects subdomain, custom domain, or internal header — and never
    falls back to a default tenant.

    In non-SaaS mode we keep the legacy single-tenant deployment alive by
    returning ``settings.default_academy_id`` so existing routes keep
    working. ``default_academy_id`` is only ever consulted in this branch.
    """

    saas_mode = getattr(app.state, "saas_mode", False)
    default_academy_id = getattr(app.state, "default_academy_id", None)
    resolver = getattr(app.state, "tenant_resolver", None)

    async def _resolve(request):
        if saas_mode and resolver is not None:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            headers = dict(request.headers)
            try:
                result = await resolver.resolve(host=host, headers=headers)
                return result.academy_id
            except TenantResolutionError:
                return None
        return default_academy_id

    return _resolve


def _build_tenant_servability_checker(app: FastAPI):
    """Build the tenant status gate used before tenant-scoped route handlers."""

    saas_mode = getattr(app.state, "saas_mode", False)
    lifecycle = getattr(app.state, "tenant_lifecycle", None)

    async def _check(academy_id: str) -> tuple[bool, str | None]:
        if not saas_mode or lifecycle is None:
            return True, None
        health = await lifecycle.get_tenant_health(academy_id)
        return health.servable, health.reason

    return _check


# ---------------------------------------------------------------------------
# Legacy single-tenant adapters (temporary)
#
# These exist so the v2 app keeps working in non-SaaS deployments and in
# Wave 2 SaaS deployments where Agent A's Mongo membership repo has not
# merged yet. They MUST NOT be used in production SaaS once the real
# repositories are wired — main.py should swap them out then.
# ---------------------------------------------------------------------------


class _LegacyUserMembershipAdapter:
    """Synthesize an ``AcademyMembership`` from the legacy User record.

    Reads ``user.academy_id`` and ``user.roles`` from the User repository
    and returns an active membership for that single academy. This keeps
    the pre-SaaS auth flow working until the real Mongo membership repo
    (Agent A, Wave 2) lands.
    """

    def __init__(self, users, default_academy_id: str) -> None:
        self._users = users
        self._default_academy_id = default_academy_id

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str
    ) -> AcademyMembership | None:
        user: User | None = await self._users.get_by_id(user_id)
        if user is None:
            return None
        # Legacy single-tenant: the user's recorded academy must match the
        # resolved tenant. We never fabricate cross-academy access here.
        user_academy = user.academy_id or self._default_academy_id
        if user_academy != academy_id:
            return None
        if not user.is_active:
            return None
        return AcademyMembership(
            membership_id=f"legacy-{user.user_id}-{academy_id}",
            academy_id=academy_id,
            user_id=user.user_id,
            roles=user.roles,
            status="active",
        )


class _NullPlatformRoleRepository:
    """Placeholder until the Mongo platform_roles repository lands."""

    async def list_active_for_user(self, user_id: str) -> list[PlatformRole]:
        return []


class _MongoPlatformRoleAdapter:
    """Adapts MongoMembershipRepository to the PlatformRoleRepository port.

    The port uses list_active_for_user(); the repo uses list_active_platform_roles().
    """

    def __init__(self, repo: MongoMembershipRepository) -> None:
        self._repo = repo

    async def list_active_for_user(self, user_id: str) -> list[PlatformRole]:
        return await self._repo.list_active_platform_roles(user_id)


class _AcademyLookupAdapter:
    """Adapt ``MongoAcademyRepository`` to ``AcademyLookupPort``.

    The current ``academies`` collection does not yet store a ``slug`` or a
    custom-domain mapping; lookups return ``None`` until those fields are
    populated. The resolver therefore rejects unknown hosts, which is the
    correct SaaS-mode behavior — never invent a tenant.
    """

    def __init__(self, academies: MongoAcademyRepository) -> None:
        self._collection = academies.collection

    async def find_by_slug(self, slug: str) -> str | None:
        doc = await self._collection.find_one({"slug": slug})
        return doc.get("academy_id") if doc else None

    async def find_by_domain(self, domain: str) -> str | None:
        doc = await self._collection.find_one({"custom_domain": domain})
        return doc.get("academy_id") if doc else None


app = create_app()
