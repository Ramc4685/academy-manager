"""Regression test for #607: shared/auth must import without a cycle.

``shared/auth/claims.py`` imports ``shared/http/errors.py``, which forces
Python to initialise the ``shared/http`` package first, whose ``__init__``
imports ``persona.py``, which used to import ``shared/auth/claims`` back at
module scope. When ``backend.v2.shared.auth`` happened to be the first of the
two packages touched in a process, ``claims`` was still half-initialised and
the import blew up with ``cannot import name 'AuthClaims' from partially
initialized module``.

The full test suite hid this: some earlier test almost always imported
``backend.v2.shared.http`` first. Running a single unit file (for example
``v2/tests/unit/test_a1_me_response.py``) hit the bad order and failed. The
guard therefore has to run in a *fresh* interpreter so it is independent of
whatever else pytest imported in this process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _import_in_fresh_interpreter(module: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_auth_claims_imports_standalone() -> None:
    """``backend.v2.shared.auth.claims`` must import on its own."""

    result = _import_in_fresh_interpreter("backend.v2.shared.auth.claims")

    assert result.returncode == 0, result.stderr


def test_auth_package_imports_standalone() -> None:
    """Importing the ``shared.auth`` package first must not cycle either."""

    result = _import_in_fresh_interpreter("backend.v2.shared.auth")

    assert result.returncode == 0, result.stderr


def test_http_package_still_imports_standalone() -> None:
    """The other import order must keep working after the fix."""

    result = _import_in_fresh_interpreter("backend.v2.shared.http")

    assert result.returncode == 0, result.stderr
