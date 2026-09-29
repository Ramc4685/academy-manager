"""Per-academy frontend base URL for outbound return links (hardcoded-values row 9).

Stripe return URLs (add-card reminder, Connect onboarding and OAuth callback)
used to be built once from the deployment's ``frontend_url``, so a parent or
owner came back on the platform host instead of their academy's subdomain,
where their session cookie lives. This builds the base URL per call from the
academy record's ``slug`` via ``academy_frontend_url``, like the invoice
checkout path already does.

Security: the host comes only from the academy record of an academy id the
caller has already authorised (claims, or an HMAC-verified OAuth state) and
never from the request. A slug that is not a plain DNS label, a missing
record, or a failed read all fail safe to the configured ``frontend_url``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

log = logging.getLogger(__name__)

AcademyBaseUrl = Callable[[str], Awaitable[str]]

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def academy_frontend_base_url_lookup(
    db: Any, *, frontend_url: str | None, default: str = ""
) -> AcademyBaseUrl:
    """``async (academy_id) -> base URL`` on that academy's own host, no trailing slash."""
    fallback = (frontend_url or default).rstrip("/")

    async def base_url(academy_id: str) -> str:
        try:
            doc = await MongoAcademyRepository(db).find_by_id(academy_id)
        except Exception:
            log.warning("academy slug lookup failed for %s; using frontend_url", academy_id)
            return fallback
        slug = str((doc or {}).get("slug") or "").strip()
        if not _DNS_LABEL.match(slug):
            if slug:
                log.warning(
                    "academy %s slug %r is not a DNS label; using frontend_url", academy_id, slug
                )
            return fallback
        return academy_frontend_url(frontend_url=fallback, academy_slug=slug)

    return base_url
