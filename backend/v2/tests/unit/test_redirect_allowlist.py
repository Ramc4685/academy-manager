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
