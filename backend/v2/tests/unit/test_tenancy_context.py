"""Tests for shared.tenancy.context."""

from __future__ import annotations

import pytest

from backend.v2.shared.tenancy.context import (
    TenantContextUnset,
    current_academy_id,
    tenant_scope,
)


def test_current_academy_id_raises_without_scope() -> None:
    with pytest.raises(TenantContextUnset):
        current_academy_id()


def test_tenant_scope_sets_and_resets() -> None:
    with tenant_scope("academy-1"):
        assert current_academy_id() == "academy-1"
    with pytest.raises(TenantContextUnset):
        current_academy_id()


def test_tenant_scope_nesting() -> None:
    with tenant_scope("outer"):
        assert current_academy_id() == "outer"
        with tenant_scope("inner"):
            assert current_academy_id() == "inner"
        assert current_academy_id() == "outer"
