"""Composition root for the v2 FastAPI app.

Wires shared infrastructure (config, logging, tracing, mongo, outbox,
dispatcher) and mounts persona route packages. No business logic here — only
glue.

Run standalone::

    uvicorn backend.v2.main:app --reload --port 8001
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Response
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from starlette.middleware.cors import CORSMiddleware

from backend.v2.composition.admin import compose_admin
from backend.v2.composition.coach import compose_coach
from backend.v2.composition.digests import (
    compose_email_credential_probe,
    compose_ops_digest_sender,
    compose_send_coach_daily_digest,
    compose_send_parent_daily_digest,
    resolve_digest_schedule,
)
from backend.v2.composition.owner import compose_owner
from backend.v2.composition.parent import compose_parent, compose_parent_webhook_handler
from backend.v2.composition.student import compose_student
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsCommand,
)
from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
    ReconcileStripePaymentIntents,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
    MongoBillingReconciliationRunRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_daily_digest import (
    SendParentDailyDigestCommand,
)
from backend.v2.contexts.identity.application.list_my_memberships_use_case import (
    ListMyMembershipsUseCase,
)
from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
)
from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    LoadAuthClaims,
)
from backend.v2.contexts.identity.application.use_cases.magic_link import (
    ConsumeMagicLink,
)
from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    User,
)
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
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
from backend.v2.contexts.identity.infrastructure.mongo_magic_link_repo import (
    MongoMagicLinkRepository,
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
from backend.v2.interfaces.magic_link_routes import router as magic_link_router
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.interfaces.owner.router import router as owner_router
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.interfaces.platform.router import router as platform_router
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.interfaces.student.router import router as student_router
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.config import Settings, get_settings
from backend.v2.shared.events import EventDispatcher, MongoOutbox
from backend.v2.shared.http import InMemoryRateLimitMiddleware, register_exception_handlers
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.observability import (
    RequestContextMiddleware,
    configure_error_tracking,
    configure_logging,
    configure_tracing,
)
from backend.v2.shared.observability.health import build_health_report
from backend.v2.shared.observability.ops_alerts import (
    capture_message,
    handle_scheduler_job_event,
)
from backend.v2.shared.observability.ops_digest import (
    INVOICE_GENERATION_JOB,
    collect_ops_digest,
    record_job_run,
    render_ops_digest,
)
from backend.v2.shared.scheduling import job_lease
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.tenancy.resolver import (
    TenantResolutionError,
    TenantResolver,
)

log = logging.getLogger(__name__)


async def _verify_email_credentials(sender: Any) -> bool | None:
    """Probe the outbound-email credential once at boot (issue #435).

    Returns the verdict: ``True`` valid, ``False`` definitely broken, ``None``
    undetermined or not applicable. Duck-typed on purpose, and ``None``-tolerant:
    a deployment with no Resend credential configured has nothing to validate
    and is skipped silently, so local and test boots pay nothing for this.

    Only ``False`` alerts. Treating a timeout as a dead key would make the
    alert channel untrustworthy the first time Resend had a slow minute.
    """
    validate = getattr(sender, "validate_credentials", None) if sender is not None else None
    if validate is None:
        return None
    try:
        check = await validate()
    except Exception:  # pragma: no cover - defensive; boot must not fail on this
        log.warning("email_credential_check_errored", exc_info=True)
        return None
    ok: bool | None = check.ok
    extra = {"ok": ok, "detail": check.detail}
    if ok is False:
        log.error("email_credential_invalid", extra=extra)
        capture_message(f"Outbound email credential rejected by provider: {check.detail}")
    elif ok:
        log.info("email_credential_ok", extra=extra)
    else:
        log.warning("email_credential_unverified", extra=extra)
    return ok


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
    app.state.list_my_memberships = ListMyMembershipsUseCase(
        memberships=membership_repo,
        academies=MongoAcademyRepository(db),
    )
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
    # Public parent magic-link consume. Tenant is resolved per-request from the
    # host; the use case itself checks the token's academy binding against it.
    app.state.consume_magic_link = ConsumeMagicLink(
        links=MongoMagicLinkRepository(db),
        tokens=get_firebase_admin_adapter(),
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

    # Student BFF wiring (UIM12) — entirely behind enable_student_login.
    # With the flag off the router is not mounted at all (see the
    # include_router call below), so /student/* 404s at routing. This
    # composition is skipped for the same reason; the belt-and-braces 404 in
    # interfaces/student/deps.get_student_use_cases covers the case where a
    # test (or a future caller) mounts the router without composing state.
    if settings.enable_student_login:
        app.state.student = compose_student(db, parent=app.state.parent)

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

    # Owner (franchise) BFF wiring — UIM11. Left unset when the flag is off so
    # the routes 404 even if something mounts them.
    if settings.enable_owner_role:
        app.state.owner = compose_owner(db)

    scheduler: AsyncIOScheduler | None = None

    # Distributed job lease: identifies this machine so exactly one machine runs
    # each scheduled job per tick (max_instances=1 only guards within a process).
    scheduler_worker_id = os.environ.get("FLY_MACHINE_ID") or f"scheduler:{uuid.uuid4()}"

    async def _process_scheduled_resumes() -> None:
        async with job_lease(
            db, "process_scheduled_resume_actions", timedelta(minutes=5), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _process_scheduled_resumes_body()

    async def _process_scheduled_resumes_body() -> None:
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
        async with job_lease(
            db, "expire_makeup_requests", timedelta(minutes=5), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _expire_makeup_requests_body()

    async def _expire_makeup_requests_body() -> None:
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
        # 60s interval: keep TTL just under the interval so a clean run's early
        # release lets the next tick reclaim, and a crash frees the lease fast.
        async with job_lease(
            db, "process_stripe_webhook_events", timedelta(seconds=55), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _process_stripe_webhook_events_body()

    async def _process_stripe_webhook_events_body() -> None:
        # `quarantined` is tracked apart from `failed` (issue #437): a failure
        # is mid-retry, a quarantine has given up. Folding them together would
        # make the one number that reaches the logs mean two opposite things.
        totals = {"processed": 0, "failed": 0, "quarantined": 0}
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
                elif result.get("status") == "quarantined":
                    totals["quarantined"] += 1
                else:
                    totals["failed"] += 1
        if totals["processed"] or totals["failed"] or totals["quarantined"]:
            log.info("stripe_webhook_events_processed", extra=totals)

    async def _reconcile_stripe_payment_intents() -> None:
        async with job_lease(
            db, "reconcile_stripe_payment_intents", timedelta(minutes=5), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _reconcile_stripe_payment_intents_body()

    async def _reconcile_stripe_payment_intents_body() -> None:
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
        async with job_lease(
            db, "process_dunning_retries", timedelta(minutes=10), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _process_dunning_retries_body()

    async def _process_dunning_retries_body() -> None:
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

    async def _generate_monthly_invoices() -> None:
        # 30-minute TTL: a full generation run walks every active enrollment in
        # every academy, so the lease must outlive a slow run rather than let a
        # second machine start a duplicate pass mid-flight.
        async with job_lease(
            db, "generate_monthly_invoices", timedelta(minutes=30), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _generate_monthly_invoices_body()

    async def _generate_monthly_invoices_body() -> None:
        # Daily tick. The per-academy gate and catch-up rules live in
        # _run_monthly_invoice_generation (module level, directly testable).
        #
        # NOTE: billing_day is interpreted in the scheduler timezone
        # (settings.scheduler_tz), NOT each academy's local timezone — same
        # tradeoff as the coach/parent digest hour above.
        now = datetime.now(scheduler.timezone)  # type: ignore[union-attr]
        academy_ids = await _scheduler_academy_ids(
            MongoAcademyRepository(db),
            runtime_academy_id,
        )

        async def _get_billing_settings() -> Any:
            return await MongoBillingSettingsRepository(db).get()

        async def _generate(period: str) -> Any:
            return await app.state.admin.generate_monthly_payments.execute(
                GenerateMonthlyPaymentsCommand(period=period)
            )

        # Issue #430: generation creates invoices, this sends them. Absent on
        # an older composition bundle, in which case generation behaves as it
        # did before and nothing is emailed.
        send_invoices = getattr(app.state.admin, "send_generated_invoices", None)

        totals = await _run_monthly_invoice_generation(
            db=db,
            academy_ids=academy_ids,
            get_billing_settings=_get_billing_settings,
            generate=_generate,
            now=now,
            send_invoices=send_invoices,
        )
        # Job-level record for the daily ops digest (issue #428), kept here in
        # the job wrapper rather than inside _run_monthly_invoice_generation so
        # that helper stays a pure, injectable unit. It is complementary to the
        # per-(academy, period) rows _record_monthly_generation writes to
        # `billing_generation_runs`: those drive the catch-up gate, this answers
        # "did the scheduled job run, and what did the last real run do".
        #
        # `academy_count` counts only academies that actually attempted
        # generation this tick, which is exactly the "meaningful" bar: on the
        # ~29 days a month when nothing is due, record a heartbeat only
        # (`meaningful=False`) instead of overwriting the last real run's counts
        # with zeros — those counts are the signal the digest exists to surface.
        record: dict[str, Any] = {key: value for key, value in totals.items() if key != "created"}
        # Match the log line's `created_count` naming (#440) so the email and
        # the structured log read the same.
        record["created_count"] = totals["created"]
        record["period"] = now.strftime("%Y-%m")
        # A tick that only emailed (issue #430's retry path: generation was
        # already recorded, but invoices were still undelivered) is meaningful
        # too — otherwise a month-long email outage would be invisible in the
        # digest on all 29 days that did not generate.
        await record_job_run(
            db,
            INVOICE_GENERATION_JOB,
            record,
            meaningful=bool(
                totals["academy_count"]
                or totals["invoices_emailed"]
                or totals["invoice_emails_failed"]
            ),
        )

    async def _send_ops_digest() -> None:
        async with job_lease(
            db, "send_ops_digest", timedelta(minutes=30), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _send_ops_digest_body()

    async def _send_ops_digest_body() -> None:
        # Owner-facing, cross-academy summary of the things that fail silently:
        # quarantined/failed Stripe webhooks, dead-letter events, dunning
        # terminals, and the last invoice-generation run. Unset OPS_ALERT_EMAIL
        # ⇒ log and skip (no recipient to fail over to).
        recipient_email = (settings.ops_alert_email or "").strip()
        if not recipient_email:
            log.info("ops_digest_skipped: OPS_ALERT_EMAIL is not configured")
            return
        # Stamp the snapshot in the scheduler timezone: the cron fires at 07:00
        # local, so a UTC stamp would put yesterday's date on the subject line
        # in any UTC+ deployment.
        snapshot = await collect_ops_digest(db, now=datetime.now(scheduler.timezone))  # type: ignore[union-attr]
        subject, body = render_ops_digest(snapshot)
        outcome = await app.state.ops_digest_sender.send(
            recipient=ResolvedRecipient(
                user_id="ops-alert",
                email=recipient_email,
                display_name="Ops",
            ),
            subject=subject,
            body=body,
        )
        extra = {
            "ok": bool(getattr(outcome, "ok", False)),
            "failed_reason": getattr(outcome, "failed_reason", None),
            "webhooks_quarantined": snapshot.webhooks_quarantined,
            "webhooks_quarantined_recent": snapshot.webhooks_quarantined_recent,
            "webhooks_failed": snapshot.webhooks_failed,
            "webhooks_failed_stale": snapshot.webhooks_failed_stale,
            "dead_letter_total": snapshot.dead_letter_total,
            "dead_letter_recent": snapshot.dead_letter_recent,
            "dunning_terminals_recent": snapshot.dunning_terminals_recent,
            "digest_sends_failed": snapshot.digest_sends_failed,
            "digest_sends_failed_exhausted": snapshot.digest_sends_failed_exhausted,
        }
        if extra["ok"]:
            log.info("ops_digest_processed", extra=extra)
        else:
            # The alerting channel failing is itself an alert. Resend never
            # raises — a rejected send comes back as SendOutcome(ok=False) — so
            # without this the digest would go missing in silence.
            log.error("ops_digest_send_failed", extra=extra)
            capture_message(f"Ops digest send failed: {extra['failed_reason']}")

    async def _send_coach_daily_digests() -> None:
        async with job_lease(
            db, "send_coach_daily_digests", timedelta(minutes=10), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _send_coach_daily_digests_body()

    async def _send_coach_daily_digests_body() -> None:
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
            # `>=`, not `==`: the digest hour OPENS the window rather than
            # being the only chance. With an exact match each academy got one
            # tick a day, so a Resend outage or a deploy spanning that single
            # hour lost the whole day's digest and the retry ladder added by
            # #435/PR #489 could never fire — there was no later tick to fire
            # on (issue #542). Later ticks are cheap: `try_claim` runs BEFORE
            # plan generation, so an already-sent recipient costs one
            # duplicate-key insert and one indexed no-op re-claim, and a `sent`
            # row can never be re-claimed. The window closes on its own at
            # midnight, when `digest_date` rolls over.
            if not (schedule.enabled and current_hour >= schedule.hour):
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
        async with job_lease(
            db, "send_parent_daily_digests", timedelta(minutes=10), scheduler_worker_id
        ) as acquired:
            if not acquired:
                return
            await _send_parent_daily_digests_body()

    async def _send_parent_daily_digests_body() -> None:
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
            # `>=`, not `==`: the digest hour OPENS the window rather than
            # being the only chance. With an exact match each academy got one
            # tick a day, so a Resend outage or a deploy spanning that single
            # hour lost the whole day's digest and the retry ladder added by
            # #435/PR #489 could never fire — there was no later tick to fire
            # on (issue #542). Later ticks are cheap: `try_claim` runs BEFORE
            # plan generation, so an already-sent recipient costs one
            # duplicate-key insert and one indexed no-op re-claim, and a `sent`
            # row can never be re-claimed. The window closes on its own at
            # midnight, when `digest_date` rolls over.
            if not (schedule.enabled and current_hour >= schedule.hour):
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

    scheduler = AsyncIOScheduler(
        timezone=settings.scheduler_tz,
        # APScheduler's default misfire_grace_time is 1 second, so any event-loop
        # stall longer than that counts as a miss. With the EVENT_JOB_MISSED
        # listener registered below, that default would turn routine stalls on
        # the 60s webhook-drain job into a steady stream of alerts. 30s is well
        # inside every job's own interval and still catches a real stall.
        job_defaults={"misfire_grace_time": 30},
    )
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
    # Automated monthly invoice generation (issue #288). Runs daily; each tick
    # generates for any academy with an unfinished period — its billing_day has
    # passed and no successful run is recorded yet, so a failed run self-heals
    # on the next tick (issue #431). The first autopay charge is NOT scheduled
    # here — it is already the attempt-0 rung of the
    # existing dunning ladder, which picks up any invoice once its due_date
    # passes (see prepare_due_states / DUNNING_SCHEDULE_DAYS). Adding a second
    # charge trigger here would risk double-charging the same invoice.
    scheduler.add_job(
        _generate_monthly_invoices,
        "cron",
        hour=3,
        minute=0,
        id="generate_monthly_invoices",
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
    # Daily owner ops digest (issue #428) — the counterpart to the scheduler
    # error listener below: the listener reports failures as they happen, this
    # reports the state that accumulates silently. Fixed daily cron in
    # settings.scheduler_tz; skipped entirely when OPS_ALERT_EMAIL is unset.
    app.state.ops_digest_sender = compose_ops_digest_sender()
    # Issue #435: an expired Resend key used to be invisible — every send became
    # SendOutcome(ok=False) and mail stopped for weeks. Probe it once at boot so
    # a dead credential is reported on the deploy that broke it. Only a real
    # authentication verdict alerts; a timeout or provider 5xx is undetermined
    # and must not page anyone. Never fatal: a mail outage must not stop the app
    # from serving requests.
    await _verify_email_credentials(compose_email_credential_probe())
    scheduler.add_job(
        _send_ops_digest,
        "cron",
        hour=7,
        minute=0,
        id="send_ops_digest",
        replace_existing=True,
        max_instances=1,
    )
    # Job crashes and misfires previously died in APScheduler's own logger and
    # never reached Sentry (only the request path was instrumented).
    scheduler.add_listener(handle_scheduler_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
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


MONTHLY_GENERATION_RUNS_COLLECTION = "billing_generation_runs"


def _previous_period(period: str) -> str:
    """``"2026-01"`` -> ``"2025-12"``."""
    year, month = (int(part) for part in period.split("-", 1))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


async def _monthly_generation_recorded(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    period: str,
) -> bool:
    """True iff a monthly generation run for ``(academy_id, period)`` succeeded.

    Issue #431: the scheduler retries an academy every day until one run
    completes, so it needs a record of success. This is a scheduling
    stop-condition, not an invoice-level guard — duplicate invoices are
    prevented by the deterministic invoice ids and the ``billing_invoice_keys``
    unique index inside generate_monthly_payments.
    """
    doc = await db[MONTHLY_GENERATION_RUNS_COLLECTION].find_one(
        {"academy_id": academy_id, "period": period},
        {"_id": 1},
    )
    return doc is not None


async def _has_monthly_generation_history(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
) -> bool:
    """True iff this academy has *any* recorded generation run.

    Gates the prior-period catch-up. An academy with no history at all is
    either newly onboarded or predates this feature; attempting the prior
    period for it would invoice enrollments for a month they may not have been
    enrolled in (``generate_monthly_payments`` charges every currently active
    enrollment for the requested period regardless of when it was created).
    Once an academy has generated at least once, a *missing* prior period
    genuinely means "we were running and lost that month" — which is exactly
    the case this catch-up exists to repair.
    """
    doc = await db[MONTHLY_GENERATION_RUNS_COLLECTION].find_one(
        {"academy_id": academy_id},
        {"_id": 1},
    )
    return doc is not None


async def _record_monthly_generation(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    period: str,
    now: datetime,
    log: logging.Logger,
) -> bool:
    """Record a completed generation run so later ticks skip this period.

    Never raises. The write lives outside the generation ``try`` on purpose: a
    ``DuplicateKeyError`` from two machines racing the 0151 unique index (or
    any transient write blip) must not be logged as a *generation* failure for
    a run that actually created invoices, nor drop that academy from the run
    summary. A lost record only costs a redundant idempotent pass next tick.
    """
    try:
        await db[MONTHLY_GENERATION_RUNS_COLLECTION].update_one(
            {"academy_id": academy_id, "period": period},
            {
                "$set": {"completed_at": now},
                "$setOnInsert": {"academy_id": academy_id, "period": period},
            },
            upsert=True,
        )
    except DuplicateKeyError:
        # Another machine recorded the same (academy, period) first. Benign:
        # the stop-condition this write exists to create already holds.
        return True
    except Exception:
        log.warning(
            "monthly_generation_run_record_failed academy=%s period=%s; "
            "generation succeeded, next tick will re-attempt idempotently",
            academy_id,
            period,
            exc_info=True,
        )
        return False
    return True


async def _resolve_billing_day(
    get_billing_settings: Callable[[], Awaitable[Any]],
    academy_id: str,
    log: logging.Logger,
) -> int:
    """This academy's billing_day, degrading to the model default on failure.

    Settings are advisory for generation: the billing context's own rule is
    that a missing or unreadable billing_settings doc "must never block the
    monthly run" (see MongoMonthlyBilling._load_invoice_due_days). Skipping the
    academy on a read failure would make an unreadable settings doc a permanent
    silent skip — the exact failure mode issue #431 set out to remove.
    """
    try:
        settings = await get_billing_settings()
        return int(settings.billing_day)
    except Exception:
        log.warning(
            "monthly_generation_billing_settings_unreadable academy=%s; using default billing_day",
            academy_id,
            exc_info=True,
        )
        return int(BillingSettings.default("").billing_day)


async def _run_monthly_invoice_generation(
    *,
    db: AsyncIOMotorDatabase[Any],
    academy_ids: list[str],
    get_billing_settings: Callable[[], Awaitable[Any]],
    generate: Callable[[str], Awaitable[Any]],
    now: datetime,
    send_invoices: Callable[[str], Awaitable[Any]] | None = None,
) -> dict[str, int]:
    """Generate monthly invoices for every academy with an unfinished period.

    Each academy generates on its own configured billing_day
    (``billing_settings.billing_day``, default 1, capped at 28 so no academy is
    skipped in February).

    Issue #431: the gate is "billing_day has passed AND no successful
    generation is recorded for the period", not ``billing_day == now.day``. An
    exact-day match meant a single failed 03:00 run (Mongo blip, lease
    handover, crash) silently skipped the whole month, recoverable only by an
    admin. Now the next daily tick retries until one run completes.

    Two periods are considered each tick: the current one, and the immediately
    prior one when it is unrecorded *and* the academy has generation history
    (see _has_monthly_generation_history). Without the prior period the
    catch-up window would end at month end, so a February billing_day=28
    academy would still get exactly one attempt and a failure spanning the
    month boundary would lose that month forever.

    The per-(academy, period) record in ``billing_generation_runs`` is what
    stops the retry. Without it every academy would re-walk every active
    enrollment every day for the rest of the month, and — more importantly —
    enrollments created *after* billing_day would start getting a full
    current-period invoice, a behaviour change this fix does not intend.
    Correctness does not depend on the record: ``generate_monthly_payments``
    is idempotent via deterministic invoice ids plus the
    ``billing_invoice_keys`` guard, so a lost or unwritten record only costs a
    redundant pass that re-reports ``skipped_existing``.

    ``get_billing_settings``, ``generate`` and ``send_invoices`` are called
    inside the academy's ``tenant_scope``. All three are injected so the
    scheduling rules above can be tested without a running app.

    ``send_invoices`` (issue #430) emails the period's undelivered invoices.
    It runs on every tick, not only the ones that generate — it is its own
    retry mechanism, since the generation gate above deliberately stops
    yielding a period once it has been generated. Its failures are contained:
    generation must never be re-attempted because an email provider was down.
    """
    period = now.strftime("%Y-%m")
    prior_period = _previous_period(period)
    totals = {
        "academy_count": 0,
        "period_run_count": 0,
        "catch_up_run_count": 0,
        "partial_run_count": 0,
        "created": 0,
        "skipped_existing": 0,
        "skipped_no_charge": 0,
        "skipped_autopay": 0,
        "skipped_paused": 0,
        "repaired_orphan_keys": 0,
        "repaired_partial_invoices": 0,
        "failed_repair": 0,
        "invoices_emailed": 0,
        "invoice_emails_failed": 0,
        "invoice_emails_skipped_autopay": 0,
    }
    log = logging.getLogger("backend.v2.scheduler")
    for academy_id in academy_ids:
        with tenant_scope(academy_id):
            try:
                due = await _due_periods(
                    db=db,
                    academy_id=academy_id,
                    period=period,
                    prior_period=prior_period,
                    get_billing_settings=get_billing_settings,
                    now=now,
                    log=log,
                )
            except Exception:
                # One academy's gate failure must not abort the run for the
                # rest. Nothing is recorded, so the next tick retries it.
                log.exception(
                    "monthly_invoice_generation_gate_failed academy=%s period=%s",
                    academy_id,
                    period,
                )
                continue
            ran_any = False
            generated_periods: list[str] = []
            for run_period, is_catch_up in due:
                try:
                    result = await generate(run_period)
                except Exception:
                    # A failing academy/period leaves no record, so the next
                    # daily tick retries exactly this (academy, period).
                    log.exception(
                        "monthly_invoice_generation_failed academy=%s period=%s",
                        academy_id,
                        run_period,
                    )
                    continue
                ran_any = True
                generated_periods.append(run_period)
                totals["period_run_count"] += 1
                created = int(getattr(result, "created", 0) or 0)
                failed_repair = int(getattr(result, "failed_repair", 0) or 0)
                if failed_repair:
                    # The run returned normally but swallowed per-enrollment
                    # repair failures. Recording success here would switch off
                    # the daily retry for exactly the enrollments that still
                    # need it, so leave the period unrecorded and let the next
                    # tick re-attempt (idempotent for everything that worked).
                    totals["partial_run_count"] += 1
                    log.warning(
                        "monthly_invoice_generation_partial",
                        extra={
                            "academy_id": academy_id,
                            "period": run_period,
                            "failed_repair": failed_repair,
                            "created_count": created,
                        },
                    )
                else:
                    await _record_monthly_generation(db, academy_id, run_period, now, log)
                if is_catch_up:
                    totals["catch_up_run_count"] += 1
                    if created:
                        # Distinct signal: this academy's billing-day run did
                        # not complete, and this late run is what actually
                        # invoiced the month.
                        log.warning(
                            "monthly_invoices_generated_by_catch_up",
                            extra={
                                "academy_id": academy_id,
                                "period": run_period,
                                "current_period": period,
                                "run_day": now.day,
                                "created_count": created,
                            },
                        )
                for key in (
                    "created",
                    "skipped_existing",
                    "skipped_no_charge",
                    "skipped_autopay",
                    "skipped_paused",
                    "repaired_orphan_keys",
                    "repaired_partial_invoices",
                    "failed_repair",
                ):
                    totals[key] += int(getattr(result, key, 0) or 0)
            if ran_any:
                totals["academy_count"] += 1
            if send_invoices is not None:
                # Deliberately outside the `due` loop, and so run on every
                # tick rather than only on generation ticks. `_due_periods`
                # stops yielding a period the moment generation is recorded,
                # so a send pass gated on it would get exactly one attempt per
                # month: a single email-provider blip on billing day would
                # mean nobody was ever told they owe money. Re-running is safe
                # because the query only selects invoices that were never
                # delivered.
                #
                # The current period is always swept; a catch-up period is
                # swept on the tick that generates it. A catch-up period whose
                # emails fail is therefore not retried — that gap is left
                # rather than sweeping every historical period daily.
                for email_period in sorted({period, *generated_periods}):
                    await _email_generated_invoices(
                        send_invoices=send_invoices,
                        academy_id=academy_id,
                        run_period=email_period,
                        totals=totals,
                        log=log,
                    )
    if totals["academy_count"]:
        # ``created`` is a reserved LogRecord attribute (the record's own
        # timestamp) and logging raises KeyError rather than letting an
        # ``extra`` key shadow it — which made this very summary line throw
        # out of the job on every run that generated anything.
        summary = {key: value for key, value in totals.items() if key != "created"}
        summary["created_count"] = totals["created"]
        log.info("monthly_invoices_generated", extra={**summary, "period": period})
    return totals


async def _email_generated_invoices(
    *,
    send_invoices: Callable[[str], Awaitable[Any]],
    academy_id: str,
    run_period: str,
    totals: dict[str, int],
    log: logging.Logger,
) -> None:
    """Email this academy's undelivered invoices and fold the counts in.

    Called inside the academy's ``tenant_scope``. Swallows every failure by
    design: generation has already been recorded at this point, and a raised
    email error would abort the remaining academies in the run.
    """
    try:
        outcome = await send_invoices(run_period)
    except Exception:
        log.exception(
            "generated_invoice_emails_failed academy=%s period=%s",
            academy_id,
            run_period,
        )
        return
    for total_key, outcome_key in (
        ("invoices_emailed", "emailed"),
        ("invoice_emails_failed", "email_failed"),
        ("invoice_emails_skipped_autopay", "skipped_autopay"),
    ):
        totals[total_key] += int(_outcome_count(outcome, outcome_key))


def _outcome_count(outcome: Any, key: str) -> int:
    """Read a count off either a mapping or an attribute-bearing result."""
    if isinstance(outcome, dict):
        value = outcome.get(key, 0)
    else:
        value = getattr(outcome, key, 0)
    return int(value or 0)


async def _due_periods(
    *,
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    period: str,
    prior_period: str,
    get_billing_settings: Callable[[], Awaitable[Any]],
    now: datetime,
    log: logging.Logger,
) -> list[tuple[str, bool]]:
    """Periods this academy still owes, oldest first, as ``(period, is_catch_up)``.

    The run records are checked *before* the settings read so the steady-state
    tick (everything already generated) costs two cheap indexed lookups and no
    settings read at all.
    """
    due: list[tuple[str, bool]] = []
    if not await _monthly_generation_recorded(db, academy_id, prior_period):
        if await _has_monthly_generation_history(db, academy_id):
            # A prior period is always past its billing_day by definition.
            due.append((prior_period, True))
    if not await _monthly_generation_recorded(db, academy_id, period):
        billing_day = await _resolve_billing_day(get_billing_settings, academy_id, log)
        if now.day >= billing_day:
            due.append((period, now.day > billing_day))
    return due


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
    configure_error_tracking(settings)
    configure_tracing(app)
    register_exception_handlers(app)

    # The middleware needs access to the LoadAuthClaims use case wired in the
    # lifespan. We expose it via app.state and the middleware reads it
    # lazily on the first request.
    app.add_middleware(_LazyTenancyMiddleware)
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        proxy_shared_secret=settings.proxy_shared_secret,
    )
    _add_cors_middleware(app, settings)
    # Added last ⇒ runs first (outermost): the request id exists before
    # tenancy/rate-limit run and is stamped on their 401/429 responses too.
    app.add_middleware(RequestContextMiddleware)

    @app.get("/api/v2/healthz")
    async def healthz(response: Response) -> dict[str, Any]:
        """Liveness for Fly's 30s check and any external uptime monitor.

        503 on a fault a machine restart can actually fix (issue #429) — a
        lost Mongo connection, a stopped scheduler, a dead dispatcher task.
        Job heartbeats are reported but never fail the check: restarting the
        process does not make an overdue job run, and flapping the machine
        would make it worse.
        """
        report, healthy = await build_health_report(
            db=getattr(app.state, "db", None),
            scheduler=getattr(app.state, "scheduler", None),
            dispatcher=getattr(app.state, "dispatcher", None),
        )
        if not healthy:
            response.status_code = 503
            log.warning("healthz_degraded", extra={"checks": report["checks"]})
        return report

    # Persona route packages.
    app.include_router(me_router, prefix="/api/v2")
    app.include_router(registration_router, prefix="/api/v2")
    app.include_router(magic_link_router, prefix="/api/v2")
    if settings.enable_platform_routes:
        app.include_router(platform_router, prefix="/api/v2")
    app.include_router(coach_router, prefix="/api/v2")
    app.include_router(parent_router, prefix="/api/v2")
    app.include_router(admin_router, prefix="/api/v2")
    if settings.enable_student_login:
        # Not registered at all when the flag is off — true 404 (no route
        # match), matching the enable_platform_routes pattern above, rather
        # than a route that exists but always errors.
        app.include_router(student_router, prefix="/api/v2")
    if settings.enable_owner_role:
        app.include_router(owner_router, prefix="/api/v2")

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
        self, *, user_id: str, academy_id: str, aliases: Sequence[str] | None = None
    ) -> AcademyMembership | None:
        # `aliases` is accepted for port compatibility. This adapter resolves
        # the User by id (which already matches user_id/auth_uid/_id) and
        # synthesizes the membership from that row, so there is no separate
        # membership key to alias-match.
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

    async def list_memberships_for_user(self, user_id: str) -> list[AcademyMembership]:
        """Synthesize a single-item membership list from the legacy User record."""
        membership = await self.get_for_user_in_academy(
            user_id=user_id, academy_id=self._default_academy_id
        )
        return [membership] if membership is not None else []


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
