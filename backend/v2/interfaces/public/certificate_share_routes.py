"""``GET /api/v2/public/certificates/{token}``: a certificate a parent shared (L5B).

Order of decisions, each before the next can run:

1. **Tenant from the host.** ``TenancyMiddleware`` resolved it from the
   request host (``request.state.resolved_academy_id``). The token never
   chooses the academy: it is looked up only inside the host's academy
   (``certs_share_token_per_academy_uq``), so a token opened on another
   academy's host is unknown there.
2. **Token shape.** Anything that is not a plausible token is a 404 before
   any read.
3. **Issued only.** A revoked, unshared or unknown token, an unknown host and
   an academy with no record all get the one identical 404.

Never cached (``no-store``): a parent's revoke must take effect on the next
load. Rate limited per client IP across every token
(``shared/http/rate_limit.py``), so the route cannot be used to walk tokens.
"""

from __future__ import annotations

import re
from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Response

from backend.v2.composition.public_page_read import PublicPageRead
from backend.v2.interfaces.public.academy_page_routes import _brand, not_found_response
from backend.v2.interfaces.public.dtos import PublicCertificateDto
from backend.v2.shared.tenancy.context import tenant_scope

router = APIRouter()

#: ``secrets.token_urlsafe(16)`` is 22 characters; allow some slack, nothing else.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _zone(name: str | None) -> Any:
    try:
        return ZoneInfo(name) if name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


@router.get(
    "/certificates/{token}",
    response_model=PublicCertificateDto,
    responses={404: {"description": "No shared certificate for this link on this host."}},
)
async def get_shared_certificate(token: str, request: Request, response: Response) -> Any:
    academy_id = getattr(request.state, "resolved_academy_id", None)
    if not academy_id or not _TOKEN_RE.fullmatch(token):
        return not_found_response()
    public_page: PublicPageRead = request.app.state.public_page
    with tenant_scope(str(academy_id)):
        profile = await public_page.get_academy_profile.execute(str(academy_id))
        if profile is None:
            return not_found_response()
        shared = await public_page.get_shared_certificate.execute(token)
    if shared is None:
        return not_found_response()
    response.headers["Cache-Control"] = "no-store"
    return PublicCertificateDto(
        academy=_brand(profile),
        recipient_name=shared.recipient_name,
        level_name=shared.level_name,
        level_number=shared.level_number,
        level_color=shared.level_color,
        cert_number=shared.cert_number,
        issued_on=shared.issued_at.astimezone(_zone(profile.timezone)).date(),
    )
