"""Governance domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class GovernancePermissionDenied(DomainError):
    code = "PlatformGovernance.PermissionDenied"
    status_code = 403


class GovernanceRequestNotFound(DomainError):
    code = "PlatformGovernance.RequestNotFound"
    status_code = 404
