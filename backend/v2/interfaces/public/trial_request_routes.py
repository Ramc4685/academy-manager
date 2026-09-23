"""``POST /api/v2/public/trial-requests``: the anonymous trial form (Lane B4).

The only public write. Order of decisions, each before the next can run:

1. **Tenant from the host.** ``TenancyMiddleware`` resolved it from the
   request host (``request.state.resolved_academy_id``). The body carries no
   academy, tenant or slug, and any such key is ignored. No tenant, no
   academy record, or a page the owner has not published: the same plain
   404 as ``GET /public/academy`` for an unknown host.
2. **Trials switched off:** ``409 Public.TrialsClosed``, a clear message the
   page can show (B3 already hides the form in that state).
3. **Server-side validation** with per-field messages (``422
   Public.InvalidTrialRequest``, ``details.fields``); submitted values are
   never echoed back. The optional class is resolved from its opaque
   ``public_id`` against the academy's PUBLISHED classes only.
4. **Honeypot filled:** the normal acknowledgement, nothing written. It runs
   after step 3 so a bot sees the same validation and the same reads as a
   person; only the contact write is skipped.
5. **One contact** through CRM's ``CreateContact`` (source ``website``), which
   dedupes a repeat to the row already on file.

The acknowledgement is the same status, body and headers for a new inquiry,
a repeat and a honeypot hit, and so is the work on the response path: the
owner email is ALWAYS handed to ``BackgroundTasks`` and the adapter decides
after the response whether to send (only for a new contact). Rate limited
per client IP and per host in ``shared/http/rate_limit.py``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.v2.composition.public_trial_requests import PublicTrialRequests
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    WebsiteInquiryForm,
)
from backend.v2.interfaces.public.academy_page_routes import not_found_response
from backend.v2.interfaces.public.dtos import PublicTrialFormRequest, PublicTrialRequestAckDto
from backend.v2.shared.tenancy.context import tenant_scope

router = APIRouter()

#: Path the rate limiter keys on (``shared/http/rate_limit.py``).
PUBLIC_TRIAL_REQUESTS_PATH = "/api/v2/public/trial-requests"
#: Raw body cap. The largest valid form is well under 3 KB.
MAX_BODY_BYTES = 8 * 1024

_ACK_BODY = PublicTrialRequestAckDto().model_dump(mode="json")
_NO_STORE = {"Cache-Control": "no-store"}


def _ack() -> JSONResponse:
    return JSONResponse(status_code=200, content=dict(_ACK_BODY), headers=dict(_NO_STORE))


def _error(status: int, code: str, message: str, **details: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=dict(_NO_STORE),
    )


def _trials_closed() -> JSONResponse:
    return _error(
        409,
        "Public.TrialsClosed",
        "Free trials are paused right now. You can still register for a class with open places.",
    )


def _invalid(fields: dict[str, str]) -> JSONResponse:
    return _error(
        422,
        "Public.InvalidTrialRequest",
        "Some details need another look.",
        fields=fields,
    )


def _filled(value: object) -> bool:
    return bool(str(value or "").strip())


async def _read_capped(request: Request) -> bytes | None:
    """The body, or None past ``MAX_BODY_BYTES`` (read in chunks, never whole)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(raw: bytes) -> tuple[PublicTrialFormRequest | None, dict[str, str]]:
    try:
        payload = json.loads(raw or b"null")
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return None, {"form": "The form could not be read. Please try again."}
    try:
        return PublicTrialFormRequest.model_validate(payload), {}
    except ValidationError as exc:
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = str(err["loc"][0]) if err.get("loc") else "form"
            fields.setdefault(loc, "Enter a valid value.")
        return None, fields


def _form(body: PublicTrialFormRequest) -> WebsiteInquiryForm:
    return WebsiteInquiryForm(
        name=body.name,
        email=body.email,
        phone=body.phone,
        player_age=None if body.player_age is None else str(body.player_age),
        class_id=body.class_id,
        message=body.message,
        contact_about_request=body.contact_about_request is True,
        marketing_opt_in=body.marketing_opt_in is True,
    )


@router.post(
    "/trial-requests",
    response_model=PublicTrialRequestAckDto,
    responses={
        404: {"description": "No published academy page on this host."},
        409: {"description": "Trials are switched off (Public.TrialsClosed)."},
        413: {"description": "Request body too large."},
        422: {"description": "Invalid fields (Public.InvalidTrialRequest, details.fields)."},
    },
)
async def submit_trial_request(request: Request, background_tasks: BackgroundTasks) -> Any:
    academy_id = getattr(request.state, "resolved_academy_id", None)
    if not academy_id:
        return not_found_response()
    academy_id = str(academy_id)
    deps: PublicTrialRequests = request.app.state.public_trial_requests
    with tenant_scope(academy_id):
        profile = await deps.get_academy_profile.execute(academy_id)
        if profile is None or not profile.settings.published:
            return not_found_response()
        if not profile.settings.trials_open:
            return _trials_closed()
        raw = await _read_capped(request)
        if raw is None:
            return _error(413, "Public.RequestTooLarge", "The form is too large to send.")
        body, errors = _parse(raw)
        if body is None:
            return _invalid(errors)
        form = _form(body)
        errors = form.errors()
        if errors:
            return _invalid(errors)
        class_id = (body.class_id or "").strip() or None
        choice = await deps.resolve_class_choice.execute(academy_id, class_id)
        if choice.unknown_id:
            return _invalid(
                {"class_id": "That class is not taking requests. Choose another or leave it blank."}
            )
        chosen = choice.chosen
        if _filled(body.website):
            # Honeypot: same acknowledgement, same background hand-off, no
            # write. Checked only after the same validation and published-class
            # read a real submission does, so the response path differs by the
            # one skipped contact write (a timing gap of a single Mongo op; the
            # per-IP/per-host rate limits are the real spam control).
            background_tasks.add_task(
                deps.notifier.notify,
                academy_id=academy_id,
                contact=None,
                created=False,
                class_title=None,
            )
            return _ack()
        # A trial needs a seat to try: a full chosen class, or an academy with
        # nothing open (or nothing listed yet), files the inquiry as a lead
        # (the waitlist and "tell me when classes open" variants).
        wants_trial = (not chosen.full) if chosen is not None else choice.any_open
        result = await deps.submit_inquiry.execute(
            form,
            requested_session_id=chosen.session_id if chosen else None,
            pipeline_status="trial" if wants_trial else "lead",
            privacy_notice_url=profile.settings.privacy_notice_url,
        )
        if result.field_errors:
            return _invalid(result.field_errors)
    background_tasks.add_task(
        deps.notifier.notify,
        academy_id=academy_id,
        contact=result.contact,
        created=result.created,
        class_title=chosen.title if chosen else None,
    )
    return _ack()
