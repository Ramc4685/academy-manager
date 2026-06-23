"""Pure resolution rule for the coach-digest schedule.

``resolve_digest_schedule`` merges the per-academy notification override with the
deprecated env fallback. It is pure (no APScheduler, no Mongo), so the precedence
and validation rules are unit-tested in isolation here.
"""

from __future__ import annotations

from backend.v2.composition.digests import ResolvedDigestSchedule, resolve_digest_schedule


def test_env_fallback_when_no_academy_override() -> None:
    # Both override fields unset → env default applies (zero behaviour change).
    out = resolve_digest_schedule(
        academy_enabled=None, academy_hour=None, env_enabled=True, env_hour=6
    )
    assert out == ResolvedDigestSchedule(enabled=True, hour=6)


def test_env_disabled_stays_disabled_without_override() -> None:
    out = resolve_digest_schedule(
        academy_enabled=None, academy_hour=None, env_enabled=False, env_hour=6
    )
    assert out.enabled is False


def test_academy_override_wins_over_env() -> None:
    # Academy opted out and chose hour 9 even though env enables at 6.
    out = resolve_digest_schedule(
        academy_enabled=False, academy_hour=9, env_enabled=True, env_hour=6
    )
    assert out == ResolvedDigestSchedule(enabled=False, hour=9)


def test_academy_enables_when_env_off() -> None:
    out = resolve_digest_schedule(
        academy_enabled=True, academy_hour=18, env_enabled=False, env_hour=6
    )
    assert out == ResolvedDigestSchedule(enabled=True, hour=18)


def test_partial_override_only_hour() -> None:
    # Hour overridden, enabled falls back to env.
    out = resolve_digest_schedule(
        academy_enabled=None, academy_hour=21, env_enabled=True, env_hour=6
    )
    assert out == ResolvedDigestSchedule(enabled=True, hour=21)


def test_out_of_range_hour_falls_back_to_env_hour() -> None:
    for bad in (-1, 24, 99):
        out = resolve_digest_schedule(
            academy_enabled=True, academy_hour=bad, env_enabled=True, env_hour=6
        )
        assert out.hour == 6, bad


def test_boundary_hours_are_kept() -> None:
    assert (
        resolve_digest_schedule(
            academy_enabled=True, academy_hour=0, env_enabled=False, env_hour=6
        ).hour
        == 0
    )
    assert (
        resolve_digest_schedule(
            academy_enabled=True, academy_hour=23, env_enabled=False, env_hour=6
        ).hour
        == 23
    )
