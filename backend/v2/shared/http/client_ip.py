"""Resolve the end user's IP address behind the Fly/Cloudflare proxy.

``request.client.host`` is the proxy's address in production, so audit
records (checkout attempts, waiver signatures) read the forwarded client
address instead, but only when the direct peer is a private/loopback proxy.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request


def request_ip(request: Request) -> str | None:
    direct_host = request.client.host if request.client else None
    if _trusted_proxy_host(direct_host):
        # Fly's edge overwrites Fly-Client-IP, so a client cannot forge it.
        fly_client = (request.headers.get("fly-client-ip") or "").strip()
        if _valid_ip(fly_client):
            return fly_client
        # The left of X-Forwarded-For is whatever the client sent; the rightmost
        # public entry is the one our own proxy appended.
        hops = (request.headers.get("x-forwarded-for") or "").split(",")
        for hop in reversed([h.strip() for h in hops]):
            if _valid_ip(hop) and not _trusted_proxy_host(hop):
                return hop
    return direct_host


def _trusted_proxy_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_private


def _valid_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
