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
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

from backend.v2.composition.admin import compose_admin
from backend.v2.composition.coach import compose_coach
from backend.v2.composition.digests import (
    compose_send_coach_daily_digest,
    compose_send_parent_daily_digest,
    resolve_digest_schedule,
)
from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
    ReconcileStripePaymentIntents,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
    MongoBillingReconciliationRunRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_daily_digest import (
    SendParentDailyDigestCommand,
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
from backend.v2.shared.tenancy.context import tenant_scope
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

    runtime_academy_id = _runtime_academy_id(settings)

    # Identity wiring — needed by TenancyMiddleware for token verification
    # and membership validation (ADR-0007).
    users_repo = MongoUserRepository(db, default_academy_id=runtime_academy_id)
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
        membership_repo = _LegacyUserMembershipAdapter(users_repo, runtime_academy_id)
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
        default_academy_id=runtime_academy_id,
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
    app.state.tenancy_mode = settings.tenancy_mode
    app.state.primary_academy_id = settings.primary_academy_id
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

    # Stripe gateway shared across all BFFs that need it.
    stripe_gw = _build_stripe(settings)

    # Coach BFF wiring — exposed as app.state.coach for routes via deps.py.
    app.state.coach = compose_coach(db, outbox, idempotency_store, stripe_gw)

    # Parent BFF wiring (Wave 2). Cross-context event handlers are registered
    # by compose_parent via install_handlers().
    app.state.parent = compose_parent(
        db,
        outbox,
        idempotency_store,
        stripe_gw,
        academy_id=runtime_academy_id,
    )
    stripe_webhook_processors = {runtime_academy_id: app.state.parent.handle_webhook_event}

    # Platform Stripe Connect onboarding (Slice I). Composition root wires the
    # real repo + gateway into the use case; the platform BFF route only sees
    # app.state.platform_connect_onboarding.
    app.state.platform_connect_onboarding = StartConnectOnboarding(
        stripe=stripe_gw,
        connected_accounts=MongoConnectedAccountRepository(db),
        allowed_redirect_origins=settings.cors_allowed_origins(),
    )

    # Admin BFF wiring (Wave 3).
    app.state.admin = compose_admin(db, outbox, idempotency_store, stripe_gw)

    scheduler: AsyncIOScheduler | None = None

    async def _process_scheduled_resumes() -> None:
        totals = {
            "processed": 0,
            "succeeded": 0,
            "blocked_capacity": 0,
            "failed": 0,
            "academy_count": 0,
        }
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            with tenant_scope(academy_id):
                result = await app.state.admin.process_scheduled_resume_actions.execute(limit=100)
            totals["academy_count"] += 1
            totals["processed"] += result.processed
            totals["succeeded"] += result.succeeded
            totals["blocked_capacity"] += result.blocked_capacity
            totals["failed"] += result.failed
        if totals["processed"]:
            log.info("scheduled_resume_actions_processed", extra=totals)

    async def _expire_makeup_requests() -> None:
        totals = {"academy_count": 0, "expired": 0}
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            with tenant_scope(academy_id):
                worker = getattr(app.state.admin, "expire_makeup_requests", None)
                if worker is None:
                    continue
                expired = await worker.execute()
            totals["academy_count"] += 1
            totals["expired"] += expired
        if totals["expired"]:
            log.info("makeup_requests_expired", extra=totals)

    async def _process_stripe_webhook_events() -> None:
        totals = {"processed": 0, "failed": 0}
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            processor = stripe_webhook_processors.get(academy_id)
            if processor is None:
                processor = compose_parent_webhook_handler(
                    db,
                    outbox,
                    stripe_gw,
                    academy_id=academy_id,
                )
                stripe_webhook_processors[academy_id] = processor
            for _ in range(25):
                result = await processor.process_next(
                    processor_id=f"scheduler-stripe-webhook-worker:{academy_id}"
                )
                if result.get("empty"):
                    break
                if result.get("processed"):
                    totals["processed"] += 1
                else:
                    totals["failed"] += 1
        if totals["processed"] or totals["failed"]:
            log.info("stripe_webhook_events_processed", extra=totals)

    async def _reconcile_stripe_payment_intents() -> None:
        totals = {
            "academy_count": 0,
            "scanned": 0,
            "repaired": 0,
            "skipped": 0,
            "quarantined": 0,
            "failed": 0,
        }
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            with tenant_scope(academy_id):
                result = await ReconcileStripePaymentIntents(
                    stripe=stripe_gw,
                    ledger=MongoBillingLedgerRepository(db),
                    run_recorder=MongoBillingReconciliationRunRepository(db),
                    academy_id=academy_id,
                    connected_accounts=MongoConnectedAccountRepository(db),
                ).execute(limit=100)
            totals["academy_count"] += 1
            totals["scanned"] += int(result.get("scanned") or 0)
            totals["repaired"] += int(result.get("repaired") or 0)
            totals["skipped"] += int(result.get("skipped") or 0)
            totals["quarantined"] += int(result.get("quarantined") or 0)
            totals["failed"] += int(result.get("failed") or 0)
        if totals["repaired"] or totals["quarantined"] or totals["failed"]:
            log.info("stripe_payment_intent_reconciliation_processed", extra=totals)

    async def _process_dunning_retries() -> None:
        totals = {
            "academy_count": 0,
            "prepared": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "dunned": 0,
            "transient": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "autopay_disabled": 0,
        }
        for academy_id in await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        ):
            with tenant_scope(academy_id):
                worker = getattr(app.state.admin, "process_dunning_retries", None)
                if worker is None:
                    log.warning(
                        "dunning_retries_worker_missing: process_dunning_retries is not "
                        "wired on app.state.admin; dunning is NOT running",
                        extra={"academy_id": academy_id},
                    )
                    continue
                result = await worker.execute(
                    limit=100,
                    worker_id=f"scheduler-dunning-worker:{academy_id}",
                )
            totals["academy_count"] += 1
            for key in (
                "prepared",
                "processed",
                "succeeded",
                "failed",
                "dunned",
                "transient",
                "notifications_sent",
                "notifications_failed",
                "autopay_disabled",
            ):
                totals[key] += int(getattr(result, key, 0) or 0)
        if totals["processed"] or totals["dunned"] or totals["autopay_disabled"]:
            log.info("dunning_retries_processed", extra=totals)

    async def _send_coach_daily_digests() -> None:
        # Hourly tick. The job runs every hour and only sends for academies whose
        # *effective* digest hour matches the current scheduler-TZ hour. The env
        # vars (settings.coach_digest_enabled/hour) are now deprecated defaults:
        # they only apply until an admin saves per-academy values, so existing
        # deployments keep their original single daily send with no behaviour
        # change. Idempotency is preserved by the existing per-(academy, coach,
        # date) try_claim — re-running the same hour sends nothing.
        #
        # NOTE: ``coach_digest_hour`` is interpreted in the scheduler timezone
        # (settings.scheduler_tz), NOT each academy's local timezone. Honouring
        # the academy's own TZ is explicit future work.
        now = datetime.now(scheduler.timezone)
        current_hour = now.hour
        on_date = now.date()
        academy_repo = MongoAcademyRepository(db)
        totals = {
            "academy_count": 0,
            "coaches": 0,
            "sent": 0,
            "skipped_empty": 0,
            "failed": 0,
            "already_claimed": 0,
        }
        for academy_id in await _scheduler_academy_ids(
            academy_repo,
            runtime_academy_id,
        ):
            # Read the raw notifications subdoc so an *unset* override falls back
            # to the env default (key present but False is a deliberate opt-out).
            doc = await academy_repo.find_by_id(academy_id)
            notifs = (doc or {}).get("notifications") or {}
            schedule = resolve_digest_schedule(
                academy_enabled=notifs.get("coach_digest_enabled"),
                academy_hour=notifs.get("coach_digest_hour"),
                env_enabled=settings.coach_digest_enabled,
                env_hour=settings.coach_digest_hour,
            )
            if not (schedule.enabled and schedule.hour == current_hour):
                continue
            with tenant_scope(academy_id):
                result = await app.state.coach_digest.execute(
                    SendCoachDailyDigestCommand(
                        academy_id=academy_id,
                        digest_date=on_date,
                        admin_cc_enabled=bool(notifs.get("daily_digest_to_admin", False)),
                    )
                )
            totals["academy_count"] += 1
            totals["coaches"] += result.total_coaches
            totals["sent"] += result.sent
            totals["skipped_empty"] += result.skipped_empty
            totals["failed"] += result.failed
            totals["already_claimed"] += result.already_claimed
        if totals["coaches"]:
            log.info("coach_daily_digests_processed", extra=totals)

    async def _send_parent_daily_digests() -> None:
        # Hourly tick, mirroring _send_coach_daily_digests: only sends for
        # academies whose *effective* parent-digest hour matches the current
        # scheduler-TZ hour. The env vars (settings.parent_digest_enabled/hour)
        # are deprecated defaults that apply only until an admin saves per-academy
        # values. Idempotency is the per-(academy, parent, date) try_claim, so a
        # re-run within the same hour sends nothing.
        #
        # NOTE: ``parent_digest_hour`` is interpreted in the scheduler timezone
        # (settings.scheduler_tz), NOT each academy's local timezone.
        now = datetime.now(scheduler.timezone)  # type: ignore[union-attr]
        current_hour = now.hour
        on_date = now.date()
        academy_repo = MongoAcademyRepository(db)
        totals = {
            "academy_count": 0,
            "parents": 0,
            "sent": 0,
            "skipped_empty": 0,
            "failed": 0,
            "already_claimed": 0,
        }
        for academy_id in await _scheduler_academy_ids(
            academy_repo,
            runtime_academy_id,
        ):
            doc = await academy_repo.find_by_id(academy_id)
            notifs = (doc or {}).get("notifications") or {}
            schedule = resolve_digest_schedule(
                academy_enabled=notifs.get("parent_digest_enabled"),
                academy_hour=notifs.get("parent_digest_hour"),
                env_enabled=settings.parent_digest_enabled,
                env_hour=settings.parent_digest_hour,
            )
            if not (schedule.enabled and schedule.hour == current_hour):
                continue
            with tenant_scope(academy_id):
                result = await app.state.parent_digest.execute(
                    SendParentDailyDigestCommand(
                        academy_id=academy_id,
                        digest_date=on_date,
                    )
                )
            totals["academy_count"] += 1
            totals["parents"] += result.total_parents
            totals["sent"] += result.sent
            totals["skipped_empty"] += result.skipped_empty
            totals["failed"] += result.failed
            totals["already_claimed"] += result.already_claimed
        if totals["parents"]:
            log.info("parent_daily_digests_processed", extra=totals)

    scheduler = AsyncIOScheduler(timezone=settings.scheduler_tz)
    scheduler.add_job(
        _process_scheduled_resumes,
        "cron",
        hour=2,
        minute=0,
        id="process_scheduled_resume_actions",
        replace_existing=True,
        # Parity with the other jobs: prevent a slow run from overlapping the
        # next tick within this process. (Cross-machine exclusivity still
        # depends on a single Fly machine — see deferred leader-election note.)
        max_instances=1,
    )
    scheduler.add_job(
        _expire_makeup_requests,
        "cron",
        hour=2,
        minute=30,
        id="expire_makeup_requests",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _process_stripe_webhook_events,
        "interval",
        seconds=60,
        id="process_stripe_webhook_events",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _reconcile_stripe_payment_intents,
        "interval",
        minutes=10,
        id="reconcile_stripe_payment_intents",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _process_dunning_retries,
        "interval",
        minutes=60,
        id="process_dunning_retries",
        replace_existing=True,
        max_instances=1,
    )
    # Coach teaching-plan digest. The sender is composed unconditionally so the
    # per-academy override (and the test-send use case) work regardless of the
    # env flag; the composed sender is still the stub unless email delivery is
    # explicitly on. The cron is now ALWAYS hourly: each tick the job resolves
    # the effective per-academy schedule and only sends for academies whose
    # effective hour matches the current scheduler-TZ hour (env flag = deprecated
    # default — ZERO behaviour change until an admin saves per-academy values).
    app.state.coach_digest = compose_send_coach_daily_digest(db)
    scheduler.add_job(
        _send_coach_daily_digests,
        "cron",
        hour="*",
        minute=0,
        id="send_coach_daily_digests",
        replace_existing=True,
        max_instances=1,
    )
    # Parent daily digest — same hourly-tick + per-academy-effective-hour model as
    # the coach digest above. Composed unconditionally so the per-academy override
    # works regardless of the env flag; the composed sender is still the stub
    # unless email delivery is explicitly on.
    app.state.parent_digest = compose_send_parent_daily_digest(db)
    scheduler.add_job(
        _send_parent_daily_digests,
        "cron",
        hour="*",
        minute=0,
        id="send_parent_daily_digests",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    app.state.scheduler = scheduler

    app.state.bootstrap_academy = BootstrapAcademy(
        store=MongoTenantBootstrapStore(db),
    )

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await dispatcher.stop()
        client.close()


async def _scheduler_academy_ids(
    academies: MongoAcademyRepository,
    default_academy_id: str,
) -> list[str]:
    academy_ids: list[str] = []
    seen: set[str] = set()
    for academy_id in await academies.list_ids():
        if academy_id and academy_id not in seen:
            academy_ids.append(academy_id)
            seen.add(academy_id)
    if default_academy_id and default_academy_id not in seen:
        academy_ids.append(default_academy_id)
    return academy_ids


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Academy Manager API",
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
    _add_cors_middleware(app, settings)

    @app.get("/api/v2/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Persona route packages.
    app.include_router(me_router, prefix="/api/v2")
    app.include_router(registration_router, prefix="/api/v2")
    if settings.enable_platform_routes:
        app.include_router(platform_router, prefix="/api/v2")
    app.include_router(coach_router, prefix="/api/v2")
    app.include_router(parent_router, prefix="/api/v2")
    app.include_router(admin_router, prefix="/api/v2")

    return app


def _runtime_academy_id(settings: Settings) -> str:
    """Return the explicit single-tenant academy used for non-SaaS launch paths."""
    if settings.tenancy_mode == "single_academy":
        if not settings.primary_academy_id:
            raise RuntimeError("PRIMARY_ACADEMY_ID is required in single_academy mode")
        return settings.primary_academy_id
    return settings.default_academy_id


def _build_stripe(settings: Settings) -> StripeGateway:
    if not settings.stripe_api_key or not settings.stripe_webhook_secret:
        if settings.env != "prod":
            from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
                FakeStripeGateway,
            )

            return FakeStripeGateway()
        raise RuntimeError(
            "STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET must be set. "
            "Use Stripe test-mode keys (sk_test_...) for local/staging and live keys for prod."
        )
    from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

    return RealStripeGateway(
        api_key=settings.stripe_api_key,
        webhook_secret=settings.stripe_webhook_secret,
        connect_webhook_secret=settings.stripe_connect_webhook_secret,
        connect_client_id=settings.stripe_connect_client_id,
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
    the resolver callable in either SaaS mode (TenantResolver), launch
    single-academy mode (PRIMARY_ACADEMY_ID), or legacy compatibility mode.
    """

    async def dispatch(self, request, call_next):
        if self._load_claims is None:
            use_case = getattr(request.app.state, "load_auth_claims", None)
            if use_case is not None:
                # Re-bind to the use case's `.execute` method so the
                # middleware can call it as load_claims(token,
                # resolved_academy_id=...).
                self._load_claims = use_case.execute
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

    In non-SaaS single-academy launch mode, resolve to PRIMARY_ACADEMY_ID. In
    legacy non-SaaS compatibility mode, resolve to the configured default
    academy so existing local/single-tenant flows keep working.
    """

    saas_mode = getattr(app.state, "saas_mode", False)
    tenancy_mode = getattr(app.state, "tenancy_mode", "multi_academy")
    primary_academy_id = getattr(app.state, "primary_academy_id", None)
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
        if tenancy_mode == "single_academy":
            return primary_academy_id
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

    Tenant routing can be stored directly on the academy row or in the
    ``academy_domains`` mapping written by platform bootstrap.
    """

    def __init__(self, academies: MongoAcademyRepository) -> None:
        self._collection = academies.collection
        self._domains = academies.collection.database["academy_domains"]

    async def find_by_slug(self, slug: str) -> str | None:
        doc = await self._collection.find_one({"slug": slug})
        return doc.get("academy_id") if doc else None

    async def find_by_domain(self, domain: str) -> str | None:
        doc = await self._collection.find_one(
            {"$or": [{"custom_domain": domain}, {"primary_domain": domain}]}
        )
        if doc:
            return doc.get("academy_id")
        doc = await self._domains.find_one({"domain": domain, "status": "verified"})
        return doc.get("academy_id") if doc else None


app = create_app()
