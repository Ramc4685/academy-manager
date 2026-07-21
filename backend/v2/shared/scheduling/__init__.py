"""Cross-machine scheduling primitives (distributed job leases)."""

from .lease import job_lease

__all__ = ["job_lease"]
