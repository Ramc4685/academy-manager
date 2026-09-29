"""Regression test for backend/scripts/parent_account_audit.py's --academy-id
requirement.

Row 36 of the hardcoded-values sweep: the script used to fall back to the
literal "acad_blno_badminton" when no --academy-id/PRIMARY_ACADEMY_ID was
given, which meant a run against a different academy silently audited BLNO
instead of failing. It must now require the id explicitly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "parent_account_audit.py"


def _run(
    *, env: dict[str, str], extra_args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(extra_args or [])],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_missing_academy_id_errors_instead_of_defaulting_to_blno() -> None:
    env = {"PATH": "/usr/bin:/bin"}
    result = _run(env=env)

    assert result.returncode == 2
    assert "--academy-id is required" in result.stderr
    assert "acad_blno_badminton" not in result.stderr


def test_academy_id_from_env_is_still_accepted() -> None:
    # No --mongo-url/--db-name either, so this still exits early, but via the
    # *next* validation error, proving --academy-id was accepted from env.
    env = {"PATH": "/usr/bin:/bin", "PRIMARY_ACADEMY_ID": "acad_blno_badminton"}
    result = _run(env=env)

    assert result.returncode == 2
    assert "--mongo-url/--db-name" in result.stderr
    assert "--academy-id is required" not in result.stderr


def test_explicit_academy_id_flag_is_accepted() -> None:
    env = {"PATH": "/usr/bin:/bin"}
    result = _run(env=env, extra_args=["--academy-id", "acad_other_tenant"])

    assert result.returncode == 2
    assert "--mongo-url/--db-name" in result.stderr
    assert "--academy-id is required" not in result.stderr
