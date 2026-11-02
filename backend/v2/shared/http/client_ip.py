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
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            first_hop = forwarded_for.split(",", 1)[0].strip()
            if _valid_ip(first_hop):
                return first_hop
        for header_name in ("fly-client-ip", "cf-connecting-ip", "x-real-ip"):
            candidate = request.headers.get(header_name)
            if candidate and _valid_ip(candidate.strip()):
                return candidate.strip()
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
