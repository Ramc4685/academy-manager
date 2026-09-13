"""Application-layer surface for the derived person lifecycle (issue #773).

The rules live in ``domain/lifecycle.py``. This module exists so the three
persona BFFs can name the lifecycle vocabulary in their response models
without importing a context's domain directly — ``tests/structural/
test_layering.py::test_interfaces_do_not_import_context_domain_directly``
requires interface -> use case -> domain, and the import-linter contract
enforces the same shape in CI.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.lifecycle import (
    OPERATIONAL_LIFECYCLES,
    PERSON_LIFECYCLES,
    LifecycleEnrollment,
    PersonLifecycle,
    PersonLifecycleState,
    derive_lifecycle,
)

__all__ = [
    "OPERATIONAL_LIFECYCLES",
    "PERSON_LIFECYCLES",
    "LifecycleEnrollment",
    "PersonLifecycle",
    "PersonLifecycleState",
    "derive_lifecycle",
]
