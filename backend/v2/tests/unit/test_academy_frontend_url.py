"""Unit tests for the per-academy frontend URL rewrite.

See PR discussion: parent-facing emails were linking to a generic
`https://academy.courtmastr.com` host regardless of academy, instead of the
academy's own subdomain (e.g. `https://blno-academy.courtmastr.com`) --
TenantResolver only resolves the latter.
"""

from __future__ import annotations

from backend.v2.shared.tenancy.academy_url import academy_frontend_url


def test_rewrites_host_first_label_to_academy_slug() -> None:
    result = academy_frontend_url(
        frontend_url="https://academy.courtmastr.com", academy_slug="blno-academy"
    )
    assert result == "https://blno-academy.courtmastr.com"


def test_strips_trailing_slash_and_path() -> None:
    result = academy_frontend_url(
        frontend_url="https://academy.courtmastr.com/", academy_slug="blno-academy"
    )
    assert result == "https://blno-academy.courtmastr.com"


def test_falls_back_to_frontend_url_when_slug_missing() -> None:
    result = academy_frontend_url(frontend_url="https://academy.courtmastr.com", academy_slug="")
    assert result == "https://academy.courtmastr.com"


def test_falls_back_when_frontend_url_missing() -> None:
    assert academy_frontend_url(frontend_url=None, academy_slug="blno-academy") == ""


def test_falls_back_when_host_has_no_subdomain_room() -> None:
    result = academy_frontend_url(
        frontend_url="https://courtmastr.com", academy_slug="blno-academy"
    )
    assert result == "https://courtmastr.com"
