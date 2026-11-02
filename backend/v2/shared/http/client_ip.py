"""Resolve the end user's IP address behind the Cloudflare BFF proxy and Fly.

``request.client.host`` is a proxy hop in production, so audit records
(checkout attempts, waiver signatures) use the same rule as the rate limiter's
client key (``rate_limit.InMemoryRateLimitMiddleware``):

1. The BFF proxy presents ``x-cm-proxy-auth`` matching the proxy shared secret
   -> trust ``CF-Connecting-IP`` (stamped by Cloudflare, forwarded unchanged).
2. Else ``Fly-Client-IP`` (stamped by Fly's edge; a client cannot forge it).
3. Else ``request.client.host`` (local dev and tests).

``X-Forwarded-For`` is never read: its left side is whatever the client sent.
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import Request

_PROXY_AUTH_HEADER = "x-cm-proxy-auth"


def request_ip(request: Request) -> str | None:
    state = getattr(getattr(request, "app", None), "state", None)
    secret = getattr(state, "proxy_shared_secret", None)
    # Truthy check: an empty secret must never validate an empty header.
    if secret:
        presented = request.headers.get(_PROXY_AUTH_HEADER)
        if presented is not None and hmac.compare_digest(presented, secret):
            cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
            if _valid_ip(cf_ip):
                return cf_ip
    fly_ip = (request.headers.get("fly-client-ip") or "").strip()
    if _valid_ip(fly_ip):
        return fly_ip
    return request.client.host if request.client else None


def _valid_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
