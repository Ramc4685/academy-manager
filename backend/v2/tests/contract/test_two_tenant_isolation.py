"""Two-tenant isolation proof, automated (roadmap L10).

Replaces the manual "Tenant isolation" row of
``docs/runbooks/saas-admin-route-matrix.md`` with a test that runs in CI.

How it works
------------
* One throwaway database per module on a real ``mongod`` (every migration
  replayed, so the production indexes and validators exist). Skipped, not
  failed, when no ``mongod`` is reachable, exactly like ``real_db``.
* Two academies are seeded, ``zalpha`` (A) and ``zbravo`` (B). Each has an
  admin, a coach and a parent, a student, a class with dated occurrences, an
  enrollment, an invoice with a line and a payment, an expense, a waitlist
  entry and a program. Every id and name is distinct, and every value that
  belongs to B carries the marker ``zbravo`` so a leak is a substring search.
* The REAL application is booted (``create_app()`` and its lifespan) in SaaS
  mode, with only the Firebase token verifier replaced: the bearer token is
  the user's email. Tenant resolution, membership checks, persona guards,
  composition and the Mongo repositories are all production code.
* Routes are enumerated from the app's router, never from a hand list, so a
  new admin, coach or parent route is covered the day it is added.

What is asserted
----------------
* Every admin/coach/parent route with a path parameter is called by academy
  A's actor for that persona, on academy A's host, with academy B's ids.
  It must answer 403 or 404, with none of B's data in the body (B's ids that
  the request itself carried may be echoed back; any other B marker fails).
  A request body, when the route needs one, is synthesised from the OpenAPI
  schema with B's ids in every id-named field. If FastAPI rejects that body
  before the handler runs (a request-validation 422) the route is counted as
  "not reached": it is safe but unproven, and the count is reported.
* Every GET route without a path parameter (lists, dashboards, reports) is
  called as A's actor, and B's markers must not appear anywhere in the body.
* Positive control: every GET route with a path parameter is also called by
  B's own actor on B's host with the same ids. A 2xx there proves the seed
  made the resource exist, so A's 404 means isolation rather than "no such
  row". Routes whose control does not answer 2xx are counted as unproven.

Allowlist
---------
``CROSS_TENANT_ALLOWLIST`` holds the reviewed routes that are legitimately not
tenant-scoped, each with its reason. Platform routes (``/api/v2/platform/``)
are cross-tenant by design and are excluded by the persona-prefix filter.

A route that leaks is marked ``strict`` xfail in ``KNOWN_LEAKS`` with the
filed GitHub issue, so the fix flips it to XPASS and forces the entry out.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
import warnings
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Tenants and actors
# ---------------------------------------------------------------------------

PLATFORM_DOMAIN = "isolation.test"
A = "zalpha"
B = "zbravo"
MARKER = B  # every B-owned value contains this substring
PERSONAS = ("admin", "coach", "parent")
PERSONA_PREFIX = re.compile(r"^/api/v2/(admin|coach|parent)/")


def _host(academy: str) -> str:
    return f"{academy}.{PLATFORM_DOMAIN}"


def _email(academy: str, persona: str) -> str:
    return f"{persona}.{academy}@example.com"


def _ids(academy: str) -> dict[str, str]:
    """Every seeded id for one academy, keyed by the route parameter name."""
    return {
        "admin_user_id": f"{academy}-user-admin",
        "coach_id": f"{academy}-user-coach",
        "parent_id": f"{academy}-user-parent",
        "family_id": f"{academy}-user-parent",
        "user_id": f"{academy}-user-parent",
        "student_id": f"{academy}-student-1",
        "session_id": f"{academy}-session-1",
        "occurrence_id": f"{academy}-session-1:2026-10-07:18:00",
        "enrollment_id": f"{academy}-enrollment-1",
        "invoice_id": f"{academy}-invoice-1",
        "line_id": f"{academy}-invoice-line-1",
        "payment_id": f"{academy}-payment-1",
        "expense_id": f"{academy}-expense-1",
        "waitlist_id": f"{academy}-waitlist-1",
        "program_id": f"{academy}-program-1",
        "application_id": f"{academy}-application-1",
        "pause_request_id": f"{academy}-pause-request-1",
        "message_id": f"{academy}-message-1",
        "period_id": f"{academy}-payout-period-1",
        "product_id": f"{academy}-product-1",
        "session_type_id": f"{academy}-session-type-1",
        "waiver_template_id": f"{academy}-waiver-template-1",
        "waiver_id": f"{academy}-waiver-1",
        "signature_id": f"{academy}-waiver-signature-1",
        # Pathway, self-service and Stripe ids are not seeded: they exist only
        # in B's namespace, so the call still proves A cannot reach them, but
        # without a positive control. Counted as "unseeded" in the summary.
        "skill_id": f"{academy}-skill-1",
        "level_id": f"{academy}-level-1",
        "rec_id": f"{academy}-levelup-rec-1",
        "note_id": f"{academy}-note-1",
        "follow_up_id": f"{academy}-follow-up-1",
        # Family contacts (People CRM Phase 4b, #950) landed after this test.
        "contact_id": f"{academy}-family-contact-1",
        "request_id": f"{academy}-request-1",
        "event_id": f"{academy}-event-1",
        "checkout_session_id": f"cs_test_{academy}_1",
    }


A_IDS = _ids(A)
B_IDS = _ids(B)

#: Parameters (path, query or body) that are not tenant-owned resource ids.
#: Routes whose only path
#: parameters are these are treated like list routes (checked for B markers).
NON_ID_PARAMS: dict[str, str] = {
    "month": "2026-10",
    "period": "2026-10",
    "report_name": "revenue",
    "role": "coach",
}

#: Schema gaps: fields the OpenAPI schema types as a bare string although the
#: use case only accepts an enum, so a synthesised "probe" would 500.
BODY_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v2/admin/skills/{skill_id}/external-refs"): {"source": "ACADEMY_CUSTOM"},
    # A model validator needs one of two optional fields.
    ("POST", "/api/v2/admin/enrollments/{enrollment_id}/pause"): {"resume_on": "2026-11-04"},
}

UNSEEDED_PARAMS = frozenset(
    {
        "skill_id",
        "level_id",
        "rec_id",
        "note_id",
        "follow_up_id",
        "contact_id",
        "request_id",
        "event_id",
        "checkout_session_id",
    }
)

# ---------------------------------------------------------------------------
# Reviewed exceptions
# ---------------------------------------------------------------------------

#: (METHOD, path) -> reason. Routes under the persona prefixes that are
#: legitimately not tenant-scoped. Keep each entry justified; review on add.
CROSS_TENANT_ALLOWLIST: dict[tuple[str, str], str] = {}

#: (METHOD, path) -> filed GitHub issue. Strict xfail: fixing the leak turns
#: the case into XPASS, which fails the run until the entry is removed.
KNOWN_LEAKS: dict[tuple[str, str], str] = {}

# ---------------------------------------------------------------------------
# Route enumeration (collection time, no database needed)
# ---------------------------------------------------------------------------


def _walk(routes: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Flatten FastAPI's route tree (handles 0.139's ``_IncludedRouter``)."""
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            context = getattr(route, "include_context", None)
            sub = prefix + (getattr(context, "prefix", "") or "")
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from _walk(original.routes, sub)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path, route


