"""Platform domain/application errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class TenantNotFound(DomainError):
    code = "Platform.TenantNotFound"
    status_code = 404


class TenantAlreadyExists(DomainError):
    code = "Platform.TenantAlreadyExists"
    status_code = 409


class TenantInvalidTransition(DomainError):
    code = "Platform.TenantInvalidTransition"
    status_code = 409
