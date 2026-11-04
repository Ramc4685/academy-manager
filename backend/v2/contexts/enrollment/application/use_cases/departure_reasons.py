"""Application-layer surface for the structured departure reason (issue #775).

The vocabulary lives in ``domain/departure_policy.py``. This module exists
for the same reason ``person_lifecycle.py`` does: the admin BFF has to name
``reason_code`` in its request and response models, and
``tests/structural/test_layering.py::test_interfaces_do_not_import_context_
domain_directly`` (plus the import-linter contract in CI) requires
interface -> use case -> domain.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.departure_policy import (
    DEPARTURE_REASON_CODES,
    DepartureReasonCode,
)

__all__ = [
    "DEPARTURE_REASON_CODES",
    "DepartureReasonCode",
]
