"""Domain-level guards for the session communication pack (#613)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.security.external_url import InvalidExternalUrl, validate_external_url


def _session(**overrides: object) -> Session:
    return Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Beginner Badminton",
        location="Court 1",
        start_at=datetime(2026, 6, 3, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 6, 3, 23, 45, tzinfo=UTC),
        capacity=12,
        **overrides,  # type: ignore[arg-type]
    )


def test_pack_defaults_to_unconfigured() -> None:
    """No stand-in defaults: a blank pack must read as "nothing configured"
    so the welcome email omits the section instead of emailing a placeholder."""
    session = _session()
    assert session.whatsapp_group_link is None
    assert session.venue_address is None
    assert session.parking_notes is None
    assert session.what_to_bring is None
    assert session.arrival_minutes_before is None
    assert session.coach_contact_policy is None
    assert session.absence_policy is None


def test_domain_model_accepts_an_https_group_link() -> None:
    session = _session(whatsapp_group_link="https://chat.whatsapp.com/AbCd1234")
    assert session.whatsapp_group_link == "https://chat.whatsapp.com/AbCd1234"


@pytest.mark.parametrize(
    "bad_link",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//evil.host/group",
        "chat.whatsapp.com/AbCd1234",
        "java\nscript:alert(1)",
    ],
)
def test_domain_model_rejects_non_http_group_links(bad_link: str) -> None:
    """The invariant, enforced for every writer — not only the HTTP boundary.

    The link becomes an ``href`` in an HTML email, where escaping stops
    attribute breakout but does nothing about the scheme. The domain raises
    the DomainError itself (pydantic only wraps ValueError), which the global
    handler renders as a 400 with a machine-readable code.
    """
    with pytest.raises(InvalidExternalUrl):
        _session(whatsapp_group_link=bad_link)


def test_blank_group_link_is_stored_as_unset() -> None:
    assert _session(whatsapp_group_link="   ").whatsapp_group_link is None


def test_arrival_minutes_is_bounded() -> None:
    """A typo must not produce "arrive 99999 minutes before" in the email."""
    with pytest.raises(ValidationError):
        _session(arrival_minutes_before=99999)
    with pytest.raises(ValidationError):
        _session(arrival_minutes_before=-5)


def test_validate_external_url_helper_contract() -> None:
    assert validate_external_url(None) is None
    assert validate_external_url("") is None
    assert validate_external_url(" https://example.com/g ") == "https://example.com/g"
    # http is accepted; only non-web schemes are refused.
    assert validate_external_url("http://example.com/g") == "http://example.com/g"
    with pytest.raises(InvalidExternalUrl):
        validate_external_url("javascript:alert(1)")
