"""Unit tests for re-hosting Firebase auth action links on a tenant portal.

Production parents received links on the project-wide Firebase host
(`https://academy-courtmastr.firebaseapp.com/__/auth/action?...`): generic,
unbranded, and identical for every academy. The rewrite must move the link to
the academy's own host while preserving the `oobCode` exactly.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from backend.v2.shared.tenancy.firebase_action_link import tenant_auth_action_link

FIREBASE_LINK = (
    "https://academy-courtmastr.firebaseapp.com/__/auth/action"
    "?mode=resetPassword&oobCode=JYBDeJ1xhh96PMbFHAwJ&apiKey=AIzaSyDVSdIRkK&lang=en"
)


def test_rehosts_link_on_the_academys_own_portal_at_auth_action() -> None:
    result = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="https://blno-academy.courtmastr.com"
    )
    parsed = urlsplit(result)
    assert parsed.scheme == "https"
    assert parsed.netloc == "blno-academy.courtmastr.com"
    assert parsed.path == "/auth/action"


def test_preserves_every_query_parameter_verbatim() -> None:
    result = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="https://blno-academy.courtmastr.com"
    )
    params = parse_qs(urlsplit(result).query)
    assert params["mode"] == ["resetPassword"]
    assert params["oobCode"] == ["JYBDeJ1xhh96PMbFHAwJ"]
    assert params["apiKey"] == ["AIzaSyDVSdIRkK"]
    assert params["lang"] == ["en"]


def test_preserves_continue_url_stamped_by_action_code_settings() -> None:
    link = f"{FIREBASE_LINK}&continueUrl=https%3A%2F%2Fblno-academy.courtmastr.com%2Flogin"
    result = tenant_auth_action_link(
        firebase_link=link, portal_url="https://blno-academy.courtmastr.com"
    )
    params = parse_qs(urlsplit(result).query)
    assert params["continueUrl"] == ["https://blno-academy.courtmastr.com/login"]


def test_two_academies_get_two_different_hosts_from_one_firebase_link() -> None:
    """The whole point of the rewrite: one Firebase project, many tenants."""
    blno = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="https://blno-academy.courtmastr.com"
    )
    smash = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="https://smash-academy.courtmastr.com"
    )
    assert urlsplit(blno).netloc == "blno-academy.courtmastr.com"
    assert urlsplit(smash).netloc == "smash-academy.courtmastr.com"
    assert parse_qs(urlsplit(blno).query)["oobCode"] == parse_qs(urlsplit(smash).query)["oobCode"]


def test_trailing_slash_on_portal_url_does_not_double_up() -> None:
    result = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="https://blno-academy.courtmastr.com/"
    )
    assert urlsplit(result).path == "/auth/action"


def test_keeps_localhost_port_for_local_and_docker_staging() -> None:
    result = tenant_auth_action_link(
        firebase_link=FIREBASE_LINK, portal_url="http://blno.localhost:3000"
    )
    parsed = urlsplit(result)
    assert parsed.scheme == "http"
    assert parsed.netloc == "blno.localhost:3000"


def test_falls_back_unchanged_when_portal_url_missing() -> None:
    assert tenant_auth_action_link(firebase_link=FIREBASE_LINK, portal_url=None) == FIREBASE_LINK
    assert tenant_auth_action_link(firebase_link=FIREBASE_LINK, portal_url="") == FIREBASE_LINK


def test_falls_back_unchanged_when_portal_url_is_not_absolute_http() -> None:
    """A relative or non-http portal value must never produce a broken invite
    link -- the un-rewritten Firebase link still works."""
    for bad in ("blno-academy.courtmastr.com", "/portal", "ftp://example.com"):
        assert tenant_auth_action_link(firebase_link=FIREBASE_LINK, portal_url=bad) == FIREBASE_LINK


def test_falls_back_unchanged_when_link_carries_no_query() -> None:
    link = "https://academy-courtmastr.firebaseapp.com/__/auth/action"
    assert tenant_auth_action_link(firebase_link=link, portal_url="https://a.example.com") == link


def test_empty_link_stays_empty() -> None:
    assert tenant_auth_action_link(firebase_link="", portal_url="https://a.example.com") == ""