@dataclass(frozen=True)
class RouteCase:
    method: str
    path: str
    persona: str

    @property
    def params(self) -> tuple[str, ...]:
        return tuple(re.findall(r"\{(\w+)(?::\w+)?\}", self.path))

    @property
    def id_params(self) -> tuple[str, ...]:
        return tuple(p for p in self.params if p not in NON_ID_PARAMS)

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    @property
    def test_id(self) -> str:
        return f"{self.method} {self.path}"


def _enumerate_routes() -> list[RouteCase]:
    from backend.v2.main import create_app

    cases: set[RouteCase] = set()
    for path, route in _walk(create_app().routes):
        match = PERSONA_PREFIX.match(path)
        if match is None:
            continue
        for method in getattr(route, "methods", None) or ():
            if method == "HEAD":
                continue
            cases.add(RouteCase(method=method, path=path, persona=match.group(1)))
    return sorted(cases, key=lambda c: (c.method != "GET", c.path, c.method))


ALL_ROUTES = _enumerate_routes()
PARAM_ROUTES = [c for c in ALL_ROUTES if c.id_params]
LIST_ROUTES = [c for c in ALL_ROUTES if c.method == "GET" and not c.id_params]
CONTROL_ROUTES = [c for c in PARAM_ROUTES if c.method == "GET"]
UNCOVERED_WRITES = [c for c in ALL_ROUTES if c.method != "GET" and not c.id_params]


