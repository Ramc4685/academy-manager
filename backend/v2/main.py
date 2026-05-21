"""Composition root for the v2 FastAPI app.

Wires shared infrastructure (config, logging, tracing, mongo, outbox,
dispatcher) and mounts persona route packages. No business logic here — only
glue.

Run standalone::

    uvicorn backend.v2.main:app --reload --port 8001

Mounted from legacy ``backend/server.py`` under ``/api/v2/*`` as well.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.composition.admin import compose_admin
from backend.v2.composition.coach import compose_coach
from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.identity.application.use_cases.load_auth_claims import (
    LoadAuthClaims,
)
from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.infrastructure.firebase_token_verifier import (
    FirebaseTokenVerifier,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import (
    MongoUserRepository,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.interfaces.platform.bootstrap_routes import router as platform_bootstrap_router
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.config import Settings, get_settings
from backend.v2.shared.events import EventDispatcher, MongoOutbox
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.observability import configure_logging, configure_tracing

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

    # Identity wiring — needed by TenancyMiddleware for token verification.
    users_repo = MongoUserRepository(db, default_academy_id=settings.default_academy_id)
    verifier = FirebaseTokenVerifier()
    load_claims = LoadAuthClaims(verifier=verifier, users=users_repo)
    app.state.load_auth_claims = load_claims
    app.state.register_public_parent = RegisterPublicParent(
        verifier=verifier,
        users=users_repo,
    )

    # Coach BFF wiring — exposed as app.state.coach for routes via deps.py.
    app.state.coach = compose_coach(db, outbox, idempotency_store)

    # Parent BFF wiring (Wave 2). Cross-context event handlers are registered
    # by compose_parent via install_handlers().
    stripe_gw = _build_stripe(settings)
    app.state.parent = compose_parent(db, outbox, idempotency_store, stripe_gw)

    # Admin BFF wiring (Wave 3).
    app.state.admin = compose_admin(db, outbox, idempotency_store, stripe_gw)

    try:
        yield
    finally:
        await dispatcher.stop()
        client.close()


def create_app() -> FastAPI:
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

    @app.get("/api/v2/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Persona route packages.
    app.include_router(me_router, prefix="/api/v2")
    app.include_router(registration_router, prefix="/api/v2")
    app.include_router(platform_bootstrap_router, prefix="/api/v2")
    app.include_router(coach_router, prefix="/api/v2")
    app.include_router(parent_router, prefix="/api/v2")
    app.include_router(admin_router, prefix="/api/v2")

    return app


def _build_stripe(settings: Settings) -> StripeGateway:
    if settings.stripe_use_fake_gateway or not settings.stripe_api_key or not settings.stripe_webhook_secret:
        return FakeStripeGateway()
    from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

    return RealStripeGateway(
        api_key=settings.stripe_api_key,
        webhook_secret=settings.stripe_webhook_secret,
    )


class _LazyTenancyMiddleware(TenancyMiddleware):
    """Resolves load_auth_claims from app.state at request time.

    Necessary because middleware is constructed during ``create_app`` (before
    the lifespan sets ``app.state.load_auth_claims``).
    """

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if self._load_claims is None:
            self._load_claims = getattr(request.app.state, "load_auth_claims", None)
            if self._load_claims is not None:
                # Re-bind to the use case's `.execute` method.
                use_case = self._load_claims
                self._load_claims = use_case.execute  # type: ignore[assignment]
        return await super().dispatch(request, call_next)


app = create_app()
