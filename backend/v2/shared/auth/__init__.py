"""Authentication primitives.

Token verification (Firebase or legacy JWT) lives here. Wave 1A wires up the
actual verification in W1A-02; this module ships placeholder types so the
skeleton compiles and routes can declare dependencies.
"""

from .claims import AuthClaims, get_auth_claims
from .middleware import TenancyMiddleware

__all__ = ["AuthClaims", "TenancyMiddleware", "get_auth_claims"]
