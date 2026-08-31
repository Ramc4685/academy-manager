"""Unsubscribe token scheme (#555).

The token is the *only* authority behind a login-less preference change, so
these tests pin the two properties that make it safe: it cannot be forged
without the secret, and it cannot be replayed against a different tenant.
"""

from __future__ import annotations

from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
    mint_unsubscribe_token,
    verify_unsubscribe_token,
)

SECRET = "s3cret-unsubscribe-key"


def test_round_trip_recovers_the_academy_and_user() -> None:
    token = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert token is not None
    assert verify_unsubscribe_token(token, secret=SECRET) == ("acad-a", "user-1")


def test_the_same_recipient_always_gets_the_same_token() -> None:
    """Re-derivable: tomorrow's digest must carry the link this one carried."""
    first = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    second = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert first == second


def test_tampered_payload_is_rejected() -> None:
    token = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert token is not None
    version, _payload, mac = token.split(".")
    forged = mint_unsubscribe_token(academy_id="acad-a", user_id="victim", secret="guess")
    assert forged is not None
    swapped_payload = forged.split(".")[1]
    assert verify_unsubscribe_token(f"{version}.{swapped_payload}.{mac}", secret=SECRET) is None


def test_wrong_secret_is_rejected() -> None:
    token = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert token is not None
    assert verify_unsubscribe_token(token, secret="another-secret") is None


def test_a_token_minted_for_one_academy_does_not_verify_as_another() -> None:
    """One family's link must never flip another tenant's row."""
    token_a = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert token_a is not None
    academy_id, user_id = verify_unsubscribe_token(token_a, secret=SECRET)  # type: ignore[misc]
    assert (academy_id, user_id) == ("acad-a", "user-1")
    # The academy is carried inside the MAC, so it cannot be edited in transit.
    token_b = mint_unsubscribe_token(academy_id="acad-b", user_id="user-1", secret=SECRET)
    assert token_a != token_b


def test_garbage_and_wrong_version_are_rejected_without_raising() -> None:
    for bad in ("", "not-a-token", "u2.abc.def", "u1.@@@.###", "u1.only-two"):
        assert verify_unsubscribe_token(bad, secret=SECRET) is None


def test_no_secret_means_no_token_and_no_verification() -> None:
    """Fail closed. An unconfigured deployment must not sign with an empty key."""
    assert mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=None) is None
    assert mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret="") is None
    real = mint_unsubscribe_token(academy_id="acad-a", user_id="user-1", secret=SECRET)
    assert real is not None
    assert verify_unsubscribe_token(real, secret=None) is None
    assert verify_unsubscribe_token(real, secret="") is None


class TestLinkBuilder:
    def test_builds_a_frontend_url_carrying_the_token(self) -> None:
        builder = UnsubscribeLinkBuilder(frontend_url="https://app.test/", secret=SECRET)
        url = builder.build(academy_id="acad-a", user_id="user-1")
        assert url is not None
        assert url.startswith("https://app.test/unsubscribe?t=")
        token = url.split("t=", 1)[1]
        assert verify_unsubscribe_token(token, secret=SECRET) == ("acad-a", "user-1")

    def test_no_secret_or_no_frontend_url_means_no_link(self) -> None:
        assert (
            UnsubscribeLinkBuilder(frontend_url="https://app.test", secret=None).build(
                academy_id="a", user_id="u"
            )
            is None
        )
        assert (
            UnsubscribeLinkBuilder(frontend_url=None, secret=SECRET).build(
                academy_id="a", user_id="u"
            )
            is None
        )


# --- the link's HOST, not just its token ------------------------------------
#
# `TenantResolver` (ADR-0007) reads the tenant from the first label of the
# request host, and `interfaces/unsubscribe_routes` refuses a request whose
# tenant did not resolve. A link built on the deployment's generic
# `frontend_url` therefore does not merely weaken the cross-tenant check — it
# is a link that cannot be acted on at all. Every other outbound link in the
# same digest (portal, magic link) already goes through `academy_frontend_url`.


def test_the_link_is_built_on_the_academys_own_subdomain() -> None:
    builder = UnsubscribeLinkBuilder(frontend_url="https://app.courtmastr.com", secret=SECRET)

    url = builder.build(academy_id="acad-a", user_id="u-1", academy_slug="blno")

    assert url is not None
    assert url.startswith("https://blno.courtmastr.com/unsubscribe?t="), url


def test_two_academies_get_links_on_their_own_hosts() -> None:
    builder = UnsubscribeLinkBuilder(frontend_url="https://app.courtmastr.com", secret=SECRET)

    a = builder.build(academy_id="acad-a", user_id="u-1", academy_slug="blno")
    b = builder.build(academy_id="acad-b", user_id="u-1", academy_slug="westside")

    assert a is not None and b is not None
    assert "//blno." in a and "//westside." in b


def test_an_apex_host_with_no_subdomain_slot_is_left_alone() -> None:
    """A 2-label host has no subdomain to replace; rewriting label 0 would
    corrupt the apex domain itself. Matches `academy_frontend_url`."""
    builder = UnsubscribeLinkBuilder(frontend_url="https://courtmastr.com", secret=SECRET)

    url = builder.build(academy_id="acad-a", user_id="u-1", academy_slug="blno")

    assert url is not None
    assert url.startswith("https://courtmastr.com/unsubscribe?t="), url