def _marks(case: RouteCase) -> list[Any]:
    issue = KNOWN_LEAKS.get(case.key)
    if issue is None:
        return []
    return [pytest.mark.xfail(strict=True, reason=f"cross-tenant leak, {issue}")]


def _params(cases: list[RouteCase]) -> list[Any]:
    return [pytest.param(c, id=c.test_id, marks=_marks(c)) for c in cases]


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _name(academy: str, what: str) -> str:
    return f"{academy.title()} {what}"


def _seed_docs(academy: str) -> dict[str, list[dict[str, Any]]]:
    ids = _ids(academy)
    users = []
    memberships = []
    for persona, uid in (
        ("admin", ids["admin_user_id"]),
        ("coach", ids["coach_id"]),
        ("parent", ids["parent_id"]),
    ):
        roles = ["admin", "owner"] if persona == "admin" else [persona]
        users.append(
            {
                "_id": uid,
                "user_id": uid,
                "firebase_uid": uid,
                "email": _email(academy, persona),
                "display_name": _name(academy, persona.title()),
                "name": _name(academy, persona.title()),
                "phone": "+15550100000",
                "academy_id": academy,
                "role": roles[0],
                "roles": roles,
                "status": "active",
                "is_active": True,
                "global_status": "active",
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
        memberships.append(
            {
                "membership_id": f"{academy}-membership-{persona}",
                "academy_id": academy,
                "user_id": uid,
                "roles": roles,
                "status": "active",
                "invited_by": ids["admin_user_id"],
                "invited_at": NOW,
                "accepted_at": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            }
        )

    session_start = datetime(2026, 10, 7, 23, 0, tzinfo=UTC)  # Wed 18:00 Chicago
    occurrences = []
    for week in range(-4, 8):
        day = date(2026, 10, 7) + timedelta(weeks=week)
        start = session_start + timedelta(weeks=week)
        occurrences.append(
            {
                "occurrence_id": f"{ids['session_id']}:{day.isoformat()}:18:00",
                "academy_id": academy,
                "session_id": ids["session_id"],
                "template_session_id": ids["session_id"],
                "start_at": start,
                "end_at": start + timedelta(minutes=45),
                "status": "scheduled",
                "scheduled_coach_id": ids["coach_id"],
                "is_billable": True,
                "is_payable": True,
            }
        )

    invoice = {
        "invoice_id": ids["invoice_id"],
        "invoice_number": f"{academy.upper()}-0001",
        "academy_id": academy,
        "parent_id": ids["parent_id"],
        "student_id": ids["student_id"],
        "enrollment_id": ids["enrollment_id"],
        "session_id": ids["session_id"],
        "period": "2026-10",
        "status": "open",
        "subtotal_cents": 12_000,
        "discount_cents": 0,
        "total_cents": 12_000,
        "amount_paid_cents": 2_000,
        "balance_due_cents": 10_000,
        "currency": "usd",
        "due_date": datetime(2026, 10, 1, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }
    return {
        "academies": [
            {
                "_id": academy,
                "academy_id": academy,
                "slug": academy,
                "primary_domain": _host(academy),
                "display_name": _name(academy, "Academy"),
                "status": "active",
                "timezone": "America/Chicago",
                "contact_email": _email(academy, "admin"),
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "academy_settings": [
            {
                "settings_id": f"{academy}-settings",
                "academy_id": academy,
                "display_name": _name(academy, "Academy"),
                "timezone": "America/Chicago",
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "users": users,
        "academy_memberships": memberships,
        "students": [
            {
                "academy_id": academy,
                "student_id": ids["student_id"],
                "first_name": academy.title(),
                "last_name": "Student",
                "full_name": _name(academy, "Student"),
                "dob": "2016-05-01",
                "skill_level": "beginner",
                "parent_id": ids["parent_id"],
                "parent_user_id": ids["parent_id"],
                "status": "active",
                "is_deleted": False,
                "created_at": NOW,
            }
        ],
        "sessions": [
            {
                "academy_id": academy,
                "session_id": ids["session_id"],
                "coach_id": ids["coach_id"],
                "title": _name(academy, "Wednesday Beginners"),
                "location": _name(academy, "Court"),
                "capacity": 12,
                "amount_cents": 12_000,
                "start_at": session_start,
                "end_at": session_start + timedelta(minutes=45),
                "status": "scheduled",
                "is_deleted": False,
                "created_at": NOW,
                "days_of_week": ["Wed"],
                "start_time": "18:00",
                "end_time": "18:45",
                "timezone": "America/Chicago",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
                "skill_level": "beginner",
                "age_group": "8-12",
                "monthly_price": 120,
                "program_id": ids["program_id"],
            }
        ],
        "session_occurrences": occurrences,
        "enrollments": [
            {
                "academy_id": academy,
                "enrollment_id": ids["enrollment_id"],
                "session_id": ids["session_id"],
                "student_id": ids["student_id"],
                "parent_id": ids["parent_id"],
                "parent_user_id": ids["parent_id"],
                "billing_type": "Standard",
                "approval_status": "approved",
                "status": "active",
                "enrolled_at": NOW,
                "is_deleted": False,
            }
        ],
        "invoices": [invoice],
        "invoice_lines": [
            {
                "line_id": ids["line_id"],
                "academy_id": academy,
                "invoice_id": ids["invoice_id"],
                "student_id": ids["student_id"],
                "enrollment_id": ids["enrollment_id"],
                "session_id": ids["session_id"],
                "line_type": "tuition",
                "kind": "tuition",
                "description": _name(academy, "October tuition"),
                "quantity": 1,
                "unit_amount_cents": 12_000,
                "amount_cents": 12_000,
                "created_at": NOW,
            }
        ],
        "ledger_payments": [
            {
                "payment_id": ids["payment_id"],
                "academy_id": academy,
                "parent_id": ids["parent_id"],
                "amount_cents": 2_000,
                "currency": "usd",
                "method": "cash",
                "source": "manual",
                "status": "succeeded",
                "unapplied_amount_cents": 0,
                "received_at": NOW,
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "payment_allocations": [
            {
                "allocation_id": f"{academy}-allocation-1",
                "academy_id": academy,
                "payment_id": ids["payment_id"],
                "invoice_id": ids["invoice_id"],
                "amount_cents": 2_000,
                "created_at": NOW,
            }
        ],
        "expenses": [
            {
                "academy_id": academy,
                "expense_id": ids["expense_id"],
                "category": "rent",
                "note": _name(academy, "court rent"),
                "amount_cents": 50_000,
                "incurred_on": datetime(2026, 9, 1, tzinfo=UTC),
                "deleted_at": None,
                "created_at": NOW,
            }
        ],
        "waitlist": [
            {
                "academy_id": academy,
                "waitlist_id": ids["waitlist_id"],
                "session_id": ids["session_id"],
                "student_id": ids["student_id"],
                "parent_id": ids["parent_id"],
                "status": "waiting",
                "position": 1,
                "joined_at": NOW,
                "created_at": NOW,
            }
        ],
        "programs": [
            {
                "academy_id": academy,
                "program_id": ids["program_id"],
                "name": _name(academy, "Junior Program"),
                "title": _name(academy, "Junior Program"),
                "status": "active",
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Module environment: throwaway database + the real app
# ---------------------------------------------------------------------------


def _mongo_url() -> str:
    return (
        os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    )


class _EmailTokenVerifier:
    """Stands in for Firebase: the bearer token IS the verified email."""

    async def verify(self, id_token: str) -> dict[str, object]:
        return {"email": id_token, "email_verified": True, "iat": 1}


@dataclass
class Env:
    client: Any
    database: Any  # sync pymongo handle on the same throwaway database
    outcomes: Counter[str] = field(default_factory=Counter)
    #: Cases worth a human look: writes A may make against B ids, and routes
    #: whose synthesised body never reached the handler.
    noted: dict[str, list[str]] = field(default_factory=dict)
    #: Set once any A-side write carrying B ids has run on this database. A's
    #: own audit log may then legitimately name those ids, so later list scans
    #: fall back to B's names, emails and titles (xdist keeps each worker's
    #: cases in collection order, so normally every list scan runs first).
    attacked_with_writes: bool = False

    def fingerprint(self, academy: str) -> dict[str, str]:
        """A SHA-256 of every stored document of ``academy``, per collection.

        Each BSON document is length-prefixed, so concatenating them in ``_id``
        order is unambiguous; collections with no document of ``academy`` are
        left out.
        """
        from bson import encode

        prints: dict[str, str] = {}
        for collection in sorted(self.database.list_collection_names()):
            if collection.startswith("system."):
                continue
            docs = self.database[collection].find({"academy_id": academy}, sort=[("_id", 1)])
            digest = hashlib.sha256()
            seen = False
            for doc in docs:
                digest.update(encode(doc))
                seen = True
            if seen:
                prints[collection] = digest.hexdigest()
        return prints

    def call(
        self,
        case: RouteCase,
        *,
        academy: str,
        ids: dict[str, str],
        openapi: dict[str, Any],
    ) -> tuple[Any, set[str]]:
        """Call ``case`` as ``academy``'s actor, filling ids from ``ids``."""
        injected: set[str] = set()

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in NON_ID_PARAMS:
                return NON_ID_PARAMS[name]
            injected.add(ids[name])
            return ids[name]

        url = re.sub(r"\{(\w+)(?::\w+)?\}", fill, case.path)
        operation = openapi["paths"].get(case.path, {}).get(case.method.lower(), {})
        query = _query_params(operation, openapi, ids, injected)
        body = _request_body(operation, openapi, ids, injected)
        if isinstance(body, dict):
            body.update(BODY_OVERRIDES.get(case.key, {}))
        headers = {
            "authorization": f"Bearer {_email(academy, case.persona)}",
            "host": _host(academy),
            "idempotency-key": str(uuid.uuid4()),
        }
        kwargs: dict[str, Any] = {"headers": headers, "params": query}
        if body is not None:
            kwargs["json"] = body
        response = self.client.request(case.method, url, **kwargs)
        return response, injected


@pytest.fixture(scope="module")
def env() -> Iterator[Env]:
    from fastapi.testclient import TestClient
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo import MongoClient

    import backend.v2.main as main_module
    from backend.v2.migrations import runner
    from backend.v2.shared.config import get_settings

    url = _mongo_url()
    name = f"zz_tenant_isolation_{os.getpid()}_{uuid.uuid4().hex[:8]}"

    async def _setup() -> str | None:
        client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
        try:
            try:
                await client.admin.command("ping")
            except Exception as exc:
                return f"no reachable mongod at {url}: {exc}"
            database = client[name]
            for module in runner._discover_migrations():
                await module.up(database)
            for academy in (A, B):
                for collection, docs in _seed_docs(academy).items():
                    await database[collection].insert_many(docs)
            return None
        finally:
            client.close()

    async def _teardown() -> None:
        client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
        try:
            await client.drop_database(name)
        finally:
            client.close()

    skip_reason = asyncio.run(_setup())
    if skip_reason is not None:
        pytest.skip(skip_reason)

    class _PausedScheduler(main_module.AsyncIOScheduler):  # type: ignore[misc,name-defined]
        """Jobs are registered exactly as in production but never fire here."""

        def start(self, paused: bool = False) -> None:
            super().start(paused=True)

    overrides = {
        "V2_ENV": "test",
        "V2_MONGO_URL": url,
        "V2_MONGO_DB": name,
        "V2_SAAS_MODE": "true",
        "V2_TENANCY_MODE": "multi_academy",
        "V2_PLATFORM_BASE_DOMAIN": PLATFORM_DOMAIN,
        "V2_ALLOW_STATIC_TENANT_PARENT_WIRING": "true",
        "V2_RUN_MIGRATIONS_ON_BOOT": "false",
    }
    with pytest.MonkeyPatch.context() as mp:
        for key, value in overrides.items():
            mp.setenv(key, value)
        mp.setattr(main_module, "FirebaseTokenVerifier", _EmailTokenVerifier)
        mp.setattr(main_module, "AsyncIOScheduler", _PausedScheduler)
        get_settings.cache_clear()
        try:
            app = main_module.create_app()
            sync_client: MongoClient[Any] = MongoClient(url, serverSelectionTimeoutMS=1500)
            with TestClient(
                app, base_url=f"http://{_host(A)}", raise_server_exceptions=False
            ) as client:
                yield Env(client=client, database=sync_client[name])
            sync_client.close()
        finally:
            get_settings.cache_clear()
            asyncio.run(_teardown())


@pytest.fixture(scope="module")
def openapi(env: Env) -> dict[str, Any]:
    schema: dict[str, Any] = env.client.app.openapi()
    return schema


# ---------------------------------------------------------------------------
# Request synthesis from the OpenAPI schema
# ---------------------------------------------------------------------------


def _id_for(field_name: str, ids: dict[str, str]) -> str | None:
    if field_name in ids:
        return ids[field_name]
    if field_name.endswith("_ids") and f"{field_name[:-4]}_id" in ids:
        return ids[f"{field_name[:-4]}_id"]
    return None


ULID_PATTERN = "^[0-9A-HJKMNP-TV-Z]{26}$"


def _resolve(schema: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = openapi["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _sample(
    schema: dict[str, Any],
    openapi: dict[str, Any],
    ids: dict[str, str],
    injected: set[str],
    name: str = "",
    depth: int = 0,
) -> Any:
    """A minimal value satisfying ``schema``, with ``ids`` in id-named fields."""
    schema = _resolve(schema, openapi)
    if depth > 6:
        return None
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if _resolve(o, openapi).get("type") != "null"]
            return _sample(options[0] if options else {}, openapi, ids, injected, name, depth + 1)
    if "allOf" in schema:
        return _sample(schema["allOf"][0], openapi, ids, injected, name, depth + 1)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "array":
        item = _sample(schema.get("items", {}), openapi, ids, injected, name, depth + 1)
        if _id_for(name, ids) is not None or schema.get("minItems"):
            return [item]
        return []
    if kind == "object" or "properties" in schema:
        required = set(schema.get("required", []))
        return {
            prop: _sample(sub, openapi, ids, injected, prop, depth + 1)
            for prop, sub in schema.get("properties", {}).items()
            if prop in required or _id_for(prop, ids) is not None
        }
    if kind == "integer":
        return max(int(schema.get("minimum", 1)), int(schema.get("exclusiveMinimum", 0)) + 1)
    if kind == "number":
        return float(max(schema.get("minimum", 1), schema.get("exclusiveMinimum", 0) + 1))
    if kind == "boolean":
        return False
    identifier = _id_for(name, ids)
    if identifier is not None:
        injected.add(identifier)
        return identifier
    fmt = schema.get("format")
    if fmt == "date":
        return "2026-10-07"
    if fmt == "date-time":
        return "2026-10-07T23:00:00Z"
    if fmt == "email":
        return "probe.zalpha@example.com"
    if name in NON_ID_PARAMS:
        return NON_ID_PARAMS[name]
    if schema.get("pattern") == ULID_PATTERN:
        return "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    return "probe"


def _query_params(
    operation: dict[str, Any], openapi: dict[str, Any], ids: dict[str, str], injected: set[str]
) -> dict[str, Any]:
    return {
        param["name"]: _sample(param.get("schema", {}), openapi, ids, injected, param["name"])
        for param in operation.get("parameters", [])
        if param.get("in") == "query" and param.get("required")
    }


def _request_body(
    operation: dict[str, Any], openapi: dict[str, Any], ids: dict[str, str], injected: set[str]
) -> Any:
    content = operation.get("requestBody", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema")
    if schema is None:
        return None
    return _sample(schema, openapi, ids, injected)


# ---------------------------------------------------------------------------
# Leak detection
# ---------------------------------------------------------------------------


def _response_text(response: Any) -> str:
    """Headers and body of ``response``, as one string to scan for B markers.

    Headers are included so a B id or name echoed only in ``Location``,
    ``Set-Cookie``, ``Content-Disposition`` or a pagination header is caught
    too.
    """
    headers = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
    return f"{headers}\n\n{response.text}"


def _foreign_markers(text: str, echoed: set[str]) -> list[str]:
    """B markers in ``text`` other than ids the request itself carried."""
    scrubbed = text
    for value in sorted(echoed, key=len, reverse=True):
        scrubbed = scrubbed.replace(value, "")
    lowered = scrubbed.lower()
    hits = []
    start = 0
    while (index := lowered.find(MARKER, start)) != -1:
        hits.append(scrubbed[max(0, index - 30) : index + 40])
        start = index + len(MARKER)
    return hits


def _is_request_validation(response: Any) -> bool:
    """FastAPI's own 422: the body/query never reached the handler."""
    if response.status_code != 422:
        return False
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, list)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_route_inventory_is_enumerated_and_reported() -> None:
    """Prints the coverage count; fails if enumeration silently finds nothing."""
    by_persona = Counter(c.persona for c in ALL_ROUTES)
    summary = (
        f"tenant isolation coverage: {len(ALL_ROUTES)} persona routes "
        f"(admin {by_persona['admin']}, coach {by_persona['coach']}, "
        f"parent {by_persona['parent']}); {len(PARAM_ROUTES)} path-parameter routes "
        f"attacked with academy B ids ({len(CONTROL_ROUTES)} GET with a positive "
        f"control); {len(LIST_ROUTES)} GET list routes scanned for B data; "
        f"{len(UNCOVERED_WRITES)} parameterless writes not covered; "
        f"{len(CROSS_TENANT_ALLOWLIST)} allowlisted; {len(KNOWN_LEAKS)} known leaks"
    )
    print(summary)
    warnings.warn(summary, stacklevel=1)
    assert by_persona["admin"] > 100 and by_persona["coach"] > 20 and by_persona["parent"] > 30
    assert len(PARAM_ROUTES) > 150
    unknown = {p for c in PARAM_ROUTES for p in c.id_params if p not in B_IDS}
    assert not unknown, f"new path parameter(s) need an id in _ids(): {sorted(unknown)}"
    stale = (set(CROSS_TENANT_ALLOWLIST) | set(KNOWN_LEAKS)) - {c.key for c in ALL_ROUTES}
    assert not stale, f"allowlist/known-leak entries for routes that no longer exist: {stale}"


def test_own_tenant_reads_its_seed(env: Env) -> None:
    """The seed is real: each academy reads its own core records by id."""
    for academy, ids in ((A, A_IDS), (B, B_IDS)):
        headers = {"authorization": f"Bearer {_email(academy, 'admin')}", "host": _host(academy)}
        for path in (
            f"/api/v2/admin/sessions/{ids['session_id']}",
            f"/api/v2/admin/students/{ids['student_id']}",
            f"/api/v2/admin/billing/invoices/{ids['invoice_id']}",
            f"/api/v2/admin/users/{ids['parent_id']}",
        ):
            response = env.client.get(path, headers=headers)
            assert response.status_code == 200, (academy, path, response.text[:300])
            assert academy in response.text


def test_duplicate_check_never_matches_the_other_tenants_people(env: Env) -> None:
    """``POST /admin/people/duplicate-check`` (People CRM Phase 4c) is a
    parameterless write-shaped read, so the enumeration above does not reach
    it. A's admin probing B's parent and coach finds nothing; B's own admin
    probing the same email finds B's family (the positive control)."""
    path = "/api/v2/admin/people/duplicate-check"

    def check(academy: str, body: dict[str, str]) -> Any:
        headers = {"authorization": f"Bearer {_email(academy, 'admin')}", "host": _host(academy)}
        return env.client.post(path, json=body, headers=headers)

    for body in (
        {"email": _email(B, "parent")},
        {"email": _email(B, "coach").upper()},
        {"email": _email(B, "parent"), "name": "zbravo"},
    ):
        response = check(A, body)
        assert response.status_code == 200, response.text[:300]
        assert response.json() == {"matches": []}, (body, response.text[:300])
        assert not _foreign_markers(_response_text(response), set(body.values()))

    control = check(B, {"email": _email(B, "parent")})
    assert control.status_code == 200, control.text[:300]
    kinds = [match["kind"] for match in control.json()["matches"]]
    assert "family" in kinds, control.text[:300]


@pytest.mark.parametrize("persona", PERSONAS)
def test_actor_cannot_use_its_token_on_the_other_tenants_host(env: Env, persona: str) -> None:
    """A's token on B's host: no membership in B, so no claims, so 401/403."""
    route = {
        "admin": "/api/v2/admin/students",
        "coach": "/api/v2/coach/sessions",
        "parent": "/api/v2/parent/children",
    }[persona]
    response = env.client.get(
        route,
        headers={"authorization": f"Bearer {_email(A, persona)}", "host": _host(B)},
    )
    assert response.status_code in (401, 403), response.text[:300]
    assert not _foreign_markers(_response_text(response), set())


@pytest.mark.parametrize("case", _params(LIST_ROUTES))
def test_list_route_holds_no_other_tenant_data(
    env: Env, openapi: dict[str, Any], case: RouteCase
) -> None:
    """Collected before the writes below, so the lists see the pristine seed."""
    if case.key in CROSS_TENANT_ALLOWLIST:
        pytest.skip(CROSS_TENANT_ALLOWLIST[case.key])
    response, injected = env.call(case, academy=A, ids=A_IDS, openapi=openapi)
    assert response.status_code < 500, f"{case.test_id}: {response.text[:400]}"
    tolerated = set(B_IDS.values()) if env.attacked_with_writes else set()
    leaked = _foreign_markers(_response_text(response), injected | tolerated)
    assert not leaked, f"{case.test_id} returned academy B data: {leaked[:3]}"
    env.outcomes["list_scanned"] += 1


@pytest.mark.parametrize("case", _params(CONTROL_ROUTES))
def test_positive_control_other_tenant_reads_its_own_ids(
    env: Env, openapi: dict[str, Any], case: RouteCase
) -> None:
    """B reading B's ids must not 5xx; 2xx proves the A-side refusal is isolation.

    Only a crash fails here. A non-2xx control (unseeded resource, a route that
    needs more state than the seed has) is reported as unproven, not failed.
    """
    response, _ = env.call(case, academy=B, ids=B_IDS, openapi=openapi)
    assert response.status_code < 500, f"{case.test_id}: {response.text[:400]}"
    if 200 <= response.status_code < 300:
        env.outcomes["control_ok"] += 1
        return
    kind = "unseeded" if set(case.id_params) & UNSEEDED_PARAMS else "unproven"
    env.outcomes[f"control_{kind}"] += 1
    pytest.skip(f"control answered {response.status_code}: {kind}, not a failure")


@pytest.mark.parametrize("case", _params(PARAM_ROUTES))
def test_path_parameter_route_refuses_other_tenants_ids(
    env: Env, openapi: dict[str, Any], case: RouteCase
) -> None:
    """A's actor, A's host, B's ids: no B data out, no B data changed.

    Outcomes, all counted in the summary:
    * 403/404 -> ``refused``, the expected answer;
    * another 4xx (a domain error such as "session not assigned") ->
      ``refused_domain``: the use case ran tenant-scoped and found nothing;
    * FastAPI's own 422 -> ``not_reached``: the synthesised body failed
      validation before the handler, so the route is safe but unproven;
    * 2xx on a read -> ``scoped_empty``: a tenant-scoped query matched no row
      (the body scan above already proved no B data came back);
    * 2xx on a write -> ``accepted_b_untouched``: A stored something that names
      a B id in A's own tenant; B's documents are verified unchanged.
    """
    if case.key in CROSS_TENANT_ALLOWLIST:
        pytest.skip(CROSS_TENANT_ALLOWLIST[case.key])
    before = env.fingerprint(B)
    if case.method != "GET":
        env.attacked_with_writes = True
    response, injected = env.call(case, academy=A, ids=B_IDS, openapi=openapi)
    after = env.fingerprint(B)

    assert response.status_code < 500, f"{case.test_id} crashed: {response.text[:400]}"
    leaked = _foreign_markers(_response_text(response), injected)
    assert not leaked, f"{case.test_id} returned academy B data: {leaked[:3]}"
    changed = sorted(c for c in set(before) | set(after) if before.get(c) != after.get(c))
    assert not changed, f"{case.test_id} as academy A changed academy B's {changed}"

    if response.status_code in (403, 404):
        outcome = "refused"
    elif _is_request_validation(response):
        outcome = "not_reached"
    elif response.status_code >= 400:
        outcome = "refused_domain"
    elif case.method == "GET":
        outcome = "scoped_empty"
    else:
        outcome = "accepted_b_untouched"
    env.outcomes[outcome] += 1
    if outcome in ("accepted_b_untouched", "not_reached"):
        detail = response.text[:160] if outcome == "not_reached" else ""
        env.noted.setdefault(outcome, []).append(
            f"{case.test_id} -> {response.status_code} {detail}".rstrip()
        )


def test_zz_outcome_summary(env: Env) -> None:
    """Reports how each case ended (per xdist worker when run in parallel)."""
    summary = "tenant isolation outcomes: " + ", ".join(
        f"{key} {value}" for key, value in sorted(env.outcomes.items())
    )
    for outcome, cases in sorted(env.noted.items()):
        summary += f"\n  {outcome}:\n    " + "\n    ".join(sorted(cases))
    print(summary)
    warnings.warn(summary, stacklevel=1)
