"""P0-1: Stripe redirect URL allowlist validation."""

from __future__ import annotations

import pytest

from backend.v2.shared.security.redirect import InvalidRedirectUrl, validate_redirect_url

ALLOWED = ["https://app.example.com", "http://localhost:3000"]


def test_allows_listed_https_origin() -> None:
    url = "https://app.example.com/parent/checkout/return?session_id=abc"
    assert validate_redirect_url(url, allowed_origins=ALLOWED) == url


def test_allows_listed_localhost_origin_with_port() -> None:
    url = "http://localhost:3000/parent/payments"
    assert validate_redirect_url(url, allowed_origins=ALLOWED) == url


def test_rejects_off_allowlist_domain() -> None:
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url("https://evil.example/phish", allowed_origins=ALLOWED)


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url("javascript:alert(1)", allowed_origins=ALLOWED)


def test_rejects_scheme_relative_open_redirect() -> None:
    # "//evil.example/x" has no scheme — must not slip through as same-origin.
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url("//evil.example/x", allowed_origins=ALLOWED)


def test_rejects_empty_url() -> None:
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url("", allowed_origins=ALLOWED)


def test_rejects_wrong_port_even_on_allowed_host() -> None:
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url("http://localhost:9999/x", allowed_origins=ALLOWED)


def test_rejects_http_when_only_https_allowlisted() -> None:
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url(
            "http://app.example.com/x", allowed_origins=["https://app.example.com"]
        )


def test_accepts_a_tenant_origin_supplied_alongside_the_static_list() -> None:
    """The tenant-aware allowlist (defect: newly onboarded academies could not
    check out) simply extends the iterable — the matcher itself is unchanged."""
    tenant_origin = "https://blno-badminton.courtmastr.com"
    url = f"{tenant_origin}/parent/checkout/return"
    assert validate_redirect_url(url, allowed_origins=[*ALLOWED, tenant_origin]) == url


def test_sibling_host_on_the_same_apex_is_still_rejected() -> None:
    """Widening for one tenant must not widen for its neighbours."""
    with pytest.raises(InvalidRedirectUrl):
        validate_redirect_url(
            "https://other-academy.courtmastr.com/pay",
            allowed_origins=[*ALLOWED, "https://blno-badminton.courtmastr.com"],
        )
