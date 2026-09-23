"""CRM domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class InvalidContact(DomainError):
    """The create-contact input failed server-side validation (missing name,
    no email and no phone, over a size cap, unknown source or stage)."""

    code = "Crm.InvalidContact"
    status_code = 422
