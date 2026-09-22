"""``import_blno`` refuses to run outside an acknowledged single-academy DB (#881).

The importer predates tenancy: it drops shared collections and writes most
documents without ``academy_id``. Issue #881 asked for the unscoped writes to
be fixed or the script deleted; the guard below is the runtime half of that
(the ``expenses`` inserts now carry ``academy_id`` / ``expense_id``).
"""

from __future__ import annotations

import pytest

from backend.scripts.import_blno import SINGLE_TENANT_ACK_ENV, single_tenant_guard


def test_returns_the_single_academy_id_when_acknowledged() -> None:
    assert single_tenant_guard(academy_ids=["acad-a"], ack="1") == "acad-a"


@pytest.mark.parametrize("ack", [None, "", "0", "yes", "true"])
def test_refuses_without_explicit_ack(ack: str | None) -> None:
    with pytest.raises(SystemExit, match=SINGLE_TENANT_ACK_ENV):
        single_tenant_guard(academy_ids=["acad-a"], ack=ack)


def test_refuses_when_a_second_academy_exists() -> None:
    with pytest.raises(SystemExit, match="found 2"):
        single_tenant_guard(academy_ids=["acad-a", "acad-b"], ack="1")


def test_refuses_when_no_academy_row_exists() -> None:
    with pytest.raises(SystemExit, match="found 0"):
        single_tenant_guard(academy_ids=[], ack="1")
