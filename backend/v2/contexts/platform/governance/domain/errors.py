"""Governance domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class GovernancePermissionDenied(DomainError):
    code = "PlatformGovernance.PermissionDenied"
    status_code = 403
