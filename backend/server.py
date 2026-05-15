from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from db import ensure_indexes, seed_users
from routers.auth_routes import router as auth_router
from routers.sessions_routes import router as sessions_router
from routers.finance_routes import router as finance_router
from routers.coaching_routes import router as coaching_router
from routers.comms_routes import router as comms_router
from routers.dashboard_routes import router as dashboard_router
from routers.extras_routes import router as extras_router
from routers.settings_routes import router as settings_router
from routers.billing_routes import router as billing_router
from routers.email_routes import router as email_router
from routers.waitlist_routes import router as waitlist_router
from routers.scheduler_routes import router as scheduler_router
from routers.calendar_routes import router as calendar_router
from routers.coach_routes import router as coach_router
from services.scheduler import start_scheduler, shutdown_scheduler


app = FastAPI(title="Badminton Academy Manager API")

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(sessions_router)
api_router.include_router(finance_router)
api_router.include_router(coaching_router)
api_router.include_router(comms_router)
api_router.include_router(dashboard_router)
api_router.include_router(extras_router)
api_router.include_router(settings_router)
api_router.include_router(billing_router)
api_router.include_router(email_router)
api_router.include_router(waitlist_router)
api_router.include_router(scheduler_router)
api_router.include_router(calendar_router)
api_router.include_router(coach_router)


@api_router.get("/")
async def root():
    return {"name": "Badminton Academy Manager API", "ok": True}


@api_router.get("/health")
async def health():
    return {"ok": True, "service": "academy-manager-api"}


app.include_router(api_router)


# CORS — use explicit origins to support httpOnly cookies with credentials
_frontend = os.environ.get("FRONTEND_URL", "")
_origins_env = os.environ.get("CORS_ORIGINS", "")
_origins = [o.strip() for o in _origins_env.split(",") if o.strip() and o.strip() != "*"]
if _frontend and _frontend not in _origins:
    _origins.append(_frontend)
# When using cookies cross-origin, allow_origin_regex covers preview subdomains
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.preview\.emergentagent\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await seed_users()
    start_scheduler()
    logger.info("Startup complete — indexes ready, admin seeded, scheduler running.")


@app.on_event("shutdown")
async def on_shutdown():
    shutdown_scheduler()
